"""
DeltaMax V5 - ARIMA Predictive Trust Alerts (Oracle version)

Purpose
-------
Predict the next 4 months for:
    1. creditScore
    2. totalCreditLimit
    3. creditWorthinessScore
    4. availableCredit
    5. anomaly_health
    6. drift_health
    7. business_health
    8. freshness_health
    9. overall_dataset_trust

V5 architecture
----------------
Oracle staging / trust results
        |
        v
This script
        |
        +--> ARIMA forecasting
        +--> Threshold breach alerts
        +--> Sharp trend deviation alerts
        +--> Confidence interval breach alerts
        |
        v
Oracle
        |
        +--> DM_V5_ARIMA_FORECASTS
        +--> DM_V5_ARIMA_ALERTS

IMPORTANT
---------
- Oracle is the only data source.
- No CSV input.
- No CSV output.
- No S3.
- This script does NOT recalculate the V5 trust score.
- Actual trust pillar values come from DM_V5_TRUST_RESULTS, which is produced
  by the existing Python + PL/SQL V5 pipeline.
- The schema metrics come from DM_V5_STG_CREDIT_BUREAU.
- Email notification is intentionally left for the separate notifier step.
"""

import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import oracledb
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")


# ============================================================
# 1. ORACLE CONFIGURATION
# ============================================================

ORACLE_USER = "DELTAMAX_V5"
ORACLE_PASSWORD = "DeltaMaxV5@2026"
ORACLE_DSN = "localhost:1521/FREEPDB1"

STAGING_TABLE = "DM_V5_STG_CREDIT_BUREAU"
TRUST_TABLE = "DM_V5_TRUST_RESULTS"

FORECAST_TABLE = "DM_V5_ARIMA_FORECASTS"
ALERT_TABLE = "DM_V5_ARIMA_ALERTS"


# ============================================================
# 2. ARIMA CONFIGURATION
# ============================================================

TRAIN_SIZE = 6
TEST_SIZE = 2
FUTURE_STEPS = 4

FORECAST_HORIZONS = [
    "MONTH+1",
    "MONTH+2",
    "MONTH+3",
    "MONTH+4",
]

SCHEMA_METRICS = [
    "creditScore",
    "totalCreditLimit",
    "creditWorthinessScore",
    "availableCredit",
]

TRUST_PILLARS = [
    "anomaly_health",
    "drift_health",
    "business_health",
    "freshness_health",
]

OVERALL_TRUST = "overall_dataset_trust"

ALL_SERIES = SCHEMA_METRICS + TRUST_PILLARS + [OVERALL_TRUST]

# Thresholds preserved from the original predictive-alert design.
THRESHOLDS = {
    "creditScore": 600.0,
    "totalCreditLimit": 50000.0,
    "creditWorthinessScore": 400.0,
    "availableCredit": 20000.0,
    "anomaly_health": 0.75,
    "drift_health": 0.75,
    "business_health": 0.75,
    "freshness_health": 0.75,
    "overall_dataset_trust": 0.75,
}


# ============================================================
# 3. ORACLE CONNECTION
# ============================================================

def get_connection():
    print("\nConnecting to Oracle...")

    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN,
    )

    print("Connected to Oracle successfully.")
    return conn


# ============================================================
# 4. CREATE RESULT TABLES
# ============================================================

