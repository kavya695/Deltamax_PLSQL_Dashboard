# BigQuery migration: local CSV outputs plus BigQuery table outputs.

import sys
import pandas as pd
from oracle_compat import missingness_flags
import numpy as np
import os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from oracle_exports import upload_to_bq
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from sklearn.neighbors import NearestNeighbors
from bq_step3 import read_source_table, write_output_table

current_year = datetime.now(timezone.utc).year

# ============================================================
# 🔧 HYPERPARAMETERS & THRESHOLDS - TUNE HERE
# ============================================================
# ============================================================
# -------- UNIFIED RISK WEIGHTS --------
W_ISO       = 0.15
W_IQR       = 0.15
W_MISSING   = 0.10
W_DUPLICATE = 0.05
W_KNN       = 0.10
W_BUSINESS  = 0.15

# -------- BUSINESS RULES (CRITICAL VIOLATIONS) --------
BR_CREDIT_SCORE_MIN = 300
BR_CREDIT_SCORE_MAX = 900
BR_ANNUAL_REVENUE_MIN = 0
BR_OUTSTANDING_DEBT_MIN = 0
BR_TOTAL_CREDIT_LIMIT_MIN = 0
BR_AVAILABLE_CREDIT_MIN = 0
BR_YEAR_ESTABLISHED_MAX = current_year
BR_MONTHS_FIRST_ACCOUNT_MIN = 0
BR_MONTHS_LAST_PAYMENT_MIN = 0

# -------- BUSINESS RULES (HIGH VIOLATIONS) --------
BR_CREDIT_UTIL_MIN = 0
BR_CREDIT_UTIL_MAX = 100
BR_NUM_ACCOUNTS_MIN = 0
BR_EMPLOYEE_COUNT_MIN = 0
BR_NUM_INQUIRIES_MIN = 0
BR_DELINQUENT_ACCOUNT_MIN = 0

# -------- BUSINESS RULES (MEDIUM VIOLATIONS) --------
BR_BANKRUPTCY_CREDIT_SCORE_MIN = 750
BR_PAYMENT_HISTORY_MAX = 100
BR_PAYMENT_HISTORY_MIN = 0

# -------- BUSINESS RULES (LOW VIOLATIONS) --------
BR_EMPLOYEE_COUNT_MAX = 5000
BR_HIGH_REVENUE_THRESHOLD = 100_000_000
BR_HIGH_REVENUE_EMPLOYEE_MIN = 5
BR_LOW_CREDIT_SCORE = 450
BR_MONTHS_LAST_PAYMENT_MAX = 120

# -------- BUSINESS HEALTH --------
MAX_POSSIBLE_FLAGS = 22

# -------- KNN ANOMALY DETECTION --------
KNN_K = 5
KNN_PERCENTILE = 0.99

# -------- ISOLATION FOREST --------
ISO_N_ESTIMATORS = 64
ISO_MAX_SAMPLES = 100000
ISO_DECISION_THRESHOLD = 0

# -------- IQR OUTLIER DETECTION --------
IQR_MULTIPLIER = 5
IQR_VIOLATION_THRESHOLD = 0

# -------- ENSEMBLE ANOMALY WEIGHTS (LEGACY - REMOVE IF UNUSED) --------
# WEIGHT_ISO_FLAG = 0.30
# WEIGHT_IQR_FLAG = 0.25
# WEIGHT_MISSING_FLAG = 0.15
# WEIGHT_DUPLICATE_FLAG = 0.10
# WEIGHT_KNN_FLAG = 0.20
ANOMALY_RISK_THRESHOLD = 0.4

# -------- DRIFT DETECTION --------
WEIGHT_MAHAL_DRIFT = 0.7
WEIGHT_PSI = 0.20
WEIGHT_MAHAL=0.7 
WEIGHT_WELCH=0.1
DRIFT_PERCENTILE = 95  # for reporting only

# -------- TRUST SCORE WEIGHTS --------
WEIGHT_ANOMALY_HEALTH = 0.55
WEIGHT_DRIFT_HEALTH = 0.15
WEIGHT_BUSINESS_HEALTH = 0.30


# ============================================================
# BIGQUERY CONFIG
# ============================================================

# ============================================================
# LOAD DATA
# ============================================================
print("\nLoading cleaned HAB dataset from BigQuery...")

df = read_source_table("migration_hab_clean_v2")

if "record_id" not in df.columns:
    raise ValueError("record_id is missing from the cleaned dataset.")

if df["record_id"].isna().any() or df["record_id"].duplicated().any():
    raise ValueError("record_id must be present and unique.")

print(f"[OK] Loaded {len(df):,} cleaned records")
print(f"[OK] Loaded {len(df.columns)} columns")


# ============================================================
# OUTPUT DIRECTORY SETUP
# ============================================================

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "results")

# Lineage-specific output directories
DIR_H = os.path.join(OUTPUT_DIR, "H")
DIR_A = os.path.join(OUTPUT_DIR, "A")
DIR_B = os.path.join(OUTPUT_DIR, "B")

os.makedirs(DIR_H, exist_ok=True)
os.makedirs(DIR_A, exist_ok=True)
os.makedirs(DIR_B, exist_ok=True)

# ============================================================
# 1️⃣ BUSINESS RULE FLAGS
# ============================================================
print("\nApplying business rules")

# ------------------------------------------------------------
# Initialize flags for all rows
# ------------------------------------------------------------
df["CRITICAL_flags"] = 0
df["HIGH_flags"] = 0
df["MEDIUM_flags"] = 0
df["LOW_flags"] = 0

# ------------------------------------------------------------
# CRITICAL RULES
# ------------------------------------------------------------
critical_conditions = [
    (df.creditScore < BR_CREDIT_SCORE_MIN) | (df.creditScore > BR_CREDIT_SCORE_MAX),
    df.annualRevenue < BR_ANNUAL_REVENUE_MIN,
    df.outstandingDebt < BR_OUTSTANDING_DEBT_MIN,
    df.totalCreditLimit < BR_TOTAL_CREDIT_LIMIT_MIN,
    df.availableCredit < BR_AVAILABLE_CREDIT_MIN,
    df.yearEstablished > BR_YEAR_ESTABLISHED_MAX,
    df.monthsSinceFirstAccount < BR_MONTHS_FIRST_ACCOUNT_MIN,
    df.monthsSinceLastPayment < BR_MONTHS_LAST_PAYMENT_MIN
]

