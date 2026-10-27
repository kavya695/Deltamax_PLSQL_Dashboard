#!/usr/bin/env python
"""Read-only, schema-aware full-row validation: BigQuery -> Oracle.

Compares rows as a multiset, including duplicates, using BigQuery's schema as
canonical semantics for each column. This avoids false mismatches such as a
BigQuery BOOL compared with Oracle VARCHAR2 'false', or a BigQuery DATE
compared with an Oracle DATE/DATETIME driver value.
"""
import os, sys, json, math, hashlib, datetime as dt, csv
from decimal import Decimal, InvalidOperation
from collections import Counter
from pathlib import Path

try:
    from google.cloud import bigquery
    import oracledb
except ImportError as exc:
    sys.exit(f"Missing dependency: {exc}\nInstall with: py -m pip install google-cloud-bigquery oracledb")

BQ_PROJECT = os.getenv("BQ_PROJECT", "datatoolunstructured")
BQ_DATASET = os.getenv("BQ_DATASET", "deltamax_migration")
BQ_TABLE = os.getenv("BQ_TABLE", "hab_combined")
ORACLE_USER = os.getenv("ORACLE_USER", "DELTAMAX_V5")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
ORACLE_HOST = os.getenv("ORACLE_HOST", "localhost")
ORACLE_PORT = int(os.getenv("ORACLE_PORT", "1521"))
ORACLE_SERVICE = os.getenv("ORACLE_SERVICE", "FREEPDB1")
ORACLE_TABLE = os.getenv("ORACLE_TABLE", "BQ_HAB_COMBINED")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5000"))
REPORT_DIR = Path.cwd() / "migration_value_validation_v3"
REPORT_DIR.mkdir(exist_ok=True)

if not ORACLE_PASSWORD:
    sys.exit('ERROR: ORACLE_PASSWORD is not set. In PowerShell run: $env:ORACLE_PASSWORD = Read-Host "Oracle password"')

def safe_ident(name):
    if not name or not name.replace("_", "").isalnum():
        raise ValueError(f"Unexpected identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'

def to_decimal(value):
    if isinstance(value, Decimal): return value
    if isinstance(value, bool): return Decimal(1 if value else 0)
    if isinstance(value, (int, float)): return Decimal(str(value))
    return Decimal(str(value).strip())

def norm_datetime(value):
    if isinstance(value, dt.datetime):
        # BigQuery DATETIME has no timezone; Oracle DATE likewise has no timezone.
        return value.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds").rstrip("0").rstrip(".")
    s = str(value).strip().replace("T", " ")
    # Preserve up to microseconds, strip insignificant trailing zeroes.
    if "." in s:
        left, right = s.split(".", 1)
        digits = "".join(c for c in right if c.isdigit())[:6].rstrip("0")
        s = left + ("." + digits if digits else "")
    return s

def normalize(value, bq_type):
    """Normalize using the BigQuery column type, not the driver's Python type."""
    typ = (bq_type or "").upper()
    if value is None:
        return [typ or "NULL", None]
    if typ in ("BOOL", "BOOLEAN"):
        if isinstance(value, bool): b = value
        else:
            s = str(value).strip().lower()
            if s in ("true", "1", "yes", "y"): b = True
            elif s in ("false", "0", "no", "n"): b = False
            else: return ["BOOL_UNPARSED", str(value).strip()]
        return ["BOOL", b]
    if typ == "DATE":
        if isinstance(value, (dt.datetime, dt.date)):
            d = value.date() if isinstance(value, dt.datetime) else value
        else:
            d = dt.date.fromisoformat(str(value).strip()[:10])
        return ["DATE", d.isoformat()]
    if typ == "DATETIME":
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            value = dt.datetime.combine(value, dt.time())
        return ["DATETIME", norm_datetime(value)]
    if typ == "TIMESTAMP":
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt.timezone.utc)
            value = value.astimezone(dt.timezone.utc)
            return ["TIMESTAMP", value.isoformat(timespec="microseconds").rstrip("0").rstrip(".")]
        return ["TIMESTAMP", str(value).strip()]
    if typ in ("INT64", "INTEGER"):
        try: return ["INT64", int(to_decimal(value))]
        except (InvalidOperation, ValueError, TypeError): return ["INT64_UNPARSED", str(value).strip()]
    if typ in ("NUMERIC", "BIGNUMERIC"):
        try:
            d = to_decimal(value)
            if d == 0: s = "0"
            else: s = format(d.normalize(), "f")
            return ["NUMBER", s]
        except (InvalidOperation, ValueError, TypeError): return ["NUMBER_UNPARSED", str(value).strip()]
    if typ in ("FLOAT", "FLOAT64"):
        try:
            f = float(value)
            if math.isnan(f): return ["FLOAT64", "NaN"]
            if math.isinf(f): return ["FLOAT64", "Infinity" if f > 0 else "-Infinity"]
            return ["FLOAT64", format(Decimal(str(f)).normalize(), "f")]
        except (ValueError, TypeError): return ["FLOAT64_UNPARSED", str(value).strip()]
    if typ in ("BYTES",):
        if isinstance(value, bytes): raw = value
        else:
            try: raw = bytes.fromhex(str(value).strip())
            except ValueError: raw = str(value).encode("utf-8")
        return ["BYTES", raw.hex()]
    # STRING and other textual types must remain text. Do not convert numeric-looking
    # strings to numbers: a ZIP code or identifier may intentionally be text.
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (dt.datetime, dt.date)):
        value = value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    return ["STRING", str(value).rstrip()]

