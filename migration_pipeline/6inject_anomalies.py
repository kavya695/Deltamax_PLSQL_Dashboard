"""
DeltaMax Step 6: Inject test anomalies into the Step 5 BigQuery output.

Input:
  datatoolunstructured.deltamax_migration.migration_hab_cleaned_v2

Outputs:
  datatoolunstructured.deltamax_migration.migration_hab_with_anomalies_v2
  datatoolunstructured.deltamax_migration.migration_anomaly_log_v2

Writes to separate output tables and does not modify Step 5 tables.
"""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "datatoolunstructured"
DATASET_ID = "deltamax_migration"
LOCATION = "asia-south1"

INPUT_TABLE = f"{PROJECT_ID}.{DATASET_ID}.migration_hab_clean_v2"
OUTPUT_TABLE = f"{PROJECT_ID}.{DATASET_ID}.migration_hab_with_anomalies_v2"
LOG_TABLE = f"{PROJECT_ID}.{DATASET_ID}.migration_anomaly_log_v2"

ENABLE_ANOMALIES = True
RANDOM_SEED = 42

DROP_RECORDS_PERCENTAGE = 5
DUPLICATE_PERCENTAGE = 10
CORRUPT_VALUES_PERCENTAGE = 20
CORRUPT_COLUMNS = ["creditScore", "annualRevenue", "outstandingDebt"]
OUTLIER_COUNT = 5000
OUTLIERS = [
    {"column": "creditScore", "value": 9999},
    {"column": "annualRevenue", "value": 1e15},
]
BUSINESS_VIOLATION_COUNT = 500
BUSINESS_VIOLATIONS = [
    {"column": "creditScore", "value": -100},
    {"column": "creditScore", "value": 2000},
    {"column": "annualRevenue", "value": -50000},
]


def upload_dataframe(client, df, table_id):
    """Replace the destination table with the supplied DataFrame."""
    config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    job = client.load_table_from_dataframe(
        df, table_id, job_config=config, location=LOCATION
    )
    job.result()
    table = client.get_table(table_id)
    print(f"[BigQuery] Uploaded {table.num_rows:,} rows to {table_id}")