def ensure_result_tables(conn):
    cursor = conn.cursor()

    try:
        cursor.execute(f"""
            BEGIN
                EXECUTE IMMEDIATE '
                    CREATE TABLE {FORECAST_TABLE} (
                        run_id              VARCHAR2(50),
                        series_name         VARCHAR2(100),
                        forecast_month     VARCHAR2(20),
                        forecast_value      NUMBER,
                        lower_95            NUMBER,
                        upper_95            NUMBER,
                        threshold_value     NUMBER,
                        arima_order         VARCHAR2(30),
                        aic                 NUMBER,
                        mae                 NUMBER,
                        rmse                NUMBER,
                        mape                NUMBER,
                        confidence_label    VARCHAR2(20),
                        created_at          TIMESTAMP DEFAULT SYSTIMESTAMP
                    )';
            EXCEPTION
                WHEN OTHERS THEN
                    IF SQLCODE != -955 THEN
                        RAISE;
                    END IF;
            END;
        """)

        cursor.execute(f"""
            BEGIN
                EXECUTE IMMEDIATE '
                    CREATE TABLE {ALERT_TABLE} (
                        run_id              VARCHAR2(50),
                        series_name         VARCHAR2(100),
                        trigger_type        VARCHAR2(100),
                        month_ahead         NUMBER,
                        forecast_month      VARCHAR2(20),
                        forecast_value      NUMBER,
                        threshold_value     NUMBER,
                        delta_value         NUMBER,
                        severity            VARCHAR2(20),
                        reason              VARCHAR2(4000),
                        created_at          TIMESTAMP DEFAULT SYSTIMESTAMP
                    )';
            EXCEPTION
                WHEN OTHERS THEN
                    IF SQLCODE != -955 THEN
                        RAISE;
                    END IF;
            END;
        """)

        conn.commit()

    finally:
        cursor.close()


# ============================================================
# 5. LOAD V5 DATA FROM ORACLE
# ============================================================

def load_schema_series(conn):
    """
    Calculate monthly means from the Oracle staging table.

    These replace the old CSV-based schema metric calculation.
    """
    sql = f"""
        SELECT
            DATA_MONTH,
            AVG(CREDITSCORE) AS CREDIT_SCORE,
            AVG(TOTALCREDITLIMIT) AS TOTAL_CREDIT_LIMIT,
            AVG(CREDITWORTHINESSSCORE) AS CREDIT_WORTHINESS_SCORE,
            AVG(AVAILABLECREDIT) AS AVAILABLE_CREDIT
        FROM {STAGING_TABLE}
        WHERE DATA_MONTH IS NOT NULL
        GROUP BY DATA_MONTH
        ORDER BY TO_DATE(DATA_MONTH, 'YYYY-MM')
    """

    df = pd.read_sql(sql, conn)

    if df.empty:
        raise RuntimeError("No monthly staging data found in Oracle.")

    df.columns = [c.lower() for c in df.columns]
    df = df.set_index("data_month")

    series = {
        "creditScore": df["credit_score"],
        "totalCreditLimit": df["total_credit_limit"],
        "creditWorthinessScore": df["credit_worthiness_score"],
        "availableCredit": df["available_credit"],
    }

    return series


def load_trust_series(conn):
    """
    Read the authoritative V5 trust pillars and final trust score.

    These values are NOT recalculated here.
    They come from the existing PL/SQL-backed V5 trust results.
    """
    sql = f"""
        SELECT
            DATA_MONTH,
            ANOMALY_HEALTH,
            DRIFT_HEALTH,
            BUSINESS_HEALTH,
            FRESHNESS_HEALTH,
            OVERALL_DATASET_TRUST
        FROM {TRUST_TABLE}
        WHERE DATA_MONTH IS NOT NULL
        ORDER BY TO_DATE(DATA_MONTH, 'YYYY-MM')
    """

    df = pd.read_sql(sql, conn)

    if df.empty:
        raise RuntimeError(
            "No rows found in DM_V5_TRUST_RESULTS. "
            "Run 03_Trust_Score.py before this predictive step."
        )

    df.columns = [c.lower() for c in df.columns]
    df = df.set_index("data_month")

    series = {
        "anomaly_health": df["anomaly_health"],
        "drift_health": df["drift_health"],
        "business_health": df["business_health"],
        "freshness_health": df["freshness_health"],
        "overall_dataset_trust": df["overall_dataset_trust"],
    }

    return series


# ============================================================
# 6. ARIMA
# ============================================================