# for cond in critical_conditions:
#     df.loc[current_mask, "CRITICAL_flags"] += cond[current_mask].astype(int)

for cond in critical_conditions:
    df["CRITICAL_flags"] += cond.astype(int)

# ------------------------------------------------------------
# HIGH RULES
# ------------------------------------------------------------
high_conditions = [
    df.availableCredit > df.totalCreditLimit,
    (df.creditUtilizationRatio < BR_CREDIT_UTIL_MIN) | (df.creditUtilizationRatio > BR_CREDIT_UTIL_MAX),
    df.numberOfAccounts < BR_NUM_ACCOUNTS_MIN,
    df.employeeCount < BR_EMPLOYEE_COUNT_MIN,
    df.numberOfInquiries < BR_NUM_INQUIRIES_MIN,
    df.delinquentAccountCount < BR_DELINQUENT_ACCOUNT_MIN
]

# for cond in high_conditions:
#     df.loc[current_mask, "HIGH_flags"] += cond[current_mask].astype(int)
for cond in high_conditions:
    df["HIGH_flags"] += cond.astype(int)
# ------------------------------------------------------------
# MEDIUM RULES
# ------------------------------------------------------------
medium_conditions = [
    (df.hasDefaulted == 1) & (df.delinquentAccountCount == 0),
    (df.hasBankruptcy == 1) & (df.creditScore > BR_BANKRUPTCY_CREDIT_SCORE_MIN),
    (df.numberOfAccounts == 0) & (df.totalCreditLimit > 0),
    (df.paymentHistoryScore > BR_PAYMENT_HISTORY_MAX) | (df.paymentHistoryScore < BR_PAYMENT_HISTORY_MIN)
]

for cond in medium_conditions:
    df["MEDIUM_flags"] += cond.astype(int)

# ------------------------------------------------------------
# LOW RULES
# ------------------------------------------------------------
low_conditions = [
    df.employeeCount > BR_EMPLOYEE_COUNT_MAX,
    (df.annualRevenue > BR_HIGH_REVENUE_THRESHOLD) & (df.employeeCount < BR_HIGH_REVENUE_EMPLOYEE_MIN),
    (df.creditScore < BR_LOW_CREDIT_SCORE) & (df.hasDelinquency == 0),
    df.monthsSinceLastPayment > BR_MONTHS_LAST_PAYMENT_MAX
]

for cond in low_conditions:
    df["LOW_flags"] += cond.astype(int)

# ------------------------------------------------------------
# TOTAL RULE VIOLATIONS
# ------------------------------------------------------------
df["rule_violations"] = 0

df["rule_violations"] = (
    df["CRITICAL_flags"]
    + df["HIGH_flags"]
    + df["MEDIUM_flags"]
    + df["LOW_flags"]
)

print("=" * 80)
print("Computing business health score based on rule violations")

df["business_health"] = 1.0

df["business_health"] = 1 - (
    df["rule_violations"] / MAX_POSSIBLE_FLAGS
)
df["business_health"] = df["business_health"].clip(0, 1)

print("Business Health = 1 - (rule_violations / MAX_POSSIBLE_FLAGS)")
print("Current business health mean:", df["business_health"].mean())

# ============================================================
# SPLIT DATASETS (AFTER BUSINESS RULES)
# ============================================================
# Do not reset index after splitting; keep original record_id intact
historical = df[df["data_lineage"] == "HISTORICAL"].copy()
A_data = df[df["data_lineage"] == "PREVIOUS_MONTH"].copy()
B_data = df[df["data_lineage"] == "CURRENT_MONTH"].copy()
# record_id was created on the full df and is preserved through copy()
datasets = {
    "H": historical,
    "A": A_data,
    "B": B_data
}

# ============================================================
# NUMERIC FEATURE PREP (UNCHANGED)
# ============================================================

exclude_cols = [
    "business_health",
    "CRITICAL_flags",
    "HIGH_flags",
    "MEDIUM_flags",
    "LOW_flags"
]

base_df = df.drop(columns=[c for c in exclude_cols if c in df.columns]).copy()
# numeric_cols = base_df.select_dtypes(include=np.number).columns.tolist()
numeric_cols = [
    "employeeCount",
    "annualRevenue",
    "creditScore",
    "outstandingDebt",
    "totalCreditLimit",
    "availableCredit",
    "paymentHistoryScore",
    "creditUtilizationRatio",
    "averageAccountAge",
    "numberOfAccounts",
    "numberOfInquiries",
    "delinquentAccountCount",
    "monthsSinceLastPayment",
    "monthsSinceFirstAccount",
    "monthsSinceLastDelinquency",
    "lastPaymentAmount",
    "highestCreditAmountEver",
    "totalAccountBalance",
    "totalMonthlyPayment",
    "debtToIncomeRatio"
]
X_hist = historical[numeric_cols].fillna(0)
# ============================================================
# 3️⃣ ANOMALY SCORE
# ============================================================
# 🔴 Define columns to EXCLUDE (VERY IMPORTANT)
exclude_cols = [
    "record_id",  # Generated based on index position
    "business_health",
    "trust_score",
    "systemHealthScore",
    "auditScore",
    "complianceFlag",
    "CRITICAL_flags",
    "HIGH_flags",
    "MEDIUM_flags",
    "LOW_flags"
]

# ✅ Create CLEAN BASE DATA (this is your TRUE base)
base_df = df.drop(columns=[col for col in exclude_cols if col in df.columns]).copy()

# ✅ Only numeric raw features
numeric_cols = base_df.select_dtypes(include=np.number).columns.tolist()

# ✅ Final input to models
X = base_df[numeric_cols].fillna(0)

print("="*80)
print("anomalies health")
print("="*80,'\n')


# ============================================================
# KNN DISTANCE (Baseline = HISTORICAL)
# ============================================================

# hyperparameters defined above: KNN_K, KNN_PERCENTILE
# ============================================================
# KNN DISTANCE (Baseline = HISTORICAL)
# ============================================================

print("\nRunning KNN distance anomaly detection...")
print("-"*70, '\n')

