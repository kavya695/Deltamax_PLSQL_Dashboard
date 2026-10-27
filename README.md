# DeltaMax V5 and Oracle MDM

This project keeps one shared React/Vite frontend and separates the two Python backends:

- `V5/` contains the DeltaMax V5 API and processing pipeline.
- `MDM/` contains the Oracle MDM pipeline and SQL scripts from `MDM_Oracle_No_CSV_No_GCP.zip`.
- `migration_pipeline/` contains the integrated Oracle migration pipeline from `Migration_Pipeline_Oracle_No_CSV_No_GCP_Integrated.zip`.
- `frontend/` is shared by both backends.

## Start all services together

Start Oracle Database first, then open one VS Code PowerShell terminal at the project root and run:

```powershell
cd "C:\Users\ksont\Downloads\DeltaMax_V5_Month_Names_Only\DeltaMax_V5_Integrated_UI"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start-local.ps1
```

The script securely prompts for the Oracle password if it is not already set, starts both the V5 API and MDM API, starts the shared Vite frontend, and checks that the APIs can connect to Oracle. By default, both APIs use the same Oracle account and password; if MDM uses a separate database user, set `MDM_DB_USER` and `MDM_DB_PASSWORD` first. It reuses healthy services already running and checks failed health responses. If port 8001 is stuck or occupied by an unhealthy listener, it chooses a free MDM port from 8002–8010 and restarts this project's Vite process with the correct MDM proxy. Open `http://localhost:5173` when the script says all services are ready.

Core Engine, Executive AI, Cloud Migration, and Security use the V5 API; MDM uses its separate API. The Oracle listener must be available at the configured DSN (default `localhost:1521/FREEPDB1`). Set `DELTAMAX_ORACLE_DSN`, `DELTAMAX_ORACLE_USER`, `MDM_DB_*`, `BQ_PROJECT`, or `BQ_DATASET` in the terminal before running the script if your setup differs. Starting services does not execute data pipelines or modify database contents.

## Shared frontend

Start the frontend from `frontend/`:

```powershell
npm install
npm run dev
```

The Vite development server proxies `/api/mdm` to the MDM API at `http://localhost:8001` and other `/api` requests to the V5 API at `http://localhost:8000` by default. Set `MDM_BACKEND_URL` or `BACKEND_URL` to change either target.

## DeltaMax V5 backend

Open PowerShell in `V5/`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-api.txt
$env:DELTAMAX_ORACLE_USER = "DELTAMAX_V5"
$env:DELTAMAX_ORACLE_PASSWORD = "YOUR_ORACLE_PASSWORD"
$env:DELTAMAX_ORACLE_DSN = "localhost:1521/FREEPDB1"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

API health: http://127.0.0.1:8000/api/health  
API docs: http://127.0.0.1:8000/docs

The V5 processing scripts are `01_generate_data.py` through `06_Business_Churn_Risk_Prediction.py`. The frontend's Executive AI overview uses the V5 Oracle API. Some other legacy dashboard pages may not have matching V5 endpoints.

## Oracle MDM backend

The MDM archive contents are in `MDM/`. Follow `MDM/README_ORACLE.md` for Oracle setup and pipeline instructions. Its dependency list is `requirements-oracle.txt`; its pipeline entry point is `run_mdm_pipeline.py`.

The MDM scripts are kept separate from V5. The MDM dashboard API is `MDM/main.py`. Set the `MDM_DB_*` environment variables from the MDM README and start it with `python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001` from `MDM/`. Vite proxies `/api/mdm` to that service (`MDM_BACKEND_URL`, default `http://localhost:8001`) and all other API paths to the V5 backend (`BACKEND_URL`, default `http://localhost:8000`).

## Oracle migration pipeline

The Oracle migration pipeline is stored separately in `migration_pipeline/`. See `migration_pipeline/README.md` and `migration_pipeline/START_HERE.txt` for setup and run instructions. This integrated version expects a valid `MIGRATION_PKG` in the selected Oracle schema.

The Cloud Migration sidebar has separate **Oracle → BigQuery** and **BigQuery → Oracle** pages. On the BigQuery → Oracle page, select `hab_combined`, `mig_pipeline_data`, or both, then start the reverse migration. Existing Oracle rows are replaced after confirmation; a failed table load rolls that table back. Missing destination tables are created from the source schema where Oracle supports the mapped types. Configure Google Application Default Credentials and install `migration_pipeline/requirements.txt` in the migration virtual environment. Set `DELTAMAX_ORACLE_PASSWORD` (or `ORACLE_PASSWORD`) in the V5 API terminal. Progress and per-table row-count validation appear on that page.

## Oracle security pipeline

The Oracle security pipeline from `Security_Pipeline_Oracle_Integrated.zip` is in `security/`. It runs independently from the V5, MDM and migration pipelines. The Security Posture frontend page reads its latest Oracle results through the V5 API at `/api/security`; finding details are served by `/api/security/finding/{record_id}/{finding_type}`. Use the same Oracle schema for the security tables and API, or configure the API's `SECURITY_ORACLE_USER`, `SECURITY_ORACLE_PASSWORD`, and `SECURITY_ORACLE_DSN` variables and grant read access to those tables. Follow `security/README.md` to create the schema and package before running it. From the `DeltaMax_V5_Integrated_UI` directory, use PowerShell:

```powershell
cd security
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:ORACLE_USER = "DELTAMAX_V5"
$env:ORACLE_PASSWORD = "YOUR_ORACLE_PASSWORD"
$env:ORACLE_DSN = "localhost:1521/FREEPDB1"
python run_security_oracle.py
```

Optional run size: `python run_security_oracle.py --rows 400 --seeded 6`.
