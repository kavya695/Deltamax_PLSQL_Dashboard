"""
1_generate_breach_data.py
=========================
Generates a synthetic customer-records dataset with intentionally injected
data-security issues across all four categories. This is the data the
security scanners (2-5) consume; it gives each scanner something real to
find so the dashboard isn't full of zeros.

Output: security/results/breach_dataset.csv
        security/results/breach_baseline.csv   (an earlier "snapshot" used
                                                 by the tamper scanner)
        security/results/breach_groundtruth.csv (which rows were seeded
                                                  with which issue — for
                                                  validation / not shown to
                                                  the dashboard)

What's intentionally seeded
---------------------------
Category 1 — Sensitive data exposure:
   * raw US-style phone numbers in notes
   * SSN-shaped strings (using test patterns, never real)
   * credit-card-shaped numbers using the IANA test PAN ranges
     (4111-1111-... etc.) so we don't risk anything resembling real PANs
   * API-key-shaped strings ("sk_test_...", "AKIA...") in notes
   * high-entropy secret strings in notes

Category 3 — Fraud / abuse signals:
   * synthetic-identity clusters: groups of accounts sharing the same
     home_address but different names and DOBs
   * future-dated rows: created_at set 30-90 days in the future
   * mass duplication: implausibly identical numeric values across rows
   * accounts whose lifetime value is wildly above the cohort's 99th
     percentile (single-account dominance pattern)

Category 4 — Tamper / integrity:
   * a "baseline" snapshot is written first; then the live dataset is
     mutated AFTER the baseline so we can show two integrity signals:
       - row_hash mismatches between baseline and current
       - fields that changed without updated_at advancing
   * a few rows have foreign_key references that point at non-existent
     reference values (broken FKs that appeared after the fact)

None of this is real PII. Patterns use documented test prefixes / fake
domains. The point is to make the detectors visible and verifiable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Oracle persistence is handled by run_security_oracle.py


# ---------- Reproducibility ----------
SEED = 7
random.seed(SEED)
np.random.seed(SEED)
rng = np.random.default_rng(SEED)


# ---------- Configuration ----------
N_BASE_ROWS_DEFAULT = 400       # the bulk "clean" population
N_SEEDED_DEFAULT = 6            # rows that carry an intentional issue
                                  # (split across the 4 categories)

OUT_DIR = Path(__file__).resolve().parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Realistic-ish vocab ----------
FIRSTS = ["Priya", "John", "Amit", "Sara", "Linh", "Kofi", "Mei", "Diego",
         "Anya", "Ravi", "Hana", "Theo", "Noor", "Kai", "Layla"]
LASTS = ["Sharma", "Smith", "Patel", "Park", "Mensah", "Tanaka", "Garcia",
         "Cohen", "Rossi", "Khan", "Adeyemi", "Lopez", "Murphy"]
CITIES = [("Austin", "TX", "78701"), ("Brooklyn", "NY", "11201"),
          ("Seattle", "WA", "98101"), ("Atlanta", "GA", "30301"),
          ("San Jose", "CA", "95101"), ("Denver", "CO", "80202"),
          ("Boston", "MA", "02101")]
JOBS = ["Software Engineer", "Sales Manager", "Nurse", "Designer",
        "Operations Lead", "Analyst", "Teacher", "Pilot", "Consultant"]
SOURCES = ["CRM", "eCommerce", "Loyalty", "POS", "ERP"]


def _rid() -> str:
    return uuid.uuid4().hex[:12].upper()


def _phone_real(rng) -> str:
    """A US-style phone string. Cosmetic — never a real allocated number."""
    return f"({rng.integers(200,999)}) {rng.integers(200,999)}-{rng.integers(1000,9999)}"


def _email_clean(first: str, last: str, rng) -> str:
    return f"{first.lower()}.{last.lower()}{rng.integers(1,99)}@example.com"


def _row_hash(d: dict, exclude: tuple = ("row_hash", "notes")) -> str:
    """Stable hash over the meaningful fields. We stringify every value so
    the hash survives a CSV round-trip (pandas would otherwise convert
    "02101" -> 2101, which changes the string repr and breaks the hash)."""
    pieces = []
    for k in sorted(d.keys()):
        if k in exclude: continue
        pieces.append(f"{k}={str(d[k])}")
    return hashlib.sha256("|".join(pieces).encode()).hexdigest()[:16]


# ============================================================
# 1) Build the clean baseline population
# ============================================================
def build_clean_rows(n: int, base_ts: datetime) -> list[dict]:
    rows = []
    for i in range(n):
        first = random.choice(FIRSTS)
        last = random.choice(LASTS)
        city, state, zip_ = random.choice(CITIES)
        dob_year = int(rng.integers(1945, 2005))
        created = base_ts - timedelta(days=int(rng.integers(30, 1500)))
        # updated_at must lie between created_at and now — never in the future,
        # otherwise the fraud scanner's future-dated check fires on the clean
        # baseline. We compute the available window and pick within it.
        max_update_days = max(1, (base_ts - created).days)
        updated = created + timedelta(days=int(rng.integers(0, max_update_days)))
        rows.append({
            "record_id":     _rid(),
            "source_system": random.choice(SOURCES),
            "first_name":    first,
            "last_name":     last,
            "email":         _email_clean(first, last, rng),
            "phone":         _phone_real(rng),
            "dob_year":      dob_year,
            "gender":        random.choice(["F", "M", "X"]),
            "city":          city,
            "state":         state,
            "zip":           zip_,
            "job_title":     random.choice(JOBS),
            "home_address":  f"{int(rng.integers(1,9999))} {random.choice(['Main','Oak','Pine','River','Cedar'])} St",
            "lifetime_value": round(float(rng.gamma(shape=2.0, scale=400.0)), 2),
            "notes":         "",   # filled in by category-1 seeders below
            "ref_country":   random.choice(["US", "CA", "UK"]),
            "created_at":    created.strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at":    updated.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    return rows


# ============================================================
# 2) Category-1 seeders (sensitive-data exposure)
# ============================================================
def seed_category_1(rows: list[dict], gt: list[dict], n: int):
    """Inject cleartext PII/credentials/PAN/SSN into the `notes` column
    of n randomly selected rows."""
    candidates = rng.choice(len(rows), size=n, replace=False)
    types = ["phone_in_notes", "ssn_in_notes",
             "pan_in_notes", "apikey_in_notes", "secret_in_notes"]
    for idx in candidates:
        kind = random.choice(types)
        r = rows[idx]
        if kind == "phone_in_notes":
            r["notes"] = f"call back at {_phone_real(rng)}, leave voicemail"
        elif kind == "ssn_in_notes":
            # 9-digit pattern that IS NOT a valid SSN (uses 000 area which is invalid)
            r["notes"] = f"verified id: 000-{int(rng.integers(10,99))}-{int(rng.integers(1000,9999))}"
        elif kind == "pan_in_notes":
            # Visa test prefix 4111 (IANA reserved test range)
            r["notes"] = f"refund pending on card 4111-1111-1111-{int(rng.integers(1000,9999))}"
        elif kind == "apikey_in_notes":
            r["notes"] = f"used token sk_test_{''.join(random.choices('abcdef0123456789', k=24))} for the call"
        else:  # secret_in_notes
            r["notes"] = f"shared aws creds AKIA{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567', k=16))} via slack"
        gt.append({"record_id": r["record_id"], "category": 1, "subtype": kind})


# ============================================================
# 3) Category-2 seeders (re-identification risk)
# ============================================================
def seed_category_2(rows: list[dict], gt: list[dict], n: int):
    """Tune some rows so the quasi-identifier combination
    (zip, dob_year, gender, job_title) is unique or near-unique.
    We do this by giving a few rows rare/unusual combinations."""
    rare_jobs = ["Astronaut", "Glaciologist", "Sommelier", "Volcanologist"]
    candidates = rng.choice(len(rows), size=n, replace=False)
    for idx in candidates:
        r = rows[idx]
        # Make this row uniquely identifiable: rare job + very specific
        # year + non-modal gender so the equivalence class is k=1.
        r["job_title"] = random.choice(rare_jobs)
        r["dob_year"] = random.choice([1928, 1932, 2003, 2004])
        r["gender"] = "X"
        gt.append({"record_id": r["record_id"], "category": 2, "subtype": "k1_singleton"})


# ============================================================
# 4) Category-3 seeders (fraud / abuse signals)
# ============================================================
def seed_category_3(rows: list[dict], gt: list[dict], n: int):
    """Inject four fraud-shaped subsets."""
    base_ts = datetime.now()
    # 4a) synthetic-identity cluster: shared address, different names+DOBs
    n_cluster = max(8, n // 4)
    shared = "1 Phantom Drive"
    idxs = rng.choice(len(rows), size=n_cluster, replace=False)
    for idx in idxs:
        rows[idx]["home_address"] = shared
        rows[idx]["zip"] = "00000"
        gt.append({"record_id": rows[idx]["record_id"], "category": 3,
                   "subtype": "synthetic_identity_cluster"})

    # 4b) future-dated rows
    n_future = max(5, n // 6)
    idxs = rng.choice(len(rows), size=n_future, replace=False)
    for idx in idxs:
        future = base_ts + timedelta(days=int(rng.integers(20, 90)))
        rows[idx]["created_at"] = future.strftime("%Y-%m-%dT%H:%M:%S")
        rows[idx]["updated_at"] = future.strftime("%Y-%m-%dT%H:%M:%S")
        gt.append({"record_id": rows[idx]["record_id"], "category": 3,
                   "subtype": "future_dated"})

    # 4c) mass duplication: implausibly identical lifetime_value
    n_dup = max(8, n // 5)
    idxs = rng.choice(len(rows), size=n_dup, replace=False)
    for idx in idxs:
        rows[idx]["lifetime_value"] = 9999.99
        gt.append({"record_id": rows[idx]["record_id"], "category": 3,
                   "subtype": "mass_duplicate_value"})

    # 4d) extreme single-account dominance (above-99th-percentile spikes)
    n_spike = max(3, n // 10)
    idxs = rng.choice(len(rows), size=n_spike, replace=False)
    for idx in idxs:
        rows[idx]["lifetime_value"] = round(float(rng.uniform(80_000, 250_000)), 2)
        gt.append({"record_id": rows[idx]["record_id"], "category": 3,
                   "subtype": "extreme_outlier_value"})


# ============================================================
# 5) Category-4 seeders (tamper / integrity)
# ============================================================
def seed_category_4(rows: list[dict], gt: list[dict], n: int):
    """We mutate AFTER the baseline snapshot has been hashed, so the
    tamper scanner can detect the change. Also break a few foreign keys
    and fields-changed-without-updated_at."""
    candidates = list(rng.choice(len(rows), size=n, replace=False))

    # 4a) silent edit: change a value, do NOT advance updated_at
    for idx in candidates[: n // 2]:
        old_val = rows[idx]["lifetime_value"]
        rows[idx]["lifetime_value"] = round(old_val * float(rng.uniform(1.5, 4.0)) + 50.0, 2)
        # deliberately do NOT touch updated_at
        gt.append({"record_id": rows[idx]["record_id"], "category": 4,
                   "subtype": "silent_edit"})

    # 4b) broken foreign key: point ref_country at a value not in the
    #     reference set ("US", "CA", "UK")
    for idx in candidates[n // 2 :]:
        rows[idx]["ref_country"] = random.choice(["ZZ", "??", "XX"])
        gt.append({"record_id": rows[idx]["record_id"], "category": 4,
                   "subtype": "broken_fk"})


# ============================================================
# Orchestration
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="Generate synthetic breach data.")
    ap.add_argument("--rows", type=int, default=N_BASE_ROWS_DEFAULT,
                    help="Clean-population row count (default 4000)")
    ap.add_argument("--seeded", type=int, default=N_SEEDED_DEFAULT,
                    help="Total seeded breach rows across all 4 categories (default 600)")
    args = ap.parse_args()

    print(f"[1/4] Building clean population — {args.rows} rows…")
    base_ts = datetime.now()
    rows = build_clean_rows(args.rows, base_ts)

    # --------- Hash + write the BASELINE first (before any mutation) ---------
    for r in rows:
        r["row_hash"] = _row_hash(r)
    baseline = pd.DataFrame(rows)
    baseline_path = OUT_DIR / "breach_baseline.csv"
    baseline.to_csv(baseline_path, index=False)
    print(f"        baseline snapshot -> {baseline_path}")
    upload_to_bq(baseline, 'security_breach_baseline')

    # --------- Now seed three categories of issues ---------
    gt: list[dict] = []
    per_cat = max(50, args.seeded // 3)
    print(f"[2/4] Seeding category 1 (sensitive data) — {per_cat} rows…")
    seed_category_1(rows, gt, per_cat)
    print(f"[2/4] Seeding category 3 (fraud signals) — {per_cat} rows…")
    seed_category_3(rows, gt, per_cat)
    print(f"[2/4] Seeding category 4 (tamper) — {per_cat} rows…")
    seed_category_4(rows, gt, per_cat)

    # --------- Recompute row_hash for the LIVE dataset ---------
    # NOTE: notes are excluded from the hash so category-1 seeding doesn't
    # by itself trigger tamper alerts. category-4 changes lifetime_value
    # and ref_country, which ARE in the hash — so those will mismatch.
    for r in rows:
        r["row_hash"] = _row_hash(r)

    # --------- Save the live dataset + groundtruth ---------
    df = pd.DataFrame(rows)
    out_path = OUT_DIR / "breach_dataset.csv"
    df.to_csv(out_path, index=False)
    print(f"[3/4] live dataset -> {out_path} ({len(df)} rows, {df.shape[1]} cols)")
    upload_to_bq(df, 'security_breach_dataset')

    gt_df = pd.DataFrame(gt)
    gt_path = OUT_DIR / "breach_groundtruth.csv"
    gt_df.to_csv(gt_path, index=False)
    print(f"[4/4] groundtruth -> {gt_path} ({len(gt_df)} seeded findings)")
    upload_to_bq(gt_df, 'security_breach_groundtruth')
    print(f"        per category: {gt_df['category'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