X_hist = historical[numeric_cols].fillna(0).values
print(f"Historical dataset shape: {X_hist.shape}")

knn = NearestNeighbors(
    n_neighbors=KNN_K,
    metric="euclidean",
    n_jobs=-1
)

knn.fit(X_hist)

hist_distances, _ = knn.kneighbors(X_hist)
hist_scores = hist_distances.mean(axis=1)
HIST_THRESHOLD = np.quantile(hist_scores, KNN_PERCENTILE)

print(f"Sample historical distances (first 5): {hist_distances[:5]}")
print(f"Sample historical scores (first 5): {hist_scores[:5]}")
print(f"Computed HIST_THRESHOLD at {KNN_PERCENTILE*100:.1f}th percentile: {HIST_THRESHOLD:.4f}")

for label, data in datasets.items():
    if len(data) == 0:
        continue

    X = data[numeric_cols].fillna(0).values
    print(f"\nDataset '{label}' shape: {X.shape}")

    distances, _ = knn.kneighbors(X)
    row_scores = distances.mean(axis=1)

    print(f"Sample row scores for {label} (first 5): {row_scores[:5]}")

    flags = (row_scores > HIST_THRESHOLD).astype(int)
    anomaly_count = flags.sum()
    total = len(flags)
    dataset_score = anomaly_count / total

    # Collect flags
    data["knn_raw"] = row_scores
    data["knn_flag"] = flags
    data["knn_dataset_score"] = dataset_score

    print(f"KNN {label}: {anomaly_count}/{total} anomalies = {dataset_score:.4f}")

print("-" * 80)
print("Running IsolationForest...")
print("-"*80)
# ============================================================
# ISOLATION FOREST (Baseline = HISTORICAL)
# ============================================================

X_hist = historical[numeric_cols].fillna(0)

iso = IsolationForest(
    n_estimators=ISO_N_ESTIMATORS,
    contamination="auto",                  # could expose as hyperparameter
    random_state=42,
    max_samples=min(ISO_MAX_SAMPLES, len(X_hist)),
    n_jobs=1
)
iso.fit(X_hist)

for label, data in datasets.items():

    X = data[numeric_cols].fillna(0)
    preds = iso.decision_function(X)

    # Collect flags (No intermediate CSV save)
    data["iso_flag"] = (preds < ISO_DECISION_THRESHOLD).astype(int)

    anomaly_count = data["iso_flag"].sum()
    total = len(data)

    anomaly_score = anomaly_count / total
    data["iso_dataset_score"] = anomaly_score

    print(f"ISO {label}: {anomaly_count}/{total} = {anomaly_score:.4f}")

print("-"*80)

# ============================================================
# Define core financial anomaly detection features
# ============================================================
ANOMALY_FEATURES = [
    "employeeCount",
    "annualRevenue",
    "creditScore",
    "outstandingDebt",
    "totalCreditLimit",
    "availableCredit",
    "paymentHistoryScore",
    "creditUtilizationRatio",
    "averageAccountAge",
    "numberOfAccounts",
    "numberOfInquiries",
    "delinquentAccountCount",
    "monthsSinceLastPayment",
    "monthsSinceFirstAccount",
    "monthsSinceLastDelinquency",
    "lastPaymentAmount",
    "highestCreditAmountEver",
    "totalAccountBalance",
    "totalMonthlyPayment",
    "debtToIncomeRatio"
]

## ============================================================
# IQR OUTLIER DETECTION (Baseline = HISTORICAL)  — M1 LOGIC
# ============================================================
print("\nRunning IQR detection")

# --- Learn bounds from HISTORICAL ---
iqr_bounds = {}

for col in ANOMALY_FEATURES:

    Q1 = historical[col].quantile(0.25)
    Q3 = historical[col].quantile(0.75)
    IQR = Q3 - Q1

    lower = Q1 - IQR_MULTIPLIER * IQR
    upper = Q3 + IQR_MULTIPLIER * IQR

    iqr_bounds[col] = (lower, upper)

# --- Apply to each dataset ---
for label, data in datasets.items():

    # store anomalous row indices
    iqr_anomalies = set()

    for col in ANOMALY_FEATURES:

        lower, upper = iqr_bounds[col]

        # find violating rows
        col_anomalies = data[
            (data[col] < lower) | (data[col] > upper)
        ].index

        # add to anomaly set
        iqr_anomalies.update(col_anomalies)

    # create result dataframe
    # mark anomalies in the dataset (No intermediate CSV save)
    data["iqr_flag"] = 0
    if len(iqr_anomalies) > 0:
        data.loc[list(iqr_anomalies), "iqr_flag"] = 1

    anomaly_count = data["iqr_flag"].sum()
    total = len(data)

    anomaly_score = anomaly_count / total if total > 0 else 0
    data["iqr_dataset_score"] = anomaly_score

    print(f"IQR {label}: {anomaly_count}/{total} = {anomaly_score:.4f}")

print("-"*80)
# ============================================================
# MISSINGNESS
# ============================================================

print("\nRunning Missingness detection (All Datasets)...")

for label, data in datasets.items():
    # Ignore fields that were not part of that source month's schema.
    data["missing_flag"] = missingness_flags(data).astype(int)
    
    anomaly_count = data["missing_flag"].sum()
    total = len(data)
    
    anomaly_score = anomaly_count / total if total > 0 else 0
    data["missing_dataset_score"] = anomaly_score
    
    print(f"Missing {label}: {anomaly_count}/{total} = {anomaly_score:.4f}")

print("-"*80)


# ============================================================
# DUPLICATE CHECK
# ============================================================

print("\nRunning Duplicate detection...")

# Define columns to EXCLUDE from duplicate check (generated/non-original columns)
dup_exclude_cols = [
    "record_id",  # Generated based on index position
    "business_health", "rule_violations",  # Business rule scores
    "CRITICAL_flags", "HIGH_flags", "MEDIUM_flags", "LOW_flags",  # Flag columns
    "data_lineage"  # Lineage column
]

