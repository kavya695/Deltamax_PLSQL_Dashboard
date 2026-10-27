# -*- coding: utf-8 -*-

"""
DeltaMax V5 - Trust / Anomaly / Drift Calculation

V5 architecture:

    Oracle
        |
        v
DM_V5_STG_CREDIT_BUREAU
        |
        v
03_Trust_Score.py
        |
        +--> Isolation Forest
        +--> KNN
        +--> IQR
        +--> Missingness
        +--> Duplicate detection
        +--> ARIMA anomaly detection
        +--> PSI
        +--> Welch T-test
        +--> Mahalanobis drift
        +--> Freshness health
        |
        v
DM_V5_ANOMALY_RESULTS
        |
        v
PL/SQL
        |
        v
Final DeltaMax Trust Score

IMPORTANT:
- No CSV input
- No CSV output
- No S3
- Oracle is the input/output data store
- Python performs ML/statistical calculations
- PL/SQL performs database-side quality/business/final trust processing
"""

import os
import sys
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

import oracledb

from sklearn.ensemble import IsolationForest
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import MinMaxScaler

from scipy.stats import ttest_ind
from pipeline_config import apply_config

try:
    from statsmodels.tsa.arima.model import ARIMA

    warnings.filterwarnings("ignore")
    HAS_ARIMA = True

except ImportError:
    HAS_ARIMA = False


# ============================================================
# 1. ORACLE CONFIGURATION
# ============================================================

ORACLE_USER = "DELTAMAX_V5"
ORACLE_PASSWORD = "DeltaMaxV5@2026"
ORACLE_DSN = "localhost:1521/FREEPDB1"

STAGING_TABLE = "DM_V5_STG_CREDIT_BUREAU"
RESULT_TABLE = "DM_V5_ANOMALY_RESULTS"


# ============================================================
# 2. HYPERPARAMETERS
# ============================================================

# ---------------- ANOMALY WEIGHTS ----------------

W_ISO = 0.20
W_IQR = 0.20
W_MISSING = 0.10
W_DUPLICATE = 0.05
W_KNN = 0.15
W_ARIMA = 0.30


# ---------------- ARIMA ----------------

ARIMA_ORDER = (1, 1, 1)

ARIMA_SIGMA_K = 3.0

ARIMA_MIN_COL_FLAGS = 2

ARIMA_MIN_TRAIN_POINTS = 5

ARIMA_FEATURES = [
    "creditScore",
    "annualRevenue",
]


# ---------------- KNN ----------------

KNN_K = 5

KNN_PERCENTILE = 0.99


# ---------------- ISOLATION FOREST ----------------

ISO_N_ESTIMATORS = 64

ISO_MAX_SAMPLES = 100000

ISO_DECISION_THRESHOLD = 0


# ---------------- IQR ----------------

IQR_MULTIPLIER = 5


# ---------------- DRIFT ----------------

WEIGHT_MAHAL = 0.70

WEIGHT_WELCH = 0.10

WEIGHT_PSI = 0.20


# ---------------- FRESHNESS ----------------

FRESHNESS_TAU = 5.0

FRESHNESS_COL = "freshness_days_late"

apply_config(globals())


# ============================================================
# 3. FEATURES THAT ACTUALLY EXIST IN V5 ORACLE
# ============================================================

NUMERIC_FEATURES = [
    "employeeCount",
    "annualRevenue",
    "creditScore",
    "outstandingDebt",
    "totalCreditLimit",
    "availableCredit",
    "paymentHistoryScore",
    "creditUtilizationRatio",
    "numberOfAccounts",
    "numberOfInquiries",
    "hasDelinquency",
    "hasDefaulted",
    "hasBankruptcy",
    "delinquentAccountCount",
    "collectionsCount",
    "chargeoffCount",
    "judgmentCount",
    "taxlienCount",
    "publicrecordCount",
    "monthsSinceLastPayment",
    "monthsSinceFirstAccount",
    "monthsSinceLastDelinquency",
    "debtToIncomeRatio",
    "creditworthinessScore",
    "yearEstablished",
    "employeeCount",
    "freshness_days_late",
]


# Remove duplicate feature names while preserving order
NUMERIC_FEATURES = list(dict.fromkeys(NUMERIC_FEATURES))


# ============================================================
# 4. ORACLE CONNECTION
# ============================================================

def get_connection():

    print("\nConnecting to Oracle...")

    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )

    print("Connected to Oracle successfully.")

    return conn


# ============================================================
# 5. CREATE RESULT TABLE
# ============================================================