def main():
    client = bigquery.Client(project=PROJECT_ID)
    print(f"\n[BigQuery] Loading Step 5 data from {INPUT_TABLE} ...")
    df = client.query(
        f"SELECT * FROM `{INPUT_TABLE}`", location=LOCATION
    ).to_dataframe()

    if df.empty:
        raise ValueError(f"Input table is empty: {INPUT_TABLE}")

    # Confirm that the full business dataset was loaded.
    required_columns = [
        "businessID",
        "creditScore",
        "annualRevenue",
        "outstandingDebt",
        "totalCreditLimit",
        "availableCredit",
        "data_lineage",
    ]

    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Input table is missing required business columns: {missing_columns}"
        )

    if len(df.columns) < 100:
        raise ValueError(
            f"Expected the full business dataset, but loaded only "
            f"{len(df.columns)} columns from {INPUT_TABLE}"
        )

    original_count = len(df)
    print(f"[OK] Loaded {original_count:,} rows and {len(df.columns)} columns.")

    log = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "enabled": ENABLE_ANOMALIES,
        "input_table": INPUT_TABLE,
        "output_table": OUTPUT_TABLE,
        "original_rows": original_count,
        "events": [],
    }

    if ENABLE_ANOMALIES:
        # 1. Drop 5% of records.
        drop_count = min(int(len(df) * DROP_RECORDS_PERCENTAGE / 100), len(df))
        if drop_count:
            indices = df.sample(n=drop_count, random_state=RANDOM_SEED).index
            df = df.drop(index=indices).reset_index(drop=True)
        log["events"].append({
            "type": "drop_records", "dropped_rows": drop_count,
            "remaining_rows": len(df),
        })
        print(f"[OK] Dropped {drop_count:,} rows; {len(df):,} remain.")

        # 2. Add duplicate records. Duplicate record_id values are intentional.
        duplicate_count = min(
            max(1, int(len(df) * DUPLICATE_PERCENTAGE / 100)), len(df)
        ) if len(df) else 0
        if duplicate_count:
            copies = df.sample(n=duplicate_count, random_state=RANDOM_SEED).copy()
            df = pd.concat([df, copies], ignore_index=True)
        log["events"].append({
            "type": "introduce_duplicates", "duplicates_added": duplicate_count,
            "rows_after": len(df),
        })
        print(f"[OK] Added {duplicate_count:,} duplicate rows; total {len(df):,}.")

        # 3. Introduce missing values.
        corrupt_count = min(int(len(df) * CORRUPT_VALUES_PERCENTAGE / 100), len(df))
        corrupt_events = []
        for column in CORRUPT_COLUMNS:
            if column not in df.columns:
                corrupt_events.append({"column": column, "status": "COLUMN_NOT_FOUND"})
                print(f"[WARNING] Missing column; skipping corruption: {column}")
                continue
            indices = df.sample(n=corrupt_count, random_state=RANDOM_SEED).index if corrupt_count else []
            df.loc[indices, column] = np.nan
            corrupt_events.append({
                "column": column, "missing_values_set": corrupt_count, "status": "OK"
            })
        log["events"].append({
            "type": "corrupt_values",
            "requested_percentage": CORRUPT_VALUES_PERCENTAGE,
            "details": corrupt_events,
        })
        print("[OK] Introduced missing values in configured columns.")

        # 4. Create outliers in up to the first 5,000 rows.
        outlier_count = min(OUTLIER_COUNT, len(df))
        outlier_events = []
        for item in OUTLIERS:
            column = item["column"]
            if column not in df.columns:
                outlier_events.append({"column": column, "status": "COLUMN_NOT_FOUND"})
                print(f"[WARNING] Missing column; skipping outlier: {column}")
                continue
            if outlier_count:
                df.loc[df.index[:outlier_count], column] = item["value"]
            outlier_events.append({
                "column": column, "value": item["value"],
                "rows_modified": outlier_count, "status": "OK",
            })
        log["events"].append({"type": "create_outliers", "details": outlier_events})
        print(f"[OK] Applied configured outliers to up to {outlier_count:,} rows.")

        # 5. Introduce business-rule violations.
        violation_events = []
        for i, item in enumerate(BUSINESS_VIOLATIONS):
            column = item["column"]
            if column not in df.columns:
                violation_events.append({"column": column, "status": "COLUMN_NOT_FOUND"})
                print(f"[WARNING] Missing column; skipping violation: {column}")
                continue
            count = min(BUSINESS_VIOLATION_COUNT, len(df))
            if count:
                indices = df.sample(n=count, random_state=RANDOM_SEED + i + 1).index
                df.loc[indices, column] = item["value"]
            violation_events.append({
                "column": column, "invalid_value": item["value"],
                "rows_modified": count, "status": "OK",
            })
        log["events"].append({
            "type": "business_rule_violations", "details": violation_events
        })
        print("[OK] Applied configured business-rule violations.")

    log["final_rows"] = len(df)
    log["final_columns"] = len(df.columns)

    print(f"\n[BigQuery] Saving anomaly-injected data to {OUTPUT_TABLE} ...")
    upload_dataframe(client, df, OUTPUT_TABLE)

    log_df = pd.DataFrame([{
        "timestamp_utc": log["timestamp_utc"],
        "input_table": INPUT_TABLE,
        "output_table": OUTPUT_TABLE,
        "enabled": ENABLE_ANOMALIES,
        "original_rows": original_count,
        "final_rows": len(df),
        "log_json": json.dumps(log, default=str),
    }])
    print(f"[BigQuery] Saving anomaly log to {LOG_TABLE} ...")
    upload_dataframe(client, log_df, LOG_TABLE)

    print("\n" + "=" * 72)
    print("STEP 6 COMPLETE")
    print(f"Input rows:  {original_count:,}")
    print(f"Output rows: {len(df):,}")
    print(f"Data table:  {OUTPUT_TABLE}")
    print(f"Log table:   {LOG_TABLE}")
    print("=" * 72)


if __name__ == "__main__":
    main()