for label, data in datasets.items():

    # Get list of original columns (exclude generated ones)
    dup_check_cols = [col for col in data.columns if col not in dup_exclude_cols]
    
    # Check duplicates on original columns only (excluding record_id and generated columns)
    dup_flags = data[dup_check_cols].duplicated(keep=False)

    
    # Store flag (No intermediate CSV save)
    data["duplicate_flag"] = dup_flags.astype(int)

    anomaly_count = data["duplicate_flag"].sum()
    total = len(data)

    anomaly_score = anomaly_count / total
    data["duplicate_dataset_score"] = anomaly_score

    print(f"Duplicate {label}: {anomaly_count}/{total} = {anomaly_score:.4f}")



# ============================================================
# 4️⃣ DRIFT SCORE (Mahalanobis + T-test vs H+A baseline)


# T-test: H+A vs B
# Mahalanobis: H+A vs B
# ============================================================

print('='*80)
print("Calculating drift using Mahalanobis distance and T-test (H+A vs B)")
print('='*80 ,"\n")

from scipy.stats import ttest_ind
from sklearn.preprocessing import MinMaxScaler

H_data = datasets["H"]
A_data = datasets["A"]
B_data = datasets["B"]

# Combined historical baseline
HA_data = pd.concat([H_data, A_data], ignore_index=True)

# --- numeric feature selection ---
exclude_cols = [
    "iso_raw","iso_score","iso_risk",
    "iqr_risk","missing_risk",
    "duplicate_risk","format_risk",
    "anomaly_risk","anomaly_health",
    "drift_raw","drift_stability",
    "base_trust","trust_score","trust_score_100","anomaly_score","anomaly_method"
]

feature_cols = [c for c in numeric_cols if c not in exclude_cols]
from scipy.stats import ttest_ind
from sklearn.preprocessing import MinMaxScaler
import numpy as np
import os

# ============================================================
# COMPUTE PSI (H+A vs B)
# ============================================================
def compute_psi(expected, actual, bins=10):
    """Compute Population Stability Index between two distributions"""
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]

    if len(expected) == 0 or len(actual) == 0:
        return 0

    breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)

    expected_counts, _ = np.histogram(expected, bins=breakpoints)
    actual_counts, _ = np.histogram(actual, bins=breakpoints)

    expected_perc = expected_counts / len(expected)
    actual_perc = actual_counts / len(actual)

    expected_perc = np.where(expected_perc == 0, 1e-6, expected_perc)
    actual_perc = np.where(actual_perc == 0, 1e-6, actual_perc)

    psi = np.sum((actual_perc - expected_perc) * np.log(actual_perc / expected_perc))

    return psi

print("\nRunning PSI (Population Stability Index) analysis...")

psi_results = []

for col in feature_cols:
    psi_val = compute_psi(HA_data[col].values, B_data[col].values)
    psi_results.append({"feature": col, "psi": psi_val})

psi_df = pd.DataFrame(psi_results)

dataset_psi = psi_df["psi"].mean()
psi_health = np.exp(-dataset_psi)

# print(f"Mean PSI: {dataset_psi:.4f}")
# print(f"PSI Health: {psi_health:.4f}")


print("-"*80)

# ============================================================
# POPULATION STABILITY INDEX (PSI)
# ============================================================

# ============================================================
# WELCH T-TEST DRIFT (dataset-level severity)
# ============================================================
def welch_drift_severity(ref_df, cur_df, features, label=""):
    scores = []
    welch_results = []

    print(f"\n[Welch Drift]")
    print("-" * 60)

    for col in features:
        xH = ref_df[col].dropna().values
        xC = cur_df[col].dropna().values

        if len(xH) < 2 or len(xC) < 2:
            continue

        t_stat, p_value = ttest_ind(xH, xC, equal_var=False)

        varH = np.var(xH, ddof=1)
        varC = np.var(xC, ddof=1)
        pooled_std = np.sqrt((varH + varC) / 2.0)

        if pooled_std == 0:
            continue

        d = (np.mean(xC) - np.mean(xH)) / pooled_std
        d_abs = abs(d)

        magnitude = 1 - np.exp(-d_abs)
        confidence = 1 - p_value
        score = magnitude * confidence

        scores.append(score)
        

    dataset_score = np.mean(scores) if scores else 0.0

    

    return dataset_score, welch_results


# ============================================================
# MAHALANOBIS BASELINE (from H)
# ============================================================

def mahalanobis_from_baseline(ref_df, cur_df, features, label=""):
    """
    Robust Mahalanobis distance calculation.
    Handles NaN, infinity, constant columns, and single-feature datasets.
    """

    # Keep only features available in both datasets
    valid_input_features = [
        col for col in features
        if col in ref_df.columns and col in cur_df.columns
    ]

    if not valid_input_features:
        print(f"[WARNING] {label}: No common features available.")
        return np.zeros(len(cur_df)), []

    # Convert values to numeric and replace infinite values with NaN
    ref = ref_df[valid_input_features].copy()
    cur = cur_df[valid_input_features].copy()

    for col in valid_input_features:
        ref[col] = pd.to_numeric(ref[col], errors="coerce")
        cur[col] = pd.to_numeric(cur[col], errors="coerce")

    ref = ref.replace([np.inf, -np.inf], np.nan)
    cur = cur.replace([np.inf, -np.inf], np.nan)

    # Use historical medians to fill missing values
    hist_median = ref.median().replace([np.inf, -np.inf], np.nan)
    hist_median = hist_median.fillna(0.0)

    ref = ref.fillna(hist_median)
    cur = cur.fillna(hist_median)

    # Convert to finite NumPy arrays
    X_hist_all = ref.to_numpy(dtype=float)
    X_cur_all = cur.to_numpy(dtype=float)

    X_hist_all = np.nan_to_num(
        X_hist_all, nan=0.0, posinf=0.0, neginf=0.0
    )
    X_cur_all = np.nan_to_num(
        X_cur_all, nan=0.0, posinf=0.0, neginf=0.0
    )

    # Remove constant or invalid historical features
    variances = np.var(X_hist_all, axis=0)
    valid_mask = np.isfinite(variances) & (variances > 1e-12)

    X_hist = X_hist_all[:, valid_mask]
    X_cur = X_cur_all[:, valid_mask]

    valid_features = [
        col for col, keep in zip(valid_input_features, valid_mask)
        if keep
    ]

    # If no varying features remain, report zero distance safely
    if len(valid_features) == 0:
        print(
            f"[WARNING] {label}: No varying historical features; "
            "returning zero Mahalanobis distances."
        )
        return np.zeros(len(cur_df)), []

    # Ensure covariance is always a 2D matrix, even for one feature
    cov = np.atleast_2d(np.cov(X_hist, rowvar=False))

    if not np.isfinite(cov).all():
        cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)

    # Regularize the covariance matrix for numerical stability
    cov = cov + 1e-6 * np.eye(len(valid_features))

    inv_cov = np.linalg.pinv(cov)

    # Calculate distances from the historical baseline mean
    hist_mean = np.mean(X_hist, axis=0)
    diff = X_cur - hist_mean

    squared_distances = np.sum((diff @ inv_cov) * diff, axis=1)
    mahal = np.sqrt(np.maximum(squared_distances, 0.0))

    # Ensure no invalid values reach later drift calculations
    mahal = np.nan_to_num(
        mahal, nan=0.0, posinf=0.0, neginf=0.0
    )

    print(
        f"[OK] {label}: Mahalanobis calculation completed "
        f"using {len(valid_features)} features."
    )

    return mahal, valid_features



