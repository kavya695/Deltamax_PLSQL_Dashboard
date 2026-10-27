# DeltaMax V5 API

This package exposes a read-only FastAPI layer over the existing Oracle V5 result tables and the Oracle security pipeline results. It does not run or modify the ML, PL/SQL, ARIMA, notifier, churn, or security scanning pipelines.

## Run

From the `V5/V5` folder:

```powershell
python -m pip install -r requirements-api.txt
python -m uvicorn api.main:app --reload
```

API docs: `http://127.0.0.1:8000/docs`

Health: `http://127.0.0.1:8000/api/health`

## Security dashboard

The frontend Security Posture page reads the latest successful security run from `SEC_RUNS`, `SEC_SUMMARY`, and `SEC_ROWS` in Oracle:

- `GET /api/security` returns summary metrics, category/severity counts, column findings, example findings, and the 50 lowest scoring records.
- `GET /api/security/finding/{record_id}/{finding_type}` returns the selected record's findings for the detail modal. Use `all` for every finding on that record.

The API connects to the same Oracle schema using `DELTAMAX_ORACLE_USER`, `DELTAMAX_ORACLE_PASSWORD`, and `DELTAMAX_ORACLE_DSN` (the existing V5 settings). For a separate security schema, set `SECURITY_ORACLE_USER`, `SECURITY_ORACLE_PASSWORD`, and `SECURITY_ORACLE_DSN` for the API process and grant it read access to the security tables. Run `security_pipeline/run_security_oracle.py` first to create a successful run.

## Churn results for all months

Run `python 06_Business_Churn_Risk_Prediction.py` to backfill monthly churn-risk results for each batch found in Oracle staging. The model's existing latest-transition holdout validation is retained.

Important interpretation:
- Earlier-month churn scores are **retrospective backfills** made by applying the trained model to historical monthly snapshots. They are not point-in-time predictions that were actually produced in those months.
- The churn model metrics stored with each batch describe the global latest-transition holdout evaluation, not a separate independently trained/evaluated model for each month.
- The script sends an optional notification for the latest month only, not one email per historical month.
- The script writes only to the existing Oracle churn tables; it does not use CSV or S3.
