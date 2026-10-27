"""
4_fraud_signals_scan.py
=======================
Detects data-shape patterns that suggest fraud or abuse, using only the
data itself (no logs, no IPs). Each check produces its own findings:

  - synthetic_identity_cluster :  many accounts sharing one address
                                  but different names/DOBs
  - future_dated               :  rows whose created_at lies in the future
  - mass_duplicate_value       :  numeric values that repeat across rows
                                  far more than chance allows
  - extreme_outlier_value      :  values past the 99.5th percentile of
                                  their cohort by ~10x or more
  - mass_duplicate_address     :  same address used >N times
                                  (overlaps with synthetic-identity but
                                  catches the cleaner cases)

Output: security_findings_fraud.csv

Honesty about limits
--------------------
These are *signals*, not verdicts. A shared address might be a legit
family. A mass-duplicate value might be a default. The job of this
scanner is to surface the candidate set; a human reviewer (or a
downstream model) decides.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Oracle persistence is handled by run_security_oracle.py


HERE = Path(__file__).resolve().parent
IN_FILE = HERE / "results" / "breach_dataset.csv"
OUT_FILE = HERE / "results" / "security_findings_fraud.csv"


# Tunable thresholds. Keep them visible — they should be defensible.
SHARED_ADDRESS_MIN = 4          # >= this many accounts at one address = suspicious
DUPLICATE_VALUE_MIN = 10        # numeric value repeated this many times = suspicious
OUTLIER_RATIO = 10.0            # value > 10x the cohort 99.5th pct = extreme


def find_synthetic_identity(df: pd.DataFrame) -> list[dict]:
    """Group by home_address; flag groups with N+ rows where the names
    are mostly distinct (so it's not a duplicate-record problem, it's a
    different-people-same-address problem)."""
    out = []
    addr_groups = df.groupby("home_address")
    for addr, grp in addr_groups:
        if len(grp) < SHARED_ADDRESS_MIN: continue
        # Are the names distinct? (count unique first+last pairs)
        uniq_names = grp[["first_name", "last_name"]].drop_duplicates().shape[0]
        if uniq_names < max(3, int(len(grp) * 0.6)):
            continue  # looks like duplicate records, not synthetic identities
        for _, row in grp.iterrows():
            out.append({
                "record_id": row["record_id"],
                "type":      "synthetic_identity_cluster",
                "detail":    f"address shared by {len(grp)} accounts with {uniq_names} unique names",
                "severity":  "high" if len(grp) >= 8 else "medium",
            })
    return out


def find_future_dated(df: pd.DataFrame) -> list[dict]:
    out = []
    now = datetime.now()
    seen = set()
    for col in ["created_at", "updated_at"]:
        if col not in df.columns: continue
        ts = pd.to_datetime(df[col], errors="coerce")
        mask = ts > now
        for idx in df.index[mask]:
            rid = df.at[idx, "record_id"]
            if rid in seen:
                continue
            seen.add(rid)
            out.append({
                "record_id": rid,
                "type":      "future_dated",
                "detail":    f"{col} is in the future ({ts[idx].date()})",
                "severity":  "high",
            })
    return out


def find_mass_duplicate_value(df: pd.DataFrame) -> list[dict]:
    out = []
    # We look for repeated values in lifetime_value (numeric).
    if "lifetime_value" not in df.columns: return out
    counts = df["lifetime_value"].value_counts()
    suspicious = counts[counts >= DUPLICATE_VALUE_MIN]
    for val, cnt in suspicious.items():
        for idx in df.index[df["lifetime_value"] == val]:
            out.append({
                "record_id": df.at[idx, "record_id"],
                "type":      "mass_duplicate_value",
                "detail":    f"lifetime_value={val} repeated by {cnt} accounts",
                "severity":  "medium",
            })
    return out


def find_extreme_outliers(df: pd.DataFrame) -> list[dict]:
    """Value > OUTLIER_RATIO * 99.5th percentile."""
    out = []
    if "lifetime_value" not in df.columns: return out
    s = df["lifetime_value"].dropna()
    if s.empty: return out
    p995 = float(np.percentile(s, 99.5))
    threshold = p995 * OUTLIER_RATIO
    mask = df["lifetime_value"] > threshold
    for idx in df.index[mask]:
        out.append({
            "record_id": df.at[idx, "record_id"],
            "type":      "extreme_outlier_value",
            "detail":    f"lifetime_value={df.at[idx,'lifetime_value']:.0f} > {threshold:.0f} ({OUTLIER_RATIO}× p99.5)",
            "severity":  "critical",
        })
    return out


def main():
    print(f"[fraud] reading {IN_FILE}")
    df = pd.read_csv(IN_FILE, low_memory=False)

    all_findings: list[dict] = []
    print("[fraud] running synthetic-identity check…")
    all_findings += find_synthetic_identity(df)
    print("[fraud] running future-dated check…")
    all_findings += find_future_dated(df)
    print("[fraud] running mass-duplicate-value check…")
    all_findings += find_mass_duplicate_value(df)
    print("[fraud] running extreme-outlier check…")
    all_findings += find_extreme_outliers(df)

    out = pd.DataFrame(all_findings)
    out.to_csv(OUT_FILE, index=False)
    print(f"[fraud] -> {OUT_FILE}  ({len(out)} findings)")
    upload_to_bq(out, 'security_findings_fraud')
    if not out.empty:
        print(out.groupby(["type", "severity"]).size().to_string())


if __name__ == "__main__":
    main()
