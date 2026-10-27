# Oracle conversion: original script retained; dataframe persistence redirected to Oracle.
"""
Large-Scale Synthetic Credit Bureau Data Generator
Generates Jan-Aug datasets with:
  - Jan: 60k rows, 50 columns (baseline)
  - Each month: +5k-10k new businesses, +1-2 new features
  - Persistent business data (carried forward with variations/anomalies)
  - Progressive anomaly injection (Jan stable → Aug chaotic)
"""

import pandas as pd
from oracle_compat import install, read_frame, write_frame
install()
import numpy as np
from datetime import datetime, timedelta
import os

# Keep global seed deterministic for reproducibility of non-anomaly parts,
# but use a separate RNG for anomaly intensities so they vary each run.
np.random.seed(42)
intensity_rng = np.random.default_rng()

# ============================================================================
# CONFIGURATION
# ============================================================================

# JAN base rows and monthly new-business counts are randomized at runtime
def get_runtime_counts():
    """Return (jan_base_rows, monthly_new_counts, months_data).

    - `jan_base_rows` is randomized between 50k and 70k.
    - `monthly_new_counts` is a dict mapping each month to a randomized
      new-business count (8k-10k), so each month can have a different value.
    Uses a fresh non-deterministic RNG so values vary across runs.
    """
    rng = np.random.default_rng()
    jan_base_rows = int(rng.integers(500, 701))
    months = ['february', 'march', 'april', 'may', 'june', 'july', 'august']
    monthly_new_counts = {m: int(rng.integers(80, 100)) for m in months}
    months_data = {
        'january': {'month_idx': 0, 'base_rows': jan_base_rows},
        'february': {'month_idx': 1},
        'march': {'month_idx': 2},
        'april': {'month_idx': 3},
        'may': {'month_idx': 4},
        'june': {'month_idx': 5},
        'july': {'month_idx': 6},
        'august': {'month_idx': 7}
    }
    return jan_base_rows, monthly_new_counts, months_data

BUSINESS_ID_PREFIX = "BIZ"

# ============================================================================
# BASE BUSINESS DATA
# ============================================================================

