"""
6_security_score.py
===================
Combines findings from the three scanners into:

  - security_findings.csv     : every finding from every scanner, unified
                                schema (record_id, category, type, detail,
                                severity, scanner)
  - security_records.csv      : per-record security score 0-100. Each
                                finding subtracts points by severity;
                                multiple findings stack. A record with
                                no findings gets 100.
  - security_summary.csv      : dataset-level summary (counts by
                                category, severity, top columns, headline
                                metrics for the dashboard).

Why a separate aggregator
-------------------------
Each scanner does one job well and stays simple. This file is where the
*policy* lives — how much to deduct, what counts as "critical", how to
present the rollup. Keeping it separate means tuning the scoring is one
file, not four.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Oracle persistence is handled by run_security_oracle.py


HERE = Path(__file__).resolve().parent
R = HERE / "results"

DSPM_FILE   = R / "security_findings_dspm.csv"
FRAUD_FILE  = R / "security_findings_fraud.csv"
TAMPER_FILE = R / "security_findings_tamper.csv"
LIVE_FILE   = R / "breach_dataset.csv"

OUT_FINDINGS = R / "security_findings.csv"
OUT_RECORDS  = R / "security_records.csv"
OUT_SUMMARY  = R / "security_summary.json"


# How many points each severity finding deducts from a record's score.
SEV_PENALTY = {"critical": 30, "high": 15, "medium": 6, "low": 2}
MIN_SCORE = 0


def _safe_read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def main():
    # 1) Pull every finding into a unified frame. Each scanner has its own
    # native columns; we normalize per scanner to (record_id, type, detail,
    # severity) before unioning, so this isn't a fragile mass-merge.
    parts = []
    for path, scanner, category, cat_id in [
        (DSPM_FILE,   "dspm",   "Sensitive data exposure",  1),
        (FRAUD_FILE,  "fraud",  "Fraud / abuse signals",    2),
        (TAMPER_FILE, "tamper", "Tamper / integrity",       3),
    ]:
        df = _safe_read(path)
        if df.empty: continue
        df = df.copy()

        # Normalize to a common schema. Some scanners use `match`, some
        # use their own columns. We pick the right ones per scanner.
        if scanner == "dspm":
            # native: record_id, column, type, match, confidence, severity
            df["detail"] = "column=" + df["column"].astype(str) + ": " + df["match"].astype(str)
        # fraud and tamper already provide `type` + `detail` + `severity`

        df["scanner"] = scanner
        df["category"] = category
        df["category_id"] = cat_id
        parts.append(df[["record_id", "scanner", "category", "category_id",
                         "type", "detail", "severity"]])

    if not parts:
        print("[score] no findings to aggregate")
        return

    findings = pd.concat(parts, ignore_index=True)
    findings.to_csv(OUT_FINDINGS, index=False)
    print(f"[score] unified findings -> {OUT_FINDINGS}  ({len(findings)})")
    upload_to_bq(findings, 'security_findings')

    # 2) Per-record score: start at 100, deduct per finding.
    findings["penalty"] = findings["severity"].map(SEV_PENALTY).fillna(0)
    record_penalty = findings.groupby("record_id")["penalty"].sum().clip(upper=100)
    live = pd.read_csv(LIVE_FILE, low_memory=False, dtype=str, keep_default_na=False)
    records = live[["record_id"]].copy()
    records["security_score"] = (100 - records["record_id"].map(record_penalty).fillna(0)).clip(lower=MIN_SCORE)

    # Worst category per record (drives the per-record badge in the UI)
    worst = (findings.sort_values("penalty", ascending=False)
                     .drop_duplicates("record_id")
                     [["record_id", "category", "severity"]])
    records = records.merge(worst, on="record_id", how="left")
    records["category"] = records["category"].fillna("—")
    records["severity"] = records["severity"].fillna("none")
    records.to_csv(OUT_RECORDS, index=False)
    print(f"[score] per-record scores -> {OUT_RECORDS}")
    upload_to_bq(records, 'security_records')

    # 3) Dataset-level summary the API will hand to the dashboard.
    n_total = len(live)
    n_affected = int(records["record_id"].isin(findings["record_id"]).sum())
    overall_score = round(float(records["security_score"].mean()), 1)

    by_category = (findings.groupby("category")
                          .size().sort_values(ascending=False)
                          .to_dict())
    by_severity = (findings.groupby("severity")
                          .size().to_dict())
    by_type = (findings.groupby(["category", "type"])
                       .size().reset_index(name="count")
                       .sort_values("count", ascending=False))
    top_types = [
        {"category": r["category"], "type": r["type"], "count": int(r["count"])}
        for _, r in by_type.head(8).iterrows()
    ]

    # Column-level rollup: which columns sat under the most DSPM findings?
    dspm = _safe_read(DSPM_FILE)
    by_column = []
    if not dspm.empty and "column" in dspm.columns:
        col_counts = dspm.groupby(["column", "type"]).size().reset_index(name="count")
        col_counts = col_counts.sort_values("count", ascending=False)
        for _, r in col_counts.head(10).iterrows():
            by_column.append({"column": r["column"], "type": r["type"], "count": int(r["count"])})

    # Top examples per category (10 each) for the dashboard table
    examples_by_cat = {}
    for cat in by_category.keys():
        sub = findings[findings["category"] == cat]
        sub = sub.sort_values("penalty", ascending=False).head(10)
        examples_by_cat[cat] = [
            {"record_id": r["record_id"], "type": r["type"],
             "detail": str(r["detail"])[:120], "severity": r["severity"]}
            for _, r in sub.iterrows()
        ]

    summary = {
        "total_records": int(n_total),
        "records_with_findings": n_affected,
        "exposure_rate_pct": round(n_affected / n_total * 100, 1) if n_total else 0,
        "overall_security_score": overall_score,
        "by_category": {k: int(v) for k, v in by_category.items()},
        "by_severity": {k: int(v) for k, v in by_severity.items()},
        "top_types": top_types,
        "by_column": by_column,
        "examples_by_category": examples_by_cat,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"[score] dataset summary -> {OUT_SUMMARY}")
    upload_json_to_bq(summary, 'security_summary')
    print(f"[score] overall security score: {overall_score} / 100")
    print(f"[score] {n_affected:,}/{n_total:,} records have at least one finding")


if __name__ == "__main__":
    main()
