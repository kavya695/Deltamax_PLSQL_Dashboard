"""Read-only API for MDM records already stored in Oracle."""

import os
from collections import Counter
from decimal import Decimal

import oracledb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="DeltaMax MDM API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_connection():
    password = os.getenv("MDM_DB_PASSWORD")
    if not password:
        raise HTTPException(status_code=503, detail="Set MDM_DB_PASSWORD before starting the MDM API.")
    dsn = oracledb.makedsn(
        os.getenv("MDM_DB_HOST", "localhost"),
        int(os.getenv("MDM_DB_PORT", "1521")),
        service_name=os.getenv("MDM_DB_SERVICE", "FREEPDB1"),
    )
    try:
        return oracledb.connect(
            user=os.getenv("MDM_DB_USER", "DELTAMAX_V5"),
            password=password,
            dsn=dsn,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Oracle connection failed: {exc}") from exc


def query_rows(cursor, sql, binds=None):
    cursor.execute(sql, binds or {})
    columns = [item[0].lower() for item in cursor.description]
    rows = []
    for row in cursor.fetchall():
        rows.append({
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in zip(columns, row)
        })
    return rows


@app.get("/api/health")
def health():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT USER FROM DUAL")
        return {"status": "ok", "database_user": cur.fetchone()[0]}
    finally:
        conn.close()


@app.get("/api/mdm")
def mdm_dashboard():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM MDM_CUSTOMER_STG) AS SOURCE_RECORDS,
                   (SELECT COUNT(*) FROM MDM_CUSTOMER_GOLDEN) AS GOLDEN_RECORDS,
                   (SELECT COUNT(*) FROM (
                       SELECT CLUSTER_ID FROM MDM_CUSTOMER_STG
                       GROUP BY CLUSTER_ID HAVING COUNT(*) > 1
                   )) AS DUPLICATE_CLUSTERS,
                   (SELECT AVG(TRUST_SCORE) FROM MDM_CUSTOMER_GOLDEN) AS MATCH_CONFIDENCE,
                   (SELECT AVG(RULES_SCORE) FROM MDM_CUSTOMER_SCORES) AS RULES_SCORE,
                   (SELECT AVG(DRIFT_SCORE) FROM MDM_CUSTOMER_SCORES) AS DRIFT_SCORE,
                   (SELECT AVG(ANOMALY_SCORE) FROM MDM_CUSTOMER_SCORES) AS ANOMALY_SCORE,
                   (SELECT AVG(TRUST_SCORE) FROM MDM_CUSTOMER_SCORES) AS OVERALL_TRUST
            FROM DUAL
        """)
        names = [item[0].lower() for item in cur.description]
        raw = dict(zip(names, cur.fetchone()))
        metrics = {
            "source_records": int(raw["source_records"] or 0),
            "golden_records": int(raw["golden_records"] or 0),
            "duplicate_clusters": int(raw["duplicate_clusters"] or 0),
            "match_confidence": round(float(raw["match_confidence"] or 0), 1),
        }
        if metrics["source_records"] == 0:
            return {"ready": False, "hint": "No MDM source records found in Oracle. Run the MDM pipeline first."}

        pipeline = query_rows(cur, """
            SELECT s.SOURCE_SYSTEM AS SOURCE,
                   COUNT(*) AS RECORDS,
                   COUNT(g.RECORD_ID) AS GOLDEN_WON,
                   ROUND(100 * COUNT(g.RECORD_ID) / NULLIF(COUNT(*), 0), 1) AS WIN_PCT
            FROM MDM_CUSTOMER_STG s
            LEFT JOIN MDM_CUSTOMER_GOLDEN g ON g.RECORD_ID = s.RECORD_ID
            GROUP BY s.SOURCE_SYSTEM
            ORDER BY s.SOURCE_SYSTEM
        """)

        golden_scores = query_rows(cur, """
            SELECT TRUST_SCORE FROM MDM_CUSTOMER_GOLDEN
            ORDER BY TRUST_SCORE
        """)
        bins = [(0, 60, "0–60"), (60, 70, "60–70"), (70, 80, "70–80"),
                (80, 90, "80–90"), (90, 101, "90–100")]
        bins = [
            (float("-inf"), 60, "Poor (<60)"),
            (60, 80, "Fair (60-80)"),
            (80, 90, "Good (80-90)"),
            (90, float("inf"), "Excellent (>90)"),
        ]
        counts = Counter()
        for row in golden_scores:
            score = float(row["trust_score"] or 0)
            for low, high, label in bins:
                if low <= score < high:
                    counts[label] += 1
                    break

        review = query_rows(cur, """
            SELECT CLUSTER_ID, FIRST_NAME || ' ' || LAST_NAME AS NAME, EMAIL,
                   SOURCE_SYSTEM AS SOURCE, TRUST_SCORE AS TRUST
            FROM MDM_CUSTOMER_GOLDEN
            ORDER BY TRUST_SCORE NULLS FIRST, CLUSTER_ID
            FETCH FIRST 100 ROWS ONLY
        """)
        pillars = {
            key: round(float(raw[column] or 0), 1)
            for key, column in (("rules", "rules_score"), ("drift", "drift_score"),
                                ("anomaly", "anomaly_score"))
        }
        return {
            "ready": True,
            "metrics": metrics,
            "pillars": pillars,
            "overall_trust": round(float(raw["overall_trust"] or 0), 1),
            "pipeline": pipeline,
            "distribution": [{"label": label, "count": counts[label]} for _, _, label in bins],
            "review": review,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not read MDM Oracle tables: {exc}") from exc
    finally:
        conn.close()


@app.get("/api/mdm/cluster/{cluster_id}")
def mdm_cluster(cluster_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = query_rows(cur, """
            SELECT s.RECORD_ID, s.SOURCE_SYSTEM, s.FIRST_NAME, s.LAST_NAME,
                   s.EMAIL, s.PHONE, s.CITY, s.STATE, s.POSTAL_CODE AS ZIP,
                   sc.TRUST_SCORE, sc.RULES_SCORE, sc.DRIFT_SCORE, sc.ANOMALY_SCORE,
                   sc.SURVIVORSHIP_REASON AS REASON_SELECTED,
                   CASE WHEN g.RECORD_ID IS NULL THEN 0 ELSE 1 END AS IS_GOLDEN
            FROM MDM_CUSTOMER_STG s
            LEFT JOIN MDM_CUSTOMER_SCORES sc ON sc.RECORD_ID = s.RECORD_ID
            LEFT JOIN MDM_CUSTOMER_GOLDEN g ON g.RECORD_ID = s.RECORD_ID
            WHERE s.CLUSTER_ID = :cluster_id
            ORDER BY CASE WHEN g.RECORD_ID IS NULL THEN 1 ELSE 0 END,
                     sc.TRUST_SCORE DESC NULLS LAST, s.RECORD_ID
        """, {"cluster_id": cluster_id})
        if not rows:
            raise HTTPException(status_code=404, detail="MDM cluster not found")
        def record(row):
            row["trust_score"] = round(float(row["trust_score"] or 0), 1)
            for key in ("rules_score", "drift_score", "anomaly_score"):
                row[key] = round(float(row[key] or 0), 1)
            row["reason_selected"] = row["reason_selected"] or "Highest trust score in cluster"
            return row
        golden = next((row for row in rows if row["is_golden"]), rows[0])
        return {
            "cluster_id": cluster_id,
            "total_records": len(rows),
            "golden_record": record(golden),
            "duplicate_candidates": [record(row) for row in rows if row is not golden],
        }
    finally:
        conn.close()