# ============================================================
# DRIFT HEALTH FOR DATASET VS BASELINE
# ============================================================
def compute_drift_health(ref_df, cur_df, features, label="", weight_mahal=WEIGHT_MAHAL_DRIFT, psi_health_input=None):
    # --- Mahalanobis ---
    mahal_raw, valid_features = mahalanobis_from_baseline(
        ref_df, cur_df, features, label
    )

    scaler = MinMaxScaler()
    mahal_norm = scaler.fit_transform(mahal_raw.reshape(-1, 1)).flatten()

    print(f"Normalized Mahalanobis mean ({label}): {mahal_norm.mean():.4f}")

    # --- Welch ---
    welch_sev, welch_results = welch_drift_severity(
        ref_df, cur_df, valid_features, label
    )

    # --- PSI ---
    psi_h = psi_health_input if psi_health_input is not None else 1.0

    # --- combine ---
    mahal_health = (1 - mahal_norm)
    welch_health = (1 - welch_sev)
    psi_health   = psi_h

    drift_health = (
        WEIGHT_MAHAL * mahal_health +
        WEIGHT_WELCH * welch_health +
        WEIGHT_PSI   * psi_health
    )
    mahal_trend = weight_mahal * (1 - mahal_norm) + (1 - weight_mahal) * (1 - welch_sev)
    drift_health = (1 - WEIGHT_PSI) * mahal_trend + WEIGHT_PSI * psi_h

    print(f"\n[Combined Drift] {label}")
    print("-" * 60)
    print(f"Mean Mahalanobis stability: {(1-mahal_norm).mean():.4f}")
    print(f"Welch stability: {(1-welch_sev):.4f}")
    print(f"PSI health: {psi_h:.4f}")
    print(f"Final drift health mean: {drift_health.mean():.4f}")
    print("=" * 60)

    return drift_health, mahal_raw, mahal_norm, welch_sev, welch_results


# ============================================================
# APPLY DRIFT: B vs (H+A) BASELINE ONLY
# ============================================================
H_data = datasets["H"]
A_data = datasets["A"].copy()
B_data = datasets["B"].copy()

# --- Create combined H+A baseline ---
HA_data = pd.concat([H_data, A_data], ignore_index=True)

# --- B vs (H+A) ---
B_health, B_mahal_raw, B_mahal_norm, B_welch, B_welch_results = compute_drift_health(
    HA_data, B_data, feature_cols, label="B vs (H+A)",
    weight_mahal=WEIGHT_MAHAL_DRIFT,
    psi_health_input=psi_health
)

# Store drift for B only (current month)
B_data["drift_health"] = B_health
B_data["drift_raw_B"] = B_mahal_raw
B_data["drift_score_B"] = B_mahal_norm
B_data["drift_health_B"] = B_health

# Default drift = 1.0 (no drift) for H and A
H_data["drift_health"] = 1.0
H_data["drift_raw_H"] = np.zeros(len(H_data))
H_data["drift_score_H"] = np.zeros(len(H_data))
H_data["drift_health_H"] = np.ones(len(H_data))

A_data["drift_health"] = 1.0
A_data["drift_raw_A"] = np.zeros(len(A_data))
A_data["drift_score_A"] = np.zeros(len(A_data))
A_data["drift_health_A"] = np.ones(len(A_data))

# Update datasets with drift columns
datasets["H"] = H_data
datasets["A"] = A_data
datasets["B"] = B_data

print(" Drift health computed (B vs H+A only)\n")

# ============================================================
# 🎯 CALCULATE OVERALL_DATASET_TRUST FOR ALL RECORDS
# ============================================================
for label, data in datasets.items():
    if len(data) == 0:
        continue
    
    # Ensure all required health columns exist
    if "anomaly_health" not in data.columns:
        data["anomaly_health"] = 1.0
    if "drift_health" not in data.columns:
        data["drift_health"] = 1.0
    if "business_health" not in data.columns:
        data["business_health"] = 1.0
    
    # Calculate overall trust using weighted formula
    data["overall_dataset_trust"] = (
        WEIGHT_ANOMALY_HEALTH * data["anomaly_health"] +
        WEIGHT_DRIFT_HEALTH * data["drift_health"] +
        WEIGHT_BUSINESS_HEALTH * data["business_health"]
    ).clip(0, 1)
    
    datasets[label] = data
    
    trust_mean = data["overall_dataset_trust"].mean()
    trust_nan = data["overall_dataset_trust"].isna().sum()
print(" overall_dataset_trust calculated for all records\n")

# Attach drift columns by record_id. Assignment replaces any stale drift
# columns already present in the input, and avoids merge suffix collisions.
for drift_data, drift_cols in [
    (B_data, ["drift_raw_B", "drift_score_B", "drift_health_B"]),
    (A_data, ["drift_raw_A", "drift_score_A", "drift_health_A"]),
    (H_data, ["drift_raw_H", "drift_score_H", "drift_health_H"]),
]:
    drift_lookup = drift_data.set_index("record_id")[drift_cols]
    for col in drift_cols:
        df[col] = df["record_id"].map(drift_lookup[col])

