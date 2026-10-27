"""DeltaMax V5 FastAPI API.

Read-only API over the existing Oracle V5 result tables.
This layer exposes the V5 read API and starts the Oracle-backed migration pipeline.
"""
import os
import math
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import oracledb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pipeline_config import CONFIG_PATH, DEFAULT_PARAMS, load_config, validate_params

ORACLE_USER = os.getenv("DELTAMAX_ORACLE_USER", "DELTAMAX_V5")
ORACLE_PASSWORD = os.getenv("DELTAMAX_ORACLE_PASSWORD", "DeltaMaxV5@2026")
ORACLE_DSN = os.getenv("DELTAMAX_ORACLE_DSN", "localhost:1521/FREEPDB1")
DRIFT_SUMMARY_PATH = Path(__file__).resolve().parents[1] / "results" / "drift_summary.json"

# The migration runner uses the same Oracle schema by default. MIG_DB_* values
# remain explicit overrides for deployments that keep the migration schema separate.
_connect_host, _connect_service = ORACLE_DSN.rsplit("/", 1)
_host, _separator, _port = _connect_host.rpartition(":")
os.environ.setdefault("MIG_DB_USER", ORACLE_USER)
os.environ.setdefault("MIG_DB_PASSWORD", ORACLE_PASSWORD)
os.environ.setdefault("MIG_DB_HOST", _host if _separator else _connect_host)
os.environ.setdefault("MIG_DB_PORT", _port if _separator else "1521")
os.environ.setdefault("MIG_DB_SERVICE", _connect_service)

from api.migration_runner import router as migration_router
from api import migration_runner as migration_service

