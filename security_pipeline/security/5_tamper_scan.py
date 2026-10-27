"""
5_tamper_scan.py
================
Detects integrity violations by comparing the current dataset against a
prior "baseline" snapshot. Three checks:

  - row_hash_mismatch     : the row's stored row_hash doesn't match its
                            content (= the row was modified after the
                            hash was computed, or the hash itself was
                            altered without re-hashing)
  - silent_edit           : the row's content differs from the baseline
                            but its updated_at didn't advance
  - broken_fk             : ref_country points at a value not in the
                            valid reference set

Output: security_findings_tamper.csv

Honesty about limits
--------------------
On snapshot data this is a demonstration of the technique, not a real-
world breach detector. In production you'd need:
  (a) signed snapshots stored on append-only media (or a managed audit
      table) so the baseline can't itself be tampered with;
  (b) the row_hash computed at write-time by a trusted ingest service;
  (c) a foreign-key reference table maintained separately.
The scanner's algorithms (hash diff + FK check + silent-edit detection)
are exactly what you'd run in production. The data assumptions are what
change.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Oracle persistence is handled by run_security_oracle.py


HERE = Path(__file__).resolve().parent
LIVE_FILE = HERE / "results" / "breach_dataset.csv"
BASE_FILE = HERE / "results" / "breach_baseline.csv"
OUT_FILE = HERE / "results" / "security_findings_tamper.csv"

# What we consider a valid ref_country in the reference table.
VALID_REF_COUNTRIES = {"US", "CA", "UK"}


def row_hash(d: dict, exclude=("row_hash", "notes")) -> str:
    """MUST match the function in 1_generate_breach_data.py.
    Stringifying every value makes the hash invariant under CSV
    round-trip (e.g. zip='02101' would otherwise become int 2101)."""
    pieces = []
    for k in sorted(d.keys()):
        if k in exclude: continue
        pieces.append(f"{k}={str(d[k])}")
    return hashlib.sha256("|".join(pieces).encode()).hexdigest()[:16]


def main():
    print(f"[tamper] reading {LIVE_FILE} and {BASE_FILE}")
    # IMPORTANT: read as strings so values like zip="02101" don't get
    # converted to int 2101, which would break hash comparison. The hash
    # was originally computed over the string form of every field.
    live = pd.read_csv(LIVE_FILE, low_memory=False, dtype=str, keep_default_na=False)
    base = pd.read_csv(BASE_FILE, low_memory=False, dtype=str, keep_default_na=False)

    findings: list[dict] = []

    # ---- Check 1: recompute hash on the LIVE row, see if it matches ----
    # On the baseline this would always pass. On the live dataset, rows
    # that were silently edited after the baseline was written will fail.
    # We exclude `notes` from the hash deliberately (so DSPM seeding alone
    # doesn't trigger the tamper alarm — only category-4 mutations do).
    print(f"[tamper] checking row_hash on {len(live)} live rows…")
    for _, row in live.iterrows():
        d = row.to_dict()
        expected = d.get("row_hash")
        actual = row_hash(d)
        if expected != actual:
            findings.append({
                "record_id": row["record_id"],
                "type":      "row_hash_mismatch",
                "detail":    f"stored={expected}, recomputed={actual}",
                "severity":  "critical",
            })

    # ---- Check 2: compare with baseline. If lifetime_value changed but
    #              updated_at did not, that's a silent edit.
    print("[tamper] cross-referencing against baseline…")
    base_idx = base.set_index("record_id")
    overlap = live[live["record_id"].isin(base_idx.index)]
    for _, row in overlap.iterrows():
        b = base_idx.loc[row["record_id"]]
        # If both lifetime_value and ref_country are unchanged we move on.
        changed_value = (row["lifetime_value"] != b["lifetime_value"]) or \
                        (row["ref_country"]    != b["ref_country"])
        if not changed_value:
            continue
        if row["updated_at"] == b["updated_at"]:
            findings.append({
                "record_id": row["record_id"],
                "type":      "silent_edit",
                "detail":    "content changed but updated_at is identical to baseline",
                "severity":  "high",
            })

    # ---- Check 3: broken foreign keys ----
    print("[tamper] checking foreign keys…")
    bad_fk = live[~live["ref_country"].isin(VALID_REF_COUNTRIES)]
    for _, row in bad_fk.iterrows():
        findings.append({
            "record_id": row["record_id"],
            "type":      "broken_fk",
            "detail":    f"ref_country='{row['ref_country']}' not in reference table",
            "severity":  "high",
        })

    out = pd.DataFrame(findings)
    out.to_csv(OUT_FILE, index=False)
    print(f"[tamper] -> {OUT_FILE}  ({len(out)} findings)")
    upload_to_bq(out, 'security_findings_tamper')
    if not out.empty:
        print(out.groupby(["type", "severity"]).size().to_string())


if __name__ == "__main__":
    main()