def fit_best_arima(series, train_size, test_size, future_steps):
    """
    Select p,d,q by lowest AIC.

    Uses:
        first 6 points = training
        next 2 points  = test
        next 4 points  = future forecast
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()

    if len(clean) < train_size + test_size:
        raise ValueError(
            f"Series has only {len(clean)} usable points. "
            f"At least {train_size + test_size} are required."
        )

    train = clean.iloc[:train_size]
    test = clean.iloc[train_size:train_size + test_size]

    best_aic = np.inf
    best_order = None
    best_model = None

    for p in range(3):
        for d in range(2):
            for q in range(3):
                try:
                    model = ARIMA(train, order=(p, d, q))
                    fitted = model.fit()

                    if fitted.aic < best_aic:
                        best_aic = fitted.aic
                        best_order = (p, d, q)
                        best_model = fitted

                except Exception:
                    continue

    if best_model is None:
        raise RuntimeError("Unable to fit any ARIMA model.")

    # Two-point validation window.
    test_forecast = best_model.get_forecast(steps=test_size)
    test_pred = test_forecast.predicted_mean
    test_ci = test_forecast.conf_int()

    mae = float(np.mean(np.abs(test.values - test_pred.values)))
    rmse = float(np.sqrt(np.mean((test.values - test_pred.values) ** 2)))

    denom = np.where(np.abs(test.values) < 1e-9, 1e-9, np.abs(test.values))
    mape = float(
        np.mean(np.abs((test.values - test_pred.values) / denom)) * 100
    )

    # Fit the selected ARIMA order on all available actual points
    # before producing the real 4-month future forecast.
    final_model = ARIMA(clean, order=best_order).fit()
    future = final_model.get_forecast(steps=future_steps)

    future_pred = future.predicted_mean
    future_ci = future.conf_int()

    residuals = final_model.resid
    residual_sigma = float(residuals.std()) if residuals.std() > 0 else 0.0

    if residual_sigma > 0:
        residual_outliers = residuals.index[
            np.abs(residuals) > 2 * residual_sigma
        ].tolist()
    else:
        residual_outliers = []

    return {
        "train": train,
        "test": test,
        "test_pred": test_pred,
        "test_ci": test_ci,
        "future_pred": future_pred,
        "future_ci": future_ci,
        "order": best_order,
        "aic": float(best_aic),
        "mae": mae,
        "rmse": rmse,
        "mape": mape,
        "residual_outliers": residual_outliers,
    }


# ============================================================
# 7. CONFIDENCE
# ============================================================

def confidence_label(mape):
    if np.isnan(mape):
        return "N/A"

    if mape < 5:
        return "HIGH"

    if mape < 15:
        return "MEDIUM"

    return "LOW"


# ============================================================
# 8. FUTURE MONTH NAMES
# ============================================================

def build_future_months(last_month, count):
    last_period = pd.Period(str(last_month), freq="M")
    return [
        str(last_period + i)
        for i in range(1, count + 1)
    ]


# ============================================================
# 9. ALERTS
# ============================================================

def severity_from_horizon(months_ahead):
    if months_ahead == 1:
        return "CRITICAL"

    if months_ahead == 2:
        return "HIGH"

    return "WATCH"


def evaluate_alerts(name, result, threshold, future_months, full_series):
    alerts = []

    future_pred = result["future_pred"]
    future_ci = result["future_ci"]

    # --------------------------------------------------------
    # A. Threshold breach
    # --------------------------------------------------------
    for step, (month_label, value) in enumerate(
        zip(future_months, future_pred.values),
        start=1,
    ):
        value = float(value)

        if value < threshold:
            alerts.append({
                "trigger_type": "Threshold Breach",
                "month_ahead": step,
                "forecast_month": month_label,
                "forecast_value": value,
                "threshold_value": float(threshold),
                "delta_value": float(threshold - value),
                "severity": severity_from_horizon(step),
                "reason": (
                    f"{name} forecast for {month_label} "
                    f"({value:.4f}) is below threshold "
                    f"{threshold:.4f}."
                ),
            })

    # --------------------------------------------------------
    # B. Sharp trend deviation
    # --------------------------------------------------------
    hmean = float(full_series.mean())
    hstd = float(full_series.std())

    if hstd > 0:
        for step, (month_label, value) in enumerate(
            zip(future_months, future_pred.values),
            start=1,
        ):
            value = float(value)
            deviation = abs(value - hmean)

            if deviation > 2 * hstd:
                alerts.append({
                    "trigger_type": "Sharp Trend Deviation",
                    "month_ahead": step,
                    "forecast_month": month_label,
                    "forecast_value": value,
                    "threshold_value": hmean,
                    "delta_value": float(deviation),
                    "severity": severity_from_horizon(step),
                    "reason": (
                        f"{name} forecast for {month_label} "
                        f"is {deviation / hstd:.1f} sigma from "
                        f"historical mean {hmean:.4f}."
                    ),
                })

    # --------------------------------------------------------
    # C. Test-window confidence interval breach
    # --------------------------------------------------------
    for i, (idx, actual) in enumerate(result["test"].items()):
        lower = float(result["test_ci"].iloc[i, 0])
        upper = float(result["test_ci"].iloc[i, 1])
        actual = float(actual)

        if actual < lower or actual > upper:
            nearest_boundary = lower if actual < lower else upper

            alerts.append({
                "trigger_type": "Confidence Interval Breach",
                "month_ahead": 0,
                "forecast_month": str(idx),
                "forecast_value": actual,
                "threshold_value": nearest_boundary,
                "delta_value": abs(actual - nearest_boundary),
                "severity": "CRITICAL",
                "reason": (
                    f"Actual {idx} value ({actual:.4f}) fell outside "
                    f"the ARIMA 95% CI [{lower:.4f}, {upper:.4f}]."
                ),
            })

    return alerts


# ============================================================
# 10. SAVE FORECASTS TO ORACLE
# ============================================================

def save_forecasts(conn, rows):
    cursor = conn.cursor()

    try:
        cursor.executemany(
            f"""
            INSERT INTO {FORECAST_TABLE} (
                run_id,
                series_name,
                forecast_month,
                forecast_value,
                lower_95,
                upper_95,
                threshold_value,
                arima_order,
                aic,
                mae,
                rmse,
                mape,
                confidence_label
            )
            VALUES (
                :1, :2, :3, :4, :5, :6, :7, :8,
                :9, :10, :11, :12, :13
            )
            """,
            rows,
        )

        conn.commit()
        print(f"[OK] Inserted {len(rows)} forecast rows into Oracle.")

    finally:
        cursor.close()


# ============================================================
# 11. SAVE ALERTS TO ORACLE
# ============================================================

def save_alerts(conn, run_id, alerts):
    cursor = conn.cursor()

    try:
        rows = [
            (
                run_id,
                a["series_name"],
                a["trigger_type"],
                a["month_ahead"],
                a["forecast_month"],
                a["forecast_value"],
                a["threshold_value"],
                a["delta_value"],
                a["severity"],
                a["reason"],
            )
            for a in alerts
        ]

        if rows:
            cursor.executemany(
                f"""
                INSERT INTO {ALERT_TABLE} (
                    run_id,
                    series_name,
                    trigger_type,
                    month_ahead,
                    forecast_month,
                    forecast_value,
                    threshold_value,
                    delta_value,
                    severity,
                    reason
                )
                VALUES (
                    :1, :2, :3, :4, :5,
                    :6, :7, :8, :9, :10
                )
                """,
                rows,
            )

        conn.commit()
        print(f"[OK] Inserted {len(rows)} alert rows into Oracle.")

    finally:
        cursor.close()


# ============================================================
# 12. MAIN
# ============================================================

def main():
    print("\n" + "=" * 78)
    print("DELTAMAX V5 - ORACLE ARIMA PREDICTIVE TRUST ALERTS")
    print("=" * 78)

    conn = get_connection()

    try:
        ensure_result_tables(conn)

        schema_series = load_schema_series(conn)
        trust_series = load_trust_series(conn)

        all_series = {}
        all_series.update(schema_series)
        all_series.update(trust_series)

        # Align every series to the same monthly index.
        combined = pd.concat(all_series, axis=1).sort_index()

        print("\nMonthly V5 data available:")
        print(combined.index.tolist())

        if len(combined) < TRAIN_SIZE + TEST_SIZE:
            raise RuntimeError(
                f"Need at least {TRAIN_SIZE + TEST_SIZE} months. "
                f"Found {len(combined)}."
            )

        last_month = combined.index[-1]
        future_months = build_future_months(
            last_month,
            FUTURE_STEPS,
        )

        run_id = datetime.now().strftime(
            "ARIMA_%Y%m%d_%H%M%S"
        )

        print(f"\nRun ID: {run_id}")
        print(f"Last actual month: {last_month}")
        print(f"Forecast months: {future_months}")

        forecast_rows = []
        all_alerts = []

        print("\n" + "=" * 78)
        print("FITTING ARIMA MODELS")
        print("=" * 78)

        for name in ALL_SERIES:
            series = combined[name].dropna()

            print(f"\n{name}")

            result = fit_best_arima(
                series,
                TRAIN_SIZE,
                TEST_SIZE,
                FUTURE_STEPS,
            )

            confidence = confidence_label(result["mape"])

            print(
                f"  ARIMA order : {result['order']}"
            )
            print(
                f"  AIC         : {result['aic']:.2f}"
            )
            print(
                f"  MAPE        : {result['mape']:.2f}%"
            )
            print(
                f"  Confidence  : {confidence}"
            )

            for i, month_label in enumerate(future_months):
                forecast_value = float(
                    result["future_pred"].iloc[i]
                )
                lower = float(
                    result["future_ci"].iloc[i, 0]
                )
                upper = float(
                    result["future_ci"].iloc[i, 1]
                )

                forecast_rows.append(
                    (
                        run_id,
                        name,
                        month_label,
                        forecast_value,
                        lower,
                        upper,
                        float(THRESHOLDS[name]),
                        str(result["order"]),
                        result["aic"],
                        result["mae"],
                        result["rmse"],
                        result["mape"],
                        confidence,
                    )
                )

            series_alerts = evaluate_alerts(
                name,
                result,
                THRESHOLDS[name],
                future_months,
                series,
            )

            for alert in series_alerts:
                alert["series_name"] = name
                all_alerts.append(alert)

        # Remove previous results for this run only is unnecessary because
        # run_id is unique. Historical runs are intentionally retained.

        save_forecasts(conn, forecast_rows)
        save_alerts(conn, run_id, all_alerts)

        print("\n" + "=" * 78)
        print("PREDICTIVE ALERT SUMMARY")
        print("=" * 78)

        print(f"Total forecasts : {len(forecast_rows)}")
        print(f"Total alerts    : {len(all_alerts)}")

        if all_alerts:
            for alert in all_alerts:
                print(
                    f"[{alert['severity']:8}] "
                    f"{alert['series_name']:24} | "
                    f"{alert['trigger_type']:28} | "
                    f"{alert['forecast_month']:10} | "
                    f"value={alert['forecast_value']:.4f}"
                )
        else:
            print("No predictive alerts fired.")

        print("\n" + "=" * 78)
        print("ARIMA PREDICTIVE STEP COMPLETED")
        print("=" * 78)
        print("No CSV files created.")
        print("No S3 operations performed.")
        print("Forecasts and alerts stored in Oracle.")

    finally:
        conn.close()
        print("\nOracle connection closed.")


if __name__ == "__main__":
    main()
