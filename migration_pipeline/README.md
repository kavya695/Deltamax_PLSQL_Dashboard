# Migration Pipeline: 9 scripts backed by Oracle

This version retains all nine original numbered Python scripts. `oracle_compat.py` redirects pandas CSV-style reads and writes to Oracle tables; the scripts do not read or write CSV files at runtime. Legacy BigQuery export calls are redirected to Oracle through `oracle_exports.py`.

## Setup
1. Start Docker Desktop and the existing `deltamax-oracle` container.
2. In SQL Developer, connect to your intended schema (e.g. `DELTAMAX_V5`, `localhost:1521/FREEPDB1`). Run `oracle_schema.sql` with F5.
3. In PowerShell in this folder, run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:MIG_DB_USER = "DELTAMAX_V5"
$env:MIG_DB_PASSWORD = "YOUR_ORACLE_PASSWORD"
$env:MIG_DB_HOST = "localhost"
$env:MIG_DB_PORT = "1521"
$env:MIG_DB_SERVICE = "FREEPDB1"
python .\run_all_oracle.py
```

Replace the password. If activation is blocked, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again.

## MIGRATION_PKG integration
- `run_all_oracle.py` now records each of the nine script stages through `MIGRATION_PKG.LOG_STEP` and calls `MIGRATION_PKG.FINISH_MIGRATION` with SUCCESS/FAILED.
- `1datagen.py` starts each new run through `MIGRATION_PKG.START_MIGRATION` (via `oracle_compat.py`).
- Script 7 calls `MIGRATION_PKG.COPY_STAGE` for the clean and anomaly datasets.
- After all nine scripts complete, the runner calls `MIGRATION_PKG.VALIDATE_STAGE` for every stored Oracle stage. A failed validation marks the run FAILED.
- Before running, compile `MIGRATION_PKG.sql` and ensure its package and body are VALID in the same schema configured in `MIG_DB_USER`.

## What changed
- All nine original scripts are included by their original filenames. The pre-migration, cleaned-data, post-migration and anomaly analytics remain Python calculations; their dataframe artifacts are stored in Oracle.
- Script 7 was deprecated in the source ZIP; it now copies clean and anomaly data between separate Oracle stages and validates row counts and business IDs. This is an Oracle landing-stage simulation, not a real Azure/GCP transfer.
- BigQuery-named exports are redirected to Oracle; no cloud client is called.
- JSON anomaly logs are stored in Oracle.
- Data is stored per `RUN_ID`; rerunning the generator creates a new run without deleting prior runs.

## One-time load to BigQuery
The optional `oracle_to_bigquery.py` exports the two completed datasets from the active local Oracle run:
`hab_post_migration` and `hab_post_migration_with_anomalies`. It writes/replaces those tables in an existing BigQuery dataset, then checks the loaded row counts. It uses Google Application Default Credentials. This is a one-time batch upload from this project's local Oracle simulation; it does not connect to Oracle Cloud (OCI) and it does not make step 7 a live cloud transfer.

In PowerShell, from this `migration_pipeline` folder, first install the added dependencies and finish a pipeline run using the Oracle setup above. Then configure Google Cloud CLI with a project that has BigQuery enabled and a user/service identity allowed to create BigQuery jobs and write tables:

```powershell
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud services enable bigquery.googleapis.com
gcloud auth application-default login
python -m pip install -r requirements.txt
$env:GOOGLE_CLOUD_PROJECT = "YOUR_GCP_PROJECT_ID"
$env:BQ_DATASET = "deltamax_migration"
bq mk --dataset "$($env:GOOGLE_CLOUD_PROJECT):$env:BQ_DATASET"
python .\run_all_oracle.py
python .\oracle_to_bigquery.py
```

If the dataset already exists, skip `bq mk`. The BigQuery dataset location is chosen when it is created; pass `--location US` (or your dataset's location) if needed. The `WRITE_TRUNCATE` setting replaces these two destination tables each time this export is run. Do not put passwords or service-account keys in source files.

## BigQuery-to-Oracle recovery

The Cloud Migration sidebar's **BigQuery → Oracle** page lets you select either or both supported source tables: `hab_combined` and `mig_pipeline_data`. It runs `bigquery_to_oracle_migration.py` through the separate `bq_to_oracle` API mode and displays per-table progress and validation results. Destinations are `BQ_HAB_COMBINED` and `BQ_MIG_PIPELINE_DATA`. A missing Oracle destination is created using the BigQuery schema mapping; an existing destination must match source column names, order, and compatible types. The page prompts before replacing existing rows. The script uses transactional `DELETE`, streams rows in batches, verifies the Oracle count before commit, and rolls back a table's delete and inserts if its load fails. Run the script without `--replace` to retain skip-if-nonempty behavior. The migration virtual environment must have this folder's requirements installed, Google Application Default Credentials must be configured for the BigQuery project, and the V5 API process must have `DELTAMAX_ORACLE_PASSWORD` (or `ORACLE_PASSWORD`) set.

## Verify
```sql
SELECT RUN_ID, STATUS, STARTED_AT, FINISHED_AT, DETAILS FROM MIGR_RUNS ORDER BY STARTED_AT DESC;
SELECT STEP_NAME, STATUS, RECORD_COUNT, DETAILS, CREATED_AT FROM MIGR_LOG WHERE RUN_ID=(SELECT RUN_ID FROM MIGR_CONTROL WHERE CONTROL_KEY='ACTIVE') ORDER BY LOG_ID;
SELECT FILE_KEY, ROW_COUNT, UPDATED_AT FROM MIGR_FILES WHERE RUN_ID=(SELECT RUN_ID FROM MIGR_CONTROL WHERE CONTROL_KEY='ACTIVE') ORDER BY FILE_KEY;
```

## Important
This is a code-level Oracle storage conversion, not a full PL/SQL rewrite of the Python machine-learning algorithms. Python syntax was checked after package integration, but the integrated full pipeline has not been executed against your live Oracle instance. Compare outputs with the original pipeline before using this as a production replacement.