def create_result_table(conn):

    print("\nChecking result table...")

    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM USER_TABLES
            WHERE TABLE_NAME = :table_name
            """,
            table_name=RESULT_TABLE
        )

        exists = cursor.fetchone()[0] > 0

        if exists:

            print(f"{RESULT_TABLE} already exists.")

            return

        print(f"{RESULT_TABLE} does not exist.")

        print("Creating result table...")

        cursor.execute(
            f"""
            CREATE TABLE {RESULT_TABLE}
            (
                batch_id                    VARCHAR2(64) NOT NULL,
                record_id                   NUMBER NOT NULL,
                businessid                  VARCHAR2(100),

                data_lineage                VARCHAR2(30),
                data_month                  VARCHAR2(50),

                iso_flag                    NUMBER DEFAULT 0,
                iqr_flag                    NUMBER DEFAULT 0,
                knn_flag                    NUMBER DEFAULT 0,
                missing_flag                NUMBER DEFAULT 0,
                duplicate_flag              NUMBER DEFAULT 0,
                arima_flag                  NUMBER DEFAULT 0,

                overall_anomaly_risk        NUMBER,
                anomaly_health              NUMBER,

                drift_health                NUMBER,
                mahalanobis_score           NUMBER,
                welch_score                 NUMBER,
                psi_score                   NUMBER,

                freshness_health            NUMBER,

                created_at                  TIMESTAMP DEFAULT SYSTIMESTAMP,

                CONSTRAINT PK_DM_V5_ANOMALY
                    PRIMARY KEY (batch_id, record_id)
            )
            """
        )

        cursor.execute(
            f"""
            CREATE INDEX IX_DM_V5_ANOMALY_BATCH
            ON {RESULT_TABLE}(batch_id)
            """
        )

        cursor.execute(
            f"""
            CREATE INDEX IX_DM_V5_ANOMALY_LINEAGE
            ON {RESULT_TABLE}(data_lineage)
            """
        )

        conn.commit()

        print(f"{RESULT_TABLE} created successfully.")

    except Exception as e:

        conn.rollback()

        print("ERROR while creating result table:")
        print(e)

        raise

    finally:

        cursor.close()


# ============================================================
# 6. READ DATA FROM ORACLE
# ============================================================

def load_staging_data(conn):

    print("\nLoading data from Oracle staging table...")

    sql = f"""
        SELECT
            BATCH_ID,
            RECORD_ID,

            BUSINESSID,
            BUSINESSNAME,

            SEGMENT,
            INDUSTRY,

            CREDITSCORE,
            ANNUALREVENUE,
            OUTSTANDINGDEBT,
            TOTALCREDITLIMIT,
            AVAILABLECREDIT,

            PAYMENTHISTORYSCORE,
            CREDITUTILIZATIONRATIO,
            NUMBEROFACCOUNTS,
            NUMBEROFINQUIRIES,

            HASDELINQUENCY,
            HASDEFAULTED,
            HASBANKRUPTCY,

            DELINQUENTACCOUNTCOUNT,
            COLLECTIONSCOUNT,
            CHARGEOFFCOUNT,
            JUDGMENTCOUNT,
            TAXLIENCOUNT,
            PUBLICRECORDCOUNT,

            MONTHSSINCELASTPAYMENT,
            MONTHSSINCEFIRSTACCOUNT,
            MONTHSSINCELASTDELINQUENCY,

            DEBTTOINCOME_RATIO,
            CREDITWORTHINESSSCORE,

            RISKPROFILE,

            DATA_LINEAGE,
            DATA_MONTH,

            YEAR_ESTABLISHED,
            EMPLOYEE_COUNT,

            LOADED_AT,

            FRESHNESS_DAYS_LATE

        FROM {STAGING_TABLE}

        ORDER BY
            DATA_LINEAGE,
            DATA_MONTH,
            RECORD_ID
    """

    cursor = conn.cursor()

    cursor.execute(sql)

    rows = cursor.fetchall()

    columns = [col[0] for col in cursor.description]

    cursor.close()

    df = pd.DataFrame(rows, columns=columns)

    print(f"Rows loaded from Oracle: {len(df)}")

    if df.empty:

        raise RuntimeError(
            f"No data found in {STAGING_TABLE}"
        )

    # ========================================================
    # Convert Oracle column names to Python names
    # ========================================================

    rename_map = {

        "BATCH_ID": "batch_id",
        "RECORD_ID": "record_id",

        "BUSINESSID": "businessID",
        "BUSINESSNAME": "businessName",

        "SEGMENT": "segment",
        "INDUSTRY": "industry",

        "CREDITSCORE": "creditScore",
        "ANNUALREVENUE": "annualRevenue",
        "OUTSTANDINGDEBT": "outstandingDebt",
        "TOTALCREDITLIMIT": "totalCreditLimit",
        "AVAILABLECREDIT": "availableCredit",

        "PAYMENTHISTORYSCORE": "paymentHistoryScore",
        "CREDITUTILIZATIONRATIO": "creditUtilizationRatio",
        "NUMBEROFACCOUNTS": "numberOfAccounts",
        "NUMBEROFINQUIRIES": "numberOfInquiries",

        "HASDELINQUENCY": "hasDelinquency",
        "HASDEFAULTED": "hasDefaulted",
        "HASBANKRUPTCY": "hasBankruptcy",

        "DELINQUENTACCOUNTCOUNT": "delinquentAccountCount",
        "COLLECTIONSCOUNT": "collectionsCount",
        "CHARGEOFFCOUNT": "chargeoffCount",
        "JUDGMENTCOUNT": "judgmentCount",
        "TAXLIENCOUNT": "taxlienCount",
        "PUBLICRECORDCOUNT": "publicrecordCount",

        "MONTHSSINCELASTPAYMENT": "monthsSinceLastPayment",
        "MONTHSSINCEFIRSTACCOUNT": "monthsSinceFirstAccount",
        "MONTHSSINCELASTDELINQUENCY": "monthsSinceLastDelinquency",

        "DEBTTOINCOME_RATIO": "debtToIncomeRatio",
        "CREDITWORTHINESSSCORE": "creditworthinessScore",

        "RISKPROFILE": "riskProfile",

        "DATA_LINEAGE": "data_lineage",
        "DATA_MONTH": "data_month",

        "YEAR_ESTABLISHED": "yearEstablished",
        "EMPLOYEE_COUNT": "employeeCount",

        "LOADED_AT": "loaded_at",

        "FRESHNESS_DAYS_LATE": "freshness_days_late",
    }

    df.rename(
        columns=rename_map,
        inplace=True
    )

    # ========================================================
    # Numeric conversion
    # ========================================================

    numeric_columns = [
        col
        for col in NUMERIC_FEATURES
        if col in df.columns
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # Ensure IDs are strings/numbers appropriately

    df["businessID"] = (
        df["businessID"]
        .astype("string")
    )

    df["data_lineage"] = (
        df["data_lineage"]
        .astype("string")
        .str.strip()
    )

    df["data_month"] = (
        df["data_month"]
        .astype("string")
        .str.strip()
    )

    return df


# ============================================================
# 7. PRINT DATASET STRUCTURE
# ============================================================

def print_dataset_structure(df):

    print("\n" + "=" * 80)

    print("ORACLE DATASET STRUCTURE")

    print("=" * 80)

    print(
        df[
            [
                "data_lineage",
                "data_month"
            ]
        ]
        .value_counts()
        .sort_index()
    )

    print("\nLineage counts:")

    print(
        df["data_lineage"]
        .value_counts()
    )

    print("\nTotal records:")

    print(len(df))

    print("=" * 80)


# ============================================================
# 8. SPLIT HISTORICAL / PREVIOUS / CURRENT
# ============================================================

def split_datasets(df):

    historical = df[
        df["data_lineage"] == "HISTORICAL"
    ].copy()

    previous = df[
        df["data_lineage"] == "PREVIOUS_MONTH"
    ].copy()

    current = df[
        df["data_lineage"] == "CURRENT_MONTH"
    ].copy()

    datasets = {
        "H": historical,
        "A": previous,
        "B": current
    }

    print("\nDataset split:")

    print(
        f"HISTORICAL     : {len(historical)}"
    )

    print(
        f"PREVIOUS_MONTH : {len(previous)}"
    )

    print(
        f"CURRENT_MONTH  : {len(current)}"
    )

    return datasets


# ============================================================
# 9. GET AVAILABLE NUMERIC FEATURES
# ============================================================

def get_model_features(df):

    features = []

    for col in NUMERIC_FEATURES:

        if col in df.columns:

            features.append(col)

    print("\nFeatures used by ML/statistical models:")

    for feature in features:

        print("  -", feature)

    print(
        f"\nTotal model features: {len(features)}"
    )

    return features


# ============================================================
# 10. KNN ANOMALY
# ============================================================

def run_knn(datasets, numeric_features):

    print("\n" + "=" * 80)

    print("KNN ANOMALY DETECTION")

    print("=" * 80)

    historical = datasets["H"]

    X_hist = (
        historical[numeric_features]
        .fillna(0)
        .to_numpy()
    )

    if len(X_hist) < 2:

        print(
            "Not enough historical data for KNN."
        )

        for data in datasets.values():

            data["knn_flag"] = 0

        return datasets

    k = min(
        KNN_K,
        max(1, len(X_hist) - 1)
    )

    knn = NearestNeighbors(
        n_neighbors=k,
        metric="euclidean",
        n_jobs=-1
    )

    knn.fit(X_hist)

    hist_distances, _ = knn.kneighbors(
        X_hist
    )

    hist_mean_distance = (
        hist_distances.mean(axis=1)
    )

    threshold = np.quantile(
        hist_mean_distance,
        KNN_PERCENTILE
    )

    print(
        f"KNN threshold: {threshold:.6f}"
    )

    for label, data in datasets.items():

        if data.empty:

            data["knn_flag"] = 0

            continue

        X = (
            data[numeric_features]
            .fillna(0)
            .to_numpy()
        )

        distances, _ = knn.kneighbors(X)

        scores = distances.mean(axis=1)

        data["knn_raw"] = scores

        data["knn_flag"] = (
            scores > threshold
        ).astype(int)

        print(
            f"{label}: "
            f"{int(data['knn_flag'].sum())}/"
            f"{len(data)} anomalies"
        )

    return datasets


# ============================================================
# 11. ISOLATION FOREST
# ============================================================

def run_isolation_forest(
    datasets,
    numeric_features
):

    print("\n" + "=" * 80)

    print("ISOLATION FOREST")

    print("=" * 80)

    historical = datasets["H"]

    X_hist = (
        historical[numeric_features]
        .fillna(0)
    )

    if X_hist.empty:

        print(
            "No historical data available."
        )

        for data in datasets.values():

            data["iso_flag"] = 0

        return datasets

    iso = IsolationForest(
        n_estimators=ISO_N_ESTIMATORS,
        contamination="auto",
        random_state=42,
        max_samples=min(
            ISO_MAX_SAMPLES,
            len(X_hist)
        ),
        n_jobs=-1
    )

    print(
        f"Training on {len(X_hist)} historical records..."
    )

    iso.fit(X_hist)

    for label, data in datasets.items():

        if data.empty:

            data["iso_flag"] = 0

            continue

        X = (
            data[numeric_features]
            .fillna(0)
        )

        predictions = (
            iso.decision_function(X)
        )

        data["iso_raw"] = predictions

        data["iso_flag"] = (
            predictions < ISO_DECISION_THRESHOLD
        ).astype(int)

        print(
            f"{label}: "
            f"{int(data['iso_flag'].sum())}/"
            f"{len(data)} anomalies"
        )

    return datasets


# ============================================================
# 12. IQR
# ============================================================

def run_iqr(
    datasets,
    numeric_features
):

    print("\n" + "=" * 80)

    print("IQR ANOMALY DETECTION")

    print("=" * 80)

    historical = datasets["H"]

    bounds = {}

    for col in numeric_features:

        series = pd.to_numeric(
            historical[col],
            errors="coerce"
        ).dropna()

        if series.empty:

            continue

        q1 = series.quantile(0.25)

        q3 = series.quantile(0.75)

        iqr = q3 - q1

        lower = (
            q1 - IQR_MULTIPLIER * iqr
        )

        upper = (
            q3 + IQR_MULTIPLIER * iqr
        )

        bounds[col] = (
            lower,
            upper
        )

    for label, data in datasets.items():

        data["iqr_flag"] = 0

        if data.empty:

            continue

        anomaly_indexes = set()

        for col in numeric_features:

            if col not in bounds:

                continue

            lower, upper = bounds[col]

            condition = (
                (data[col] < lower)
                |
                (data[col] > upper)
            )

            indexes = data.index[
                condition.fillna(False)
            ]

            anomaly_indexes.update(
                indexes.tolist()
            )

        if anomaly_indexes:

            data.loc[
                list(anomaly_indexes),
                "iqr_flag"
            ] = 1

        print(
            f"{label}: "
            f"{int(data['iqr_flag'].sum())}/"
            f"{len(data)} anomalies"
        )

    return datasets


# ============================================================
# 13. MISSINGNESS
# ============================================================

def run_missingness(datasets):

    print("\n" + "=" * 80)

    print("MISSINGNESS DETECTION")

    print("=" * 80)

    for label, data in datasets.items():

        data["missing_flag"] = 0

        if data.empty:

            continue

        # V5 rule:
        # Missingness is evaluated primarily
        # against CURRENT_MONTH.

        if label != "B":

            print(
                f"{label}: skipped "
                f"(baseline data)"
            )

            continue

        excluded = [
            "batch_id",
            "record_id",
            "businessID",
            "businessName",
            "segment",
            "industry",
            "data_lineage",
            "data_month",
            "riskProfile",
            "loaded_at"
        ]

        check_columns = [
            col
            for col in data.columns
            if col not in excluded
        ]

        null_counts = (
            data[check_columns]
            .isna()
            .sum(axis=1)
        )

        data["missing_flag"] = (
            null_counts > 0
        ).astype(int)

        print(
            f"B: "
            f"{int(data['missing_flag'].sum())}/"
            f"{len(data)} records have missing values"
        )

    return datasets


# ============================================================
# 14. DUPLICATE DETECTION
# ============================================================

def run_duplicates(datasets):

    print("\n" + "=" * 80)

    print("DUPLICATE DETECTION")

    print("=" * 80)

    for label, data in datasets.items():

        if data.empty:

            data["duplicate_flag"] = 0

            continue

        duplicate_flags = data.duplicated(
            keep=False
        )

        data["duplicate_flag"] = (
            duplicate_flags.astype(int)
        )

        print(
            f"{label}: "
            f"{int(data['duplicate_flag'].sum())}/"
            f"{len(data)} duplicate records"
        )

    return datasets


# ============================================================
# 15. ARIMA
# ============================================================

def run_arima(datasets):

    print("\n" + "=" * 80)

    print("ARIMA ANOMALY DETECTION")

    print("=" * 80)

    for data in datasets.values():

        data["arima_flag"] = 0

        data["arima_col_flag_count"] = 0

    if not HAS_ARIMA:

        print(
            "statsmodels is not installed."
        )

        print(
            "ARIMA will be skipped."
        )

        return datasets

    H = datasets["H"]

    A = datasets["A"]

    B = datasets["B"]

    if B.empty:

        print(
            "No CURRENT_MONTH data."
        )

        return datasets

    train = pd.concat(
        [H, A],
        ignore_index=True
    )

    print(
        f"ARIMA training records: {len(train)}"
    )

    print(
        f"Current-month records: {len(B)}"
    )

    processed = 0

    skipped = 0

    # --------------------------------------------------------
    # For each business
    # --------------------------------------------------------

    for business_id, train_business in train.groupby(
        "businessID"
    ):

        business_key = str(
            business_id
        )

        b_rows = B[
            B["businessID"].astype(str)
            == business_key
        ]

        if b_rows.empty:

            continue

        row_flag_counts = np.zeros(
            len(b_rows),
            dtype=int
        )

        # ----------------------------------------------------
        # Each ARIMA feature
        # ----------------------------------------------------

        for feature in ARIMA_FEATURES:

            if feature not in train_business.columns:

                continue

            if feature not in B.columns:

                continue

            # Use actual data_month ordering.
            monthly = (
                train_business
                .dropna(subset=[feature])
                .groupby("data_month")[feature]
                .mean()
            )

            if monthly.empty:

                skipped += 1

                continue

            try:

                # Convert YYYY-MM values into sortable order.
                monthly.index = (
                    monthly.index
                    .astype(str)
                )

                monthly = monthly.sort_index()

                values = monthly.values

                if len(values) < ARIMA_MIN_TRAIN_POINTS:

                    skipped += 1

                    continue

                model = ARIMA(
                    values,
                    order=ARIMA_ORDER
                )

                fitted = model.fit()

                forecast = float(
                    fitted.forecast(
                        steps=1
                    )[0]
                )

                residuals = (
                    np.asarray(
                        fitted.resid,
                        dtype=float
                    )
                )

                residual_std = float(
                    np.std(residuals)
                )

                if not np.isfinite(
                    residual_std
                ) or residual_std == 0:

                    residual_std = 1.0

                threshold = (
                    ARIMA_SIGMA_K
                    * residual_std
                )

                actual = pd.to_numeric(
                    b_rows[feature],
                    errors="coerce"
                ).to_numpy(
                    dtype=float
                )

                valid = np.isfinite(
                    actual
                )

                if valid.any():

                    deviations = np.abs(
                        actual[valid]
                        - forecast
                    )

                    row_flag_counts[valid] += (
                        deviations > threshold
                    ).astype(int)

                processed += 1

            except Exception:

                skipped += 1

                continue

        # ----------------------------------------------------
        # Write flags back
        # ----------------------------------------------------

        B.loc[
            b_rows.index,
            "arima_col_flag_count"
        ] = row_flag_counts

    B["arima_flag"] = (
        B["arima_col_flag_count"]
        >= ARIMA_MIN_COL_FLAGS
    ).astype(int)

    print(
        f"ARIMA B anomalies: "
        f"{int(B['arima_flag'].sum())}/"
        f"{len(B)}"
    )

    print(
        f"ARIMA series processed: {processed}"
    )

    print(
        f"ARIMA series skipped: {skipped}"
    )

    datasets["B"] = B

    return datasets


# ============================================================
# 16. PSI
# ============================================================

def compute_psi(
    expected,
    actual,
    bins=10
):

    expected = np.asarray(
        expected,
        dtype=float
    )

    actual = np.asarray(
        actual,
        dtype=float
    )

    expected = expected[
        np.isfinite(expected)
    ]

    actual = actual[
        np.isfinite(actual)
    ]

    if (
        len(expected) == 0
        or len(actual) == 0
    ):

        return 0.0

    # --------------------------------------------------------
    # Constant reference
    # --------------------------------------------------------

    if np.nanmin(expected) == np.nanmax(expected):

        ref_value = expected[0]

        expected_less = np.mean(
            expected < ref_value
        )

        actual_less = np.mean(
            actual < ref_value
        )

        if len(actual) == 0:

            return 0.0

    # --------------------------------------------------------
    # Normal PSI
    # --------------------------------------------------------

    percentiles = np.linspace(
        0,
        100,
        bins + 1
    )

    breakpoints = np.percentile(
        expected,
        percentiles
    )

    breakpoints = np.unique(
        breakpoints
    )

    if len(breakpoints) < 2:

        return 0.0

    expected_counts, _ = np.histogram(
        expected,
        bins=breakpoints
    )

    actual_counts, _ = np.histogram(
        actual,
        bins=breakpoints
    )

    expected_pct = (
        expected_counts
        / len(expected)
    )

    actual_pct = (
        actual_counts
        / len(actual)
    )

    expected_pct = np.where(
        expected_pct <= 0,
        1e-6,
        expected_pct
    )

    actual_pct = np.where(
        actual_pct <= 0,
        1e-6,
        actual_pct
    )

    psi = np.sum(
        (
            actual_pct
            - expected_pct
        )
        *
        np.log(
            actual_pct
            / expected_pct
        )
    )

    return float(
        max(0.0, psi)
    )


# ============================================================
# 17. WELCH DRIFT
# ============================================================

def compute_welch_drift(
    reference,
    current,
    features
):

    scores = []

    for feature in features:

        x_ref = pd.to_numeric(
            reference[feature],
            errors="coerce"
        ).dropna().to_numpy()

        x_cur = pd.to_numeric(
            current[feature],
            errors="coerce"
        ).dropna().to_numpy()

        if (
            len(x_ref) < 2
            or len(x_cur) < 2
        ):

            continue

        try:

            _, p_value = ttest_ind(
                x_ref,
                x_cur,
                equal_var=False
            )

            var_ref = np.var(
                x_ref,
                ddof=1
            )

            var_cur = np.var(
                x_cur,
                ddof=1
            )

            pooled_std = np.sqrt(
                (var_ref + var_cur)
                / 2.0
            )

            if (
                not np.isfinite(
                    pooled_std
                )
                or pooled_std == 0
            ):

                continue

            effect = (
                np.mean(x_cur)
                - np.mean(x_ref)
            ) / pooled_std

            magnitude = (
                1
                - np.exp(
                    -abs(effect)
                )
            )

            confidence = (
                1
                - p_value
            )

            score = (
                magnitude
                * confidence
            )

            scores.append(
                float(
                    np.clip(
                        score,
                        0,
                        1
                    )
                )
            )

        except Exception:

            continue

    if not scores:

        return 0.0

    return float(
        np.mean(scores)
    )


# ============================================================
# 18. MAHALANOBIS DRIFT
# ============================================================

def compute_mahalanobis(
    reference,
    current,
    features
):

    ref = reference[
        features
    ].apply(
        pd.to_numeric,
        errors="coerce"
    )

    cur = current[
        features
    ].apply(
        pd.to_numeric,
        errors="coerce"
    )

    # Fill using reference means
    means = ref.mean()

    ref = ref.fillna(means)

    cur = cur.fillna(means)

    ref_values = ref.to_numpy(
        dtype=float
    )

    cur_values = cur.to_numpy(
        dtype=float
    )

    if ref_values.shape[1] == 0:

        return np.zeros(
            len(cur_values)
        )

    variance = np.var(
        ref_values,
        axis=0
    )

    valid = variance > 1e-12

    if not valid.any():

        return np.zeros(
            len(cur_values)
        )

    ref_values = ref_values[
        :, valid
    ]

    cur_values = cur_values[
        :, valid
    ]

    valid_means = means.to_numpy()[
        valid
    ]

    # --------------------------------------------------------
    # Covariance
    # --------------------------------------------------------

    if ref_values.shape[1] == 1:

        variance_value = np.var(
            ref_values[:, 0]
        )

        if variance_value <= 1e-12:

            return np.zeros(
                len(cur_values)
            )

        diff = (
            cur_values[:, 0]
            - valid_means[0]
        )

        return np.abs(
            diff
        ) / np.sqrt(
            variance_value
        )

    covariance = np.cov(
        ref_values,
        rowvar=False
    )

    if covariance.ndim == 0:

        covariance = np.array(
            [[float(covariance)]]
        )

    if covariance.ndim == 1:

        covariance = np.diag(
            covariance
        )

    trace = np.trace(
        covariance
    )

    if not np.isfinite(trace):

        trace = 1.0

    eps = (
        1e-6
        * max(
            trace,
            1.0
        )
        / covariance.shape[0]
    )

    covariance_regularized = (
        covariance
        + eps
        * np.eye(
            covariance.shape[0]
        )
    )

    inverse_covariance = np.linalg.pinv(
        covariance_regularized
    )

    diff = (
        cur_values
        - valid_means
    )

    mahal_squared = np.sum(
        (
            diff
            @ inverse_covariance
        )
        * diff,
        axis=1
    )

    mahal_squared = np.maximum(
        mahal_squared,
        0
    )

    return np.sqrt(
        mahal_squared
    )


# ============================================================
# 19. DRIFT CALCULATION
# ============================================================

def run_drift(datasets, numeric_features):
    """Calculate record-level drift scores for each chronological batch.

    The first batch establishes the baseline (1.0 by definition because no
    earlier batch exists). Each subsequent batch is compared with all prior
    batches. This avoids assigning 1.0 to every historical batch by default.
    """
    print("\n" + "=" * 80)
    print("DRIFT DETECTION BY MONTHLY BATCH")
    print("=" * 80)

    non_empty = [df for df in datasets.values() if not df.empty]
    if not non_empty:
        return datasets

    all_rows = pd.concat(non_empty, ignore_index=True)
    if "batch_id" not in all_rows.columns:
        raise KeyError("batch_id is required for monthly drift calculation")

    # Batch IDs are formatted V5_YYYY_MM, so lexical ordering is chronological.
    batch_ids = sorted(all_rows["batch_id"].dropna().astype(str).unique())
    available_features = [
        f for f in numeric_features
        if f in all_rows.columns and pd.api.types.is_numeric_dtype(all_rows[f])
    ]
    if not available_features:
        available_features = [
            f for f in numeric_features if f in all_rows.columns
        ]
    if not available_features:
        raise ValueError("No numeric features available for drift calculation")

    # Initialize explicit output fields; every batch receives calculated values
    # or the documented first-batch baseline values.
    for df in non_empty:
        df["drift_health"] = np.nan
        df["mahalanobis_score"] = 0.0
        df["welch_score"] = 0.0
        df["psi_score"] = 0.0

    for position, batch_id in enumerate(batch_ids):
        current = all_rows[all_rows["batch_id"].astype(str) == batch_id].copy()
        current_idx = current.index

        if position == 0:
            # The earliest available month is the initial reference baseline.
            all_rows.loc[current_idx, "drift_health"] = 1.0
            all_rows.loc[current_idx, "mahalanobis_score"] = 0.0
            all_rows.loc[current_idx, "welch_score"] = 0.0
            all_rows.loc[current_idx, "psi_score"] = 0.0
            print(f"{batch_id}: initial baseline; drift health = 1.000000 (not comparable)")
            continue

        prior_ids = set(batch_ids[:position])
        reference = all_rows[all_rows["batch_id"].astype(str).isin(prior_ids)].copy()
        if len(reference) < 2 or len(current) < 2:
            all_rows.loc[current_idx, "drift_health"] = 1.0
            print(f"{batch_id}: insufficient comparison data; using neutral score")
            continue

        psi_values = []
        for feature in available_features:
            ref_values = pd.to_numeric(reference[feature], errors="coerce").dropna().to_numpy()
            cur_values = pd.to_numeric(current[feature], errors="coerce").dropna().to_numpy()
            if len(ref_values) and len(cur_values):
                psi_values.append(compute_psi(ref_values, cur_values))
        dataset_psi = float(np.mean(psi_values)) if psi_values else 0.0
        psi_health = float(np.exp(-dataset_psi))

        mahal_current = compute_mahalanobis(reference, current, available_features)
        mahal_reference = compute_mahalanobis(reference, reference, available_features)
        finite_reference = mahal_reference[np.isfinite(mahal_reference)]
        finite_current = np.where(np.isfinite(mahal_current), mahal_current, 0.0)
        # Calibrate distance against the historical 99th percentile. A zero
        # baseline spread is treated as no usable distance signal, not as drift.
        scale = float(np.quantile(finite_reference, 0.99)) if len(finite_reference) else 0.0
        if scale > 1e-12:
            mahal_norm = np.clip(finite_current / scale, 0.0, 1.0)
        else:
            mahal_norm = np.zeros(len(current), dtype=float)
        mahal_health = 1.0 - mahal_norm

        welch_severity = compute_welch_drift(reference, current, available_features)
        welch_health = float(np.clip(1.0 - welch_severity, 0.0, 1.0))
        drift = np.clip(
            WEIGHT_MAHAL * mahal_health
            + WEIGHT_WELCH * welch_health
            + WEIGHT_PSI * psi_health,
            0.0,
            1.0,
        )

        all_rows.loc[current_idx, "drift_health"] = drift
        all_rows.loc[current_idx, "mahalanobis_score"] = mahal_norm
        all_rows.loc[current_idx, "welch_score"] = welch_severity
        all_rows.loc[current_idx, "psi_score"] = dataset_psi
        print(
            f"{batch_id}: reference_batches={position}, records={len(current)}, "
            f"PSI={dataset_psi:.6f}, drift_health={float(np.mean(drift)):.6f}"
        )

    # Put the updated calculated values back into their original H/A/B frames.
    # Use stable identity columns so duplicate index labels across frames do not matter.
    key_cols = ["batch_id", "record_id"]
    metric_cols = ["drift_health", "mahalanobis_score", "welch_score", "psi_score"]
    metrics = all_rows[key_cols + metric_cols].drop_duplicates(key_cols).set_index(key_cols)
    for label, df in datasets.items():
        if df.empty:
            continue
        values = []
        for _, row in df.iterrows():
            key = (str(row["batch_id"]), row["record_id"])
            if key in metrics.index:
                m = metrics.loc[key]
                values.append([m[c] for c in metric_cols])
            else:
                values.append([1.0, 0.0, 0.0, 0.0])
        df.loc[:, metric_cols] = np.asarray(values, dtype=float)
        datasets[label] = df

    return datasets


# ============================================================
# 20. FRESHNESS HEALTH
# ============================================================

def run_freshness(datasets):

    print("\n" + "=" * 80)

    print("FRESHNESS HEALTH")

    print("=" * 80)

    for label, data in datasets.items():

        if data.empty:

            data["freshness_health"] = 1.0

            continue

        if FRESHNESS_COL not in data.columns:

            print(
                f"{label}: freshness column missing."
            )

            data["freshness_health"] = 1.0

            continue

        days_late = pd.to_numeric(
            data[FRESHNESS_COL],
            errors="coerce"
        )

        days_late = (
            days_late
            .fillna(0)
            .clip(lower=0)
        )

        data[
            "freshness_days_late_clean"
        ] = days_late

        data[
            "freshness_health"
        ] = np.exp(
            -days_late
            / FRESHNESS_TAU
        )

        print(
            f"{label}: "
            f"mean freshness health = "
            f"{data['freshness_health'].mean():.6f}"
        )

    return datasets


# ============================================================
# 21. COMBINE ANOMALY FLAGS
# ============================================================

def calculate_anomaly_health(datasets):

    print("\n" + "=" * 80)

    print("FINAL ANOMALY HEALTH")

    print("=" * 80)

    required_flags = [
        "iso_flag",
        "iqr_flag",
        "missing_flag",
        "duplicate_flag",
        "knn_flag",
        "arima_flag"
    ]

    for label, data in datasets.items():

        if data.empty:

            continue

        for flag in required_flags:

            if flag not in data.columns:

                data[flag] = 0

            data[flag] = (
                data[flag]
                .fillna(0)
                .astype(int)
            )

        data[
            "overall_anomaly_risk"
        ] = (

            W_ISO
            * data["iso_flag"]

            +

            W_IQR
            * data["iqr_flag"]

            +

            W_MISSING
            * data["missing_flag"]

            +

            W_DUPLICATE
            * data["duplicate_flag"]

            +

            W_KNN
            * data["knn_flag"]

            +

            W_ARIMA
            * data["arima_flag"]
        )

        data[
            "anomaly_health"
        ] = (

            1
            - data[
                "overall_anomaly_risk"
            ]
        ).clip(
            0,
            1
        )

        print(
            f"{label}: "
            f"anomaly health = "
            f"{data['anomaly_health'].mean():.6f}"
        )

    return datasets


# ============================================================
# 22. SAVE RESULTS TO ORACLE
# ============================================================

def save_results_to_oracle(
    conn,
    datasets
):

    print("\n" + "=" * 80)

    print("SAVING RESULTS TO ORACLE")

    print("=" * 80)

    cursor = conn.cursor()

    # --------------------------------------------------------
    # Delete previous calculated results for the same batches
    # --------------------------------------------------------

    batch_ids = sorted(
        set(
            pd.concat(
                [
                    data[
                        "batch_id"
                    ]
                    for data in datasets.values()
                    if not data.empty
                ]
            ).astype(str)
        )
    )

    print(
        f"Batches to replace: {batch_ids}"
    )

    for batch_id in batch_ids:

        cursor.execute(
            f"""
            DELETE FROM {RESULT_TABLE}
            WHERE BATCH_ID = :batch_id
            """,
            batch_id=batch_id
        )

    # --------------------------------------------------------
    # Prepare rows
    # --------------------------------------------------------

    rows = []

    for label, data in datasets.items():

        if data.empty:

            continue

        for _, row in data.iterrows():

            rows.append(
                (
                    str(row["batch_id"]),

                    int(row["record_id"]),

                    (
                        None
                        if pd.isna(
                            row["businessID"]
                        )
                        else str(
                            row["businessID"]
                        )
                    ),

                    str(
                        row["data_lineage"]
                    ),

                    str(
                        row["data_month"]
                    ),

                    int(
                        row["iso_flag"]
                    ),

                    int(
                        row["iqr_flag"]
                    ),

                    int(
                        row["knn_flag"]
                    ),

                    int(
                        row["missing_flag"]
                    ),

                    int(
                        row["duplicate_flag"]
                    ),

                    int(
                        row["arima_flag"]
                    ),

                    float(
                        row[
                            "overall_anomaly_risk"
                        ]
                    ),

                    float(
                        row[
                            "anomaly_health"
                        ]
                    ),

                    float(
                        row.get(
                            "drift_health",
                            1.0
                        )
                    ),

                    float(
                        row.get(
                            "mahalanobis_score",
                            0.0
                        )
                    ),

                    float(
                        row.get(
                            "welch_score",
                            0.0
                        )
                    ),

                    float(
                        row.get(
                            "psi_score",
                            0.0
                        )
                    ),

                    float(
                        row.get(
                            "freshness_health",
                            1.0
                        )
                    )
                )
            )

    # --------------------------------------------------------
    # Insert
    # --------------------------------------------------------

    insert_sql = f"""
        INSERT INTO {RESULT_TABLE}
        (
            BATCH_ID,
            RECORD_ID,
            BUSINESSID,

            DATA_LINEAGE,
            DATA_MONTH,

            ISO_FLAG,
            IQR_FLAG,
            KNN_FLAG,
            MISSING_FLAG,
            DUPLICATE_FLAG,
            ARIMA_FLAG,

            OVERALL_ANOMALY_RISK,
            ANOMALY_HEALTH,

            DRIFT_HEALTH,
            MAHALANOBIS_SCORE,
            WELCH_SCORE,
            PSI_SCORE,

            FRESHNESS_HEALTH
        )
        VALUES
        (
            :1,
            :2,
            :3,

            :4,
            :5,

            :6,
            :7,
            :8,
            :9,
            :10,
            :11,

            :12,
            :13,

            :14,
            :15,
            :16,
            :17,

            :18
        )
    """

    cursor.executemany(
        insert_sql,
        rows
    )

    conn.commit()

    print(
        f"Inserted {len(rows)} result rows."
    )

    cursor.close()

# ============================================================
# PL/SQL PROCESSING
# ============================================================

def run_plsql_process_batch(conn, batch_id):

    print("\n" + "=" * 80)
    print(f"RUNNING DELTAMAX V5 PL/SQL FOR BATCH: {batch_id}")
    print("=" * 80)

    cursor = conn.cursor()

    try:

        cursor.callproc(
            "DELTAMAX_V5_PKG.PROCESS_BATCH",
            [batch_id]
        )

        conn.commit()

        print(
            f"PL/SQL PROCESS_BATCH completed successfully "
            f"for {batch_id}"
        )

    except Exception as e:

        conn.rollback()

        print("\nPL/SQL PROCESS_BATCH FAILED")
        print(f"Batch ID : {batch_id}")
        print(f"Error    : {e}")

        raise

    finally:

        cursor.close()


def read_final_trust(conn, batch_id):

    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                TOTAL_RECORDS,
                ANOMALY_HEALTH,
                DRIFT_HEALTH,
                BUSINESS_HEALTH,
                FRESHNESS_HEALTH,
                OVERALL_DATASET_TRUST
            FROM DM_V5_TRUST_RESULTS
            WHERE BATCH_ID = :batch_id
            """,
            {
                "batch_id": batch_id
            }
        )

        row = cursor.fetchone()

        if row is None:

            raise RuntimeError(
                f"No trust result found for batch {batch_id}"
            )

        print("\n" + "=" * 80)
        print(f"FINAL DELTAMAX TRUST RESULT - {batch_id}")
        print("=" * 80)

        print(f"Total Records       : {row[0]}")
        print(f"Anomaly Health      : {row[1]}")
        print(f"Drift Health        : {row[2]}")
        print(f"Business Health     : {row[3]}")
        print(f"Freshness Health    : {row[4]}")
        print(f"Overall Trust Score : {row[5]}")

        print("=" * 80)

        return row

    finally:

        cursor.close()