# ============================================================
# 🎯 UNIFIED OVERALL RISK MODEL (ENSEMBLE)
# ============================================================


scores = {}
datasets_final = {}

for label in ["H", "A", "B"]:
    df_final = datasets[label].copy()
    
    # record_id is already in the data as data.index or was added earlier
    # 1. Business Risk (from rule_violations)
    # rule_violations was already calculated for current_mask (B) 
    # but we should ensure it's available for all or 0 if not applicable.
    # The original script had a complex way of merging it back.
    # Let's just use what's in 'df' if needed, or ensure it's in df_final.
    
    # In earlier sections, df["business_health"] was calculated for CURRENT ONLY.
    # But for final output, we want these flags for all.
    
    # Let's ensure rule_violations and business_health are in df_final
    if "rule_violations" not in df_final.columns:
        # If not there, it means it wasn't calculated for this lineage (H or A)
        # However, the user might want it. For now, let's fill with 0 if missing.
        df_final["rule_violations"] = 0
    
    if "business_health" not in df_final.columns:
        df_final["business_health"] = 1.0

    df_final["business_risk"] = (df_final["rule_violations"] / 5).clip(0, 1)

    # 2. Drift is used ONLY for reporting (not in anomaly risk)
    # Drift comes directly from datasets (already computed)
    if "drift_health" not in df_final.columns:
        df_final["drift_health"] = 1.0

    # 3. Overall Unified Risk Calculation (anomalies ONLY, drift is separate metric)
    df_final["overall_anomaly_risk"] = (
          W_ISO       * df_final["iso_flag"]
        + W_IQR       * df_final["iqr_flag"]
        + W_MISSING   * df_final["missing_flag"]
        + W_DUPLICATE * df_final["duplicate_flag"]
        + W_KNN       * df_final["knn_flag"]
        + W_BUSINESS  * df_final["business_risk"]
    )
    
    df_final["anomaly_health"] = 1 - df_final["overall_anomaly_risk"]

    # Store dataset mean
    scores[label] = df_final["overall_anomaly_risk"].mean()

    print(f"{label} - Mean Anomaly Health: {df_final['anomaly_health'].mean():.4f}")

    # Save for later
    datasets_final[label] = df_final

# =========================================================
# OVERALL ANOMALY HEALTH (AFTER LOOP)
# =========================================================

overall_anomaly_health = 0.0
overall_anomaly_count = 0
for l in ["H", "A", "B"]:
    ds = datasets_final.get(l, pd.DataFrame(columns=["anomaly_health"]))
    overall_anomaly_health += ds["anomaly_health"].sum()
    overall_anomaly_count += len(ds)

if overall_anomaly_count > 0:
    overall_anomaly_health = overall_anomaly_health / overall_anomaly_count
else:
    overall_anomaly_health = 1.0

print(f"\nOverall Anomaly Health (Weighted H+A+B): {overall_anomaly_health:.4f}")
# --------------------------------------------------------
# Rename/Prepare columns for final output
# --------------------------------------------------------
# Store this df_final in a dict for later use
# (Already stored in loop above)

# Attach diagnostics by record_id. Assignment overwrites any prior run's
# lineage-specific diagnostics and avoids duplicate merge suffixes.
for label in ["H", "A", "B"]:
    df_final = datasets_final.get(label, pd.DataFrame())
    if df_final.empty:
        continue

    label_cols = ["iso_flag", "iqr_flag", "knn_flag", "duplicate_flag", "missing_flag", 
                  "overall_anomaly_risk", "anomaly_health", "drift_health"]

    final_lookup = df_final.set_index("record_id")[label_cols]
    for col in label_cols:
        df[f"{col}_{label}"] = df["record_id"].map(final_lookup[col])
# ------------------------------------------------------------
# 📊 CURRENT MONTH DATA HEALTH (FINAL KPI)
# ------------------------------------------------------------

# ============================================================
# SUMMARY
# ============================================================


# ✅ Ensure all drift_health columns exist
for col in ["drift_health_H", "drift_health_A", "drift_health_B"]:
    if col not in df.columns:
        df[col] = np.nan

# ✅ Fill missing H values (where merge didn't find matches)
df.loc[(df["data_lineage"] == "HISTORICAL") & (df["drift_health_H"].isna()), "drift_health_H"] = 1.0

# Calculate overall_dataset_trust directly per record
df["overall_dataset_trust"] = np.nan

# Historical (Lineage H)
df.loc[df["data_lineage"] == "HISTORICAL", "overall_dataset_trust"] = (
    WEIGHT_ANOMALY_HEALTH * df.loc[df["data_lineage"] == "HISTORICAL", "anomaly_health_H"] +
    WEIGHT_DRIFT_HEALTH   * df.loc[df["data_lineage"] == "HISTORICAL", "drift_health_H"] +
    WEIGHT_BUSINESS_HEALTH * df.loc[df["data_lineage"] == "HISTORICAL", "business_health"]
)

# Previous Month (Lineage A)
df.loc[df["data_lineage"] == "PREVIOUS_MONTH", "overall_dataset_trust"] = (
    WEIGHT_ANOMALY_HEALTH * df.loc[df["data_lineage"] == "PREVIOUS_MONTH", "anomaly_health_A"] +
    WEIGHT_DRIFT_HEALTH   * df.loc[df["data_lineage"] == "PREVIOUS_MONTH", "drift_health_A"] +
    WEIGHT_BUSINESS_HEALTH * df.loc[df["data_lineage"] == "PREVIOUS_MONTH", "business_health"]
)

# Current Month (Lineage B)
df.loc[df["data_lineage"] == "CURRENT_MONTH", "overall_dataset_trust"] = (
    WEIGHT_ANOMALY_HEALTH * df.loc[df["data_lineage"] == "CURRENT_MONTH", "anomaly_health_B"] +
    WEIGHT_DRIFT_HEALTH   * df.loc[df["data_lineage"] == "CURRENT_MONTH", "drift_health_B"] +
    WEIGHT_BUSINESS_HEALTH * df.loc[df["data_lineage"] == "CURRENT_MONTH", "business_health"]
)

# Calculate global summary statistics (for reporting)
print("\n=== GLOBAL DATASET TRUST SUMMARY ===")

