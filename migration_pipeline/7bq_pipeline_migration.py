
from google.cloud import bigquery
import google.auth

# DeltaMax V5 - BigQuery pipeline migration
PROJECT_ID = "datatoolunstructured"
DATASET_ID = "deltamax_migration"
LOCATION = "asia-south1"

client = bigquery.Client(project=PROJECT_ID)

# Source table, destination table, expected row count

# Source table, destination table, expected row count
TABLES = [
    (
        "migration_hab_clean_v2",
        "migration_hab_post_migration_input_v2",
        39161,
    ),
    (
        "migration_hab_with_anomalies_v2",
        "migration_hab_post_migration_with_anomalies_input_v2",
        40923,
    ),
]



def get_row_count(table_name):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    query = f"SELECT COUNT(*) AS total FROM `{table_id}`"
    result = list(client.query(query, location=LOCATION).result())
    return result[0]["total"]


def copy_table(source_name, destination_name, expected_rows):
    source_id = f"{PROJECT_ID}.{DATASET_ID}.{source_name}"
    destination_id = f"{PROJECT_ID}.{DATASET_ID}.{destination_name}"

    print(f"\nChecking source table: {source_name}")

    source_count = get_row_count(source_name)
    print(f"Source rows: {source_count:,}")

    if source_count != expected_rows:
        raise RuntimeError(
            f"Expected {expected_rows:,} rows in {source_name}, "
            f"but found {source_count:,}. Copy cancelled."
        )

    print(f"Copying to: {destination_name}")

    sql = f"""
        CREATE OR REPLACE TABLE `{destination_id}` AS
        SELECT *
        FROM `{source_id}`
    """

    client.query(sql, location=LOCATION).result()

    destination_count = get_row_count(destination_name)
    print(f"Destination rows: {destination_count:,}")

    if destination_count != source_count:
        raise RuntimeError(
            f"Row-count mismatch for {destination_name}: "
            f"source={source_count:,}, destination={destination_count:,}"
        )

    print(f"SUCCESS: {destination_name}")


def main():
    print("=" * 60)
    print("DELTAMAX V5 - BIGQUERY PIPELINE MIGRATION")
    print("=" * 60)
    print(f"Project:  {PROJECT_ID}")
    print(f"Dataset:  {DATASET_ID}")
    print(f"Location: {LOCATION}")

    # Verify the dataset exists and is in the expected location.
    dataset = client.get_dataset(f"{PROJECT_ID}.{DATASET_ID}")

    if dataset.location.lower() != LOCATION.lower():
        raise RuntimeError(
            f"Dataset location is {dataset.location}, "
            f"not {LOCATION}. Stopping."
        )

    for source, destination, expected in TABLES:
        copy_table(source, destination, expected)

    print("\n" + "=" * 60)
    print("STEP 7 COMPLETE")
    print("Both input tables were copied and row counts verified.")
    print("=" * 60)


if __name__ == "__main__":
    main()
