"""
Load selected BigQuery tables into their corresponding Oracle destinations.

Loads ONLY:
  BigQuery hab_combined      -> Oracle BQ_HAB_COMBINED
  BigQuery mig_pipeline_data -> Oracle BQ_MIG_PIPELINE_DATA

Missing Oracle destination tables are created from the BigQuery schema. By
default, non-empty destinations are skipped. Pass --replace to transactionally
replace their rows; a failed load rolls back and preserves the previous rows.
"""
import argparse
import csv
import json
import os
from decimal import Decimal
from pathlib import Path

from google.cloud import bigquery
import oracledb

PROJECT_ID = os.getenv("BQ_PROJECT", "datatoolunstructured")
DATASET_ID = os.getenv("BQ_DATASET", "deltamax_migration")
ORACLE_USER = os.getenv("ORACLE_USER", "DELTAMAX_V5")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
ORACLE_DSN = os.getenv("ORACLE_DSN", "localhost:1521/FREEPDB1")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
REPORT_PATH = "bigquery_to_oracle_report.csv"


TABLES = [
    # DeltaMax V5 (10)
    ("dm_v5_anomaly_results", "BQ_DM_V5_ANOMALY_RESULTS"),
    ("dm_v5_arima_alerts", "BQ_DM_V5_ARIMA_ALERTS"),
    ("dm_v5_arima_forecasts", "BQ_DM_V5_ARIMA_FORECASTS"),
    ("dm_v5_churn_feature_importance", "BQ_DM_V5_CHURN_FEATURE_IMPORTANCE"),
    ("dm_v5_churn_model_metrics", "BQ_DM_V5_CHURN_MODEL_METRICS"),
    ("dm_v5_churn_risk_results", "BQ_DM_V5_CHURN_RISK_RESULTS"),
    ("dm_v5_error_log", "BQ_DM_V5_ERROR_LOG"),
    ("dm_v5_quality_results", "BQ_DM_V5_QUALITY_RESULTS"),
    ("dm_v5_stg_credit_bureau", "BQ_DM_V5_STG_CREDIT_BUREAU"),
    ("dm_v5_trust_results", "BQ_DM_V5_TRUST_RESULTS"),

    # MDM (4)
    ("mdm_customer_golden", "BQ_MDM_CUSTOMER_GOLDEN"),
    ("mdm_customer_scores", "BQ_MDM_CUSTOMER_SCORES"),
    ("mdm_customer_stg", "BQ_MDM_CUSTOMER_STG"),
    ("mdm_run_log", "BQ_MDM_RUN_LOG"),

    # Migration (10)
    ("migr_control", "BQ_MIGR_CONTROL"),
    ("migr_files", "BQ_MIGR_FILES"),
    ("migr_json_logs", "BQ_MIGR_JSON_LOGS"),
    ("migr_log", "BQ_MIGR_LOG"),
    ("migr_rows", "BQ_MIGR_ROWS"),
    ("migr_runs", "BQ_MIGR_RUNS"),
    ("mig_pipeline_data", "BQ_MIG_PIPELINE_DATA"),
    ("mig_pipeline_log", "BQ_MIG_PIPELINE_LOG"),
    ("mig_pipeline_metrics", "BQ_MIG_PIPELINE_METRICS"),
    ("mig_pipeline_runs", "BQ_MIG_PIPELINE_RUNS"),

    # Security (5)
    ("sec_datasets", "BQ_SEC_DATASETS"),
    ("sec_log", "BQ_SEC_LOG"),
    ("sec_rows", "BQ_SEC_ROWS"),
    ("sec_runs", "BQ_SEC_RUNS"),
    ("sec_summary", "BQ_SEC_SUMMARY"),
]



def quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def oracle_count(cursor, table_name):
    cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table_name)}")
    return int(cursor.fetchone()[0])


