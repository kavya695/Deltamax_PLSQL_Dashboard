"""DeltaMax Oracle -> BigQuery migration for all 29 known tables.

Safe behavior:
- Loads into temporary staging tables first.
- Checks Oracle and BigQuery row counts for every table.
- Does NOT replace destination tables unless --publish is supplied.
- With --publish, publishes only after every staging table passes row-count validation.

Run from Windows PowerShell after installing oracledb and google-cloud-bigquery.
"""
import argparse
import getpass
import json
import os
import sys
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import oracledb
from google.cloud import bigquery

PROJECT_ID = os.getenv("BQ_PROJECT", "datatoolunstructured")
DATASET_ID = os.getenv("BQ_DATASET", "deltamax_migration")
LOCATION = os.getenv("BQ_LOCATION", "asia-south1")
ORACLE_USER_DEFAULT = os.getenv("MIG_DB_USER", "DELTAMAX_V5")
ORACLE_HOST_DEFAULT = os.getenv("MIG_DB_HOST", "localhost")
ORACLE_PORT_DEFAULT = int(os.getenv("MIG_DB_PORT", "1521"))
ORACLE_SERVICE_DEFAULT = os.getenv("MIG_DB_SERVICE", "FREEPDB1")

TABLES = [
    # DeltaMax V5 (10)
    "DM_V5_ANOMALY_RESULTS", "DM_V5_ARIMA_ALERTS", "DM_V5_ARIMA_FORECASTS",
    "DM_V5_CHURN_FEATURE_IMPORTANCE", "DM_V5_CHURN_MODEL_METRICS",
    "DM_V5_CHURN_RISK_RESULTS", "DM_V5_ERROR_LOG", "DM_V5_QUALITY_RESULTS",
    "DM_V5_STG_CREDIT_BUREAU", "DM_V5_TRUST_RESULTS",
    # MDM (4)
    "MDM_CUSTOMER_GOLDEN", "MDM_CUSTOMER_SCORES", "MDM_CUSTOMER_STG", "MDM_RUN_LOG",
    # Migration (10)
    "MIGR_CONTROL", "MIGR_FILES", "MIGR_JSON_LOGS", "MIGR_LOG", "MIGR_ROWS",
    "MIGR_RUNS", "MIG_PIPELINE_DATA", "MIG_PIPELINE_LOG", "MIG_PIPELINE_METRICS",
    "MIG_PIPELINE_RUNS",
    # Security (5)
    "SEC_DATASETS", "SEC_LOG", "SEC_ROWS", "SEC_RUNS", "SEC_SUMMARY",
]


def bq_type(oracle_type, precision, scale):
    t = (oracle_type or "").upper()
    if t in {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "CLOB", "NCLOB", "LONG", "RAW", "LONG RAW"}:
        return "STRING"
    if t == "DATE":
        return "DATETIME"  # Oracle DATE includes a time component.
    if t.startswith("TIMESTAMP"):
        return "TIMESTAMP" if ("TIME ZONE" in t or "LOCAL TIME ZONE" in t) else "DATETIME"
    if t in {"BINARY_FLOAT", "BINARY_DOUBLE", "FLOAT"}:
        return "FLOAT64"
    if t == "NUMBER" or t.startswith("NUMBER") or t == "DECIMAL" or t == "INTEGER":
        if precision is not None and scale is not None and scale == 0 and precision <= 18:
            return "INT64"
        # Oracle NUMBER without precision/scale can exceed NUMERIC's 9-digit
        # fractional scale. BIGNUMERIC also covers the wider integer range.
        if precision is None or scale is None:
            return "BIGNUMERIC"
        integer_digits = max(0, precision - scale)
        fractional_digits = max(0, scale)
        if integer_digits <= 29 and fractional_digits <= 9:
            return "NUMERIC"
        if integer_digits <= 38 and fractional_digits <= 38:
            return "BIGNUMERIC"
        return "FLOAT64"
    # Safer fallback: preserve unknown Oracle types as text instead of silently losing data.
    return "STRING"


def normalize_value(value, target_type):
    if value is None:
        return None
    if hasattr(value, "read") and callable(value.read):  # Oracle LOB
        value = value.read()
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = value.hex().upper()
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if target_type == "INT64":
            return int(value)
        if target_type in {"NUMERIC", "BIGNUMERIC"}:
            return str(value)
        return float(value)
    if target_type == "STRING":
        return str(value)
    if target_type == "INT64":
        return int(value)
    if target_type == "FLOAT64":
        return float(value)
    if target_type in {"NUMERIC", "BIGNUMERIC"}:
        return str(value)
    return value