app = FastAPI(title="DeltaMax V5 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(migration_router)


def get_connection():
    try:
        return oracledb.connect(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Oracle connection failed: {exc}") from exc


def rows_as_dicts(cursor):
    columns = [d[0].lower() for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def clean_value(value: Any):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def clean_rows(rows):
    return [{k: clean_value(v) for k, v in row.items()} for row in rows]


@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT USER AS DB_USER FROM DUAL")
        row = cur.fetchone()
        return {"status": "ok", "database_user": row[0]}
    finally:
        conn.close()


@app.get("/api/batches")
def batches():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT BATCH_ID, COUNT(*) AS TOTAL_RECORDS
            FROM DM_V5_STG_CREDIT_BUREAU
            GROUP BY BATCH_ID
            ORDER BY BATCH_ID
        """)
        rows = rows_as_dicts(cur)
        return {"batches": clean_rows(rows)}
    finally:
        conn.close()


@app.get("/api/trust/trend")
def trust_trend():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT BATCH_ID, TOTAL_RECORDS, ANOMALY_HEALTH, DRIFT_HEALTH,
                   BUSINESS_HEALTH, FRESHNESS_HEALTH, OVERALL_DATASET_TRUST
            FROM DM_V5_TRUST_RESULTS
            ORDER BY BATCH_ID
        """)
        return {"trend": clean_rows(rows_as_dicts(cur))}
    finally:
        conn.close()


@app.get("/api/trust/{batch_id}")
def trust(batch_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT BATCH_ID, TOTAL_RECORDS, ANOMALY_HEALTH, DRIFT_HEALTH,
                   BUSINESS_HEALTH, FRESHNESS_HEALTH, OVERALL_DATASET_TRUST,
                   CREATED_AT
            FROM DM_V5_TRUST_RESULTS
            WHERE BATCH_ID = :batch_id
        """, {"batch_id": batch_id})
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Trust result not found: {batch_id}")
        return clean_rows([dict(zip([d[0].lower() for d in cur.description], row))])[0]
    finally:
        conn.close()


@app.get("/api/quality/{batch_id}")
def quality(batch_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS TOTAL_RECORDS,
                   NVL(SUM(CASE WHEN MISSING_FLAG = 1 THEN 1 ELSE 0 END), 0) AS MISSING_RECORDS,
                   NVL(SUM(CASE WHEN DUPLICATE_FLAG = 1 THEN 1 ELSE 0 END), 0) AS DUPLICATE_RECORDS,
                   NVL(SUM(NVL(BUSINESS_RULE_FLAGS, 0)), 0) AS TOTAL_BUSINESS_RULE_FLAGS,
                   MIN(QUALITY_HEALTH) AS MIN_QUALITY_HEALTH,
                   AVG(QUALITY_HEALTH) AS AVG_QUALITY_HEALTH
            FROM DM_V5_QUALITY_RESULTS
            WHERE BATCH_ID = :batch_id
        """, {"batch_id": batch_id})
        return clean_rows([dict(zip([d[0].lower() for d in cur.description], cur.fetchone()))])[0]
    finally:
        conn.close()


@app.get("/api/errors/{batch_id}")
def errors(batch_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT REASON_CODE, COUNT(*) AS ERROR_COUNT
            FROM DM_V5_ERROR_LOG
            WHERE BATCH_ID = :batch_id
            GROUP BY REASON_CODE
            ORDER BY ERROR_COUNT DESC
        """, {"batch_id": batch_id})
        return {"errors": clean_rows(rows_as_dicts(cur))}
    finally:
        conn.close()


@app.get("/api/anomalies/{batch_id}")
def anomalies(batch_id: str, limit: int = Query(50, ge=1, le=500)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT *
            FROM (
                SELECT BATCH_ID, RECORD_ID, BUSINESSID, DATA_LINEAGE, DATA_MONTH,
                       ISO_FLAG, IQR_FLAG, KNN_FLAG, MISSING_FLAG, DUPLICATE_FLAG,
                       ARIMA_FLAG, OVERALL_ANOMALY_RISK, ANOMALY_HEALTH,
                       DRIFT_HEALTH, MAHALANOBIS_SCORE, WELCH_SCORE, PSI_SCORE,
                       FRESHNESS_HEALTH, CREATED_AT
                FROM DM_V5_ANOMALY_RESULTS
                WHERE BATCH_ID = :batch_id
                ORDER BY OVERALL_ANOMALY_RISK DESC NULLS LAST
            )
            WHERE ROWNUM <= :limit
        """, {"batch_id": batch_id, "limit": limit})
        return {"anomalies": clean_rows(rows_as_dicts(cur))}
    finally:
        conn.close()


@app.get("/api/anomaly-record/{record_id}")
def anomaly_record_detail(record_id: int):
    """Record-level detail for the Core Engine anomaly popup."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT A.BATCH_ID AS A_BATCH_ID, A.RECORD_ID AS A_RECORD_ID,
                   A.BUSINESSID AS A_BUSINESSID, A.DATA_LINEAGE AS A_DATA_LINEAGE,
                   A.DATA_MONTH AS A_DATA_MONTH, A.ISO_FLAG AS A_ISO_FLAG,
                   A.IQR_FLAG AS A_IQR_FLAG, A.KNN_FLAG AS A_KNN_FLAG,
                   A.MISSING_FLAG AS A_MISSING_FLAG, A.DUPLICATE_FLAG AS A_DUPLICATE_FLAG,
                   A.ARIMA_FLAG AS A_ARIMA_FLAG, A.OVERALL_ANOMALY_RISK AS A_RISK,
                   A.ANOMALY_HEALTH AS A_ANOMALY_HEALTH, A.DRIFT_HEALTH AS A_DRIFT_HEALTH,
                   A.FRESHNESS_HEALTH AS A_FRESHNESS_HEALTH,
                   S.*
            FROM DM_V5_ANOMALY_RESULTS A
            LEFT JOIN DM_V5_STG_CREDIT_BUREAU S
              ON S.BATCH_ID = A.BATCH_ID AND S.RECORD_ID = A.RECORD_ID
            WHERE A.RECORD_ID = :record_id
            ORDER BY A.BATCH_ID DESC
            FETCH FIRST 1 ROW ONLY
        """, {"record_id": record_id})
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Anomaly record not found: {record_id}")
        record = clean_rows([dict(zip([d[0].lower() for d in cur.description], row))])[0]
        rename = {
            "businessid": "businessID", "businessname": "businessName",
            "creditscore": "creditScore", "annualrevenue": "annualRevenue",
            "outstandingdebt": "outstandingDebt", "totalcreditlimit": "totalCreditLimit",
            "availablecredit": "availableCredit", "paymenthistoryscore": "paymentHistoryScore",
            "creditutilizationratio": "creditUtilizationRatio", "numberofaccounts": "numberOfAccounts",
            "numberofinquiries": "numberOfInquiries", "hasdelinquency": "hasDelinquency",
            "hasdefaulted": "hasDefaulted", "hasbankruptcy": "hasBankruptcy",
            "delinquentaccountcount": "delinquentAccountCount", "collectionsCount".lower(): "collectionsCount",
            "chargeoffcount": "chargeoffCount", "judgmentcount": "judgmentCount",
            "taxliencount": "taxLienCount", "publicrecordcount": "publicRecordCount",
            "monthssincelastpayment": "monthsSinceLastPayment", "monthssincefirstaccount": "monthsSinceFirstAccount",
            "monthssincelastdelinquency": "monthsSinceLastDelinquency", "debttoincome_ratio": "debtToIncomeRatio",
            "creditworthinessscore": "creditWorthinessScore", "riskprofile": "riskProfile",
            "data_lineage": "data_lineage", "data_month": "data_month",
            "year_established": "yearEstablished", "employee_count": "employeeCount",
            "freshness_days_late": "freshness_days_late",
        }
        internal = {key for key in record if key.startswith("a_")}
        raw_record = {rename.get(key, key): value for key, value in record.items() if key not in internal}
        detector_defs = [
            ("iso_flag", "ISO", "Isolation Forest signal"),
            ("iqr_flag", "IQR", "Interquartile range outlier"),
            ("knn_flag", "KNN", "Nearest-neighbor outlier"),
            ("missing_flag", "Missing", "Missing data signal"),
            ("duplicate_flag", "Duplicate", "Duplicate record signal"),
            ("arima_flag", "ARIMA", "Time-series anomaly signal"),
        ]
        detectors = [{
            "key": key, "label": label, "meaning": meaning,
            "fired": bool(record.get(f"a_{key}")), "threshold": "V5 detector flag",
        } for key, label, meaning in detector_defs]
        drift_values = []
        try:
            cur.execute("""
                SELECT DRIFT_HEALTH FROM DM_V5_ANOMALY_RESULTS
                WHERE BATCH_ID = :batch_id AND DATA_LINEAGE = :lineage
            """, {"batch_id": record.get("a_batch_id"), "lineage": record.get("a_data_lineage")})
            drift_values = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
        except oracledb.DatabaseError:
            drift_values = []
        labels = ["0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"]
        bins = []
        for i, label in enumerate(labels):
            count = sum((min(int(v * 5), 4) == i) for v in drift_values)
            bins.append({"label": label, "count": count, "is_record": False})
        own_drift = float(record.get("a_drift_health") or 0)
        if drift_values:
            bins[min(int(own_drift * 5), 4)]["is_record"] = True

        risk = _percent(record.get("a_risk")) or 0
        fired_count = sum(item["fired"] for item in detectors)
        return {
            "ready": True, "record_id": record_id,
            "businessID": record.get("a_businessid"), "lineage": record.get("a_data_lineage"),
            "severity": "HIGH" if risk >= 70 else "MEDIUM" if risk >= 50 else "LOW",
            "overall_anomaly_risk": risk, "fired_count": fired_count,
            "raw_record": raw_record, "schema_anomaly_fields": [],
            "trust_metrics": {
                "overall_trust": None,
                "anomaly_health": _percent(record.get("a_anomaly_health")),
                "drift_health": _percent(record.get("a_drift_health")),
                "business_health": None,
                "freshness_health": _percent(record.get("a_freshness_health")),
            },
            "trust_threshold": None, "below_threshold": None, "detectors": detectors,
            "drift_distribution": {
                "lineage": record.get("a_data_lineage"), "lineage_records": len(drift_values),
                "record_drift_health": _percent(record.get("a_drift_health")), "bins": bins,
            } if drift_values else None,
            "business_rules": {
                "evaluable": False, "estimated_violations": None,
                "note": "Record-level business-rule details are not stored in the V5 anomaly results.",
                "catalogue": [],
            },
            "freshness_days_late": record.get("freshness_days_late"), "freshness_tau": None,
        }
    except oracledb.DatabaseError as exc:
        oracle_error = exc.args[0] if exc.args else None
        if getattr(oracle_error, "code", None) == 942:
            return {"ready": False, "error": "V5 anomaly or staging tables are not available yet."}
        raise
    finally:
        conn.close()


@app.get("/api/arima/forecasts")
def arima_forecasts(run_id: str | None = None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if run_id:
            cur.execute("""
                SELECT * FROM DM_V5_ARIMA_FORECASTS
                WHERE RUN_ID = :run_id
                ORDER BY SERIES_NAME, FORECAST_MONTH
            """, {"run_id": run_id})
        else:
            cur.execute("""
                SELECT * FROM DM_V5_ARIMA_FORECASTS
                WHERE RUN_ID = (SELECT MAX(RUN_ID) FROM DM_V5_ARIMA_FORECASTS)
                ORDER BY SERIES_NAME, FORECAST_MONTH
            """)
        return {"forecasts": clean_rows(rows_as_dicts(cur))}
    finally:
        conn.close()


@app.get("/api/arima/alerts")
def arima_alerts(run_id: str | None = None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if run_id:
            cur.execute("""
                SELECT * FROM DM_V5_ARIMA_ALERTS
                WHERE RUN_ID = :run_id
                ORDER BY SEVERITY, FORECAST_MONTH
            """, {"run_id": run_id})
        else:
            cur.execute("""
                SELECT * FROM DM_V5_ARIMA_ALERTS
                WHERE RUN_ID = (SELECT MAX(RUN_ID) FROM DM_V5_ARIMA_ALERTS)
                ORDER BY SEVERITY, FORECAST_MONTH
            """)
        rows = clean_rows(rows_as_dicts(cur))
        summary = {}
        for row in rows:
            sev = row.get("severity") or "UNKNOWN"
            summary[sev] = summary.get(sev, 0) + 1
        return {"summary": summary, "alerts": rows}
    finally:
        conn.close()


@app.get("/api/alerts")
def executive_alerts():
    """Compatibility response for the Executive AI alerts page, backed by V5 ARIMA rows."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        forecasts, alerts, available = _latest_arima_results(cur)
        if not available:
            return {"ready": False, "hint": "No ARIMA results are available yet. Run 04_ARIMA_Predictive_Trust_Alerts.py."}
        forecast_lookup = {
            ((r.get("series_name") or "").lower(), str(r.get("forecast_month"))): r
            for r in forecasts
        }
        output = []
        for row in alerts:
            key = ((row.get("series_name") or "").lower(), str(row.get("forecast_month")))
            forecast = forecast_lookup.get(key, {})
            trust_series = key[0] in {"anomaly_health", "drift_health", "business_health", "freshness_health", "overall_dataset_trust"}
            scale = _percent if trust_series else lambda value: value
            output.append({
                "metric": row.get("series_name"), "trigger": row.get("trigger_type"),
                "month": row.get("forecast_month"), "severity": row.get("severity"),
                "forecast": scale(forecast.get("forecast_value")),
                "threshold": scale(forecast.get("threshold_value")),
                "reason": row.get("reason"),
            })
        return {"ready": True, "alerts": output}
    finally:
        conn.close()


@app.get("/api/churn/{batch_id}")
def churn(batch_id: str, limit: int = Query(100, ge=1, le=1000)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT RISK_TIER, COUNT(*) AS RISK_COUNT
            FROM DM_V5_CHURN_RISK_RESULTS
            WHERE BATCH_ID = :batch_id
            GROUP BY RISK_TIER
            ORDER BY RISK_TIER
        """, {"batch_id": batch_id})
        summary = clean_rows(rows_as_dicts(cur))

        cur.execute("""
            SELECT * FROM (
                SELECT BATCH_ID, BUSINESSID, BUSINESSNAME, CHURN_PROBABILITY,
                       RISK_TIER, LIKELY_CHURN_REASON, PREDICTED_CHURN_BY,
                       TOP_RISK_FACTORS, CREATED_AT
                FROM DM_V5_CHURN_RISK_RESULTS
                WHERE BATCH_ID = :batch_id
                ORDER BY CHURN_PROBABILITY DESC NULLS LAST
            )
            WHERE ROWNUM <= :limit
        """, {"batch_id": batch_id, "limit": limit})
        results = clean_rows(rows_as_dicts(cur))
        return {"available": bool(results), "summary": summary, "results": results}
    finally:
        conn.close()


@app.get("/api/churn/{batch_id}/metrics")
def churn_metrics(batch_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM DM_V5_CHURN_MODEL_METRICS
            WHERE BATCH_ID = :batch_id
            ORDER BY CREATED_AT DESC
            FETCH FIRST 1 ROW ONLY
        """, {"batch_id": batch_id})
        row = cur.fetchone()
        if row is None:
            return {
                "available": False,
                "batch_id": batch_id,
                "message": "Churn model metrics are not available for this batch yet."
            }
        result = clean_rows([dict(zip([d[0].lower() for d in cur.description], row))])[0]
        result["available"] = True
        return result
    finally:
        conn.close()


ENGINE_METHODS = (
    ("ISO", "iso_flag"),
    ("IQR", "iqr_flag"),
    ("KNN", "knn_flag"),
    ("Missing", "missing_flag"),
    ("Duplicate", "duplicate_flag"),
    ("ARIMA", "arima_flag"),
)


@app.get("/api/hyperparams")
def get_hyperparams():
    try:
        params, _ = load_config()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not load hyperparameter configuration: {exc}") from exc
    return {
        "ready": True,
        "params": params,
        "defaults": dict(DEFAULT_PARAMS),
        "supported_params": list(DEFAULT_PARAMS),
    }


@app.post("/api/hyperparams")
def save_hyperparams(payload: dict[str, Any]):
    try:
        current, history = load_config()
        changes = validate_params(payload.get("params"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = {**current, **changes}
    name = payload.get("name", "Custom config")
    if not isinstance(name, str) or len(name) > 100:
        raise HTTPException(status_code=400, detail="name must be a string of at most 100 characters")

    history.insert(0, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name.strip() or "Custom config",
        "params": updated,
    })
    history = history[:100]
    CONFIG_PATH.write_text(
        json.dumps({"params": updated, "history": history}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"success": True, "params": updated}


@app.get("/api/hyperparams/history")
def hyperparams_history():
    try:
        _, history = load_config()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not load hyperparameter history: {exc}") from exc
    return {"ready": True, "history": history}


def _engine_rows(cur):
    cur.execute("""
        SELECT A.BATCH_ID, A.RECORD_ID, A.BUSINESSID, A.DATA_LINEAGE,
               A.DATA_MONTH, A.ISO_FLAG, A.IQR_FLAG, A.KNN_FLAG,
               A.MISSING_FLAG, A.DUPLICATE_FLAG, A.ARIMA_FLAG,
               A.OVERALL_ANOMALY_RISK, A.ANOMALY_HEALTH, A.DRIFT_HEALTH,
               A.MAHALANOBIS_SCORE, A.WELCH_SCORE, A.PSI_SCORE,
               A.FRESHNESS_HEALTH, S.FRESHNESS_DAYS_LATE
        FROM DM_V5_ANOMALY_RESULTS A
        LEFT JOIN DM_V5_STG_CREDIT_BUREAU S
          ON S.BATCH_ID = A.BATCH_ID AND S.RECORD_ID = A.RECORD_ID
        ORDER BY A.BATCH_ID, A.RECORD_ID
    """)
    return clean_rows(rows_as_dicts(cur))


def _engine_current_trust(cur):
    cur.execute("""
        SELECT BATCH_ID, OVERALL_DATASET_TRUST, DRIFT_HEALTH,
               BUSINESS_HEALTH, FRESHNESS_HEALTH
        FROM DM_V5_TRUST_RESULTS
        ORDER BY BATCH_ID
    """)
    rows = clean_rows(rows_as_dicts(cur))
    return rows[-1] if rows else None


def _engine_flagged(row):
    return any(row.get(column) for _, column in ENGINE_METHODS)


def _engine_percent(value):
    return _percent(value)


@app.get("/api/anomaly-records")
def anomaly_records(lineage: str = "all", limit: int = Query(100, ge=1, le=500), business: str | None = None):
    """V5 anomaly results formatted for the Executive AI affected-records view."""
    conn = get_connection()
    try:
        rows = _engine_rows(conn.cursor())
        if not rows:
            return {"ready": False, "hint": "No anomaly results found. Run the V5 trust pipeline first."}
        total = len(rows)
        total_flagged = sum(_engine_flagged(row) for row in rows)
        total_businesses = len({row.get("businessid") for row in rows if row.get("businessid")})
        business_rows = defaultdict(list)
        for row in rows:
            if row.get("businessid"):
                business_rows[row["businessid"]].append(row)
        anomalous_businesses = {bid for bid, group in business_rows.items() if any(_engine_flagged(r) for r in group)}
        by_detector = {
            label: sum(bool(row.get(column)) for row in rows)
            for label, column in ENGINE_METHODS
        }
        selected = rows
        if business:
            selected = [row for row in selected if str(row.get("businessid")) == business]
        lineage = lineage.upper()
        lineage_value = {"B": "CURRENT_MONTH", "A": "PREVIOUS_MONTH", "H": "HISTORICAL"}.get(lineage)
        if lineage_value:
            selected = [row for row in selected if row.get("data_lineage") == lineage_value]
        selected.sort(key=lambda row: row.get("overall_anomaly_risk") or 0, reverse=True)
        records = []
        for row in selected[:limit]:
            risk = _percent(row.get("overall_anomaly_risk")) or 0
            fired_count = sum(bool(row.get(column)) for _, column in ENGINE_METHODS)
            records.append({
                "record_id": row.get("record_id"), "businessID": row.get("businessid"),
                "lineage": row.get("data_lineage"), "trust": _percent(row.get("anomaly_health")),
                "anomaly_risk": risk, "severity": "HIGH" if risk >= 70 else "MEDIUM" if risk >= 50 else "LOW",
                "fired_count": fired_count,
            })
        businesses = []
        for bid, group in business_rows.items():
            flagged = [row for row in group if _engine_flagged(row)]
            if flagged:
                businesses.append({
                    "businessID": bid, "records": len(group), "anomalous": len(flagged),
                    "worst_risk": max((_percent(r.get("overall_anomaly_risk")) or 0) for r in flagged),
                })
        businesses.sort(key=lambda row: row["worst_risk"], reverse=True)
        return {
            "ready": True, "total_records": total, "total_businesses": total_businesses,
            "total_anomalous_records": total_flagged, "below_threshold_count": total_flagged,
            "anomalous_businesses": len(anomalous_businesses), "trust_threshold": 75,
            "risk_threshold": 50, "records": records, "businesses": businesses,
            "by_detector": by_detector,
        }
    except oracledb.DatabaseError as exc:
        oracle_error = exc.args[0] if exc.args else None
        if getattr(oracle_error, "code", None) == 942:
            return {"ready": False, "hint": "Anomaly result tables are not available yet. Run the V5 trust pipeline first."}
        raise
    finally:
        conn.close()


@app.get("/api/churn-risk")
def executive_churn_risk(tier: str = "all", limit: int = Query(100, ge=1, le=1000)):
    """Latest V5 churn scores formatted for the Executive AI churn-risk view."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(BATCH_ID) FROM DM_V5_CHURN_RISK_RESULTS")
        batch_id = cur.fetchone()[0]
        if not batch_id:
            return {"ready": False, "hint": "No churn results found. Run 06_Business_Churn_Risk_Prediction.py first."}
        cur.execute("""
            SELECT C.BUSINESSID, C.BUSINESSNAME, C.CHURN_PROBABILITY, C.RISK_TIER,
                   C.LIKELY_CHURN_REASON, C.PREDICTED_CHURN_BY, C.TOP_RISK_FACTORS,
                    S.INDUSTRY, S.SEGMENT, S.CREDITSCORE,
                    S.CREDITWORTHINESSSCORE, S.PAYMENTHISTORYSCORE,
                    S.DELINQUENTACCOUNTCOUNT, S.CREDITUTILIZATIONRATIO
            FROM DM_V5_CHURN_RISK_RESULTS C
            LEFT JOIN (
                SELECT BUSINESSID, INDUSTRY, SEGMENT, CREDITSCORE,
                       CREDITWORTHINESSSCORE, PAYMENTHISTORYSCORE,
                       DELINQUENTACCOUNTCOUNT, CREDITUTILIZATIONRATIO
                FROM (
                    SELECT BUSINESSID, INDUSTRY, SEGMENT, CREDITSCORE,
                           CREDITWORTHINESSSCORE, PAYMENTHISTORYSCORE,
                           DELINQUENTACCOUNTCOUNT, CREDITUTILIZATIONRATIO,
                           ROW_NUMBER() OVER (
                               PARTITION BY BUSINESSID
                               ORDER BY DATA_MONTH DESC NULLS LAST, RECORD_ID DESC
                           ) AS ROW_NUM
                    FROM DM_V5_STG_CREDIT_BUREAU
                    WHERE BATCH_ID = :batch_id
                )
                WHERE ROW_NUM = 1
            ) S ON S.BUSINESSID = C.BUSINESSID
            WHERE C.BATCH_ID = :batch_id
            ORDER BY C.CHURN_PROBABILITY DESC NULLS LAST
        """, {"batch_id": batch_id})
        scored = clean_rows(rows_as_dicts(cur))
        counts = Counter((row.get("risk_tier") or "UNKNOWN").upper() for row in scored)
        at_risk = counts.get("CRITICAL", 0) + counts.get("HIGH", 0)
        filtered = scored if tier.lower() == "all" else [r for r in scored if (r.get("risk_tier") or "").upper() == tier.upper()]
        cur.execute("""
            SELECT FEATURE_NAME, IMPORTANCE FROM DM_V5_CHURN_FEATURE_IMPORTANCE
            WHERE BATCH_ID = :batch_id ORDER BY IMPORTANCE DESC
        """, {"batch_id": batch_id})
        importance = clean_rows(rows_as_dicts(cur))
        cur.execute("""
            SELECT ROC_AUC, PR_AUC, TOP_DECILE_LIFT, BASE_CHURN_RATE_TEST, HOLDOUT_TRANSITION
            FROM DM_V5_CHURN_MODEL_METRICS WHERE BATCH_ID = :batch_id
            ORDER BY CREATED_AT DESC FETCH FIRST 1 ROW ONLY
        """, {"batch_id": batch_id})
        metric_row = cur.fetchone()
        metrics = clean_rows([dict(zip([d[0].lower() for d in cur.description], metric_row))])[0] if metric_row else None
        auc = metrics.get("roc_auc") if metrics else None
        validation = {
            "roc_auc": auc, "pr_auc": metrics.get("pr_auc") if metrics else None,
            "top_decile_lift": metrics.get("top_decile_lift") if metrics else None,
            "confidence": "high" if auc is not None and auc >= .8 else "medium" if auc is not None and auc >= .65 else "low",
        } if metrics else None
        mapped = []
        for row in filtered[:limit]:
            probability = float(row.get("churn_probability") or 0)
            mapped.append({
                "businessID": row.get("businessid"), "businessName": row.get("businessname"),
                "industry": row.get("industry") or "—", "segment": row.get("segment") or "—",
                "churn_probability": round(probability * 100, 2),
                "risk_tier": row.get("risk_tier"), "likely_churn_reason": row.get("likely_churn_reason"),
                "predicted_churn_by": row.get("predicted_churn_by"), "top_risk_factors": row.get("top_risk_factors"),
                "creditScore": round(float(row["creditscore"])) if row.get("creditscore") is not None else None,
                "creditWorthinessScore": round(float(row["creditworthinessscore"])) if row.get("creditworthinessscore") is not None else None,
                "paymentHistoryScore": round(float(row["paymenthistoryscore"])) if row.get("paymenthistoryscore") is not None else None,
                "delinquentAccountCount": round(float(row["delinquentaccountcount"])) if row.get("delinquentaccountcount") is not None else None,
                "creditUtilizationRatio": round(float(row["creditutilizationratio"]), 2) if row.get("creditutilizationratio") is not None else None,
            })
        return {
            "ready": True, "total_businesses": len(scored), "at_risk_count": at_risk,
            "avg_churn_probability": round(sum(float(r.get("churn_probability") or 0) for r in scored) / len(scored) * 100, 2) if scored else 0,
            "tier_counts": {name: counts.get(name, 0) for name in ("CRITICAL", "HIGH", "WATCH", "LOW")},
            "tier_colors": {"CRITICAL": "#e7000b", "HIGH": "#fe9a00", "WATCH": "#2563eb", "LOW": "#179765"},
            "by_industry": [], "by_segment": [], "feature_importance": [
                {"feature": r.get("feature_name"), "importance": r.get("importance")} for r in importance
            ], "validation": validation, "businesses": mapped,
        }
    except oracledb.DatabaseError as exc:
        oracle_error = exc.args[0] if exc.args else None
        if getattr(oracle_error, "code", None) == 942:
            return {"ready": False, "hint": "Churn result tables are not available yet. Run 06_Business_Churn_Risk_Prediction.py first."}
        raise
    finally:
        conn.close()


@app.get("/api/engine/anomaly")
def engine_anomaly():
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = _engine_rows(cur)
        if not rows:
            return {"ready": False, "hint": "No anomaly results found. Run the V5 trust pipeline first."}

        current_trust = _engine_current_trust(cur)
        current = [row for row in rows if row.get("data_lineage") == "CURRENT_MONTH"]
        if not current:
            current_batch = rows[-1].get("batch_id")
            current = [row for row in rows if row.get("batch_id") == current_batch]

        methods = [
            {
                "label": label,
                "flagged": sum(bool(row.get(column)) for row in rows),
            }
            for label, column in ENGINE_METHODS
        ]
        lineage_groups = defaultdict(list)
        overlap = Counter()
        for row in rows:
            lineage_groups[row.get("data_lineage") or "UNKNOWN"].append(row)
        for row in current:
            overlap[sum(bool(row.get(column)) for _, column in ENGINE_METHODS)] += 1

        lineage_breakdown = []
        for lineage, group in sorted(lineage_groups.items()):
            summary = {"lineage": lineage, "total": len(group)}
            for label, column in ENGINE_METHODS:
                summary[label] = sum(bool(row.get(column)) for row in group)
            lineage_breakdown.append(summary)

        worst_records = []
        for row in sorted(
            rows,
            key=lambda item: item.get("overall_anomaly_risk") or 0,
            reverse=True,
        )[:20]:
            risk = _engine_percent(row.get("overall_anomaly_risk"))
            methods_fired = [
                label for label, column in ENGINE_METHODS if row.get(column)
            ]
            worst_records.append({
                "record_id": row.get("record_id"),
                "businessID": row.get("businessid"),
                "lineage": row.get("data_lineage"),
                "trust": _engine_percent(row.get("anomaly_health")),
                "risk": risk,
                "methods": methods_fired,
            })

        return {
            "ready": True,
            "current_month_trust": _engine_percent(
                current_trust.get("overall_dataset_trust") if current_trust else None
            ),
            "total_records": len(rows),
            "any_signal_flagged": sum(_engine_flagged(row) for row in rows),
            "flagged_records": None,
            "records_this_month": len(current),
            "any_signal_this_month": sum(_engine_flagged(row) for row in current),
            "critical_this_month": None,
            "pillar_stats": None,
            "by_method": methods,
            "lineage_breakdown": lineage_breakdown,
            "overlap_dist": [
                {"methods": count, "records": overlap.get(count, 0)}
                for count in range(len(ENGINE_METHODS) + 1)
            ],
            "worst_records": worst_records,
        }
    finally:
        conn.close()


@app.get("/api/engine/drift")
def engine_drift():
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = _engine_rows(cur)
        if not rows:
            return {"ready": False, "hint": "No drift results found. Run the V5 trust pipeline first."}

        groups = defaultdict(list)
        for row in rows:
            groups[row.get("data_lineage") or "UNKNOWN"].append(row)
        lineage_drift = []
        for lineage, group in sorted(groups.items()):
            values = [row["drift_health"] for row in group if row.get("drift_health") is not None]
            lineage_drift.append({
                "lineage": lineage,
                "total": len(group),
                "drift_health": _engine_percent(sum(values) / len(values)) if values else None,
            })

        health_counts = Counter()
        for row in rows:
            health = _engine_percent(row.get("drift_health"))
            if health is None:
                continue
            label = "Low (<50%)" if health < 50 else "Moderate (50–74%)" if health < 75 else "Healthy (≥75%)"
            health_counts[label] += 1

        current = [row for row in rows if row.get("data_lineage") == "CURRENT_MONTH"]
        if not current:
            latest_batch = rows[-1].get("batch_id")
            current = [row for row in rows if row.get("batch_id") == latest_batch]
        worst_drift = [
            {
                "businessID": row.get("businessid"),
                "drift_health": _engine_percent(row.get("drift_health")),
            }
            for row in sorted(
                current,
                key=lambda item: item.get("drift_health")
                if item.get("drift_health") is not None else float("inf"),
            )[:15]
        ]
        try:
            with DRIFT_SUMMARY_PATH.open("r", encoding="utf-8") as summary_file:
                model_health = json.load(summary_file)
            if not isinstance(model_health, dict) or not isinstance(model_health.get("current_month"), dict):
                model_health = None
        except (OSError, json.JSONDecodeError):
            model_health = None

        return {
            "ready": True,
            "lineage_drift": lineage_drift,
            "drift_dist": [
                {"label": label, "count": health_counts[label]}
                for label in ("Low (<50%)", "Moderate (50–74%)", "Healthy (≥75%)")
            ],
            "worst_drift": worst_drift,
            "model_health": model_health,
        }
    finally:
        conn.close()


@app.get("/api/engine/business")
def engine_business():
    conn = get_connection()
    try:
        cur = conn.cursor()
        current_trust = _engine_current_trust(cur)
        if not current_trust:
            return {"ready": False, "hint": "No trust results found. Run the V5 trust pipeline first."}

        batch_id = current_trust["batch_id"]
        cur.execute("""
            SELECT COUNT(*) AS TOTAL_RECORDS,
                   NVL(SUM(CASE WHEN NVL(BUSINESS_RULE_FLAGS, 0) > 0 THEN 1 ELSE 0 END), 0) AS FLAGGED_RECORDS,
                   NVL(MAX(BUSINESS_RULE_FLAGS), 0) AS MAX_FLAGS,
                   AVG(QUALITY_HEALTH) AS AVG_QUALITY_HEALTH,
                   NVL(AVG(BUSINESS_RULE_FLAGS), 0) AS AVG_FLAGS
            FROM DM_V5_QUALITY_RESULTS
            WHERE BATCH_ID = :batch_id
        """, {"batch_id": batch_id})
        summary = clean_rows(rows_as_dicts(cur))[0]
        cur.execute("""
            SELECT NVL(BUSINESS_RULE_FLAGS, 0) AS BUSINESS_RULE_FLAGS, COUNT(*) AS RECORD_COUNT
            FROM DM_V5_QUALITY_RESULTS
            WHERE BATCH_ID = :batch_id
            GROUP BY NVL(BUSINESS_RULE_FLAGS, 0)
            ORDER BY BUSINESS_RULE_FLAGS
        """, {"batch_id": batch_id})
        flag_groups = clean_rows(rows_as_dicts(cur))
        severity_dist = []
        for group in flag_groups:
            flag_count = int(group.get("business_rule_flags") or 0)
            if flag_count == 0:
                label = "Clean (0)"
            else:
                label = f"{flag_count} rule flag{'s' if flag_count != 1 else ''}"
            severity_dist.append({"label": label, "count": group.get("record_count") or 0})

        return {
            "ready": True,
            "max_possible_flags": summary.get("max_flags") or 0,
            "severity_dist": severity_dist,
            "lineage_business": [{
                "lineage": "CURRENT_MONTH",
                "total": summary.get("total_records") or 0,
                "business_health": _engine_percent(current_trust.get("business_health")),
                "avg_violations": round(float(summary.get("avg_flags") or 0), 2),
                "max_violations": summary.get("max_flags") or 0,
            }],
            "worst_business": [],
            "current_month_trust": _engine_percent(current_trust.get("business_health")),
            "total_records": summary.get("total_records") or 0,
            "flagged_records": summary.get("flagged_records") or 0,
        }
    finally:
        conn.close()


@app.get("/api/engine/freshness")
def engine_freshness():
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = _engine_rows(cur)
        if not rows:
            return {"ready": False, "hint": "No freshness results found. Run the V5 trust pipeline first."}

        lateness = [max(0, float(row.get("freshness_days_late") or 0)) for row in rows]
        late = [value for value in lateness if value > 0]
        total = len(rows)
        fresh_values = [
            row["freshness_health"] for row in rows
            if row.get("freshness_health") is not None
        ]
        bins = (
            ("On time", lambda value: value == 0),
            ("1–2 days", lambda value: 0 < value <= 2),
            ("3–7 days", lambda value: 2 < value <= 7),
            ("8+ days", lambda value: value > 7),
        )
        distribution = [
            {"label": label, "count": sum(test(value) for value in lateness)}
            for label, test in bins
        ]

        monthly_values = defaultdict(list)
        lineage_values = defaultdict(list)
        for row in rows:
            health = row.get("freshness_health")
            if health is not None:
                monthly_values[row.get("data_month") or "Unknown"].append(health)
                lineage_values[row.get("data_lineage") or "UNKNOWN"].append(health)
        monthly_lateness = defaultdict(list)
        for row, days_late in zip(rows, lateness):
            monthly_lateness[row.get("data_month") or "Unknown"].append(days_late)

        monthly = [
            {
                "month": month,
                "avg_freshness": _engine_percent(
                    sum(monthly_values[month]) / len(monthly_values[month])
                ) if monthly_values[month] else None,
                "avg_days_late": round(sum(days) / len(days), 2) if days else 0,
            }
            for month, days in sorted(monthly_lateness.items())
        ]
        lineage_breakdown = [
            {
                "lineage": lineage,
                "total": len(values),
                "avg_freshness": _engine_percent(sum(values) / len(values)) if values else None,
                "late_count": sum(
                    max(0, float(row.get("freshness_days_late") or 0)) > 0
                    for row in rows if (row.get("data_lineage") or "UNKNOWN") == lineage
                ),
                "late_rate": round(
                    sum(
                        max(0, float(row.get("freshness_days_late") or 0)) > 0
                        for row in rows if (row.get("data_lineage") or "UNKNOWN") == lineage
                    ) / len(values) * 100, 2
                ) if values else 0,
                "avg_days_late": round(
                    sum(
                        max(0, float(row.get("freshness_days_late") or 0))
                        for row in rows if (row.get("data_lineage") or "UNKNOWN") == lineage
                    ) / len(values), 2
                ) if values else 0,
            }
            for lineage, values in sorted(lineage_values.items())
        ]
        latest_batch = rows[-1].get("batch_id")
        current = [row for row in rows if row.get("batch_id") == latest_batch]
        worst_records = [
            {
                "record_id": row.get("record_id"),
                "businessID": row.get("businessid"),
                "data_month": row.get("data_month"),
                "lineage": row.get("data_lineage"),
                "days_late": max(0, float(row.get("freshness_days_late") or 0)),
                "freshness_health": _engine_percent(row.get("freshness_health")),
            }
            for row in sorted(
                current,
                key=lambda item: float(item.get("freshness_days_late") or 0),
                reverse=True,
            )[:20]
            if float(row.get("freshness_days_late") or 0) > 0
        ]

        return {
            "ready": True,
            "total_records": total,
            "late_count": len(late),
            "ontime_count": total - len(late),
            "late_rate": round(len(late) / total * 100, 2) if total else 0,
            "avg_days_late": round(sum(lateness) / total, 2) if total else 0,
            "max_days_late": max(lateness, default=0),
            "avg_days_late_of_late": round(sum(late) / len(late), 2) if late else 0,
            "fresh_pct": _engine_percent(sum(fresh_values) / len(fresh_values)) if fresh_values else None,
            "distribution": distribution,
            "monthly": monthly,
            "lineage_breakdown": lineage_breakdown,
            "worst_records": worst_records,
        }
    finally:
        conn.close()


@app.get("/api/security")
def security():
    """Return the latest successful Oracle security pipeline results."""
    conn = _security_connection()
    try:
        cur = conn.cursor()
        run_id = _latest_security_run(cur)
        if not run_id:
            return {"ready": False, "hint": "No successful Oracle security run is available yet. Run security_pipeline/run_security_oracle.py."}

        cur.execute("SELECT SUMMARY_JSON FROM SEC_SUMMARY WHERE RUN_ID = :run_id", run_id=run_id)
        row = cur.fetchone()
        if not row:
            return {"ready": False, "hint": "The latest security run has no summary. Run the security pipeline again."}
        summary = _read_json_clob(row[0]) or {}

        cur.execute("""
            SELECT PAYLOAD FROM SEC_ROWS
            WHERE RUN_ID = :run_id AND DATASET_KEY = 'security_records'
            ORDER BY ROW_NUM
        """, run_id=run_id)
        records = [_read_json_clob(r[0]) for r in cur.fetchall()]
        worst_records = sorted(
            (r for r in records if r),
            key=lambda r: (float(r.get("security_score") or 0), str(r.get("record_id", ""))),
        )[:50]
        return {
            "ready": True,
            "run_id": run_id,
            "overall_score": summary.get("overall_security_score", 0),
            "total_records": summary.get("total_records", 0),
            "records_with_findings": summary.get("records_with_findings", 0),
            "exposure_rate_pct": summary.get("exposure_rate_pct", 0),
            "by_category": summary.get("by_category", {}),
            "by_severity": summary.get("by_severity", {}),
            "by_column": summary.get("by_column", []),
            "examples_by_category": summary.get("examples_by_category", {}),
            "worst_records": worst_records,
        }
    except oracledb.Error as exc:
        raise HTTPException(status_code=503, detail=f"Oracle security results unavailable: {exc}") from exc
    finally:
        conn.close()


@app.get("/api/security/finding/{record_id}/{finding_type}")
def security_finding(record_id: str, finding_type: str = "all"):
    """Return findings for one record for the existing detail modal."""
    conn = _security_connection()
    try:
        cur = conn.cursor()
        run_id = _latest_security_run(cur)
        if not run_id:
            return {"ready": False, "error": "No successful Oracle security run is available."}
        cur.execute("""
            SELECT PAYLOAD FROM SEC_ROWS
            WHERE RUN_ID = :run_id AND DATASET_KEY = 'security_findings'
            ORDER BY ROW_NUM
        """, run_id=run_id)
        findings = [_read_json_clob(r[0]) for r in cur.fetchall()]
        matches = [f for f in findings if f and str(f.get("record_id")) == record_id]
        if finding_type != "all":
            matches = [f for f in matches if str(f.get("type")) == finding_type]
        if not matches:
            return {"ready": False, "error": "No matching security findings were found for this record."}
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        matches.sort(key=lambda f: rank.get(str(f.get("severity", "")).lower(), 4))
        return {
            "ready": True,
            "primary": matches[0],
            "related_findings": matches[1:],
            "total_findings_this_record": len(matches),
        }
    except oracledb.Error as exc:
        raise HTTPException(status_code=503, detail=f"Oracle security findings unavailable: {exc}") from exc
    finally:
        conn.close()


def _security_connection():
    """Use security-specific credentials when supplied, then the V5 schema."""
    user = os.getenv("SECURITY_ORACLE_USER", os.getenv("ORACLE_USER", ORACLE_USER))
    password = os.getenv("SECURITY_ORACLE_PASSWORD", os.getenv("ORACLE_PASSWORD", ORACLE_PASSWORD))
    dsn = os.getenv("SECURITY_ORACLE_DSN", os.getenv("ORACLE_DSN", ORACLE_DSN))
    try:
        return oracledb.connect(user=user, password=password, dsn=dsn)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Oracle security connection failed: {exc}") from exc


def _latest_security_run(cursor):
    cursor.execute("""
        SELECT RUN_ID FROM SEC_RUNS
        WHERE STATUS = 'SUCCESS'
        ORDER BY FINISHED_AT DESC NULLS LAST, STARTED_AT DESC
        FETCH FIRST 1 ROWS ONLY
    """)
    row = cursor.fetchone()
    return row[0] if row else None


def _read_json_clob(value):
    if value is None:
        return None
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value) if isinstance(value, str) else value


@app.get("/api/forecast")
def forecast():
    """Return the monthly V5 history and latest persisted ARIMA run for the forecast UI."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        forecasts, alerts, has_run = _latest_arima_results(cur)
        if not has_run:
            return {"ready": False, "hint": "No ARIMA forecast run found in Oracle. Run backend_v5/04_ARIMA_Predictive_Trust_Alerts.py after the V5 trust and staging data are ready."}

        # The ARIMA script trains on these same monthly means and trust values.
        cur.execute("""
            SELECT DATA_MONTH, AVG(CREDITSCORE) AS CREDIT_SCORE,
                   AVG(TOTALCREDITLIMIT) AS TOTAL_CREDIT_LIMIT,
                   AVG(CREDITWORTHINESSSCORE) AS CREDIT_WORTHINESS_SCORE,
                   AVG(AVAILABLECREDIT) AS AVAILABLE_CREDIT
            FROM DM_V5_STG_CREDIT_BUREAU
            WHERE DATA_MONTH IS NOT NULL
            GROUP BY DATA_MONTH ORDER BY TO_DATE(DATA_MONTH, 'YYYY-MM')
        """)
        metric_history = clean_rows(rows_as_dicts(cur))
        cur.execute("""
            SELECT DATA_MONTH, ANOMALY_HEALTH, DRIFT_HEALTH, BUSINESS_HEALTH,
                   FRESHNESS_HEALTH, OVERALL_DATASET_TRUST
            FROM DM_V5_TRUST_RESULTS
            WHERE DATA_MONTH IS NOT NULL ORDER BY TO_DATE(DATA_MONTH, 'YYYY-MM')
        """)
        trust_history = clean_rows(rows_as_dicts(cur))

        series_defs = [
            ("overall_dataset_trust", "Overall trust", "pillar", True, trust_history, "overall_dataset_trust"),
            ("anomaly_health", "Anomaly health", "pillar", False, trust_history, "anomaly_health"),
            ("drift_health", "Drift health", "pillar", False, trust_history, "drift_health"),
            ("business_health", "Business health", "pillar", False, trust_history, "business_health"),
            ("freshness_health", "Freshness health", "pillar", False, trust_history, "freshness_health"),
            ("creditScore", "Credit score", "metric", False, metric_history, "credit_score"),
            ("totalCreditLimit", "Total credit limit", "metric", False, metric_history, "total_credit_limit"),
            ("creditWorthinessScore", "Credit worthiness score", "metric", False, metric_history, "credit_worthiness_score"),
            ("availableCredit", "Available credit", "metric", False, metric_history, "available_credit"),
        ]
        forecasts_by_name = defaultdict(list)
        for row in forecasts:
            forecasts_by_name[(row.get("series_name") or "").lower()].append(row)

        result_series = []
        for name, label, kind, overall, history, value_key in series_defs:
            matching = forecasts_by_name.get(name.lower(), [])
            scale = _percent if kind == "pillar" else lambda v: v
            actuals = [scale(row.get(value_key)) for row in history]
            hist_labels = [str(row.get("data_month")) for row in history]
            matching.sort(key=lambda row: str(row.get("forecast_month") or ""))
            result_series.append({
                "key": name, "name": name, "label": label, "kind": kind, "is_overall": overall,
                "hist_labels": hist_labels, "hist_values": actuals,
                "forecast_labels": [str(row.get("forecast_month")) for row in matching],
                "forecast_values": [scale(row.get("forecast_value")) for row in matching],
                "lower_95": [scale(row.get("lower_95")) for row in matching],
                "upper_95": [scale(row.get("upper_95")) for row in matching],
                "threshold": scale(matching[0].get("threshold_value")) if matching else None,
                "arima_order": matching[0].get("arima_order", "N/A") if matching else "N/A",
                "mape": matching[0].get("mape") if matching else None,
                "confidence": (matching[0].get("confidence_label") or "unknown").lower() if matching else "unknown",
            })

        ui_alerts = []
        for row in alerts:
            is_trust = (row.get("series_name") or "").lower() in {
                "anomaly_health", "drift_health", "business_health",
                "freshness_health", "overall_dataset_trust",
            }
            scale_alert = _percent if is_trust else lambda value: value
            ui_alerts.append({
                "metric": row.get("series_name"), "trigger": row.get("trigger_type"),
                "month": row.get("forecast_month"), "severity": row.get("severity"),
                "forecast": scale_alert(row.get("forecast_value")),
                "threshold": scale_alert(row.get("threshold_value")),
                "reason": row.get("reason"),
            })
        return {"ready": True, "horizon": 4, "series": result_series, "alerts": ui_alerts,
                "mom_change": {"labels": [], "series": {}}}
    finally:
        conn.close()



# Frontend compatibility endpoints for the supplied DeltaMax dashboard.
# Values from Oracle are normalized to the 0-100 scale used by the UI.
def _percent(value):
    if value is None:
        return None
    value = float(value)
    return round(value * 100 if abs(value) <= 1 else value, 2)

def _latest_arima_results(cur):
    try:
        cur.execute("SELECT MAX(RUN_ID) FROM DM_V5_ARIMA_FORECASTS")
        run_id = cur.fetchone()[0]
        if not run_id:
            return [], [], False

        cur.execute("""
            SELECT SERIES_NAME, FORECAST_MONTH, FORECAST_VALUE, LOWER_95, UPPER_95, THRESHOLD_VALUE
            FROM DM_V5_ARIMA_FORECASTS
            WHERE RUN_ID = :run_id
            ORDER BY SERIES_NAME, FORECAST_MONTH
        """, {"run_id": run_id})
        forecasts = clean_rows(rows_as_dicts(cur))

        cur.execute("""
            SELECT SERIES_NAME, TRIGGER_TYPE, FORECAST_MONTH, SEVERITY, REASON
            FROM DM_V5_ARIMA_ALERTS
            WHERE RUN_ID = :run_id
            ORDER BY MONTH_AHEAD, SERIES_NAME
        """, {"run_id": run_id})
        alerts = clean_rows(rows_as_dicts(cur))
        return forecasts, alerts, True
    except oracledb.DatabaseError as exc:
        oracle_error = exc.args[0] if exc.args else None
        if getattr(oracle_error, "code", None) == 942:
            return [], [], False
        raise

@app.get("/api/home")
def home():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT BATCH_ID, TOTAL_RECORDS, ANOMALY_HEALTH, DRIFT_HEALTH,
                   BUSINESS_HEALTH, FRESHNESS_HEALTH, OVERALL_DATASET_TRUST
            FROM DM_V5_TRUST_RESULTS ORDER BY BATCH_ID
        """)
        rows = clean_rows(rows_as_dicts(cur))
        if not rows:
            return {"ready": False, "hint": "No trust results found in Oracle yet. Run the V5 processing scripts first."}
        labels = [str(r.get("batch_id", "")) for r in rows]
        trust = [_percent(r.get("overall_dataset_trust")) for r in rows]
        last = rows[-1]
        prior = [v for v in trust[:-1] if v is not None]
        current_label = labels[-1]
        current_records = int(last.get("total_records") or 0)
        # The source V5 trust table stores health as 0..1. The UI displays 0..100.
        pillars = {
            "anomaly_health": _percent(last.get("anomaly_health")) or 0,
            "drift_health": _percent(last.get("drift_health")) or 0,
            "business_health": _percent(last.get("business_health")) or 0,
            "freshness_health": _percent(last.get("freshness_health")) or 0,
        }
        cur.execute("SELECT COUNT(*) FROM DM_V5_STG_CREDIT_BUREAU WHERE BATCH_ID = :batch_id", {"batch_id": last.get("batch_id")})
        current_records = int(cur.fetchone()[0] or current_records)
        cur.execute("""SELECT COUNT(*) FROM DM_V5_QUALITY_RESULTS
                       WHERE BATCH_ID = :batch_id AND (NVL(MISSING_FLAG,0)=1 OR NVL(DUPLICATE_FLAG,0)=1 OR NVL(BUSINESS_RULE_FLAGS,0)>0)""", {"batch_id": last.get("batch_id")})
        flagged = int(cur.fetchone()[0] or 0)
        forecasts, alerts, arima_run_available = _latest_arima_results(cur)
        trust_forecasts = [
            row for row in forecasts
            if (row.get("series_name") or "").lower() == "overall_dataset_trust"
        ]
        trend_labels = labels + [str(row["forecast_month"]) for row in trust_forecasts]
        trend_actual = trust + [None] * len(trust_forecasts)
        trend_forecast = [None] * len(trust) + [
            _percent(row.get("forecast_value")) for row in trust_forecasts
        ]
        trend_lower = [None] * len(trust) + [
            _percent(row.get("lower_95")) for row in trust_forecasts
        ]
        trend_upper = [None] * len(trust) + [
            _percent(row.get("upper_95")) for row in trust_forecasts
        ]
        return {
            "ready": True, "last_modified": current_label,
            "metrics": {
                "overall_trust": _percent(last.get("overall_dataset_trust")) or 0,
                "datasets_monitored": len(rows), "active_anomalies": flagged,
                "rules_pass_rate": pillars["business_health"],
                "current_month_trust": _percent(last.get("overall_dataset_trust")) or 0,
                "current_month_label": current_label,
                "prev_months_avg_trust": round(sum(prior)/len(prior),2) if prior else None,
                "prev_months_count": len(prior), "prev_months_range": ", ".join(labels[:-1]),
                "current_month_records": current_records, "current_month_flagged": flagged
            },
            "pillars": pillars,
            "trend": {"labels": trend_labels, "actual": trend_actual, "forecast": trend_forecast,
                      "lower_95": trend_lower, "upper_95": trend_upper, "n_hist": len(labels)},
            "use_cases": [{"name":"Executive AI", "score": _percent(last.get("overall_dataset_trust")) or 0, "real": True}],
            "arima_run_available": arima_run_available,
            "recent_alerts": [
                {
                    "severity": row.get("severity"),
                    "metric": row.get("series_name"),
                    "trigger": f"{row.get('trigger_type')}: {row.get('reason')}",
                    "month": row.get("forecast_month"),
                }
                for row in alerts
            ]
        }
    finally:
        conn.close()

