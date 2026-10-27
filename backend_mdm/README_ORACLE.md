# MDM on Oracle — no CSV, no GCP, no S3

This version adapts the uploaded MDM project to store source, scoring, and golden-record data in Oracle. It does not read or write CSV files and does not upload data to GCP or S3.

## Architecture
- `MDM_CUSTOMER_STG`: generated customer source records
- `MDM_CUSTOMER_SCORES`: trust score details from the existing `trust_score_engine.py`
- `MDM_CUSTOMER_GOLDEN`: one highest-trust record per `CLUSTER_ID`
- `MDM_RUN_LOG`: step outcomes and record counts
- `MDM_PKG`: PL/SQL validation/status helpers and golden-record refresh

The existing detailed scoring rules remain in Python, as in the DeltaMax V5 architecture where ML/statistical work stays in Python. The records and all outputs are persisted in Oracle. PL/SQL performs database-side validation, golden-record selection and run logging.

## 1. Start Oracle
Start Docker Desktop, then start the existing `deltamax-oracle` container. Verify with `docker ps`. The container should publish port 1521 and Oracle service `FREEPDB1` should be ready.

## 2. Create tables/package in SQL Developer
Connect using your existing Oracle schema (for example `DELTAMAX_V5`, service `FREEPDB1`, host `localhost`, port `1521`). Open `oracle/01_schema.sql` and run as script (F5). Then run `oracle/02_mdm_pkg.sql` as script (F5). If your MDM tables should be isolated from V5, create a separate schema with appropriate DBA privileges and connect as that schema; do not create users from this application script.

## 3. Install Python dependency
Use the Python environment for this project:
```powershell
python -m pip install oracledb
```
Install the other dependencies required by `trust_score_engine.py` only if missing. The pipeline does not require pandas for CSV processing anymore.

## 4. Set connection credentials in PowerShell
```powershell
$env:MDM_DB_USER = "DELTAMAX_V5"
$env:MDM_DB_PASSWORD = "YOUR_ORACLE_SCHEMA_PASSWORD"
$env:MDM_DB_HOST = "localhost"
$env:MDM_DB_PORT = "1521"
$env:MDM_DB_SERVICE = "FREEPDB1"
```
Use the actual password you set for your schema. Avoid storing it in source code.

## 5. Run the MDM pipeline
From the folder containing these scripts:
```powershell
python .\1generate_data.py
python .\2run_scoring.py
python .\3run_golden.py
```
Or run all steps in order:
```powershell
python .\run_mdm_pipeline.py
```
The generator deliberately clears the MDM staging/scores/golden tables before loading a fresh synthetic demo dataset. Do not use that generator against real customer data unless you intend to replace the demo data.

## 6. Verify results
Run `oracle/03_queries.sql` in SQL Developer (F5). Expected approximate scale with `MDM_NUM_CUSTOMERS=1000`: source records between 3,000 and 5,000; golden records about 1,000. Counts depend on the random generation.

## 7. Connect the MDM results to the shared frontend
The MDM API reads the tables above and serves the existing MDM overview, source systems, review queue, and cluster details. In a PowerShell window opened in `backend_mdm`, install the API dependencies and start it:
```powershell
python -m pip install -r requirements-oracle.txt
$env:MDM_DB_USER = "DELTAMAX_V5"
$env:MDM_DB_PASSWORD = "YOUR_ORACLE_SCHEMA_PASSWORD"
$env:MDM_DB_HOST = "localhost"
$env:MDM_DB_PORT = "1521"
$env:MDM_DB_SERVICE = "FREEPDB1"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Keep that window open. Start the Vite frontend in another PowerShell window from `frontend` with `npm run dev`. The Vite proxy sends `/api/mdm` requests to port 8001 and continues sending the other API requests to the V5 backend on port 8000. Turn off the dashboard's Demo mode to see live Oracle MDM results. The MDM API is read-only; run `python .\run_mdm_pipeline.py` from `backend_mdm` when you need to refresh the Oracle data.

## Notes
- The uploaded source generator previously wrote `results/*.csv` and imported `bq_utils.upload_to_bq`. Those storage actions have been removed from the Oracle version.
- No Google Cloud project or bucket is used. No CSV files are produced by the pipeline.
- `DELTAMAX_V5` is used as the example connection/schema name because it exists in the user's Oracle setup. A separate MDM schema is optional but requires creation by an authorized DBA.
- The uploaded source code is synthetic demo data, not an import of real customer records.
