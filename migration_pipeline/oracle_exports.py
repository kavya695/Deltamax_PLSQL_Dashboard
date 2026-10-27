
"""Export DeltaMax migration results to Google BigQuery."""

import json
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "datatoolunstructured"
DATASET_ID = "deltamax_migration"
LOCATION = "asia-south1"


def upload_to_bq(df, table_name):
    """Upload a pandas DataFrame to a BigQuery table."""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("upload_to_bq expects a pandas DataFrame.")

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )

    job = client.load_table_from_dataframe(
        df,
        table_id,
        job_config=job_config,
        location=LOCATION,
    )
    job.result()

    table = client.get_table(table_id)
    print(
        f"[BigQuery] Uploaded {table.num_rows:,} rows "
        f"to {table_id}"
    )


def upload_json_to_bq(obj, table_name):
    """Store a JSON object as one row in a BigQuery table."""

    json_text = json.dumps(obj, default=str)
    df = pd.DataFrame([{"data": json_text}])

    upload_to_bq(df, table_name)
