# DeltaMax V5 — Churn across all months

## What this change does
- Scores every month present in `DM_V5_STG_CREDIT_BUREAU`.
- Stores each month's predictions under that month's existing `BATCH_ID`.
- Replaces the prior results for each batch as the script already did.
- Sends at most one email for the latest month.

## Important modeling caveat
The model is trained and validated using the existing latest-transition holdout process. Applying that trained model to earlier monthly snapshots creates **retrospective historical scores**, not point-in-time predictions. The historical scores are useful for browsing monthly risk distributions, but should not be described as forecasts that were generated at the time. The metrics copied alongside each batch are global holdout metrics, not per-month model evaluations.

## Run
From the project folder containing `06_Business_Churn_Risk_Prediction.py`:

```powershell
python .\\06_Business_Churn_Risk_Prediction.py
```

The script connects to Oracle and writes to:
- `DM_V5_CHURN_RISK_RESULTS`
- `DM_V5_CHURN_MODEL_METRICS`
- `DM_V5_CHURN_FEATURE_IMPORTANCE`

After it completes, restart/reload FastAPI and select any batch in the dashboard.