# Overall statistics across all datasets
overall_trust_mean = df["overall_dataset_trust"].mean()
overall_anomaly = 1 - (np.mean(list(scores.values())) if scores else 0.0)
overall_drift_health = B_data["drift_health"].mean() if len(B_data) > 0 else 1.0  # B vs (H+A) only
overall_business = df["business_health"].mean()

print(f"Final Business Health: {overall_business:.4f}")
print(f"Final Anomaly Health: {overall_anomaly:.4f}")
print(f"Final Drift Health (B vs H+A): {overall_drift_health:.4f}")
print(f"Overall Trust Score: {overall_trust_mean:.4f}")
print(f"Overall Trust Score (0-100): {overall_trust_mean * 100:.1f}")
print("=" * 80)

# Calculate per-lineage statistics for summary report
dataset_anomaly_health_H = 1 - scores.get("H", 0.0)
dataset_drift_health_H = 1.0  # H is baseline, no drift
dataset_business_health_H = df[df["data_lineage"] == "HISTORICAL"]["business_health"].mean() if len(df[df["data_lineage"] == "HISTORICAL"]) > 0 else 1.0

dataset_anomaly_health_A = 1 - scores.get("A", 0.0)
dataset_drift_health_A = 1.0  # A is part of baseline (H+A), no drift
dataset_business_health_A = df[df["data_lineage"] == "PREVIOUS_MONTH"]["business_health"].mean() if len(df[df["data_lineage"] == "PREVIOUS_MONTH"]) > 0 else 1.0

dataset_anomaly_health_B = 1 - scores.get("B", 0.0)
dataset_drift_health_B = B_data["drift_health"].mean() if len(B_data) > 0 else 1.0  # B vs (H+A)
dataset_business_health_B = df[df["data_lineage"] == "CURRENT_MONTH"]["business_health"].mean() if len(df[df["data_lineage"] == "CURRENT_MONTH"]) > 0 else 1.0

# ------------------------------------------------------------
# Calculate per-lineage trust scores
dataset_trust_H_scalar = (
    WEIGHT_ANOMALY_HEALTH * dataset_anomaly_health_H +
    WEIGHT_DRIFT_HEALTH * dataset_drift_health_H +
    WEIGHT_BUSINESS_HEALTH * dataset_business_health_H
)

dataset_trust_A_scalar = (
    WEIGHT_ANOMALY_HEALTH * dataset_anomaly_health_A +
    WEIGHT_DRIFT_HEALTH * dataset_drift_health_A +
    WEIGHT_BUSINESS_HEALTH * dataset_business_health_A
)

dataset_trust_B_scalar = (
    WEIGHT_ANOMALY_HEALTH * dataset_anomaly_health_B +
    WEIGHT_DRIFT_HEALTH * dataset_drift_health_B +
    WEIGHT_BUSINESS_HEALTH * dataset_business_health_B
)

overall_trust_scalar = (
    WEIGHT_ANOMALY_HEALTH * overall_anomaly +
    WEIGHT_DRIFT_HEALTH * overall_drift_health +
    WEIGHT_BUSINESS_HEALTH * overall_business
)

# SAVE — OVERALL TRUST SCORE SUMMARY (per lineage + overall)
# ---------------------------------------------------------------
trust_summary = pd.DataFrame([
    {
        "pipeline_stage":       "Cleaned",
        "data_lineage":         "HISTORICAL",
        "anomaly_health":       dataset_anomaly_health_H,
        "drift_health":         dataset_drift_health_H,
        "business_health":      dataset_business_health_H,
        "overall_dataset_trust": dataset_trust_H_scalar,
    },
    {
        "pipeline_stage":       "Cleaned",
        "data_lineage":         "PREVIOUS_MONTH",
        "anomaly_health":       dataset_anomaly_health_A,
        "drift_health":         dataset_drift_health_A,
        "business_health":      dataset_business_health_A,
        "overall_dataset_trust": dataset_trust_A_scalar,
    },
    {
        "pipeline_stage":       "Cleaned",
        "data_lineage":         "CURRENT_MONTH",
        "anomaly_health":       dataset_anomaly_health_B,
        "drift_health":         dataset_drift_health_B,
        "business_health":      dataset_business_health_B,
        "overall_dataset_trust": dataset_trust_B_scalar,
    },
])

TRUST_SUMMARY_FILE = os.path.join(OUTPUT_DIR, "overall_trust_score_entire_data_Cleaned.csv")
trust_summary.to_csv(TRUST_SUMMARY_FILE, index=False)
upload_to_bq(trust_summary, 'migration_overall_trust_cleaned_v2')

# ------------------------------------------------------------
# 🎯 FINAL OUTPUT SAVING (Refactored)
# ------------------------------------------------------------
print("\nSaving final consolidated H, A, B datasets...")

FINAL_COLUMNS = [
    "record_id", "businessID", "data_lineage",
    "iso_flag", "iqr_flag", "knn_flag", "duplicate_flag", "missing_flag",
    "psi_score", "mahalanobis_score", "welch_score",
    "anomaly_health", "drift_health", "business_health",
    "overall_anomaly_risk", "overall_dataset_trust"
]

