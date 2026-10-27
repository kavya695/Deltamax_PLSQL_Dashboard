"""
Read-only audit of BigQuery -> Oracle table migration.
No inserts, updates, deletes, truncates, or table recreation are performed.

Requirements:
  pip install google-cloud-bigquery oracledb
  BigQuery Application Default Credentials configured
  ORACLE_PASSWORD environment variable set
"""

import csv
import os
from pathlib import Path

from google.cloud import bigquery
import oracledb

PROJECT_ID = "datatoolunstructured"
DATASET_ID = "deltamax_migration"
ORACLE_USER = os.getenv("ORACLE_USER", "DELTAMAX_V5")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
ORACLE_DSN = os.getenv("ORACLE_DSN", "localhost:1521/FREEPDB1")
REPORT_PATH = "bigquery_oracle_migration_audit.csv"


def oracle_table_name(source_name):
    # Examples: hab_combined -> BQ_HAB_COMBINED
    #           _stage_x -> BQ_T__STAGE_X
    name = source_name.upper()
    return "BQ_T_" + name if name.startswith("_STAGE_") else "BQ_" + name


def get_oracle_tables(cursor):
    cursor.execute("""
        SELECT table_name
        FROM user_tables
        WHERE table_name LIKE 'BQ\\_%' ESCAPE '\\'
    """)
    return {row[0] for row in cursor.fetchall()}


def oracle_count(cursor, table_name):
    # table_name comes from Oracle USER_TABLES, not user input.
    cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    return int(cursor.fetchone()[0])


def main():
    if not ORACLE_PASSWORD:
        raise ValueError(
            "ORACLE_PASSWORD is not set. Set it in your terminal before running."
        )

    print("Connecting to BigQuery...")
    bq_client = bigquery.Client(project=PROJECT_ID)
    print("Connecting to Oracle...")
    connection = oracledb.connect(
        user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN
    )

    report_rows = []
    try:
        with connection.cursor() as cursor:
            oracle_tables = get_oracle_tables(cursor)
            source_tables = sorted(
                bq_client.list_tables(f"{PROJECT_ID}.{DATASET_ID}"),
                key=lambda t: t.table_id.lower(),
            )
            matched_oracle_tables = set()

            for item in source_tables:
                source_name = item.table_id
                destination_name = oracle_table_name(source_name)
                row = {
                    "bigquery_table": source_name,
                    "oracle_table": destination_name,
                    "bigquery_rows": "",
                    "oracle_rows": "",
                    "status": "",
                    "details": "",
                }

                try:
                    source = bq_client.get_table(
                        f"{PROJECT_ID}.{DATASET_ID}.{source_name}"
                    )
                    source_rows = int(source.num_rows or 0)
                    row["bigquery_rows"] = source_rows

                    if destination_name not in oracle_tables:
                        row["status"] = "MISSING_IN_ORACLE"
                        row["details"] = "Corresponding Oracle table does not exist."
                    else:
                        matched_oracle_tables.add(destination_name)
                        destination_rows = oracle_count(cursor, destination_name)
                        row["oracle_rows"] = destination_rows
                        if source_rows == destination_rows:
                            row["status"] = "MATCH"
                            row["details"] = "Source and destination row counts match."
                        else:
                            row["status"] = "COUNT_MISMATCH"
                            row["details"] = (
                                f"BigQuery has {source_rows:,} rows; "
                                f"Oracle has {destination_rows:,} rows."
                            )
                except Exception as exc:
                    row["status"] = "ERROR"
                    row["details"] = str(exc)

                report_rows.append(row)
                print(
                    f"[{row['status']}] {source_name} -> {destination_name} | "
                    f"BigQuery={row['bigquery_rows']} | Oracle={row['oracle_rows']}"
                )

            for extra in sorted(oracle_tables - matched_oracle_tables):
                report_rows.append({
                    "bigquery_table": "",
                    "oracle_table": extra,
                    "bigquery_rows": "",
                    "oracle_rows": oracle_count(cursor, extra),
                    "status": "NO_SOURCE_MATCH",
                    "details": "No source table mapped using the migration naming convention.",
                })
                print(f"[NO_SOURCE_MATCH] Oracle table {extra}")

        with open(REPORT_PATH, "w", newline="", encoding="utf-8-sig") as f:
            fields = [
                "bigquery_table", "oracle_table", "bigquery_rows",
                "oracle_rows", "status", "details",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report_rows)

        summary = {}
        for row in report_rows:
            summary[row["status"]] = summary.get(row["status"], 0) + 1

        print("\n=== AUDIT SUMMARY ===")
        for status, count in sorted(summary.items()):
            print(f"{status}: {count}")
        print(f"\nReport saved to: {Path(REPORT_PATH).resolve()}")
        print("Read-only audit completed; no data was changed.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
