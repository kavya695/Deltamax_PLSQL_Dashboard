# Security Pipeline — Oracle Edition

This package adapts the supplied security pipeline to persist generated data and results in Oracle instead of writing CSV/JSON output files or uploading to BigQuery.

## Included scripts
- `security/1_generate_breach_data.py` — original synthetic data generation functions
- `security/2_dspm_scan.py` — sensitive data exposure scanner
- `security/4_fraud_signals_scan.py` — fraud/abuse scanner
- `security/5_tamper_scan.py` — tamper/integrity scanner
- `security/6_security_score.py` — original scoring policy/constants
- `run_security_oracle.py` — executes all script logic in memory and persists results in Oracle
- `oracle_security_schema_and_package.sql` — creates Oracle tables and `SECURITY_PKG`

## Important design
The pipeline keeps the Python scanning and scoring algorithms in Python. Oracle stores the baseline, generated security data, ground-truth rows, each scanner's findings, unified findings, per-record scores, summary JSON, run history and step logs. No CSV output files are required by the Oracle runner. The supplied original scripts are retained for their algorithms; the runner calls their functions directly rather than their CSV-writing `main()` methods.

## 1. Create tables and package
1. Start the existing Oracle Docker container `deltamax-oracle`.
2. Open SQL Developer and connect to the schema that will own the security tables. Use your current `DELTAMAX_V5` connection if you want to keep it in the same schema.
3. Open `oracle_security_schema_and_package.sql`.
4. Press **F5 (Run Script)**.
5. Confirm `SECURITY_PKG` and `SECURITY_PKG` body are VALID and tables `SEC_RUNS`, `SEC_LOG`, `SEC_DATASETS`, `SEC_ROWS`, `SEC_SUMMARY` exist.

Run the schema script only once. If tables already exist, do not rerun blindly; Oracle will report name conflicts. Do not drop existing tables.

## 2. Install Python dependencies
Open PowerShell in the extracted project folder:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and activate again.

## 3. Configure Oracle credentials
Set the password for the Oracle schema you used in SQL Developer (replace the example with your actual password; do not share it):
```powershell
$env:ORACLE_USER = "DELTAMAX_V5"
$env:ORACLE_PASSWORD = "YOUR_ORACLE_PASSWORD"
$env:ORACLE_DSN = "localhost:1521/FREEPDB1"
```

## 4. Run all security scripts against Oracle
```powershell
python run_security_oracle.py
```
Optional row count:
```powershell
python run_security_oracle.py --rows 400 --seeded 6
```
This will generate synthetic rows in memory, run all three scanners and the scoring aggregator, and persist results into Oracle. It does not write CSV output files. The generator's existing per-category minimum is 50 seeded records, so `--seeded 6` does not mean only six rows are injected.

## 5. Verify in SQL Developer
```sql
SELECT RUN_ID, STATUS, STARTED_AT, FINISHED_AT, DETAILS
FROM SEC_RUNS
ORDER BY STARTED_AT DESC;

SELECT STEP_NAME, STATUS, RECORD_COUNT, DETAILS, CREATED_AT
FROM SEC_LOG
WHERE RUN_ID = (SELECT RUN_ID FROM SEC_RUNS ORDER BY STARTED_AT DESC FETCH FIRST 1 ROW ONLY)
ORDER BY LOG_ID;

SELECT DATASET_KEY, ROW_COUNT
FROM SEC_DATASETS
WHERE RUN_ID = (SELECT RUN_ID FROM SEC_RUNS ORDER BY STARTED_AT DESC FETCH FIRST 1 ROW ONLY)
ORDER BY DATASET_KEY;

SELECT JSON_VALUE(SUMMARY_JSON, '$.overall_security_score') AS OVERALL_SECURITY_SCORE,
       JSON_VALUE(SUMMARY_JSON, '$.total_records') AS TOTAL_RECORDS,
       JSON_VALUE(SUMMARY_JSON, '$.records_with_findings') AS RECORDS_WITH_FINDINGS
FROM SEC_SUMMARY
WHERE RUN_ID = (SELECT RUN_ID FROM SEC_RUNS ORDER BY STARTED_AT DESC FETCH FIRST 1 ROW ONLY);
```

## Storage layout
- `SEC_RUNS`: each execution and its final status
- `SEC_LOG`: step-by-step statuses
- `SEC_DATASETS`: one metadata row per dataset per run
- `SEC_ROWS`: row payloads stored as JSON in Oracle CLOBs, keyed by run and dataset
- `SEC_SUMMARY`: dataset-level security summary JSON

The JSON CLOB storage preserves the flexible source schemas without creating a separate physical Oracle column for every source field. Use the dashboard API/backend to query these tables. Do not put database credentials in frontend code.

## Notes
- The scripts generate synthetic test data; findings are simulated test scenarios, not proof of a real security incident.
- Python still runs the detection/scoring algorithms. The Oracle package tracks runs and steps; it does not rewrite regex/statistical scanning logic into PL/SQL.
- This project does not include a frontend/API integration yet.
