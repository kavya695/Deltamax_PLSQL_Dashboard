# Original nine-script conversion map

| Original stage | Oracle edition behaviour |
|---|---|
| `1datagen.py` | Original synthetic business-credit generator retained; monthly outputs written directly to Oracle. Starts a new RUN_ID. |
| `2HAB.py` | Original H/A/B lineage combination retained; reads monthly Oracle stages and writes combined stage to Oracle. |
| `3pre-migration_check.py` | Original Python business-rule, anomaly, drift and trust calculations retained; outputs/trust summaries written to Oracle. |
| `4cleaning.py` | Original anomaly-health threshold logic retained; cleaned and discarded datasets written to Oracle. |
| `5Data_check_cleaned.py` | Original cleaned-data validation/trust calculations retained; outputs written to Oracle. |
| `6inject_anomalies.py` | Original anomaly injection configuration and operations retained; anomalous stage and JSON log written to Oracle. |
| `7migrate_azure_to_gcp.py` | Source was deprecated; replaced with an Oracle source-to-target stage copy for clean and anomaly datasets, with row/key validation. |
| `8post-migration_check.py` | Original post-migration analytics retained; reads Oracle target stage and writes results to Oracle. |
| `9post_migration_with_anomalies.py` | Original anomaly-aware post-migration analytics retained; reads Oracle anomaly target stage and writes results to Oracle. |

The original filenames and Python calculation logic remain. Persistence has been changed from filesystem CSV/JSON artifacts and BigQuery helper calls to Oracle tables. The `FILE_KEY` column keeps logical artifact names (for example `results/hab_clean.csv`) as labels only; no file with that name is created. The Python machine-learning calculations are not converted to PL/SQL; PL/SQL is used for database persistence and Oracle run/log metadata.


## MIGRATION_PKG runtime integration
- Run creation delegates to `MIGRATION_PKG.START_MIGRATION`.
- Stage log records delegate to `MIGRATION_PKG.LOG_STEP`.
- Script 7 delegates Oracle stage copies to `MIGRATION_PKG.COPY_STAGE`.
- Final stage row-count checks delegate to `MIGRATION_PKG.VALIDATE_STAGE`.
- Pipeline completion or failure delegates to `MIGRATION_PKG.FINISH_MIGRATION`.
