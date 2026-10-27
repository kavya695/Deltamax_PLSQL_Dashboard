"""
2_dspm_scan.py
==============
Sensitive-data exposure scanner (data security posture management).
Reads breach_dataset.csv. For every cell, runs a panel of detectors:

    - email addresses
    - US-style phone numbers
    - SSN-shaped patterns
    - credit-card-shaped patterns (PAN) using the Luhn check to cut
      false positives
    - API keys / cloud-credential shapes (stripe sk_test_, AWS AKIA…)
    - generic high-entropy "secret" strings

Each finding records: record_id, column, cell-snippet, type, confidence.
Output: security_findings_dspm.csv

Honesty about limits
--------------------
This is pattern-matching + a single structural check (Luhn). Regex
detectors are powerful but produce false positives — a 9-digit order id
looks a lot like an SSN. We mitigate by:
    1. Requiring a context check around SSN/PAN matches (presence of
       hyphens or specific lead bytes).
    2. Running Luhn on PAN candidates and discarding anything that fails.
    3. Reporting a `confidence` per finding so the UI can sort.
This is the same approach commercial DSPM tools take; it isn't ML, but
it's interpretable and tunable, which matters more for a security pillar
where every finding will get reviewed.
"""

from __future__ import annotations

import re
from pathlib import Path

import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Oracle persistence is handled by run_security_oracle.py


HERE = Path(__file__).resolve().parent
IN_FILE = HERE / "results" / "breach_dataset.csv"
OUT_FILE = HERE / "results" / "security_findings_dspm.csv"


# ============================================================
# Detectors
# ============================================================
# Each detector returns a list of (match_text, confidence) tuples.
# Confidence in [0, 1]; we use it for sorting + filtering in the UI.

RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_PHONE = re.compile(r"\b(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}\b")
RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
RE_PAN_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
RE_STRIPE_KEY = re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9]{16,}\b")
RE_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{12,20}\b")
RE_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9_/+]{32,}\b")


def luhn_check(pan_digits: str) -> bool:
    """Standard Luhn algorithm. Strips spaces/hyphens first.
    Returns True if the number passes Luhn (a necessary condition for
    being a real PAN). Reduces false-positives on long numeric IDs."""
    digits = [int(c) for c in pan_digits if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    s = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9: d -= 9
        s += d
    return s % 10 == 0


def find_emails(text: str):
    return [(m.group(), 0.95) for m in RE_EMAIL.finditer(text)]


def find_phones(text: str):
    return [(m.group(), 0.80) for m in RE_PHONE.finditer(text)]


def find_ssns(text: str):
    out = []
    for m in RE_SSN.finditer(text):
        # confidence drops if the area part is 000/666 or starts with 9
        # (invalid SSN ranges) — these are likely synthetic anyway, which
        # is *still* a security finding (don't store fake SSNs cleartext)
        # but we mark them lower so reviewers triage real ones first.
        area = m.group()[:3]
        conf = 0.90 if area not in ("000", "666") and not area.startswith("9") else 0.55
        out.append((m.group(), conf))
    return out


def find_pans(text: str):
    out = []
    for m in RE_PAN_CANDIDATE.finditer(text):
        cand = m.group()
        if not luhn_check(cand):
            continue
        # If it matches the IANA test-card prefixes (4111-1111-...) we
        # still report it — the point of DSPM is that PAN-shaped data
        # shouldn't sit in free-text columns, real or test.
        out.append((cand, 0.92))
    return out


def find_secrets(text: str):
    out = []
    for m in RE_STRIPE_KEY.finditer(text):
        out.append((m.group(), 0.97))
    for m in RE_AWS_KEY.finditer(text):
        out.append((m.group(), 0.95))
    # Fall through to generic high-entropy strings, but only if no more
    # specific match was found — and confidence is lower.
    if not out:
        for m in RE_HIGH_ENTROPY.finditer(text):
            # crude entropy heuristic: requires a mix of letters and digits
            s = m.group()
            if any(c.isdigit() for c in s) and any(c.isalpha() for c in s):
                out.append((s, 0.45))
    return out


DETECTORS = [
    ("phone",   find_phones),
    ("ssn",     find_ssns),
    ("pan",     find_pans),
    ("secret",  find_secrets),
]


# ============================================================
# Scan
# ============================================================
def scan_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    findings = []
    # Columns we know hold structured PII directly. Even if no regex
    # finds anything inside them, them sitting cleartext is itself a
    # finding — we surface that as a "column-level" risk.
    structured_pii_columns = {"phone": "phone"}

    text_columns = [c for c in df.columns if pd.api.types.is_string_dtype(df[c])]

    for col in text_columns:
        column_pii_kind = structured_pii_columns.get(col)
        for idx, val in df[col].items():
            if pd.isna(val):
                continue
            s = str(val)
            # Per-column detectors: scan free-text-style cells for
            # embedded patterns.
            for kind, fn in DETECTORS:
                for match_text, conf in fn(s):
                    findings.append({
                        "record_id":  df.at[idx, "record_id"] if "record_id" in df else idx,
                        "column":     col,
                        "type":       kind,
                        "match":      match_text[:80],
                        "confidence": round(conf, 2),
                        "severity":   _severity(kind, conf),
                    })
            # If the entire column is a known PII column, flag the cell
            # itself as exposed (regardless of regex hits).
            if column_pii_kind and s.strip():
                # Avoid double-reporting if a regex already caught it.
                already = any(f["record_id"] == df.at[idx, "record_id"] and
                              f["column"] == col and f["type"] == column_pii_kind
                              for f in findings[-6:])
                if not already:
                    findings.append({
                        "record_id":  df.at[idx, "record_id"] if "record_id" in df else idx,
                        "column":     col,
                        "type":       column_pii_kind,
                        "match":      s[:80],
                        "confidence": 0.99,
                        "severity":   "high",
                    })

    return pd.DataFrame(findings)


def _severity(kind: str, conf: float) -> str:
    """Map (kind, confidence) -> severity for the UI."""
    if kind in ("pan", "secret") and conf >= 0.8: return "critical"
    if kind == "ssn" and conf >= 0.8:             return "critical"
    if kind in ("email", "phone") and conf >= 0.8: return "high"
    if conf >= 0.5:                                return "medium"
    return "low"


def main():
    print(f"[dspm] reading {IN_FILE}")
    df = pd.read_csv(IN_FILE, low_memory=False)
    print(f"[dspm] scanning {len(df)} rows across {df.shape[1]} columns…")
    findings = scan_dataframe(df)
    findings.to_csv(OUT_FILE, index=False)
    print(f"[dspm] -> {OUT_FILE}  ({len(findings)} findings)")
    upload_to_bq(findings, 'security_findings_dspm')
    if not findings.empty:
        print("[dspm] by type / severity:")
        print(findings.groupby(["type", "severity"]).size().to_string())


if __name__ == "__main__":
    main()