def generate_base_businesses(num_rows=None, seed_offset=0):
    """Generate baseline business data with 50 initial columns.

    If `num_rows` is None, default to 60000 to preserve previous behavior.
    """
    if num_rows is None:
        num_rows = 60000
    
    industries = ['Retail', 'Manufacturing', 'Technology', 'Healthcare', 'Finance', 
                  'Logistics', 'Real Estate', 'Consulting', 'Energy', 'Hospitality',
                  'Education', 'Entertainment', 'Agriculture', 'Construction', 'Telecom']
    
    legal_structures = ['LLC', 'C-Corp', 'S-Corp', 'Partnership', 'Sole Proprietor', 'Non-Profit']
    
    states = ['CA', 'NY', 'TX', 'FL', 'IL', 'PA', 'OH', 'GA', 'NC', 'MI', 'NJ', 'VA', 
              'WA', 'AZ', 'MA', 'TN', 'MO', 'MD', 'WI', 'CO']
    
    cities = [f'City_{i}' for i in range(500)]
    
    # Generate more realistic business names using prefix/suffix pools
    name_prefixes = [
        'Acme', 'Pioneer', 'Summit', 'Apex', 'BlueLake', 'Silverline', 'Greenfield', 'Quantum',
        'Brighton', 'Everest', 'Crescent', 'Harbor', 'Atlas', 'Nimbus', 'Vertex', 'Ironwood',
        'Walnut', 'Sterling', 'Omega', 'Nova', 'Suncrest', 'Riverside', 'Maple', 'NorthPoint',
        'Clearview', 'Horizon', 'Redwood', 'Lakeside', 'Benchmark', 'Catalyst'
    ]
    name_suffixes = ['LLC', 'Inc', 'Group', 'Solutions', 'Systems', 'Partners', 'Holdings', 'Technologies', 'Enterprises', 'Services']

    print(f"Generating {num_rows} base businesses...")
    
    # Segment distribution: 60% SME, 25% CORPORATE, 15% MICRO
    segments = np.random.choice(['SME', 'CORPORATE', 'MICRO'], size=num_rows, p=[0.6, 0.25, 0.15])
    
    data = {
        'businessID': [f"{BUSINESS_ID_PREFIX}{i+1+seed_offset:08d}" for i in range(num_rows)],
        'segment': segments,
        'businessName': [f"{np.random.choice(name_prefixes)} {np.random.choice(name_suffixes)} {i+1+seed_offset}" for i in range(num_rows)],
        'industry': np.random.choice(industries, num_rows),
        'legalStructure': np.random.choice(legal_structures, num_rows),
        'yearEstablished': np.random.randint(1990, 2024, num_rows),
        'registeredAddress_Street': [f"{np.random.randint(1, 99999)} Business St" for _ in range(num_rows)],
        'registeredAddress_City': np.random.choice(cities, num_rows),
        'registeredAddress_State': np.random.choice(states, num_rows),
        'registeredAddress_ZipCode': [f"{np.random.randint(10000, 99999)}" for _ in range(num_rows)],
        'contactPerson_Name': [f"Contact_{i+1+seed_offset}" for i in range(num_rows)],
        'contactPerson_Title': np.random.choice(['CEO', 'CFO', 'COO', 'Manager', 'Owner', 'Director'], num_rows),
        'contactPerson_Email': [f"contact_{i+1+seed_offset}@business.com" for i in range(num_rows)],
        'phoneNumber': [f"{np.random.randint(200, 999)}-{np.random.randint(200, 999)}-{np.random.randint(1000, 9999)}" for _ in range(num_rows)],
        'website': [f"www.business{i+1+seed_offset}.com" for i in range(num_rows)],
        'employeeCount': np.random.choice([1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 5000], num_rows),
        'annualRevenue': np.random.lognormal(mean=10, sigma=2, size=num_rows),
        'creditScore': np.random.uniform(550, 800, num_rows),
        'outstandingDebt': np.random.exponential(scale=100000, size=num_rows),
        'totalCreditLimit': np.random.lognormal(mean=11, sigma=2, size=num_rows),
        'availableCredit': np.random.lognormal(mean=10.5, sigma=2, size=num_rows),
        'paymentHistoryScore': np.random.uniform(50, 100, num_rows),
        'creditUtilizationRatio': np.random.uniform(10, 95, num_rows),
        'averageAccountAge': np.random.exponential(scale=8, size=num_rows),
        'numberOfAccounts': np.random.randint(1, 30, num_rows),
        'numberOfInquiries': np.random.poisson(lam=3, size=num_rows),
        'hasDelinquency': np.random.binomial(1, 0.1, num_rows),
        'hasDefaulted': np.random.binomial(1, 0.02, num_rows),
        'hasBankruptcy': np.random.binomial(1, 0.01, num_rows),
        'delinquentAccountCount': np.random.poisson(lam=1, size=num_rows),
        'sixtyDayDelinquent': np.random.binomial(1, 0.05, num_rows),
        'ninetyDayDelinquent': np.random.binomial(1, 0.02, num_rows),
        'oneHundredTwentyDayDelinquent': np.random.binomial(1, 0.01, num_rows),
        'accountStatus_Active': np.random.binomial(1, 0.85, num_rows),
        'accountStatus_Closed': np.random.binomial(1, 0.10, num_rows),
        'accountStatus_Dormant': np.random.binomial(1, 0.05, num_rows),
        'collectionsCount': np.random.poisson(lam=0.5, size=num_rows),
        'chargeoffCount': np.random.poisson(lam=0.2, size=num_rows),
        'judgmentCount': np.random.poisson(lam=0.1, size=num_rows),
        'taxLienCount': np.random.poisson(lam=0.05, size=num_rows),
        'publicRecordCount': np.random.poisson(lam=0.3, size=num_rows),
        'monthsSinceLastPayment': np.random.exponential(scale=3, size=num_rows),
        'monthsSinceFirstAccount': np.random.exponential(scale=100, size=num_rows),
        'monthsSinceLastDelinquency': np.random.exponential(scale=24, size=num_rows),
        'lastPaymentAmount': np.random.lognormal(mean=9, sigma=2, size=num_rows),
        'highestCreditAmountEver': np.random.lognormal(mean=11.5, sigma=2, size=num_rows),
        'totalAccountBalance': np.random.lognormal(mean=10.5, sigma=2, size=num_rows),
        'totalMonthlyPayment': np.random.lognormal(mean=8, sigma=2, size=num_rows),
        'debtToIncomeRatio': np.random.uniform(0, 1, num_rows),
        'creditWorthinessScore': np.random.uniform(200, 850, num_rows),
        'riskProfile': np.random.choice(['Low', 'Medium', 'High', 'Very_High'], num_rows),
    }
    
    return pd.DataFrame(data)

# ============================================================================
# REGIME EVENTS (EVENT-DRIVEN ANOMALIES, NOT MONOTONIC RAMP)
# ============================================================================

