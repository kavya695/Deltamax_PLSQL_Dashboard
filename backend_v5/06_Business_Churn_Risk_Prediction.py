"""
DeltaMax V5 - Business Churn Risk Prediction (Oracle)

Reads DM_V5_STG_CREDIT_BUREAU, trains the existing Random Forest churn model,
creates SHAP explanations, stores results in Oracle, and optionally sends
CRITICAL/HIGH alerts through SendGrid.

No CSV input/output.
No S3 operations.
"""

import os
import warnings
import pandas as pd
import numpy as np
import oracledb
import shap

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score

warnings.filterwarnings("ignore")

# ---------------- CONFIG ----------------
ORACLE_USER = "DELTAMAX_V5"
ORACLE_PASSWORD = "DeltaMaxV5@2026"
ORACLE_DSN = "localhost:1521/FREEPDB1"

STAGING_TABLE = "DM_V5_STG_CREDIT_BUREAU"
RESULT_TABLE = "DM_V5_CHURN_RISK_RESULTS"
METRICS_TABLE = "DM_V5_CHURN_MODEL_METRICS"
IMPORTANCE_TABLE = "DM_V5_CHURN_FEATURE_IMPORTANCE"

SENDGRID_API_KEY = os.getenv("DELTAMAX_SENDGRID_API_KEY")
SENDER = os.getenv("DELTAMAX_ALERT_SENDER")
RECEIVER = os.getenv("DELTAMAX_ALERT_RECEIVER")

RISK_PROFILE_MAP = {"Low": 0, "Medium": 1, "High": 2, "Very_High": 3}

# averageAccountAge is intentionally omitted because it does not exist
# in the current Oracle staging table.
BAD_COLS = [
    "creditutilizationratio", "debttoincome_ratio",
    "delinquentaccountcount", "collectionscount",
    "chargeoffcount", "judgmentcount", "taxliencount",
    "numberofinquiries", "hasdelinquency", "hasdefaulted",
    "hasbankruptcy"
]
GOOD_COLS = [
    "creditscore", "paymenthistoryscore",
    "monthssincelastdelinquency", "creditworthiness_score"
]
FEATURE_COLS = BAD_COLS + GOOD_COLS + ["riskprofile_ordinal"]

TIER_QUANTILES = {"CRITICAL": 0.95, "HIGH": 0.85, "WATCH": 0.65}


# ---------------- ORACLE ----------------

def get_connection():
    print("Connecting to Oracle...")
    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )
    print("Connected to Oracle successfully.")
    return conn


def load_data(conn):
    sql = f"""
        SELECT
            BATCH_ID, RECORD_ID, BUSINESSID, BUSINESSNAME,
            INDUSTRY, SEGMENT, CREDITSCORE, PAYMENTHISTORYSCORE,
            CREDITUTILIZATIONRATIO, DELINQUENTACCOUNTCOUNT,
            COLLECTIONSCOUNT, CHARGEOFFCOUNT, JUDGMENTCOUNT,
            TAXLIENCOUNT, NUMBEROFINQUIRIES, HASDELINQUENCY,
            HASDEFAULTED, HASBANKRUPTCY, MONTHSSINCELASTDELINQUENCY,
            DEBTTOINCOME_RATIO,
            CREDITWORTHINESSSCORE AS CREDITWORTHINESS_SCORE,
            RISKPROFILE, DATA_MONTH
        FROM {STAGING_TABLE}
        WHERE BUSINESSID IS NOT NULL
          AND DATA_MONTH IS NOT NULL
        ORDER BY DATA_MONTH, BUSINESSID, RECORD_ID
    """

    df = pd.read_sql(sql, conn)
    if df.empty:
        raise RuntimeError("No usable records found in Oracle staging.")

    df.columns = [c.lower() for c in df.columns]

    for col in BAD_COLS + GOOD_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[col].median()).fillna(0)

    df["riskprofile_ordinal"] = (
        df["riskprofile"].astype(str).str.strip()
        .map(RISK_PROFILE_MAP).fillna(1)
    )

    df["businessid"] = df["businessid"].astype(str)
    df["businessname"] = df["businessname"].fillna(df["businessid"])
    df["data_month"] = df["data_month"].astype(str).str.strip()

    # One business per month; retain the latest record.
    df = (
        df.sort_values(["data_month", "businessid", "record_id"])
          .drop_duplicates(["data_month", "businessid"], keep="last")
          .reset_index(drop=True)
    )

    return df