@app.get("/api/status")
def api_status():
    try:
        return {"status":"ok", "database": health()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


ASSISTANT_AGENTS = [
    {
        "id": "exec", "label": "Executive agent", "icon": "ti-chart-bar",
        "blurb": "Trust, quality, churn risk, and current alerts from the Executive AI dashboard.",
        "starters": [
            "What does the current dashboard show for trust and data quality?",
            "Which businesses have the highest churn risk?",
            "What do the latest forecast alerts say?",
        ], "dedicated": False,
    },
    {
        "id": "mdm", "label": "MDM agent", "icon": "ti-database",
        "blurb": "Golden records, duplicate clusters, and source-system results from MDM.",
        "starters": [
            "How many source records, golden records, and duplicate clusters are there?",
            "Which source system has the highest golden-record win rate?",
            "Show the golden records with the lowest trust scores.",
        ], "dedicated": False,
    },
    {
        "id": "migration", "label": "Migration agent", "icon": "ti-cloud-upload",
        "blurb": "Latest Oracle ↔ BigQuery transfer status and per-table validation.",
        "starters": [
            "How many tables passed the latest Oracle to BigQuery validation?",
            "Which tables failed the latest migration check?",
            "How many rows were transferred from BigQuery to Oracle?",
        ], "dedicated": False,
    },
    {
        "id": "security", "label": "Security agent", "icon": "ti-shield-lock",
        "blurb": "Latest security scan score, findings, severity, and affected columns.",
        "starters": [
            "What is the latest security score and how many records have findings?",
            "How many critical and high-severity findings were found?",
            "Which columns have the most security findings?",
        ], "dedicated": False,
    },
]


def _assistant_table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": columns, "rows": rows[:12], "truncated": len(rows) > 12}


def _assistant_executive(question: str) -> tuple[str, dict[str, Any] | None]:
    q = question.lower()
    if any(word in q for word in ("churn", "at risk", "highest risk", "critical risk")):
        result = executive_churn_risk(limit=1000)
        if not result.get("ready"):
            return result.get("hint", "Churn results are not available on the dashboard yet."), None
        businesses = result.get("businesses") or []
        tiers = result.get("tier_counts") or {}
        tables = [[b.get("businessName"), b.get("businessID"), b.get("risk_tier"),
                   f"{float(b.get('churn_probability') or 0):.2f}%",
                   b.get("likely_churn_reason")] for b in businesses[:5]]
        answer = (
            f"Latest churn dashboard: **{result.get('total_businesses', 0):,} businesses** scored; "
            f"**{result.get('at_risk_count', 0):,}** are Critical or High risk "
            f"(Critical {tiers.get('CRITICAL', 0):,}, High {tiers.get('HIGH', 0):,}); "
            f"average churn probability is **{result.get('avg_churn_probability', 0):.2f}%**. "
            "The table shows the five highest-probability businesses returned by the dashboard."
        )
        if businesses:
            first = businesses[0]
            answer += (
                f"\n\nHighest listed: **{first.get('businessName')}** "
                f"({first.get('businessID')}), {first.get('risk_tier')} at "
                f"{float(first.get('churn_probability') or 0):.2f}%. "
                f"Reason: {first.get('likely_churn_reason') or 'No reason recorded.'}"
            )
        return answer, _assistant_table(
            ["Business", "Business ID", "Risk", "Churn probability", "Dashboard reason"], tables
        )

    # Forecast questions should answer from the forecast series itself. Keep
    # alert questions on the alert endpoint so a request for future values is
    # not mistaken for a request for alert events.
    if "forecast" in q or "arima" in q:
        result = forecast()
        if not result.get("ready"):
            return result.get("hint", "No forecast data is available on the dashboard yet."), None
        series = next((s for s in result.get("series", [])
                       if s.get("is_overall") or (s.get("key") or "").lower() == "overall_dataset_trust"), None)
        if not series or not series.get("forecast_values"):
            return "The dashboard has no future overall-trust values in its latest forecast run.", None
        labels = series.get("forecast_labels") or []
        values = series.get("forecast_values") or []
        lower = series.get("lower_95") or []
        upper = series.get("upper_95") or []
        rows = []
        for i, value in enumerate(values[:4]):
            month = labels[i] if i < len(labels) else f"Month {i + 1}"
            if value is None:
                continue
            interval = "—"
            if i < len(lower) and i < len(upper) and lower[i] is not None and upper[i] is not None:
                interval = f"{float(lower[i]):.2f}–{float(upper[i]):.2f}"
            rows.append([month, f"{float(value):.2f}", interval])
        if not rows:
            return "The latest forecast run contains no usable overall-trust predictions.", None
        hist = series.get("hist_values") or []
        latest = next((float(v) for v in reversed(hist) if v is not None), None)
        final_value = next((float(v) for v in reversed(values[:4]) if v is not None), None)
        first_month = labels[0] if labels else "the first forecast month"
        final_month = rows[-1][0]
        answer = f"The latest ARIMA run forecasts overall trust for the next {len(rows)} month(s):"
        if latest is not None and final_value is not None:
            delta = final_value - latest
            direction = "rise" if delta > 0.005 else "fall" if delta < -0.005 else "stay about the same"
            answer += (f" It is expected to **{direction}** from **{latest:.2f}** at the latest observed point "
                       f"to **{final_value:.2f}** in **{final_month}** ({delta:+.2f} points).")
        answer += " The table gives the monthly forecast and its 95% interval where available; these are model estimates, not observed results."
        return answer, _assistant_table(["Month", "Forecast trust", "95% interval"], rows)

    if any(word in q for word in ("alert", "alerts")):
        result = executive_alerts()
        alerts = result.get("alerts") or []
        if not result.get("ready"):
            return result.get("hint", "No forecast alerts are available on the dashboard yet."), None
        if not alerts:
            return "The latest forecast run is available and reports **no active alerts**.", None
        tables = [[a.get("severity"), a.get("metric"), a.get("month"), a.get("trigger"), a.get("reason")]
                  for a in alerts[:8]]
        return f"The latest forecast run has **{len(alerts)} alert(s)**. Here are the first results, in dashboard order.", _assistant_table(
            ["Severity", "Metric", "Month", "Trigger", "Reason"], tables
        )

    result = home()
    if not result.get("ready"):
        return result.get("hint", "Executive dashboard data is not available yet."), None
    m = result.get("metrics") or {}
    p = result.get("pillars") or {}
    answer = (
        f"Current Executive AI dashboard ({m.get('current_month_label', 'latest batch')}): "
        f"overall trust **{m.get('overall_trust', 0):.1f}%**, "
        f"**{m.get('current_month_records', 0):,}** records, and "
        f"**{m.get('current_month_flagged', 0):,}** flagged records. "
        f"Health pillars: anomaly {p.get('anomaly_health', 0):.1f}%, "
        f"drift {p.get('drift_health', 0):.1f}%, business rules {p.get('business_health', 0):.1f}%, "
        f"freshness {p.get('freshness_health', 0):.1f}%."
    )
    return answer, _assistant_table(
        ["Dashboard measure", "Current value"],
        [["Overall trust", f"{m.get('overall_trust', 0):.1f}%"],
         ["Records", f"{m.get('current_month_records', 0):,}"],
         ["Flagged records", f"{m.get('current_month_flagged', 0):,}"],
         ["Anomaly health", f"{p.get('anomaly_health', 0):.1f}%"],
         ["Drift health", f"{p.get('drift_health', 0):.1f}%"],
         ["Business rules", f"{p.get('business_health', 0):.1f}%"],
         ["Freshness", f"{p.get('freshness_health', 0):.1f}%"]],
    )


def _assistant_mdm(question: str) -> tuple[str, dict[str, Any] | None]:
    mdm_password = os.getenv("MDM_DB_PASSWORD") or ORACLE_PASSWORD
    mdm_dsn = oracledb.makedsn(
        os.getenv("MDM_DB_HOST", "localhost"),
        int(os.getenv("MDM_DB_PORT", "1521")),
        service_name=os.getenv("MDM_DB_SERVICE", "FREEPDB1"),
    )
    conn = oracledb.connect(
        user=os.getenv("MDM_DB_USER", ORACLE_USER),
        password=mdm_password,
        dsn=mdm_dsn,
    )
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM MDM_CUSTOMER_STG) AS SOURCE_RECORDS,
                   (SELECT COUNT(*) FROM MDM_CUSTOMER_GOLDEN) AS GOLDEN_RECORDS,
                   (SELECT COUNT(*) FROM (
                       SELECT CLUSTER_ID FROM MDM_CUSTOMER_STG
                       GROUP BY CLUSTER_ID HAVING COUNT(*) > 1
                   )) AS DUPLICATE_CLUSTERS,
                   (SELECT AVG(TRUST_SCORE) FROM MDM_CUSTOMER_GOLDEN) AS AVG_GOLDEN_TRUST
            FROM DUAL
        """)
        totals = dict(zip([d[0].lower() for d in cur.description], cur.fetchone()))
        cur.execute("""
            SELECT s.SOURCE_SYSTEM, COUNT(*) AS RECORDS,
                   COUNT(g.RECORD_ID) AS GOLDEN_WINS,
                   ROUND(100 * COUNT(g.RECORD_ID) / NULLIF(COUNT(*), 0), 1) AS WIN_RATE
            FROM MDM_CUSTOMER_STG s
            LEFT JOIN MDM_CUSTOMER_GOLDEN g ON g.RECORD_ID = s.RECORD_ID
            GROUP BY s.SOURCE_SYSTEM ORDER BY WIN_RATE DESC NULLS LAST
        """)
        source_rows = clean_rows(rows_as_dicts(cur))
        cur.execute("""
            SELECT CLUSTER_ID, FIRST_NAME || ' ' || LAST_NAME AS CUSTOMER,
                   SOURCE_SYSTEM, TRUST_SCORE
            FROM MDM_CUSTOMER_GOLDEN ORDER BY TRUST_SCORE NULLS FIRST, CLUSTER_ID
            FETCH FIRST 5 ROWS ONLY
        """)
        low_trust = clean_rows(rows_as_dicts(cur))
        source_records = int(totals.get("source_records") or 0)
        duplicate_clusters = int(totals.get("duplicate_clusters") or 0)
        if source_records == 0:
            return "The MDM dashboard has no source records to report.", None
        answer = (
            f"Current MDM dashboard: **{source_records:,} source records**, "
            f"**{int(totals.get('golden_records') or 0):,} golden records**, "
            f"**{duplicate_clusters:,} duplicate clusters**, and average golden-record trust "
            f"**{float(totals.get('avg_golden_trust') or 0):.1f}**."
        )
        if source_rows:
            winner = source_rows[0]
            answer += (f"\n\nHighest golden-record win rate: **{winner.get('source_system')}** "
                       f"at {winner.get('win_rate')}% ({winner.get('golden_wins')} of {winner.get('records')} records).")
        q = question.lower()
        if any(word in q for word in ("lowest trust", "low trust", "review")) and low_trust:
            answer += "\n\nThe lowest-trust golden records are listed below."
            return answer, _assistant_table(
                ["Cluster", "Customer", "Winning source", "Trust score"],
                [[r.get("cluster_id"), r.get("customer"), r.get("source_system"), r.get("trust_score")] for r in low_trust],
            )
        return answer, _assistant_table(
            ["Source system", "Records", "Golden wins", "Win rate"],
            [[r.get("source_system"), r.get("records"), r.get("golden_wins"), f"{r.get('win_rate')}%"] for r in source_rows],
        )
    finally:
        conn.close()


def _assistant_security(question: str) -> tuple[str, dict[str, Any] | None]:
    result = security()
    if not result.get("ready"):
        return result.get("hint", "Security dashboard results are not available yet."), None
    severity = result.get("by_severity") or {}
    categories = result.get("by_category") or {}
    answer = (
        f"Latest security dashboard run **{result.get('run_id')}**: overall score "
        f"**{float(result.get('overall_score') or 0):.1f}**, "
        f"**{int(result.get('records_with_findings') or 0):,} of {int(result.get('total_records') or 0):,}** records have findings "
        f"({float(result.get('exposure_rate_pct') or 0):.1f}% exposure rate). "
        f"Severity counts: {', '.join(f'{k} {v}' for k, v in severity.items()) or 'none reported'}."
    )
    if categories:
        answer += "\nFinding categories: " + ", ".join(f"{k}: {v}" for k, v in categories.items()) + "."
    columns = result.get("by_column") or []
    q = question.lower()
    if any(word in q for word in ("column", "field")) and columns:
        return answer + "\n\nColumns with the most findings are listed below.", _assistant_table(
            ["Column", "Findings"],
            [[item.get("column") or item.get("field") or item.get("name"),
              item.get("count", item.get("findings", item.get("total")))] for item in columns[:8]],
        )
    worst = result.get("worst_records") or []
    return answer, _assistant_table(
        ["Record", "Security score", "Findings"],
        [[r.get("record_id"), r.get("security_score"), r.get("findings_count", r.get("total_findings"))] for r in worst[:5]],
    ) if worst else None


def _assistant_migration(question: str) -> tuple[str, dict[str, Any] | None]:
    q = question.lower()
    reverse = "bigquery to oracle" in q or "bigquery → oracle" in q or "reverse" in q or "to oracle" in q
    result = migration_service.bigquery_to_oracle_results() if reverse else migration_service.migration_results()
    if not result.get("ready"):
        return result.get("hint", "No completed migration report is available on the dashboard."), None
    metrics = result.get("metrics") or {}
    tables = result.get("tables") or []
    failed = [row for row in tables if not (row.get("passed") if not reverse else row.get("status") == "SUCCESS")]
    passed = int(metrics.get("tables_passed") or 0)
    total = int(metrics.get("table_count") or len(tables))
    direction = "BigQuery → Oracle" if reverse else "Oracle → BigQuery"
    source_rows = metrics.get("total_source_rows") if reverse else metrics.get("total_oracle_rows")
    destination_rows = metrics.get("total_oracle_rows") if reverse else metrics.get("total_bigquery_rows")
    answer = (
        f"Latest **{direction}** migration report: **{passed} of {total} tables passed**; "
        f"{int(source_rows or 0):,} source rows and {int(destination_rows or 0):,} destination rows are reported. "
        f"Overall status: **{result.get('status', 'unknown')}**."
    )
    if failed:
        answer += "\nTables needing attention: " + ", ".join(
            str(row.get("source_table") or row.get("table") or row.get("oracle_table")) for row in failed[:10]
        ) + "."
    rows = []
    for item in tables[:12]:
        if reverse:
            rows.append([item.get("source_table"), item.get("oracle_table"), item.get("status"),
                         item.get("source_rows_expected"), item.get("oracle_rows_after"), item.get("details")])
        else:
            rows.append([item.get("table"), item.get("stage"), item.get("final"), item.get("oracle_rows"),
                         item.get("bigquery_rows"), "MATCH" if item.get("passed") else "CHECK"])
    labels = (["BigQuery source", "Oracle destination", "Status", "BigQuery rows", "Oracle rows", "Details"] if reverse else
              ["Oracle table", "BigQuery staging table", "Final BigQuery table", "Oracle rows", "BigQuery rows", "Check"])
    return answer, _assistant_table(labels, rows)


@app.get("/api/agents")
def assistant_agents():
    return {"ready": True, "agents": ASSISTANT_AGENTS}


@app.get("/api/agent/health")
def assistant_health():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT USER FROM DUAL")
        return {"ready": True, "configured": True, "source": "oracle-dashboard", "database_user": cur.fetchone()[0]}
    finally:
        conn.close()


@app.post("/api/agent")
def ask_dashboard_agent(payload: dict[str, Any]):
    question = str(payload.get("question") or "").strip()
    agent = str(payload.get("agent") or "exec").strip().lower()
    if not question:
        return {"ready": False, "error": "Enter a question about the dashboard."}
    handlers = {
        "exec": _assistant_executive,
        "mdm": _assistant_mdm,
        "migration": _assistant_migration,
        "security": _assistant_security,
    }
    handler = handlers.get(agent)
    if handler is None:
        return {"ready": False, "error": "Choose Executive, MDM, Migration, or Security agent."}
    try:
        answer, data = handler(question)
        return {"ready": True, "answer": answer, "data": data, "agent": agent, "source": "Oracle-backed dashboard"}
    except HTTPException as exc:
        return {
            "ready": True,
            "answer": f"I couldn’t read the live {agent} dashboard data. {exc.detail}",
            "agent": agent, "source": "Oracle-backed dashboard",
        }
    except (oracledb.Error, KeyError, TypeError, ValueError) as exc:
        return {
            "ready": True,
            "answer": f"I couldn’t answer from the live {agent} dashboard data because that data is unavailable or incomplete. Check that the corresponding dashboard tables and latest run are present. ({type(exc).__name__})",
            "agent": agent, "source": "Oracle-backed dashboard",
        }