REGIME_EVENTS = {
    'january': [],  # Baseline clean
    'february': [],  # Still clean
    'march': [
        # March: SME delinquency spike (supply chain stress)
        {'segment': 'SME', 'feature': 'delinquentAccountCount', 'add': 3}
    ],
    'april': [
        # April: sector-wide credit utilization jump
        {'segment': 'CORPORATE', 'feature': 'creditUtilizationRatio', 'mult': 1.25}
    ],
    'may': [
        # May: MICRO credit score degradation
        {'segment': 'MICRO', 'feature': 'creditScore', 'add': -50}
    ],
    'june': [
        # June: Widespread debt increase across all segments
        {'segment': None, 'feature': 'outstandingDebt', 'mult': 1.35}
    ],
    'july': [
        # July: SME bankruptcy/default risk spiking
        {'segment': 'SME', 'feature': 'hasDefaulted', 'set': 1},
        # SME also sees payment delays
        {'segment': 'SME', 'feature': 'monthsSinceLastPayment', 'mult': 2.0}
    ],
    'august': [
        # August: system-wide chaos - all segments degraded
        {'segment': None, 'feature': 'creditScore', 'add': -80},
        {'segment': None, 'feature': 'hasDelinquency', 'set': 1},
        {'segment': 'SME', 'feature': 'publicRecordCount', 'add': 2}
    ]
}

def apply_regime_event(df, month_name):
    """Apply event-driven anomalies for the given month."""
    df = df.copy()
    events = REGIME_EVENTS.get(month_name, [])
    
    for event in events:
        segment = event.get('segment')
        feature = event.get('feature')
        
        # Apply to this segment only (or all if segment is None)
        if segment is None:
            mask = pd.Series([True] * len(df), index=df.index)
        else:
            mask = df['segment'] == segment
        
        if feature not in df.columns:
            continue
        
        # Apply transformation with randomized intensity per run
        if 'add' in event:
            # scale additive effects randomly each run (preserve sign)
            base = event['add']
            scale = intensity_rng.uniform(0.7, 1.4)
            add_val = int(np.sign(base) * max(1, abs(int(base * scale))))
            df.loc[mask, feature] = df.loc[mask, feature] + add_val
        elif 'mult' in event:
            # scale multiplicative effects randomly each run
            base = event['mult']
            mult_val = base * float(intensity_rng.uniform(0.8, 1.3))
            df.loc[mask, feature] = df.loc[mask, feature] * mult_val
        elif 'set' in event:
            # Only set a fraction to create realism
            num_affected = max(1, int(mask.sum() * float(intensity_rng.uniform(0.05, 0.2))))
            if num_affected > 0:
                affected_idx = np.random.choice(df[mask].index, size=num_affected, replace=False)
                df.loc[affected_idx, feature] = event['set']
    
    # Add minor natural noise everywhere (baseline variability)
    for col in df.select_dtypes(include=['float64']).columns:
        if col not in ['businessID']:
            df[col] = df[col] + np.random.normal(0, df[col].std() * 0.02, len(df))
    
    # Clip creditScore to valid range
    if 'creditScore' in df.columns:
        df['creditScore'] = df['creditScore'].clip(300, 850)
    
    return df

def inject_january_anomalies(df):
    """Jan baseline: minimal anomalies, natural noise only."""
    return apply_regime_event(df, 'january')

def inject_february_anomalies(df):
    """Feb: regime events."""
    return apply_regime_event(df, 'february')

def inject_march_anomalies(df):
    """Mar: regime events."""
    return apply_regime_event(df, 'march')

def inject_april_anomalies(df):
    """Apr: regime events."""
    return apply_regime_event(df, 'april')

def inject_may_anomalies(df):
    """May: regime events."""
    return apply_regime_event(df, 'may')

def inject_june_anomalies(df):
    """Jun: regime events."""
    return apply_regime_event(df, 'june')

def inject_july_anomalies(df):
    """Jul: regime events."""
    return apply_regime_event(df, 'july')

def inject_august_anomalies(df):
    """Aug: regime events."""
    return apply_regime_event(df, 'august')

# ============================================================================
# NEW COLUMNS FOR CURRENT MONTHS (Jun, Jul, Aug)
# ============================================================================

def add_new_columns_june(df):
    """Add 3 new columns for June (25 total)."""
    df['auditScore'] = np.random.uniform(0, 100, len(df))
    df['riskRating'] = np.random.choice(['Low', 'Medium', 'High', 'Critical'], len(df))
    df['lastAuditDate'] = pd.date_range('2025-01-01', periods=len(df), freq='h')
    return df