def build_panel(df):
    months = sorted(df["data_month"].unique().tolist())

    if len(months) < 3:
        raise RuntimeError(
            f"Need at least 3 months for churn modeling. Found {len(months)}."
        )

    frames = {m: df[df["data_month"] == m].copy() for m in months}
    rows = []

    for i in range(len(months) - 1):
        current = frames[months[i]].copy()
        next_ids = set(frames[months[i + 1]]["businessid"])

        current["as_of_month"] = months[i]
        current["target_month"] = months[i + 1]
        current["churned_next_month"] = (
            ~current["businessid"].isin(next_ids)
        ).astype(int)

        rows.append(current)

    return pd.concat(rows, ignore_index=True), months, frames


# ---------------- MODEL ----------------

def train_and_validate(panel, months):
    holdout_target = months[-1]

    train = panel[panel["target_month"] != holdout_target]
    test = panel[panel["target_month"] == holdout_target]

    X_train = train[FEATURE_COLS]
    y_train = train["churned_next_month"]
    X_test = test[FEATURE_COLS]
    y_test = test["churned_next_month"]

    if y_train.nunique() < 2:
        raise RuntimeError("Training data contains only one churn class.")

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=25,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, proba) if y_test.nunique() >= 2 else np.nan
    pr_auc = (
        average_precision_score(y_test, proba)
        if y_test.nunique() >= 2 else np.nan
    )

    order = np.argsort(-proba)
    top_n = max(1, len(order) // 10)
    base_rate = float(y_test.mean())
    top_rate = float(y_test.iloc[order[:top_n]].mean())
    lift = top_rate / base_rate if base_rate > 0 else np.nan

    metrics = {
        "holdout_transition": f"Global holdout {months[-2]} -> {holdout_target}",
        "n_train": len(train),
        "n_test": len(test),
        "base_churn_rate_test": base_rate,
        "roc_auc": None if np.isnan(auc) else float(auc),
        "pr_auc": None if np.isnan(pr_auc) else float(pr_auc),
        "top_decile_lift": None if np.isnan(lift) else float(lift)
    }

    return model, metrics


def score_month(model, month_frame, retrospective=True):
    """Score one monthly snapshot. Historical backfills are retrospective, not point-in-time predictions."""
    live = month_frame.copy()
    live["churn_probability"] = model.predict_proba(
        live[FEATURE_COLS]
    )[:, 1]

    q = live["churn_probability"].quantile

    def tier(p):
        if p >= q(TIER_QUANTILES["CRITICAL"]):
            return "CRITICAL"
        if p >= q(TIER_QUANTILES["HIGH"]):
            return "HIGH"
        if p >= q(TIER_QUANTILES["WATCH"]):
            return "WATCH"
        return "LOW"

    live["risk_tier"] = live["churn_probability"].apply(tier)

    importances = dict(zip(FEATURE_COLS, model.feature_importances_))

    print("Calculating SHAP explanations...")
    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(live[FEATURE_COLS])

    if isinstance(sv, list):
        sv_churn = sv[1]
    elif isinstance(sv, np.ndarray) and sv.ndim == 3:
        sv_churn = sv[:, :, 1]
    else:
        sv_churn = sv

    shap_df = pd.DataFrame(
        sv_churn, columns=FEATURE_COLS, index=live.index
    )
    raw_pct = pd.DataFrame(
        {c: live[c].rank(pct=True) for c in FEATURE_COLS},
        index=live.index
    )

    factors = []
    for idx in live.index:
        contrib = shap_df.loc[idx].sort_values(ascending=False)
        parts = []

        for feat in contrib.index[:3]:
            if contrib[feat] <= 0:
                break
            pct = raw_pct.loc[idx, feat] * 100
            direction = "high" if pct >= 50 else "low"
            parts.append(f"{direction} {feat} ({pct:.0f}th pct)")

        factors.append("; ".join(parts))

    live["top_risk_factors"] = factors
    live["likely_churn_reason"] = live["top_risk_factors"].apply(
        lambda x: f"Elevated risk driven by {x}"
        if x else "Elevated risk profile relative to peers"
    )
    live["predicted_churn_by"] = (
        "Next month (retrospective backfill)" if retrospective else "Next month"
    )

    return live.sort_values("churn_probability", ascending=False), importances


# ---------------- SAVE TO ORACLE ----------------

def save_to_oracle(conn, batch_id, scored, metrics, importances):
    cur = conn.cursor()

    try:
        cur.execute(
            f"DELETE FROM {RESULT_TABLE} WHERE BATCH_ID = :1",
            [batch_id]
        )
        cur.execute(
            f"DELETE FROM {METRICS_TABLE} WHERE BATCH_ID = :1",
            [batch_id]
        )
        cur.execute(
            f"DELETE FROM {IMPORTANCE_TABLE} WHERE BATCH_ID = :1",
            [batch_id]
        )

        rows = []
        for _, r in scored.iterrows():
            rows.append((
                batch_id,
                str(r["businessid"]),
                str(r["businessname"])[:500],
                float(r["churn_probability"]),
                str(r["risk_tier"]),
                str(r["likely_churn_reason"])[:4000],
                str(r["predicted_churn_by"])[:50],
                str(r["top_risk_factors"])[:4000]
            ))

        cur.executemany(
            f"""
            INSERT INTO {RESULT_TABLE}
            (BATCH_ID, BUSINESSID, BUSINESSNAME, CHURN_PROBABILITY,
             RISK_TIER, LIKELY_CHURN_REASON, PREDICTED_CHURN_BY,
             TOP_RISK_FACTORS)
            VALUES (:1,:2,:3,:4,:5,:6,:7,:8)
            """,
            rows
        )

        cur.execute(
            f"""
            INSERT INTO {METRICS_TABLE}
            (BATCH_ID, HOLDOUT_TRANSITION, N_TRAIN, N_TEST,
             BASE_CHURN_RATE_TEST, ROC_AUC, PR_AUC, TOP_DECILE_LIFT)
            VALUES (:1,:2,:3,:4,:5,:6,:7,:8)
            """,
            [
                batch_id,
                metrics["holdout_transition"],
                metrics["n_train"],
                metrics["n_test"],
                metrics["base_churn_rate_test"],
                metrics["roc_auc"],
                metrics["pr_auc"],
                metrics["top_decile_lift"]
            ]
        )

        importance_rows = [
            (batch_id, feature, float(value))
            for feature, value in sorted(
                importances.items(), key=lambda x: -x[1]
            )
        ]

        cur.executemany(
            f"""
            INSERT INTO {IMPORTANCE_TABLE}
            (BATCH_ID, FEATURE_NAME, IMPORTANCE)
            VALUES (:1,:2,:3)
            """,
            importance_rows
        )

        conn.commit()
        print(f"[OK] Churn result rows inserted: {len(rows):,}")
        print(f"[OK] Feature importance rows inserted: {len(importance_rows)}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------- EMAIL ----------------

def send_email(scored, metrics, latest_month):
    at_risk = scored[scored["risk_tier"].isin(["CRITICAL", "HIGH"])]

    if at_risk.empty:
        print("[OK] No CRITICAL/HIGH businesses. No email sent.")
        return

    if not SENDGRID_API_KEY or not SENDER or not RECEIVER:
        print("[SKIP] SendGrid environment variables are not configured.")
        return

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        rows = []
        for _, r in at_risk.head(25).iterrows():
            rows.append(
                f"""
                <tr>
                  <td>{r['businessname']}</td>
                  <td>{r['businessid']}</td>
                  <td>{r['risk_tier']}</td>
                  <td>{r['churn_probability']:.3f}</td>
                  <td>{r['top_risk_factors']}</td>
                </tr>
                """
            )

        html = f"""
        <html><body>
        <h2>DeltaMax V5 - Business Churn Risk Alerts</h2>
        <p>Latest Oracle month: <b>{latest_month}</b></p>
        <p>CRITICAL/HIGH businesses: <b>{len(at_risk):,}</b></p>
        <p>
          Holdout: {metrics['holdout_transition']}<br>
          ROC-AUC: {metrics['roc_auc']}<br>
          PR-AUC: {metrics['pr_auc']}<br>
          Top-decile lift: {metrics['top_decile_lift']}
        </p>
        <table border="1" cellpadding="6" cellspacing="0">
          <tr>
            <th>Business</th><th>ID</th><th>Tier</th>
            <th>Probability</th><th>Risk Factors</th>
          </tr>
          {''.join(rows)}
        </table>
        <p>Source: Oracle {RESULT_TABLE}. No CSV or S3 used.</p>
        </body></html>
        """

        message = Mail(
            from_email=SENDER,
            to_emails=RECEIVER,
            subject=f"DeltaMax V5 Business Churn Risk Alerts - {len(at_risk)}",
            html_content=html
        )

        response = SendGridAPIClient(SENDGRID_API_KEY).send(message)
        print(f"[OK] SendGrid status: {response.status_code}")

    except Exception as exc:
        print(f"[ERR] SendGrid email error: {exc}")


# ---------------- MAIN ----------------

def main():
    print("=" * 78)
    print("DELTAMAX V5 - ORACLE BUSINESS CHURN RISK PREDICTION")
    print("ALL-MONTH CHURN BACKFILL")
    print("=" * 78)

    conn = None

    try:
        conn = get_connection()
        df = load_data(conn)

        print(f"[OK] Oracle rows loaded: {len(df):,}")

        panel, months, frames = build_panel(df)
        print(f"[OK] Months: {', '.join(months)}")
        print(f"[OK] Panel rows: {len(panel):,}")
        print(
            f"[OK] Overall churn rate: "
            f"{panel['churned_next_month'].mean():.4f}"
        )

        print("\\n" + "=" * 78)
        print("TRAINING + TIME-BASED VALIDATION")
        print("=" * 78)

        model, metrics = train_and_validate(panel, months)

        print(f"Holdout transition: {metrics['holdout_transition']}")
        print(f"Training rows: {metrics['n_train']:,}")
        print(f"Validation rows: {metrics['n_test']:,}")
        print(f"ROC-AUC: {metrics['roc_auc']}")
        print(f"PR-AUC: {metrics['pr_auc']}")
        print(f"Top-decile lift: {metrics['top_decile_lift']}")

        # The model is trained using earlier transitions and validated on the
        # latest transition. Applying it to earlier monthly snapshots is a
        # retrospective backfill for dashboard history, NOT an as-of-month
        # forecast. The UI/database labels make that distinction explicit.
        all_scored = {}
        importances = dict(zip(FEATURE_COLS, model.feature_importances_))
        latest_month = months[-1]

        for month in months:
            month_frame = frames[month].copy()
            batch_ids = (
                month_frame["batch_id"].dropna().astype(str).unique().tolist()
            )
            if len(batch_ids) != 1:
                raise RuntimeError(
                    f"Expected one BATCH_ID for {month}, found: {batch_ids}"
                )
            batch_id = batch_ids[0]
            retrospective = month != latest_month

            print("\\n" + "-" * 78)
            print(
                f"SCORING {month} - {batch_id}"
                + (" (RETROSPECTIVE BACKFILL)" if retrospective else " (LATEST MONTH)")
            )
            print("-" * 78)

            scored, _ = score_month(
                model, month_frame, retrospective=retrospective
            )

            for tier in ["CRITICAL", "HIGH", "WATCH", "LOW"]:
                count = int((scored["risk_tier"] == tier).sum())
                print(f"{tier:8}: {count:>7,}")

            save_to_oracle(
                conn, batch_id, scored, metrics, importances
            )
            all_scored[month] = (batch_id, scored)
            print(f"[OK] Saved {len(scored):,} churn scores for {batch_id}")

        # Email only the latest month's results, avoiding one email per month.
        latest_batch_id, latest_scored = all_scored[latest_month]
        send_email(latest_scored, metrics, latest_month)

        print("\\n" + "=" * 78)
        print("BUSINESS CHURN RISK BACKFILL COMPLETED")
        print("=" * 78)
        print(f"Months scored: {len(all_scored)}")
        print(f"First month: {months[0]}")
        print(f"Latest month: {latest_month}")
        print(f"Latest batch: {latest_batch_id}")
        print(f"Results: {RESULT_TABLE}")
        print(f"Metrics: {METRICS_TABLE}")
        print(f"Importance: {IMPORTANCE_TABLE}")
        print("Historical monthly scores are retrospective backfills.")
        print("Model metrics are global latest-transition holdout metrics.")
        print("No CSV files used.")
        print("No S3 operations performed.")

    finally:
        if conn:
            conn.close()
            print("\\nOracle connection closed.")


if __name__ == "__main__":
    main()