def write_report(path, run_tag, project_id, dataset_id, location, report,
                 status, published=False, error=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_tag,
        "source_cloud": "Oracle",
        "target_cloud": "BigQuery",
        "project": project_id,
        "dataset": dataset_id,
        "location": location,
        "status": status,
        "published": bool(published and status == "SUCCESS"),
        "publish_requested": published,
        "error": error,
        "tables": report,
        "metrics": {
            "table_count": len(report),
            "tables_passed": sum(bool(row.get("passed")) for row in report),
            "total_oracle_rows": sum(int(row.get("oracle_rows") or 0) for row in report),
            "total_bigquery_rows": sum(int(row.get("bigquery_rows") or 0) for row in report),
            "count_mismatches": sum(
                row.get("oracle_rows") is not None
                and row.get("bigquery_rows") is not None
                and row.get("oracle_rows") != row.get("bigquery_rows")
                for row in report
            ),
        },
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Migrate all 29 DeltaMax Oracle tables to BigQuery staging tables.")
    parser.add_argument("--publish", action="store_true", help="Replace destination tables after all staging row counts pass. Use only after reviewing the report.")
    parser.add_argument("--batch-size", type=int, default=5000, help="Oracle rows fetched per batch while preparing a single BigQuery load (default: 5000).")
    parser.add_argument("--oracle-user", default=ORACLE_USER_DEFAULT)
    parser.add_argument("--oracle-host", default=ORACLE_HOST_DEFAULT)
    parser.add_argument("--oracle-port", type=int, default=ORACLE_PORT_DEFAULT)
    parser.add_argument("--oracle-service", default=ORACLE_SERVICE_DEFAULT)
    parser.add_argument("--report-path", default=str(Path(__file__).with_name("oracle_to_bigquery_latest.json")))
    args = parser.parse_args()

    password = os.getenv("MIG_DB_PASSWORD") or os.getenv("ORACLE_PASSWORD")
    if not password:
        if not sys.stdin.isatty():
            raise RuntimeError("Set MIG_DB_PASSWORD or ORACLE_PASSWORD before running from the UI.")
        password = getpass.getpass(f"Oracle password for {args.oracle_user}: ")
    project_id = os.getenv("BQ_PROJECT", PROJECT_ID)
    dataset_id = os.getenv("BQ_DATASET", DATASET_ID)
    location = os.getenv("BQ_LOCATION", LOCATION)
    dsn = oracledb.makedsn(args.oracle_host, args.oracle_port, service_name=args.oracle_service)
    print(f"Connecting to Oracle {args.oracle_host}:{args.oracle_port}/{args.oracle_service} ...")
    oracle = oracledb.connect(user=args.oracle_user, password=password, dsn=dsn)
    bq = bigquery.Client(project=project_id)
    dataset_ref = f"{project_id}.{dataset_id}"
    dataset = bq.get_dataset(dataset_ref)
    if dataset.location.lower() != location.lower():
        raise RuntimeError(f"Dataset location is {dataset.location}, expected {location}. Check BQ_DATASET/BQ_LOCATION before continuing.")

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = []
    write_report(args.report_path, run_tag, project_id, dataset_id, location,
                 report, "RUNNING")
    try:
        with oracle.cursor() as meta:
            for table in TABLES:
                print(f"\n[{table}] Reading Oracle schema...")
                staging_name = f"_stage_{table.lower()}_{run_tag}"
                staging_id = f"{dataset_ref}.{staging_name}"
                final_id = f"{dataset_ref}.{table.lower()}"
                table_report = {
                    "table": table, "stage": staging_name, "final": final_id,
                    "oracle_rows": None, "bigquery_rows": None,
                    "passed": False, "published": False,
                }
                report.append(table_report)
                write_report(args.report_path, run_tag, project_id, dataset_id,
                             location, report, "RUNNING")
                meta.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, DATA_PRECISION, DATA_SCALE, NULLABLE
                    FROM ALL_TAB_COLUMNS
                    WHERE OWNER = :owner AND TABLE_NAME = :table_name
                    ORDER BY COLUMN_ID
                """, owner=args.oracle_user.upper(), table_name=table)
                columns = meta.fetchall()
                if not columns:
                    raise RuntimeError(f"Table {table} was not found under Oracle schema {args.oracle_user.upper()}.")

                schema = [bigquery.SchemaField(c[0], bq_type(c[1], c[2], c[3]), mode="NULLABLE" if c[4] == "Y" else "REQUIRED") for c in columns]
                stage_table = bigquery.Table(staging_id, schema=schema)
                bq.create_table(stage_table, exists_ok=False)

                # RAW columns are converted to hex strings, preserving their bytes losslessly.
                select_parts = []
                for col_name, data_type, *_ in columns:
                    quoted = '"' + col_name.replace('"', '""') + '"'
                    if data_type.upper() in {"RAW", "LONG RAW"}:
                        select_parts.append(f"RAWTOHEX({quoted}) AS {quoted}")
                    else:
                        select_parts.append(quoted)
                select_sql = f"SELECT {', '.join(select_parts)} FROM \"{args.oracle_user.upper()}\".\"{table}\""
                # Keep memory bounded while making only one BigQuery table write
                # per source table. Repeated WRITE_APPEND jobs can hit BigQuery's
                # per-table update quota even when each batch is small.
                oracle_count = 0
                with tempfile.TemporaryDirectory(prefix="deltamax_bq_load_") as temp_dir:
                    jsonl_path = Path(temp_dir) / f"{table.lower()}.jsonl"
                    with oracle.cursor() as src, jsonl_path.open("w", encoding="utf-8") as payload:
                        src.arraysize = args.batch_size
                        src.execute(select_sql)
                        while True:
                            fetched = src.fetchmany(args.batch_size)
                            if not fetched:
                                break
                            for record in fetched:
                                row = {
                                    col[0]: normalize_value(record[idx], schema[idx].field_type)
                                    for idx, col in enumerate(columns)
                                }
                                payload.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                                payload.write("\n")
                            oracle_count += len(fetched)
                            print(f"  Read {oracle_count:,} rows...", end="\r", flush=True)

                    load_config = bigquery.LoadJobConfig(
                        schema=schema,
                        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                        write_disposition="WRITE_TRUNCATE",
                    )
                    print(f"  Uploading {oracle_count:,} rows to BigQuery in one load job...", flush=True)
                    with jsonl_path.open("rb") as payload:
                        job = bq.load_table_from_file(
                            payload, staging_id, size=jsonl_path.stat().st_size,
                            location=location, job_config=load_config,
                        )
                        job.result()
                print(f"  Uploaded {oracle_count:,} rows in one BigQuery load job.")

                bq_count = bq.get_table(staging_id).num_rows
                passed = oracle_count == bq_count
                print(f"  Oracle rows: {oracle_count:,} | BigQuery staging rows: {bq_count:,} | {'PASS' if passed else 'FAIL'}")
                table_report.update({
                    "oracle_rows": oracle_count, "bigquery_rows": bq_count,
                    "passed": passed,
                })
                write_report(args.report_path, run_tag, project_id, dataset_id,
                             location, report, "RUNNING")
                if not passed:
                    raise RuntimeError(f"Row-count validation failed for {table}; destination tables have not been replaced.")

        print("\nAll 29 staging tables passed row-count validation.")
        if args.publish:
            print("Publishing staged tables to final destination names...")
            # All tables have been staged and validated before any destination is changed.
            for item in report:
                source = bq.get_table(f"{dataset_ref}.{item['stage']}")
                dest_id = item["final"]
                copy_config = bigquery.CopyJobConfig(write_disposition="WRITE_TRUNCATE")
                bq.copy_table(source, dest_id, job_config=copy_config, location=location).result()
                item["published"] = True
                write_report(args.report_path, run_tag, project_id, dataset_id,
                             location, report, "PUBLISHING", published=True)
                print(f"  Published {item['table']} -> {dest_id}")
            print("Publish completed. Staging tables are retained for rollback/review; delete them only after verification.")
        else:
            print("\nSAFE MODE: final tables were not changed.")
            print("Review the counts above. If correct, rerun the same command with --publish to replace final tables.")

        print("\nSUMMARY")
        print("Table count:", len(report))
        print("Oracle total rows:", f"{sum(x['oracle_rows'] for x in report):,}")
        print("BigQuery staging total rows:", f"{sum(x['bigquery_rows'] for x in report):,}")
        print("Report:")
        print(json.dumps(report, indent=2))
        write_report(args.report_path, run_tag, project_id, dataset_id,
                     location, report, "SUCCESS", published=args.publish)
    except Exception as exc:
        write_report(args.report_path, run_tag, project_id, dataset_id, location,
                     report, "FAILED", published=args.publish, error=str(exc))
        raise
    finally:
        oracle.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