def canonical_row(values, types):
    normalized = [normalize(v, t) for v, t in zip(values, types)]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), payload

def main():
    print(f"BigQuery source: {BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}")
    print(f"Oracle target:   {ORACLE_USER.upper()}.{ORACLE_TABLE.upper()}")
    print("Read-only comparison; no data will be changed.")
    bq = bigquery.Client(project=BQ_PROJECT)
    conn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, host=ORACLE_HOST, port=ORACLE_PORT, service_name=ORACLE_SERVICE)
    cur = conn.cursor(); cur.arraysize = BATCH_SIZE
    try:
        bq_schema = bq.get_table(f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}").schema
        bq_columns = [f.name for f in bq_schema]
        bq_types = [f.field_type for f in bq_schema]
        cur.execute("SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS WHERE OWNER=:owner AND TABLE_NAME=:table_name ORDER BY COLUMN_ID", owner=ORACLE_USER.upper(), table_name=ORACLE_TABLE.upper())
        oracle_columns = [r[0] for r in cur.fetchall()]
        oracle_by_upper = {c.upper(): c for c in oracle_columns}
        missing = [c for c in bq_columns if c.upper() not in oracle_by_upper]
        extra = [c for c in oracle_columns if c.upper() not in {x.upper() for x in bq_columns}]
        if missing or extra:
            print("ERROR: schema columns differ.")
            if missing: print("Oracle missing:", ", ".join(missing))
            if extra: print("Oracle extra:", ", ".join(extra))
            return 2
        oracle_cols = [oracle_by_upper[c.upper()] for c in bq_columns]
        table_q = f"{safe_ident(ORACLE_USER.upper())}.{safe_ident(ORACLE_TABLE.upper())}"
        bq_table_q = f"`{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"
        bq_count = next(iter(bq.query(f"SELECT COUNT(*) AS n FROM {bq_table_q}").result()))["n"]
        cur.execute(f"SELECT COUNT(*) FROM {table_q}"); oracle_count = cur.fetchone()[0]
        print(f"Rows in BigQuery: {bq_count:,}\nRows in Oracle:   {oracle_count:,}\nColumns compared: {len(bq_columns)}")
        print("Fingerprinting BigQuery rows...")
        select_bq = ", ".join(f"`{c}`" for c in bq_columns)
        bq_hashes, bq_samples = Counter(), {}
        for row in bq.query(f"SELECT {select_bq} FROM {bq_table_q}").result(page_size=BATCH_SIZE):
            fp, payload = canonical_row([row[c] for c in bq_columns], bq_types)
            bq_hashes[fp] += 1; bq_samples.setdefault(fp, payload)
        print(f"  Processed {sum(bq_hashes.values()):,} rows.")
        print("Fingerprinting Oracle rows using BigQuery column types...")
        cur.execute(f"SELECT {', '.join(safe_ident(c) for c in oracle_cols)} FROM {table_q}")
        oracle_hashes, oracle_samples = Counter(), {}; processed = 0
        while True:
            batch = cur.fetchmany(BATCH_SIZE)
            if not batch: break
            for row in batch:
                fp, payload = canonical_row(row, bq_types)
                oracle_hashes[fp] += 1; oracle_samples.setdefault(fp, payload)
            processed += len(batch)
            if processed % (BATCH_SIZE * 20) == 0: print(f"  Processed {processed:,} rows...")
        print(f"  Processed {processed:,} rows.")
        bq_only, oracle_only = bq_hashes - oracle_hashes, oracle_hashes - bq_hashes
        bq_only_n, oracle_only_n = sum(bq_only.values()), sum(oracle_only.values())
        exact = sum((bq_hashes & oracle_hashes).values())
        result = "PASS" if bq_count == oracle_count and not bq_only_n and not oracle_only_n else "MISMATCHES_FOUND"
        report_path = REPORT_DIR / "unmatched_full_rows.csv"
        with report_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["STATUS", "FINGERPRINT_SHA256", "EXTRA_OCCURRENCES", "NORMALIZED_ROW_JSON"])
            for fp, n in bq_only.most_common(): w.writerow(["BIGQUERY_ONLY", fp, n, bq_samples.get(fp, "")])
            for fp, n in oracle_only.most_common(): w.writerow(["ORACLE_ONLY", fp, n, oracle_samples.get(fp, "")])
        summary = {"bigquery_table": f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}", "oracle_table": f"{ORACLE_USER.upper()}.{ORACLE_TABLE.upper()}", "bigquery_rows": bq_count, "oracle_rows": oracle_count, "columns_compared": len(bq_columns), "comparison_method": "SHA-256 of all columns normalized according to BigQuery schema; multiset duplicate counts preserved", "exact_full_row_matches_including_repeats": exact, "bigquery_only_row_occurrences": bq_only_n, "oracle_only_row_occurrences": oracle_only_n, "distinct_bigquery_only_row_fingerprints": len(bq_only), "distinct_oracle_only_row_fingerprints": len(oracle_only), "result": result, "notes": ["Read-only comparison.", "Duplicate business/month keys are supported.", "Normalization follows BigQuery column types to align driver representations."]}
        (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("\n=== SCHEMA-AWARE FULL-ROW VALIDATION ===")
        print("Result:", result); print(f"Exact full-row matches (including repeats): {exact:,}"); print(f"BigQuery-only row occurrences: {bq_only_n:,}"); print(f"Oracle-only row occurrences: {oracle_only_n:,}")
        print("Reports saved in:", REPORT_DIR.resolve()); print("  summary.json\n  unmatched_full_rows.csv")
        return 0 if result == "PASS" else 1
    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