# ============================================================
# 23. VERIFY ORACLE RESULTS
# ============================================================

def verify_results(conn):

    print("\n" + "=" * 80)

    print("VERIFYING ORACLE RESULTS")

    print("=" * 80)

    cursor = conn.cursor()

    # --------------------------------------------------------
    # Total rows
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM {RESULT_TABLE}
        """
    )

    total = cursor.fetchone()[0]

    print(
        f"Total anomaly result rows: {total}"
    )

    # --------------------------------------------------------
    # Lineage
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            DATA_LINEAGE,
            COUNT(*) AS RECORD_COUNT
        FROM {RESULT_TABLE}
        GROUP BY DATA_LINEAGE
        ORDER BY DATA_LINEAGE
        """
    )

    print("\nResults by lineage:")

    for row in cursor.fetchall():

        print(
            f"{row[0]:<30} {row[1]}"
        )

    # --------------------------------------------------------
    # Health summary
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            DATA_LINEAGE,
            COUNT(*) AS RECORD_COUNT,

            ROUND(
                AVG(ANOMALY_HEALTH),
                6
            ) AS ANOMALY_HEALTH,

            ROUND(
                AVG(DRIFT_HEALTH),
                6
            ) AS DRIFT_HEALTH,

            ROUND(
                AVG(FRESHNESS_HEALTH),
                6
            ) AS FRESHNESS_HEALTH

        FROM {RESULT_TABLE}

        GROUP BY DATA_LINEAGE

        ORDER BY DATA_LINEAGE
        """
    )

    print(
        "\nHealth summary:"
    )

    print(
        "LINEAGE | RECORDS | ANOMALY | DRIFT | FRESHNESS"
    )

    for row in cursor.fetchall():

        print(
            row
        )

    cursor.close()


# ============================================================
# 24. MAIN
# ============================================================

# ============================================================
# 24. MAIN
# ============================================================


def main():

    start_time = time.time()


    print("\n")
    print("=" * 80)
    print("DELtamax V5 TRUST / ANOMALY ENGINE")
    print("=" * 80)


    conn = None


    try:

        # ----------------------------------------------------
        # Connect
        # ----------------------------------------------------

        conn = get_connection()


        # ----------------------------------------------------
        # Create result table
        # ----------------------------------------------------

        create_result_table(conn)


        # ----------------------------------------------------
        # Read Oracle staging data
        # ----------------------------------------------------

        df = load_staging_data(conn)


        # ----------------------------------------------------
        # Print structure
        # ----------------------------------------------------

        print_dataset_structure(df)


        # ----------------------------------------------------
        # Split H/A/B
        # ----------------------------------------------------

        datasets = split_datasets(df)


        # ----------------------------------------------------
        # Determine available features
        # ----------------------------------------------------

        numeric_features = get_model_features(
            df
        )


        # ----------------------------------------------------
        # KNN
        # ----------------------------------------------------

        datasets = run_knn(
            datasets,
            numeric_features
        )


        # ----------------------------------------------------
        # Isolation Forest
        # ----------------------------------------------------

        datasets = run_isolation_forest(
            datasets,
            numeric_features
        )


        # ----------------------------------------------------
        # IQR
        # ----------------------------------------------------

        datasets = run_iqr(
            datasets,
            numeric_features
        )


        # ----------------------------------------------------
        # Missingness
        # ----------------------------------------------------

        datasets = run_missingness(
            datasets
        )


        # ----------------------------------------------------
        # Duplicate
        # ----------------------------------------------------

        datasets = run_duplicates(
            datasets
        )


        # ----------------------------------------------------
        # ARIMA
        # ----------------------------------------------------

        datasets = run_arima(
            datasets
        )


        # ----------------------------------------------------
        # Drift
        # ----------------------------------------------------

        datasets = run_drift(
            datasets,
            numeric_features
        )


        # ----------------------------------------------------
        # Freshness
        # ----------------------------------------------------

        datasets = run_freshness(
            datasets
        )


        # ----------------------------------------------------
        # Overall anomaly health
        # ----------------------------------------------------

        datasets = calculate_anomaly_health(
            datasets
        )


        # ----------------------------------------------------
        # Save Python anomaly results to Oracle
        # ----------------------------------------------------

        save_results_to_oracle(
            conn,
            datasets
        )


        # ----------------------------------------------------
        # Verify Python anomaly results
        # ----------------------------------------------------

        verify_results(
            conn
        )


        # ----------------------------------------------------
        # Run DeltaMax V5 PL/SQL
        # ----------------------------------------------------

        batch_ids = sorted(
            set(
                str(batch_id)
                for batch_id in df["batch_id"].dropna().unique()
            )
        )


        print("\n" + "=" * 80)
        print("STARTING PL/SQL PROCESSING")
        print("=" * 80)

        print(
            f"Number of batches to process: "
            f"{len(batch_ids)}"
        )


        for batch_id in batch_ids:

            print(
                f"\nProcessing batch: {batch_id}"
            )


            run_plsql_process_batch(
                conn,
                batch_id
            )


            read_final_trust(
                conn,
                batch_id
            )


        print("\n" + "=" * 80)
        print("PL/SQL PROCESSING COMPLETED")
        print("=" * 80)


        # ----------------------------------------------------
        # Overall summary
        # ----------------------------------------------------

        all_results = pd.concat(
            [
                data
                for data in datasets.values()
                if not data.empty
            ],
            ignore_index=True
        )


        print("\n" + "=" * 80)
        print("FINAL PYTHON CALCULATION SUMMARY")
        print("=" * 80)


        print(
            f"Total records: "
            f"{len(all_results)}"
        )


        print(
            f"Overall anomaly health: "
            f"{all_results['anomaly_health'].mean():.6f}"
        )


        print(
            f"Overall freshness health: "
            f"{all_results['freshness_health'].mean():.6f}"
        )


        if not datasets["B"].empty:

            print(
                f"Current-month anomaly health: "
                f"{datasets['B']['anomaly_health'].mean():.6f}"
            )


            print(
                f"Current-month drift health: "
                f"{datasets['B']['drift_health'].mean():.6f}"
            )


            print(
                f"Current-month freshness health: "
                f"{datasets['B']['freshness_health'].mean():.6f}"
            )


        elapsed = (
            time.time()
            - start_time
        )


        print(
            f"\nExecution time: "
            f"{elapsed:.2f} seconds"
        )


        print("\n" + "=" * 80)


        print(
            "03_Trust_Score.py completed successfully."
        )


        print(
            "No CSV files were created."
        )


        print(
            "No S3 operations were performed."
        )


        print(
            "Results stored in Oracle."
        )


        print(
            "PL/SQL quality and trust processing completed."
        )


        print("=" * 80)


    except Exception as e:


        print("\n" + "=" * 80)


        print(
            "ERROR IN 03_Trust_Score.py"
        )


        print("=" * 80)


        print(
            type(e).__name__,
            ":",
            e
        )


        if conn:

            try:

                conn.rollback()

            except Exception:

                pass


        raise


    finally:


        if conn:

            conn.close()


            print(
                "\nOracle connection closed."
            )


# ============================================================
# RUN
# ============================================================


if __name__ == "__main__":

    main()