from google.cloud import bigquery
import pandas as pd

PROJECT_ID = "datatoolunstructured"
DATASET_ID = "deltamax_migration"
LOCATION = "asia-south1"


client = bigquery.Client(project=PROJECT_ID)

def read_source_table(table_name):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    return client.query(
        f"SELECT * FROM `{table_id}`",
        location=LOCATION
    ).to_dataframe()

def write_output_table(df, table_name):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"

    try:
        client.get_table(table_id)
    except Exception as exc:
        from google.api_core.exceptions import NotFound
        if not isinstance(exc, NotFound):
            raise
    else:
        raise RuntimeError(
            f"Output table already exists: {table_id}. "
            "No data was written."
        )

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_EMPTY
    )

    job = client.load_table_from_dataframe(
        df,
        table_id,
        job_config=job_config,
        location=LOCATION
    )
    job.result()
    print(f"[BigQuery] Created {table_id} with {len(df)} rows")