def oracle_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT column_name, data_type, char_length, data_precision, data_scale
        FROM user_tab_columns
        WHERE table_name = :table_name
        ORDER BY column_id
        """,
        table_name=table_name,
    )
    return cursor.fetchall()


def oracle_type(field):
    field_type = field.field_type.upper()
    if field.mode == "REPEATED" or field_type in ("RECORD", "STRUCT", "JSON", "STRING", "GEOGRAPHY"):
        return "CLOB"
    if field_type in ("BIGNUMERIC", "BIGDECIMAL"):
        # Oracle NUMBER is limited to 38 digits. Keep BigQuery's wider exact
        # decimal values as text so the migration never rounds or truncates.
        return "VARCHAR2(128 CHAR)"
    if field_type == "BYTES":
        return "BLOB"
    if field_type in ("BOOL", "BOOLEAN"):
        return "NUMBER(1)"
    if field_type in ("INTEGER", "INT64"):
        return "NUMBER(19)"
    if field_type in ("FLOAT", "FLOAT64"):
        return "BINARY_DOUBLE"
    if field_type in ("NUMERIC", "DECIMAL", "BIGNUMERIC", "BIGDECIMAL"):
        precision_value = getattr(field, "precision", None)
        scale_value = getattr(field, "scale", None)
        precision = int(precision_value if precision_value is not None else (76 if "BIG" in field_type else 38))
        scale = int(scale_value if scale_value is not None else (38 if "BIG" in field_type else 9))
        if precision > 38:
            raise ValueError(
                f"BigQuery column {field.name} has precision {precision}; "
                "Oracle NUMBER supports at most 38 digits."
            )
        if scale > precision:
            raise ValueError(f"BigQuery column {field.name} has scale greater than precision.")
        return f"NUMBER({precision},{scale})"
    if field_type == "TIMESTAMP":
        return "TIMESTAMP(9) WITH TIME ZONE"
    if field_type == "DATETIME":
        return "TIMESTAMP(9)"
    if field_type == "DATE":
        return "DATE"
    if field_type == "TIME":
        return "VARCHAR2(30 CHAR)"
    raise ValueError(f"Unsupported BigQuery type {field_type} for column {field.name}.")


def oracle_type_matches(field, destination_column):
    field_type = field.field_type.upper()
    destination_type = destination_column[1].upper()
    if field.mode == "REPEATED" or field_type in (
        "RECORD", "STRUCT", "JSON", "STRING", "GEOGRAPHY", "BIGNUMERIC", "BIGDECIMAL"
    ):
        return destination_type in ("CLOB", "NCLOB", "VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR")
    if field_type == "BYTES":
        return destination_type == "BLOB"
    if field_type in ("BOOL", "BOOLEAN", "INTEGER", "INT64", "NUMERIC", "DECIMAL", "BIGNUMERIC", "BIGDECIMAL"):
        if destination_type != "NUMBER":
            return False
        if field_type in ("INTEGER", "INT64"):
            target_precision, target_scale = destination_column[3], destination_column[4]
            integer_capacity = (
                38 if target_precision is None
                else int(target_precision) - int(target_scale or 0)
            )
            return integer_capacity >= 19
        if field_type in ("BOOL", "BOOLEAN"):
            target_precision = destination_column[3]
            return target_precision is None or int(target_precision) >= 1
        if field_type in ("NUMERIC", "DECIMAL", "BIGNUMERIC", "BIGDECIMAL"):
            source_precision = getattr(field, "precision", None)
            source_scale = getattr(field, "scale", None)
            source_precision = int(
                source_precision if source_precision is not None
                else (76 if "BIG" in field_type else 38)
            )
            source_scale = int(
                source_scale if source_scale is not None
                else (38 if "BIG" in field_type else 9)
            )
            target_precision, target_scale = destination_column[3], destination_column[4]
            if source_precision > 38:
                return False
            if target_precision is not None:
                target_scale = int(target_scale or 0)
                if int(target_precision) - target_scale < source_precision - source_scale:
                    return False
                if target_scale < source_scale:
                    return False
        return True
    if field_type in ("FLOAT", "FLOAT64"):
        return destination_type in ("BINARY_DOUBLE", "BINARY_FLOAT", "FLOAT", "NUMBER")
    if field_type == "TIMESTAMP":
        return destination_type.startswith("TIMESTAMP")
    if field_type == "DATETIME":
        return destination_type.startswith("TIMESTAMP")
    if field_type == "DATE":
        return destination_type == "DATE"
    if field_type == "TIME":
        return destination_type in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR")
    return False


def create_oracle_table(cursor, table_name, schema):
    definitions = [
        f"{quote_identifier(field.name.upper())} {oracle_type(field)}"
        for field in schema
    ]
    cursor.execute(
        f"CREATE TABLE {quote_identifier(table_name)} ({', '.join(definitions)})"
    )
    print(f"[SCHEMA] Created Oracle table {table_name} from BigQuery schema.")





def convert_value(value, field, destination_type=None):
    if value is None:
        return None

    field_type = field.field_type.upper()

    # Preserve BigQuery timestamps as UTC-aware datetimes.
    if field_type == "TIMESTAMP":
        from datetime import timezone

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        if destination_type and "TIME ZONE" not in destination_type.upper():
            return value.replace(tzinfo=None)
        return value

    # Oracle NUMBER(1) is used for BigQuery BOOL in this existing schema.
    if field_type in ("BOOL", "BOOLEAN"):
        return 1 if value else 0

    if field_type in ("NUMERIC", "BIGNUMERIC", "BIGDECIMAL") and destination_type and destination_type.upper() in (
        "VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "CLOB", "NCLOB"
    ):
        return str(value)

    if field_type in ("NUMERIC", "BIGNUMERIC", "BIGDECIMAL") and not isinstance(value, Decimal):
        return Decimal(str(value))

    if field_type in ("RECORD", "STRUCT", "JSON") or field.mode == "REPEATED":
        if hasattr(value, "items"):
            value = dict(value.items())
        return json.dumps(value, default=str, ensure_ascii=False)

    if field_type in ("GEOGRAPHY", "TIME"):
        return str(value)

    if field_type == "BYTES":
        return bytes(value)

    return value


def load_one(bq_client, connection, source_name, destination_name, replace_existing=False):
    report = {
        "source_table": source_name,
        "oracle_table": destination_name,
        "destination_created": False,
        "run_id": os.getenv("MIGRATION_RUN_ID", ""),
        "source_rows_expected": "",
        "oracle_rows_before": "",
        "oracle_rows_after": "",
        "status": "FAILED",
        "details": "",
    }

    with connection.cursor() as cursor:
        source_id = f"{PROJECT_ID}.{DATASET_ID}.{source_name}"
        source_table = bq_client.get_table(source_id)
        schema = source_table.schema
        report["source_rows_expected"] = int(source_table.num_rows)

        destination_columns = oracle_columns(cursor, destination_name)
        if not destination_columns:
            create_oracle_table(cursor, destination_name, schema)
            destination_columns = oracle_columns(cursor, destination_name)
            report["destination_created"] = True

        before = oracle_count(cursor, destination_name)
        report["oracle_rows_before"] = before
        if before != 0 and not replace_existing:
            report["status"] = "SKIPPED_NONEMPTY"
            report["details"] = (
                f"Destination contains {before:,} rows. No data was inserted. "
                "Use --replace to replace destination rows transactionally."
            )
            print(f"[SKIP] {destination_name} contains {before:,} rows; refusing to append.")
            return report

        source_columns = [f.name.upper() for f in schema]
        destination_names = [column[0].upper() for column in destination_columns]

        if source_columns != destination_names:
            report["details"] = (
                "Column mismatch. Source columns and Oracle columns must match "
                "by name and order. No rows were inserted. "
                f"Source={source_columns}; Oracle={destination_names}"
            )
            print(f"[ERROR] {source_name}: source and Oracle column lists differ.")
            return report

        incompatible = [
            f"{field.name} ({field.field_type} -> {column[1]})"
            for field, column in zip(schema, destination_columns)
            if not oracle_type_matches(field, column)
        ]
        if incompatible:
            report["details"] = (
                "Oracle destination column types are incompatible with BigQuery: "
                + ", ".join(incompatible)
            )
            print(f"[ERROR] {source_name}: incompatible source/destination column types.")
            return report

        query = f"SELECT * FROM `{source_id}`"
        rows = bq_client.query(query).result(page_size=BATCH_SIZE)
        quoted_cols = ", ".join(quote_identifier(c) for c in destination_names)
        binds = ", ".join(f":{i}" for i in range(1, len(schema) + 1))
        insert_sql = (
            f'INSERT INTO "{destination_name}" ({quoted_cols}) '
            f"VALUES ({binds})"
        )

        loaded = 0
        batch = []
        try:
            input_types = {
                "CLOB": oracledb.DB_TYPE_CLOB,
                "NCLOB": oracledb.DB_TYPE_NCLOB,
                "BLOB": oracledb.DB_TYPE_BLOB,
            }
            bind_types = [
                input_types.get(column[1].upper())
                for column in destination_columns
            ]
            if any(bind_types):
                cursor.setinputsizes(*bind_types)

            if replace_existing and before:
                cursor.execute(f"DELETE FROM {quote_identifier(destination_name)}")
                print(f"[REPLACE] Removed {before:,} existing rows from {destination_name} (pending commit)")

            for row in rows:
                converted = []
                for i, field in enumerate(schema):
                    destination_type = destination_columns[i][1].upper()
                    value = convert_value(row[i], field, destination_type)
                    max_length = destination_columns[i][2]
                    if (
                        value is not None
                        and isinstance(value, str)
                        and destination_type in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR")
                        and max_length
                        and len(value) > max_length
                    ):
                        raise ValueError(
                            f"Value for column {field.name} is {len(value)} characters, "
                            f"but Oracle {destination_type} supports {max_length}. "
                            "Use a CLOB destination column to preserve longer strings."
                        )
                    converted.append(value)
                batch.append(tuple(converted))
                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(insert_sql, batch)
                    loaded += len(batch)
                    print(f"[LOAD] {destination_name}: {loaded:,} rows loaded so far")
                    batch.clear()

            if batch:
                cursor.executemany(insert_sql, batch)
                loaded += len(batch)

            after = oracle_count(cursor, destination_name)
            report["oracle_rows_after"] = after
            if loaded == int(source_table.num_rows) and after == int(source_table.num_rows):
                connection.commit()
                report["status"] = "SUCCESS"
                report["details"] = (
                    "Destination table created; source and Oracle row counts match."
                    if report["destination_created"]
                    else "Source and Oracle row counts match; destination rows replaced."
                    if replace_existing and before
                    else "Source and Oracle row counts match."
                )
                print(f"[OK] {source_name} -> {destination_name}: {after:,} rows")
            else:
                connection.rollback()
                report["status"] = "COUNT_MISMATCH"
                report["details"] = (
                    f"Loaded={loaded}; source_expected={source_table.num_rows}; "
                    f"Oracle_before={before}; Oracle_observed={after}. "
                    "The transaction was rolled back; original destination rows were preserved."
                )
                report["oracle_rows_after"] = before
                print(f"[WARN] {destination_name}: source and destination counts differ")

        except Exception:
            connection.rollback()
            raise

    return report


def main():
    parser = argparse.ArgumentParser(description="Load selected BigQuery tables into Oracle.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing destination rows; failed table loads are rolled back.",
    )
    parser.add_argument(
        "--tables",
        default=",".join(source for source, _ in TABLES),
        help="Comma-separated BigQuery source table names to migrate.",
    )
    args = parser.parse_args()
    table_map = dict(TABLES)
    selected_tables = [name.strip() for name in args.tables.split(",") if name.strip()]
    if not selected_tables or len(set(selected_tables)) != len(selected_tables):
        parser.error("Select one or more distinct source tables.")
    unknown_tables = set(selected_tables) - table_map.keys()
    if unknown_tables:
        parser.error(f"Unsupported BigQuery source table(s): {', '.join(sorted(unknown_tables))}")

    if not ORACLE_PASSWORD:
        raise ValueError(
            "ORACLE_PASSWORD is not set. Set it in your terminal before running."
        )

    bq_client = bigquery.Client(project=PROJECT_ID)
    connection = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN,
    )

    reports = []
    try:
        for source_name in selected_tables:
            destination_name = table_map[source_name]
            print(f"\n=== {source_name} -> {destination_name} ===")
            try:
                report = load_one(
                    bq_client,
                    connection,
                    source_name,
                    destination_name,
                    replace_existing=args.replace,
                )
            except Exception as exc:
                connection.rollback()
                report = {
                    "run_id": os.getenv("MIGRATION_RUN_ID", ""),
                    "source_table": source_name,
                    "oracle_table": destination_name,
                    "destination_created": False,
                    "source_rows_expected": "",
                    "oracle_rows_before": "",
                    "oracle_rows_after": "",
                    "status": "FAILED",
                    "details": str(exc),
                }
                print(f"[ERROR] {source_name}: {exc}")
            reports.append(report)

        with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "run_id",
                    "source_table",
                    "oracle_table",
                    "destination_created",
                    "source_rows_expected",
                    "oracle_rows_before",
                    "oracle_rows_after",
                    "status",
                    "details",
                ],
            )
            writer.writeheader()
            writer.writerows(reports)

        print(f"\nRecovery report written to: {Path(REPORT_PATH).resolve()}")
        print("Finished. Review the status for each table above.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