# Map the lineage-specific columns in 'df' back to generic names for the final files
for label, folder in [("H", DIR_H), ("A", DIR_A), ("B", DIR_B)]:
    lineage_val = "HISTORICAL" if label == "H" else "PREVIOUS_MONTH" if label == "A" else "CURRENT_MONTH"
    lineage_df = df[df["data_lineage"] == lineage_val].copy()
    
    # Get the cleaned dataset version
    clean_data = datasets_final.get(label, pd.DataFrame())
    
    # Ensure optional score columns exist before merge (avoid KeyError)
    for optional_col in ["psi_score", "mahalanobis_score", "welch_score"]:
        if optional_col not in clean_data.columns:
            clean_data[optional_col] = np.nan

    if len(clean_data) > 0:
        # Merge drift metrics and trust scores from cleaned datasets
        lineage_df = lineage_df.merge(
            clean_data[["record_id", "drift_health", "overall_dataset_trust", "psi_score", "mahalanobis_score", "welch_score"]],
            on="record_id",
            how="left",
            suffixes=("", "_new")
        )
        
        # Use the new values where available
        if "drift_health_new" in lineage_df.columns:
            lineage_df.loc[lineage_df["drift_health_new"].notna(), "drift_health"] = lineage_df.loc[lineage_df["drift_health_new"].notna(), "drift_health_new"]
        if "overall_dataset_trust_new" in lineage_df.columns:
            lineage_df.loc[lineage_df["overall_dataset_trust_new"].notna(), "overall_dataset_trust"] = lineage_df.loc[lineage_df["overall_dataset_trust_new"].notna(), "overall_dataset_trust_new"]
    
    # Map the suffixed columns back to generic names
    if f"iso_flag_{label}" in lineage_df.columns:
        lineage_df["iso_flag"] = lineage_df[f"iso_flag_{label}"]
        lineage_df["iqr_flag"] = lineage_df[f"iqr_flag_{label}"]
        lineage_df["knn_flag"] = lineage_df[f"knn_flag_{label}"]
        lineage_df["duplicate_flag"] = lineage_df[f"duplicate_flag_{label}"]
        lineage_df["missing_flag"] = lineage_df[f"missing_flag_{label}"]
        lineage_df["anomaly_health"] = lineage_df[f"anomaly_health_{label}"]
        if "drift_health" not in lineage_df.columns or lineage_df["drift_health"].isna().all():
            lineage_df["drift_health"] = lineage_df[f"drift_health_{label}"]
        lineage_df["overall_anomaly_risk"] = lineage_df[f"overall_anomaly_risk_{label}"]
    
    # Ensure overall_dataset_trust exists and has no NaN
    if "overall_dataset_trust" not in lineage_df.columns or lineage_df["overall_dataset_trust"].isna().all():
        lineage_df["overall_dataset_trust"] = (
            WEIGHT_ANOMALY_HEALTH * lineage_df["anomaly_health"] +
            WEIGHT_DRIFT_HEALTH * lineage_df["drift_health"] +
            WEIGHT_BUSINESS_HEALTH * lineage_df["business_health"]
        ).clip(0, 1)
    
    # Fill any remaining NaN in overall_dataset_trust
    lineage_df.loc[lineage_df["overall_dataset_trust"].isna(), "overall_dataset_trust"] = (
        WEIGHT_ANOMALY_HEALTH * lineage_df.loc[lineage_df["overall_dataset_trust"].isna(), "anomaly_health"] +
        WEIGHT_DRIFT_HEALTH * lineage_df.loc[lineage_df["overall_dataset_trust"].isna(), "drift_health"] +
        WEIGHT_BUSINESS_HEALTH * lineage_df.loc[lineage_df["overall_dataset_trust"].isna(), "business_health"]
    ).clip(0, 1)
    
    # Filter to requested columns
    out_df = lineage_df[[c for c in FINAL_COLUMNS if c in lineage_df.columns]].copy()
    
    # Fill missing values with 0 where appropriate
    for c in ["iso_flag", "iqr_flag", "knn_flag", "duplicate_flag", "missing_flag"]:
        if c in out_df.columns:
            out_df[c] = out_df[c].fillna(0).astype(int)

    file_name = f"final_{label}_Cleaned.csv"
    path = os.path.join(folder, file_name)
    out_df.to_csv(path, index=False)
    upload_to_bq(out_df, f'migration_tenant_{label}_cleaned_v2')


# Save combined HAB dataset with trust scores
print("\n" + "="*80)
print("Saving combined HAB dataset with trust scores...")
print("="*80)

# Create unified columns from lineage-specific ones for the combined file
df_hab = df.copy()

# Create unified anomaly_health (merge the lineage-specific columns)
df_hab["anomaly_health"] = np.nan
if "anomaly_health_H" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "anomaly_health"] = df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "anomaly_health_H"]
if "anomaly_health_A" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "anomaly_health"] = df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "anomaly_health_A"]
if "anomaly_health_B" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "anomaly_health"] = df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "anomaly_health_B"]

# Create unified drift_health (merge the lineage-specific columns)
df_hab["drift_health"] = np.nan
if "drift_health_H" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "drift_health"] = df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "drift_health_H"]
if "drift_health_A" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "drift_health"] = df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "drift_health_A"]
if "drift_health_B" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "drift_health"] = df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "drift_health_B"]

# Fill any remaining NaN drift_health with anomaly_health
if "anomaly_health" in df_hab.columns:
    df_hab.loc[df_hab["drift_health"].isna(), "drift_health"] = df_hab.loc[df_hab["drift_health"].isna(), "anomaly_health"]

# Create unified overall_dataset_trust (ensures all records have it)
df_hab["overall_dataset_trust"] = (
    WEIGHT_ANOMALY_HEALTH * df_hab["anomaly_health"] +
    WEIGHT_DRIFT_HEALTH * df_hab["drift_health"] +
    WEIGHT_BUSINESS_HEALTH * df_hab["business_health"]
).clip(0, 1)

# Create unified overall_anomaly_risk
df_hab["overall_anomaly_risk"] = np.nan
if "overall_anomaly_risk_H" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "overall_anomaly_risk"] = df_hab.loc[df_hab["data_lineage"] == "HISTORICAL", "overall_anomaly_risk_H"]
if "overall_anomaly_risk_A" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "overall_anomaly_risk"] = df_hab.loc[df_hab["data_lineage"] == "PREVIOUS_MONTH", "overall_anomaly_risk_A"]
if "overall_anomaly_risk_B" in df_hab.columns:
    df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "overall_anomaly_risk"] = df_hab.loc[df_hab["data_lineage"] == "CURRENT_MONTH", "overall_anomaly_risk_B"]

hab_output_cols = [c for c in FINAL_COLUMNS if c in df_hab.columns]
hab_df = df_hab[hab_output_cols].copy()

# Fill missing values where appropriate
for c in ["iso_flag", "iqr_flag", "knn_flag", "duplicate_flag", "missing_flag"]:
    if c in hab_df.columns:
        hab_df[c] = hab_df[c].fillna(0).astype(int)

hab_path = os.path.join(OUTPUT_DIR, "hab_with_trust_Cleaned.csv")
hab_df.to_csv(hab_path, index=False)
upload_to_bq(hab_df, 'migration_hab_cleaned_v2')