def add_new_columns_july(df):
    """Add 2 more columns for July (27 total)."""
    df = add_new_columns_june(df)
    df['complianceFlag'] = np.random.binomial(1, 0.15, len(df))
    df['regulatoryStatus'] = np.random.choice(['Compliant', 'Non-Compliant', 'Pending'], len(df))
    # Inject some invalid values
    invalid_idx = np.random.choice(df.index, size=max(1, int(len(df) * 0.05)), replace=False)
    for idx in invalid_idx:
        df.loc[idx, 'auditScore'] = np.random.choice([101, 500, -50])
    return df

def add_new_columns_august(df):
    """Add 2 more columns for August (29 total)."""
    df = add_new_columns_july(df)
    df['expectedDefaultRate'] = np.random.uniform(0, 1, len(df))
    df['systemHealthScore'] = np.random.uniform(0, 100, len(df))
    # Inject anomalies in new fields
    invalid_idx = np.random.choice(df.index, size=max(1, int(len(df) * 0.1)), replace=False)
    for idx in invalid_idx:
        df.loc[idx, 'systemHealthScore'] = np.random.choice([101, 500, -100, np.nan])
    return df

# ============================================================================
# MAIN GENERATION LOGIC
# ============================================================================

def generate_all_months():
    """Generate all monthly datasets with persistent and new businesses."""
    # Randomize dataset sizes for this run
    jan_base_rows, monthly_new_counts, MONTHS_DATA = get_runtime_counts()

    # Generate January (baseline)
    print("\n" + "="*80)
    print(f"GENERATING JANUARY (Baseline: {jan_base_rows} rows, ~50 columns)")
    print("="*80)
    df_january = generate_base_businesses(jan_base_rows)
    df_january = inject_january_anomalies(df_january)
    df_january = df_january[['businessID'] + [c for c in df_january.columns if c != 'businessID']]
    
    save_month_data(df_january, 'january')
    print(f"[OK] January: {len(df_january)} rows, {len(df_january.columns)} columns")
    
    
    # Store all businesses so far
    all_businesses = df_january[['businessID', 'businessName', 'industry', 'legalStructure', 
                                   'yearEstablished', 'registeredAddress_Street', 
                                   'registeredAddress_City', 'registeredAddress_State', 
                                   'registeredAddress_ZipCode', 'contactPerson_Name',
                                   'contactPerson_Title', 'contactPerson_Email', 'phoneNumber', 'website',
                                   'employeeCount']].copy()
    
    current_seed = jan_base_rows
    
    # Generate February onwards
    months_order = ['february', 'march', 'april', 'may', 'june', 'july', 'august']
    
    for idx, month_name in enumerate(months_order):
        print("\n" + "="*80)
        current_month_new = monthly_new_counts.get(month_name, 0)
        print(f"GENERATING {month_name.upper()} (Current: {len(all_businesses) + current_month_new} rows — adding {current_month_new} )")
        print("="*80)
        
        # Add new businesses (count varies per month)
        new_businesses = generate_base_businesses(current_month_new, seed_offset=current_seed)
        current_seed += current_month_new
        # --- Introduce missing values into a small fraction of new rows ---
        if len(new_businesses) > 0:
            # pick some columns to inject missingness (mix of numeric and categorical)
            candidate_cols = [c for c in new_businesses.columns if c not in ['businessID','businessName','segment']]
            missing_frac = float(intensity_rng.uniform(0.01, 0.05))  # 1% - 5% missing in selected cols
            n_missing_rows = max(1, int(len(new_businesses) * missing_frac))
            if candidate_cols and n_missing_rows > 0:
                cols_to_nan = intensity_rng.choice(candidate_cols, size=min(len(candidate_cols), max(1, int(len(candidate_cols)*0.2))), replace=False)
                for col in cols_to_nan:
                    idxs = intensity_rng.choice(new_businesses.index, size=n_missing_rows, replace=False)
                    new_businesses.loc[idxs, col] = np.nan

        # --- Occasionally append duplicates of existing records as anomaly noise ---
        duplicate_rate = float(intensity_rng.uniform(0.001, 0.02))  # 0.1% - 2% duplicates
        dup_count = int(len(new_businesses) * duplicate_rate)
        if dup_count > 0 and 'all_businesses' in locals() and len(all_businesses) > 0:
            dup_source = all_businesses.sample(n=min(dup_count, len(all_businesses)), random_state=None)
            # Ensure duplicated rows get new businessID collision to simulate true duplicates optionally
            dup_rows = dup_source.copy()
            # Keep businessID same to create true duplicate entries
            new_businesses = pd.concat([new_businesses, dup_rows], ignore_index=True)
        
        # Combine all businesses (old + new)
        all_businesses_month = pd.concat(
            [df_january if month_name == 'february' else all_businesses_df_previous, new_businesses],
            ignore_index=True
        )
        
        # For subsequent months, use previous month's data as starting point (entity trajectory persistence)
        if month_name == 'february':
            df_month = pd.concat([df_january, new_businesses], ignore_index=True)
        else:
            # Carry forward existing businesses with realistic trajectory updates
            df_existing = df_month[df_month['businessID'].isin(all_businesses['businessID'])].copy()
            
            # Apply realistic trajectory: entities maintain their characteristics but evolve
            # This creates longitudinal stability (credit bureau realism)
            for col in df_existing.select_dtypes(include=['float64']).columns:
                if col not in ['businessID', 'segment']:
                    # 95% momentum (carry forward with small variation) + 5% shock risk
                    momentum = np.random.uniform(0.95, 1.05, len(df_existing))
                    shock_mask = np.random.rand(len(df_existing)) < 0.05
                    
                    # Apply momentum to most rows
                    df_existing[col] = df_existing[col] * momentum
                    
                    # Apply shock to 5% (represents market events)
                    if shock_mask.sum() > 0:
                        df_existing.loc[shock_mask, col] = df_existing.loc[shock_mask, col] * np.random.uniform(0.7, 2.0, shock_mask.sum())

            # ----------------
            # Churn: businesses exit each month (random fraction)
            # ----------------
            churn_rate = float(intensity_rng.uniform(0.01, 0.06))  # 1% - 6% exit per month
            dropped_ids = []
            if churn_rate > 0 and len(df_existing) > 0:
                keep_frac = max(0.0, 1.0 - churn_rate)
                keep_count = max(1, int(len(df_existing) * keep_frac))
                kept = df_existing.sample(n=keep_count, random_state=None)
                # compute dropped ids for logging
                dropped_ids = list(set(df_existing['businessID'].astype(str)) - set(kept['businessID'].astype(str)))
                df_existing = kept.reset_index(drop=True)
                # save dropped ids to outputs for audit
                # out_dir = os.path.join(os.path.dirname(__file__),  'outputs')
                # os.makedirs(out_dir, exist_ok=True)
                # if dropped_ids:
                #     dropped_df = pd.DataFrame({'businessID': dropped_ids, 'month': month_name, 'reason': 'churn'})
                #     dropped_df.to_csv(os.path.join(out_dir, f'left_businesses_{month_name}.csv'), index=False)
            
            df_month = pd.concat([df_existing, new_businesses], ignore_index=True)
        
        # Apply month-specific anomalies
        if month_name == 'february':
            df_month = inject_february_anomalies(df_month)
        elif month_name == 'march':
            df_month = inject_march_anomalies(df_month)
        elif month_name == 'april':
            df_month = inject_april_anomalies(df_month)
            df_month = add_new_columns_june(df_month)
        elif month_name == 'may':
            df_month = inject_may_anomalies(df_month)
            df_month = add_new_columns_june(df_month)
        elif month_name == 'june':
            df_month = inject_june_anomalies(df_month)
            df_month = add_new_columns_june(df_month)
        elif month_name == 'july':
            df_month = inject_july_anomalies(df_month)
            df_month = add_new_columns_july(df_month)
        elif month_name == 'august':
            df_month = inject_august_anomalies(df_month)
            df_month = add_new_columns_august(df_month)
        
        # Reorder columns
        df_month = df_month[['businessID'] + [c for c in df_month.columns if c != 'businessID']]
        
        save_month_data(df_month, month_name)
        print(f"[OK] {month_name.title()}: {len(df_month)} rows, {len(df_month.columns)} columns")
        print(df_month.head())
        
        # Update tracking
        all_businesses = all_businesses_month.copy()
        all_businesses_df_previous = df_month.copy()
    
    print("\n" + "="*80)
    print("[OK] ALL DATASETS GENERATED SUCCESSFULLY!")
    print("="*80)
    print("\nGenerated all 8 months: January, February, March, April, May, June, July, August")

def save_month_data(df, month_name):
    """Store each generated month directly in Oracle."""
    filename = f"credit_bureau_data_{month_name}_.csv"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    write_frame(filepath, df)
    print(f"  Stored in Oracle stage: {filename}")

# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    from oracle_compat import begin_new_run
    begin_new_run()
    generate_all_months()
