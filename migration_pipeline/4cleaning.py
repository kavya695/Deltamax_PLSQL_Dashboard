import pandas as pd
from bq_step3 import read_source_table, write_output_table

print("Loading Step 3 results from BigQuery...")
df = read_source_table("migration_hab_pre_migration_v2")
print(f"[OK] Loaded {len(df):,} records with {len(df.columns)} columns")

required = [
    "record_id", "businessID", "data_lineage", "anomaly_health",
    "drift_health", "business_health", "overall_anomaly_risk",
    "overall_dataset_trust",
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise ValueError(
        f"Step 3 output is missing required columns: {missing}. "
        "Run the updated Step 3 script first."
    )

if df["record_id"].isna().any():
    raise ValueError("record_id contains null values; refusing to clean records.")
if df["record_id"].duplicated().any():
    raise ValueError("record_id is not unique; refusing to clean records.")

RISK_THRESHOLD = 0.30
HEALTH_THRESHOLD = 1.0 - RISK_THRESHOLD
print(f"Cleaning rule: anomaly_health >= {HEALTH_THRESHOLD:.2f}")

# Keep every column, including all original business features.
clean_mask = pd.to_numeric(df["anomaly_health"], errors="coerce") >= HEALTH_THRESHOLD
clean_df = df.loc[clean_mask].copy().reset_index(drop=True)
discarded_df = df.loc[~clean_mask].copy().reset_index(drop=True)

print("\nData lineage counts in cleaned data:")
print(clean_df["data_lineage"].value_counts(dropna=False))
print("\nData lineage counts in discarded data:")
print(discarded_df["data_lineage"].value_counts(dropna=False))

print(f"\nTotal input records: {len(df):,}")
print(f"Cleaned records: {len(clean_df):,}")
print(f"Discarded records: {len(discarded_df):,}")
if len(clean_df) + len(discarded_df) != len(df):
    raise RuntimeError("Validation failed: cleaned + discarded != input rows.")
if set(clean_df["record_id"]).intersection(set(discarded_df["record_id"])):
    raise RuntimeError("Validation failed: record IDs appear in both outputs.")

print("\nSaving full cleaned records to BigQuery...")
write_output_table(clean_df, "migration_hab_clean_v2")
print("\nSaving full discarded records to BigQuery...")
write_output_table(discarded_df, "migration_hab_discarded_v2")

print("\nStep 4 complete. Original business columns and record_id were preserved.")
