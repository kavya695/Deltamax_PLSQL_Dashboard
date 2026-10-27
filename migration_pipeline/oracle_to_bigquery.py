"""One-time export of completed Oracle pipeline stages to BigQuery.

This reads the local Oracle-backed stages created by run_all_oracle.py. It does
not connect to OCI Oracle, and it does not change the simulated step 7 flow.
"""

from __future__ import annotations

import argparse
import os

from google.cloud import bigquery

from oracle_compat import active_run_id, read_frame


STAGES = {
    "hab_post_migration.csv": "hab_post_migration",
    "hab_post_migration_with_anomalies.csv": "hab_post_migration_with_anomalies",
}


def export(project: str, dataset: str, location: str | None = None) -> None:
    client = bigquery.Client(project=project, location=location)
    run_id = active_run_id()
    print(f"Exporting Oracle pipeline run {run_id} to {project}.{dataset}")

    for stage, table_name in STAGES.items():
        frame = read_frame(f"results/{stage}")
        if frame.empty:
            raise RuntimeError(f"Stage {stage} has no rows; run the Oracle pipeline first.")

        table_id = f"{project}.{dataset}.{table_name}"
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        job = client.load_table_from_dataframe(frame, table_id, job_config=job_config)
        job.result()
        loaded_rows = client.get_table(table_id).num_rows
        if loaded_rows != len(frame):
            raise RuntimeError(
                f"Row count mismatch for {table_id}: uploaded {loaded_rows}, source {len(frame)}"
            )
        print(f"Loaded and verified {loaded_rows:,} rows: {table_id}")

    print("BigQuery one-time load completed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"),
                        help="Google Cloud project ID (or GOOGLE_CLOUD_PROJECT)")
    parser.add_argument("--dataset", default=os.getenv("BQ_DATASET"),
                        help="Existing BigQuery dataset ID (or BQ_DATASET)")
    parser.add_argument("--location", default=os.getenv("BQ_LOCATION"),
                        help="Optional BigQuery dataset location, e.g. US or asia-south1")
    args = parser.parse_args()
    if not args.project or not args.dataset:
        parser.error("provide --project and --dataset, or set GOOGLE_CLOUD_PROJECT and BQ_DATASET")
    export(args.project, args.dataset, args.location)


if __name__ == "__main__":
    main()
