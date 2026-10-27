"""
DeltaMax V5 - Synthetic Credit Bureau Data Generator (Oracle-only)

Flow:

    Python synthetic data generator
                ->
          Oracle Database
                ->
    DELTAMAX_V5.DM_V5_STG_CREDIT_BUREAU

Output: Oracle only. No CSV files. No S3 uploads.
"""

import sys
import math
import numpy as np
import pandas as pd
import oracledb


# ============================================================
# RANDOM SEEDS
# ============================================================

np.random.seed(42)
intensity_rng = np.random.default_rng()


# ============================================================
# CONFIGURATION
# ============================================================

# Oracle connection
ORACLE_USER = "DELTAMAX_V5"
ORACLE_PASSWORD = "DeltaMaxV5@2026"
ORACLE_DSN = "localhost:1521/FREEPDB1"
ORACLE_TABLE = "DM_V5_STG_CREDIT_BUREAU"


# IMPORTANT:
# True  = only January is loaded for testing
# False = January through December
RUN_JANUARY_ONLY = False


# Load behaviour
# Kept for compatibility/documentation.
# The actual ML lineage is assigned by month below.
DATA_LINEAGE = "SYNTHETIC"
REPLACE_EXISTING_BATCH = True


# ============================================================
# DATA LINEAGE MAPPING
# ============================================================

def get_data_lineage(month_num):
    """
    Map generated months to the lineage expected by
    03_Trust_Score.py.

    January through October = HISTORICAL
    November                = PREVIOUS_MONTH
    December                = CURRENT_MONTH
    """

    if 1 <= month_num <= 10:
        return "HISTORICAL"

    elif month_num == 11:
        return "PREVIOUS_MONTH"

    elif month_num == 12:
        return "CURRENT_MONTH"

    else:
        raise ValueError(
            f"Invalid month number: {month_num}"
        )


# ============================================================
# DATASET SIZE
# ============================================================

GENERATION_YEAR = 2026
JAN_BASE_ROWS = 500
MONTHLY_NEW_BUSINESSES = 50

BUSINESS_ID_PREFIX = "BIZ"


# ============================================================
# BASE BUSINESS DATA
# ============================================================

def generate_base_businesses(num_rows=None, seed_offset=0):

    if num_rows is None:
        num_rows = JAN_BASE_ROWS

    industries = [
        'Retail',
        'Manufacturing',
        'Technology',
        'Healthcare',
        'Finance',
        'Logistics',
        'Real Estate',
        'Consulting',
        'Energy',
        'Hospitality',
        'Education',
        'Entertainment',
        'Agriculture',
        'Construction',
        'Telecom'
    ]

    legal_structures = [
        'LLC',
        'C-Corp',
        'S-Corp',
        'Partnership',
        'Sole Proprietor',
        'Non-Profit'
    ]

    states = [
        'CA', 'NY', 'TX', 'FL', 'IL', 'PA', 'OH', 'GA', 'NC',
        'MI', 'NJ', 'VA', 'WA', 'AZ', 'MA', 'TN', 'MO', 'MD',
        'WI', 'CO'
    ]

    cities = [
        f'City_{i}'
        for i in range(500)
    ]

    name_prefixes = [
        'Acme',
        'Pioneer',
        'Summit',
        'Apex',
        'BlueLake',
        'Silverline',
        'Greenfield',
        'Quantum',
        'Brighton',
        'Everest',
        'Crescent',
        'Harbor',
        'Atlas',
        'Nimbus',
        'Vertex',
        'Ironwood',
        'Walnut',
        'Sterling',
        'Omega',
        'Nova',
        'Suncrest',
        'Riverside',
        'Maple',
        'NorthPoint',
        'Clearview',
        'Horizon',
        'Redwood',
        'Lakeside',
        'Benchmark',
        'Catalyst'
    ]

    name_suffixes = [
        'LLC',
        'Inc',
        'Group',
        'Solutions',
        'Systems',
        'Partners',
        'Holdings',
        'Technologies',
        'Enterprises',
        'Services'
    ]

    segments = np.random.choice(
        ['SME', 'CORPORATE', 'MICRO'],
        size=num_rows,
        p=[0.6, 0.25, 0.15]
    )

    data = {

        'businessID': [
            f"{BUSINESS_ID_PREFIX}{i + 1 + seed_offset:08d}"
            for i in range(num_rows)
        ],

        'segment': segments,

        'businessName': [
            f"{np.random.choice(name_prefixes)} "
            f"{np.random.choice(name_suffixes)} "
            f"{i + 1 + seed_offset}"
            for i in range(num_rows)
        ],

        'industry': np.random.choice(
            industries,
            num_rows
        ),

        'legalStructure': np.random.choice(
            legal_structures,
            num_rows
        ),

        'yearEstablished': np.random.randint(
            1990,
            2024,
            num_rows
        ),

        'registeredAddress_Street': [
            f"{np.random.randint(1, 99999)} Business St"
            for _ in range(num_rows)
        ],

        'registeredAddress_City': np.random.choice(
            cities,
            num_rows
        ),

        'registeredAddress_State': np.random.choice(
            states,
            num_rows
        ),

        'registeredAddress_ZipCode': [
            f"{np.random.randint(10000, 99999)}"
            for _ in range(num_rows)
        ],

        'contactPerson_Name': [
            f"Contact_{i + 1 + seed_offset}"
            for i in range(num_rows)
        ],

        'contactPerson_Title': np.random.choice(
            [
                'CEO',
                'CFO',
                'COO',
                'Manager',
                'Owner',
                'Director'
            ],
            num_rows
        ),

        'contactPerson_Email': [
            f"contact_{i + 1 + seed_offset}@business.com"
            for i in range(num_rows)
        ],

        'phoneNumber': [
            f"{np.random.randint(200, 999)}-"
            f"{np.random.randint(200, 999)}-"
            f"{np.random.randint(1000, 9999)}"
            for _ in range(num_rows)
        ],

        'website': [
            f"www.business{i + 1 + seed_offset}.com"
            for i in range(num_rows)
        ],

        'employeeCount': np.random.choice(
            [
                1,
                2,
                5,
                10,
                25,
                50,
                100,
                250,
                500,
                1000,
                5000
            ],
            num_rows
        ),

        'annualRevenue': np.random.lognormal(
            mean=10,
            sigma=2,
            size=num_rows
        ),

        'creditScore': np.random.uniform(
            550,
            800,
            num_rows
        ),

        'outstandingDebt': np.random.exponential(
            scale=100000,
            size=num_rows
        ),

        'totalCreditLimit': np.random.lognormal(
            mean=11,
            sigma=2,
            size=num_rows
        ),

        'availableCredit': np.random.lognormal(
            mean=10.5,
            sigma=2,
            size=num_rows
        ),

        'paymentHistoryScore': np.random.uniform(
            50,
            100,
            num_rows
        ),

        'creditUtilizationRatio': np.random.uniform(
            10,
            95,
            num_rows
        ),

        'averageAccountAge': np.random.exponential(
            scale=8,
            size=num_rows
        ),

        'numberOfAccounts': np.random.randint(
            1,
            30,
            num_rows
        ),

        'numberOfInquiries': np.random.poisson(
            lam=3,
            size=num_rows
        ),

        'hasDelinquency': np.random.binomial(
            1,
            0.1,
            num_rows
        ),

        'hasDefaulted': np.random.binomial(
            1,
            0.02,
            num_rows
        ),

        'hasBankruptcy': np.random.binomial(
            1,
            0.01,
            num_rows
        ),

        'delinquentAccountCount': np.random.poisson(
            lam=1,
            size=num_rows
        ),

        'sixtyDayDelinquent': np.random.binomial(
            1,
            0.05,
            num_rows
        ),

        'ninetyDayDelinquent': np.random.binomial(
            1,
            0.02,
            num_rows
        ),

        'oneHundredTwentyDayDelinquent': np.random.binomial(
            1,
            0.01,
            num_rows
        ),

        'accountStatus_Active': np.random.binomial(
            1,
            0.85,
            num_rows
        ),

        'accountStatus_Closed': np.random.binomial(
            1,
            0.10,
            num_rows
        ),

        'accountStatus_Dormant': np.random.binomial(
            1,
            0.05,
            num_rows
        ),

        'collectionsCount': np.random.poisson(
            lam=0.5,
            size=num_rows
        ),

        'chargeoffCount': np.random.poisson(
            lam=0.2,
            size=num_rows
        ),

        'judgmentCount': np.random.poisson(
            lam=0.1,
            size=num_rows
        ),

        'taxLienCount': np.random.poisson(
            lam=0.05,
            size=num_rows
        ),

        'publicRecordCount': np.random.poisson(
            lam=0.3,
            size=num_rows
        ),

        'monthsSinceLastPayment': np.random.exponential(
            scale=3,
            size=num_rows
        ),

        'monthsSinceFirstAccount': np.random.exponential(
            scale=100,
            size=num_rows
        ),

        'monthsSinceLastDelinquency': np.random.exponential(
            scale=24,
            size=num_rows
        ),

        'lastPaymentAmount': np.random.lognormal(
            mean=9,
            sigma=2,
            size=num_rows
        ),

        'highestCreditAmountEver': np.random.lognormal(
            mean=11.5,
            sigma=2,
            size=num_rows
        ),

        'totalAccountBalance': np.random.lognormal(
            mean=10.5,
            sigma=2,
            size=num_rows
        ),

        'totalMonthlyPayment': np.random.lognormal(
            mean=8,
            sigma=2,
            size=num_rows
        ),

        'debtToIncomeRatio': np.random.uniform(
            0,
            1,
            num_rows
        ),

        'creditWorthinessScore': np.random.uniform(
            200,
            850,
            num_rows
        ),

        'riskProfile': np.random.choice(
            [
                'Low',
                'Medium',
                'High',
                'Very_High'
            ],
            num_rows
        ),
    }

    return pd.DataFrame(data)


# ============================================================
# REGIME EVENTS
# ============================================================

REGIME_EVENTS = {

    'january': [],

    'february': [],

    'march': [
        {
            'segment': 'SME',
            'feature': 'delinquentAccountCount',
            'add': 3
        }
    ],

    'april': [
        {
            'segment': 'CORPORATE',
            'feature': 'creditUtilizationRatio',
            'mult': 1.25
        }
    ],

    'may': [
        {
            'segment': 'MICRO',
            'feature': 'creditScore',
            'add': -50
        }
    ],

    'june': [
        {
            'segment': None,
            'feature': 'outstandingDebt',
            'mult': 1.35
        }
    ],

    'july': [
        {
            'segment': 'SME',
            'feature': 'hasDefaulted',
            'set': 1
        },
        {
            'segment': 'SME',
            'feature': 'monthsSinceLastPayment',
            'mult': 2.0
        }
    ],

    'august': [
        {
            'segment': None,
            'feature': 'creditScore',
            'add': -80
        },
        {
            'segment': None,
            'feature': 'hasDelinquency',
            'set': 1
        },
        {
            'segment': 'SME',
            'feature': 'publicRecordCount',
            'add': 2
        }
    ],

    'september': [
        {
            'segment': 'CORPORATE',
            'feature': 'creditScore',
            'add': 30
        },
        {
            'segment': 'SME',
            'feature': 'creditUtilizationRatio',
            'mult': 0.95
        }
    ],

    'october': [
        {
            'segment': None,
            'feature': 'delinquentAccountCount',
            'mult': 0.8
        },
        {
            'segment': 'MICRO',
            'feature': 'creditScore',
            'add': 40
        }
    ],

    'november': [
        {
            'segment': None,
            'feature': 'monthsSinceLastPayment',
            'mult': 0.85
        },
        {
            'segment': None,
            'feature': 'hasDelinquency',
            'set': 0
        }
    ],

    'december': [
        {
            'segment': None,
            'feature': 'creditScore',
            'add': 20
        },
        {
            'segment': None,
            'feature': 'creditUtilizationRatio',
            'mult': 0.90
        }
    ]
}


def apply_regime_event(df, month_name):

    df = df.copy()

    events = REGIME_EVENTS.get(
        month_name,
        []
    )

    for event in events:

        segment = event.get('segment')
        feature = event.get('feature')

        if segment is None:

            mask = pd.Series(
                [True] * len(df),
                index=df.index
            )

        else:

            mask = (
                df['segment'] == segment
            )

        if feature not in df.columns:
            continue

        if 'add' in event:

            base = event['add']

            scale = intensity_rng.uniform(
                0.7,
                1.4
            )

            add_val = int(
                np.sign(base)
                * max(
                    1,
                    abs(
                        int(
                            base * scale
                        )
                    )
                )
            )

            df.loc[
                mask,
                feature
            ] = (
                df.loc[
                    mask,
                    feature
                ] + add_val
            )

        elif 'mult' in event:

            base = event['mult']

            mult_val = (
                base
                * float(
                    intensity_rng.uniform(
                        0.8,
                        1.3
                    )
                )
            )

            df.loc[
                mask,
                feature
            ] = (
                df.loc[
                    mask,
                    feature
                ] * mult_val
            )

        elif 'set' in event:

            num_affected = max(
                1,
                int(
                    mask.sum()
                    * float(
                        intensity_rng.uniform(
                            0.05,
                            0.2
                        )
                    )
                )
            )

            if num_affected > 0:

                affected_idx = np.random.choice(
                    df[mask].index,
                    size=num_affected,
                    replace=False
                )

                df.loc[
                    affected_idx,
                    feature
                ] = event['set']

    # Natural noise
    for col in df.select_dtypes(
        include=['float64']
    ).columns:

        if col not in ['businessID']:

            df[col] = (
                df[col]
                + np.random.normal(
                    0,
                    df[col].std() * 0.02,
                    len(df)
                )
            )

    # Credit score limits
    if 'creditScore' in df.columns:

        df['creditScore'] = df[
            'creditScore'
        ].clip(
            300,
            850
        )

    return df


def inject_january_anomalies(df):
    return apply_regime_event(
        df,
        'january'
    )


def inject_february_anomalies(df):
    return apply_regime_event(
        df,
        'february'
    )


def inject_march_anomalies(df):
    return apply_regime_event(
        df,
        'march'
    )


def inject_april_anomalies(df):
    return apply_regime_event(
        df,
        'april'
    )


def inject_may_anomalies(df):
    return apply_regime_event(
        df,
        'may'
    )


def inject_june_anomalies(df):
    return apply_regime_event(
        df,
        'june'
    )


def inject_july_anomalies(df):
    return apply_regime_event(
        df,
        'july'
    )


def inject_august_anomalies(df):
    return apply_regime_event(
        df,
        'august'
    )


def inject_september_anomalies(df):
    return apply_regime_event(
        df,
        'september'
    )


def inject_october_anomalies(df):
    return apply_regime_event(
        df,
        'october'
    )


def inject_november_anomalies(df):
    return apply_regime_event(
        df,
        'november'
    )


def inject_december_anomalies(df):
    return apply_regime_event(
        df,
        'december'
    )


# ============================================================
# LATER-MONTH COLUMNS
# ============================================================

def add_new_columns_june(df):

    df['auditScore'] = np.random.uniform(
        0,
        100,
        len(df)
    )

    df['riskRating'] = np.random.choice(
        [
            'Low',
            'Medium',
            'High',
            'Critical'
        ],
        len(df)
    )

    df['lastAuditDate'] = pd.date_range(
        '2025-01-01',
        periods=len(df),
        freq='h'
    )

    return df


def add_new_columns_july(df):

    df = add_new_columns_june(df)

    df['complianceFlag'] = np.random.binomial(
        1,
        0.15,
        len(df)
    )

    df['regulatoryStatus'] = np.random.choice(
        [
            'Compliant',
            'Non-Compliant',
            'Pending'
        ],
        len(df)
    )

    invalid_idx = np.random.choice(
        df.index,
        size=max(
            1,
            int(len(df) * 0.05)
        ),
        replace=False
    )

    for idx in invalid_idx:

        df.loc[
            idx,
            'auditScore'
        ] = np.random.choice(
            [
                101,
                500,
                -50
            ]
        )

    return df


def add_new_columns_august(df):

    df = add_new_columns_july(df)

    df['expectedDefaultRate'] = np.random.uniform(
        0,
        1,
        len(df)
    )

    df['systemHealthScore'] = np.random.uniform(
        0,
        100,
        len(df)
    )

    invalid_idx = np.random.choice(
        df.index,
        size=max(
            1,
            int(len(df) * 0.1)
        ),
        replace=False
    )

    for idx in invalid_idx:

        df.loc[
            idx,
            'systemHealthScore'
        ] = np.random.choice(
            [
                101,
                500,
                -100,
                np.nan
            ]
        )

    return df


def add_new_columns_september(df):

    df = add_new_columns_august(df)

    df['marketConditionIndex'] = np.random.uniform(
        0,
        100,
        len(df)
    )

    df['recoveryTrendScore'] = np.random.uniform(
        0,
        100,
        len(df)
    )

    return df


def add_new_columns_october(df):

    df = add_new_columns_september(df)

    df['sectorPerformance'] = np.random.choice(
        [
            'Strong',
            'Stable',
            'Weak'
        ],
        len(df)
    )

    df['creditQualityRating'] = np.random.choice(
        [
            'AAA',
            'AA',
            'A',
            'BBB',
            'BB'
        ],
        len(df)
    )

    return df


def add_new_columns_november(df):

    df = add_new_columns_october(df)

    df['yearEndProjectedDefault'] = np.random.uniform(
        0,
        0.1,
        len(df)
    )

    df['capitalAdequacyRatio'] = np.random.uniform(
        0.5,
        2.0,
        len(df)
    )

    return df


def add_new_columns_december(df):

    df = add_new_columns_november(df)

    df['annualHealthScore'] = np.random.uniform(
        0,
        100,
        len(df)
    )

    df['nextYearOutlook'] = np.random.choice(
        [
            'Positive',
            'Stable',
            'Negative'
        ],
        len(df)
    )

    return df


# ============================================================
# TIMESTAMP FEATURES
# ============================================================

EXPECTED_ARRIVAL_DAYS = (
    1,
    5,
    10,
    15,
    20,
    25,
    28
)


def add_timestamp_features(
    df,
    year,
    month,
    month_idx
):

    df = df.copy()

    if 'expected_arrival_day' not in df.columns:

        df['expected_arrival_day'] = (
            df['businessID'].apply(
                lambda x:
                int(
                    np.random.RandomState(
                        hash(x) % 2**31
                    ).choice(
                        EXPECTED_ARRIVAL_DAYS
                    )
                )
            )
        )

    df['expected_arrival_day'] = (
        df['expected_arrival_day']
        .fillna(15)
        .astype(int)
        .clip(1, 28)
    )

    df['expected_arrival_date'] = (
        df['expected_arrival_day'].apply(
            lambda day:
            pd.Timestamp(
                year,
                month,
                min(int(day), 28)
            )
        )
    )

    num_records = len(df)

    is_anomaly = (
        np.random.random(num_records)
        < 0.05
    )

    delays = np.zeros(
        num_records
    )

    delays[~is_anomaly] = np.random.choice(
        [
            0,
            1,
            2,
            3
        ],
        size=(~is_anomaly).sum(),
        p=[
            0.4,
            0.35,
            0.15,
            0.1
        ]
    )

    delays[is_anomaly] = np.random.uniform(
        10,
        30,
        size=is_anomaly.sum()
    )

    df['ingestion_delay_days'] = delays

    df['is_anomalous_delay'] = is_anomaly

    df['ingestion_date'] = (
        df['expected_arrival_date']
        + pd.to_timedelta(
            df['ingestion_delay_days'],
            unit='D'
        )
    )

    df['freshness_days_late'] = (
        df['ingestion_delay_days']
    )

    df['data_month'] = (
        f"{year}-{month:02d}"
    )

    df['month_idx'] = month_idx

    df['year'] = year

    df['month_num'] = month

    return df


# ============================================================
# MONTHLY GENERATION
# ============================================================

MONTH_MAP = {

    'january': 1,
    'february': 2,
    'march': 3,
    'april': 4,
    'may': 5,
    'june': 6,
    'july': 7,
    'august': 8,
    'september': 9,
    'october': 10,
    'november': 11,
    'december': 12
}


MONTH_PIPELINE = {

    'january': (
        inject_january_anomalies,
        None
    ),

    'february': (
        inject_february_anomalies,
        None
    ),

    'march': (
        inject_march_anomalies,
        None
    ),

    'april': (
        inject_april_anomalies,
        add_new_columns_june
    ),

    'may': (
        inject_may_anomalies,
        add_new_columns_june
    ),

    'june': (
        inject_june_anomalies,
        add_new_columns_june
    ),

    'july': (
        inject_july_anomalies,
        add_new_columns_july
    ),

    'august': (
        inject_august_anomalies,
        add_new_columns_august
    ),

    'september': (
        inject_september_anomalies,
        add_new_columns_september
    ),

    'october': (
        inject_october_anomalies,
        add_new_columns_october
    ),

    'november': (
        inject_november_anomalies,
        add_new_columns_november
    ),

    'december': (
        inject_december_anomalies,
        add_new_columns_december
    )
}


IDENTITY_COLS = [

    'businessID',
    'businessName',
    'industry',
    'legalStructure',
    'yearEstablished',
    'registeredAddress_Street',
    'registeredAddress_City',
    'registeredAddress_State',
    'registeredAddress_ZipCode',
    'contactPerson_Name',
    'contactPerson_Title',
    'contactPerson_Email',
    'phoneNumber',
    'website',
    'employeeCount'
]


def _reorder(df):

    return df[
        ['businessID']
        + [
            c
            for c in df.columns
            if c != 'businessID'
        ]
    ]


def generate_monthly_datasets():

    year = GENERATION_YEAR

    # --------------------------------------------------------
    # JANUARY
    # --------------------------------------------------------

    df_january = generate_base_businesses(
        JAN_BASE_ROWS
    )

    df_january = inject_january_anomalies(
        df_january
    )

    df_january = _reorder(
        df_january
    )

    df_january = add_timestamp_features(
        df_january,
        year,
        1,
        0
    )

    yield (
        'january',
        1,
        df_january
    )

    # Keep identity information
    # for future monthly generation.
    all_businesses = df_january[
        IDENTITY_COLS
    ].copy()

    current_seed = JAN_BASE_ROWS

    df_prev = df_january

    # --------------------------------------------------------
    # FEBRUARY - DECEMBER
    # --------------------------------------------------------

    months_order = [
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october',
        'november',
        'december'
    ]

    for idx, month_name in enumerate(
        months_order
    ):

        month_idx = idx + 1

        month_num = MONTH_MAP[
            month_name
        ]

        target_total = (
            JAN_BASE_ROWS
            + MONTHLY_NEW_BUSINESSES
            * month_idx
        )

        # Existing businesses
        df_existing = df_prev.copy()

        # ----------------------------------------------------
        # Apply natural monthly changes
        # ----------------------------------------------------

        if month_name != 'february':

            for col in df_existing.select_dtypes(
                include=['float64']
            ).columns:

                if col not in [
                    'businessID',
                    'segment'
                ]:

                    momentum = np.random.uniform(
                        0.95,
                        1.05,
                        len(df_existing)
                    )

                    shock_mask = (
                        np.random.rand(
                            len(df_existing)
                        ) < 0.05
                    )

                    df_existing[col] = (
                        df_existing[col]
                        * momentum
                    )

                    if shock_mask.sum() > 0:

                        df_existing.loc[
                            shock_mask,
                            col
                        ] = (
                            df_existing.loc[
                                shock_mask,
                                col
                            ]
                            * np.random.uniform(
                                0.7,
                                2.0,
                                shock_mask.sum()
                            )
                        )

        # ----------------------------------------------------
        # Churn
        # ----------------------------------------------------

        churn_rate = float(
            intensity_rng.uniform(
                0.01,
                0.06
            )
        )

        if (
            churn_rate > 0
            and len(df_existing) > 0
        ):

            keep_count = max(
                1,
                int(
                    len(df_existing)
                    * max(
                        0.0,
                        1.0 - churn_rate
                    )
                )
            )

            df_existing = (
                df_existing
                .sample(
                    n=keep_count,
                    random_state=None
                )
                .reset_index(
                    drop=True
                )
            )

        # ----------------------------------------------------
        # Determine how many new records are needed
        # ----------------------------------------------------

        need = max(
            0,
            target_total
            - len(df_existing)
        )

        duplicate_rate = float(
            intensity_rng.uniform(
                0.001,
                0.02
            )
        )

        dup_count = min(
            int(
                need
                * duplicate_rate
                / (1.0 + duplicate_rate)
            ),
            len(df_existing)
        )

        fresh_count = (
            need
            - dup_count
        )

        # ----------------------------------------------------
        # Generate new businesses
        # ----------------------------------------------------

        new_businesses = (
            generate_base_businesses(
                fresh_count,
                seed_offset=current_seed
            )
        )

        current_seed += fresh_count

        if len(new_businesses) > 0:

            candidate_cols = [
                c
                for c in new_businesses.columns
                if c not in [
                    'businessID',
                    'businessName',
                    'segment'
                ]
            ]

            missing_frac = float(
                intensity_rng.uniform(
                    0.01,
                    0.05
                )
            )

            n_missing_rows = max(
                1,
                int(
                    len(new_businesses)
                    * missing_frac
                )
            )

            if (
                candidate_cols
                and n_missing_rows > 0
            ):

                cols_to_nan = intensity_rng.choice(
                    candidate_cols,
                    size=min(
                        len(candidate_cols),
                        max(
                            1,
                            int(
                                len(candidate_cols)
                                * 0.2
                            )
                        )
                    ),
                    replace=False
                )

                for col in cols_to_nan:

                    idxs = intensity_rng.choice(
                        new_businesses.index,
                        size=min(
                            n_missing_rows,
                            len(new_businesses)
                        ),
                        replace=False
                    )

                    new_businesses.loc[
                        idxs,
                        col
                    ] = np.nan

        # ----------------------------------------------------
        # Duplicate records
        # ----------------------------------------------------

        if dup_count > 0:

            dup_rows = (
                df_existing
                .sample(
                    n=dup_count,
                    random_state=None
                )
                .copy()
            )

            new_businesses = pd.concat(
                [
                    new_businesses,
                    dup_rows
                ],
                ignore_index=True
            )

        # ----------------------------------------------------
        # Maintain identity history
        # ----------------------------------------------------

        all_businesses = pd.concat(
            [
                all_businesses,
                new_businesses[
                    IDENTITY_COLS
                ]
            ],
            ignore_index=True
        )

        # ----------------------------------------------------
        # Build month
        # ----------------------------------------------------

        df_month = pd.concat(
            [
                df_existing,
                new_businesses
            ],
            ignore_index=True
        )

        inject_fn, new_cols_fn = (
            MONTH_PIPELINE[month_name]
        )

        df_month = inject_fn(
            df_month
        )

        if new_cols_fn is not None:

            df_month = new_cols_fn(
                df_month
            )

        df_month = _reorder(
            df_month
        )

        df_month = add_timestamp_features(
            df_month,
            year,
            month_num,
            month_idx
        )

        yield (
            month_name,
            month_num,
            df_month
        )

        df_prev = df_month


# ============================================================
# ORACLE LOADING
# ============================================================

COLUMN_MAP = [

    ('businessID', 'businessid'),
    ('businessName', 'businessname'),
    ('segment', 'segment'),
    ('industry', 'industry'),

    ('creditScore', 'creditscore'),
    ('annualRevenue', 'annualrevenue'),
    ('outstandingDebt', 'outstandingdebt'),
    ('totalCreditLimit', 'totalcreditlimit'),
    ('availableCredit', 'availablecredit'),

    ('paymentHistoryScore', 'paymenthistoryscore'),
    ('creditUtilizationRatio', 'creditutilizationratio'),

    ('numberOfAccounts', 'numberofaccounts'),
    ('numberOfInquiries', 'numberofinquiries'),

    ('hasDelinquency', 'hasdelinquency'),
    ('hasDefaulted', 'hasdefaulted'),
    ('hasBankruptcy', 'hasbankruptcy'),

    ('delinquentAccountCount', 'delinquentaccountcount'),
    ('collectionsCount', 'collectionscount'),
    ('chargeoffCount', 'chargeoffcount'),
    ('judgmentCount', 'judgmentcount'),
    ('taxLienCount', 'taxliencount'),
    ('publicRecordCount', 'publicrecordcount'),

    ('monthsSinceLastPayment', 'monthssincelastpayment'),
    ('monthsSinceFirstAccount', 'monthssincefirstaccount'),
    ('monthsSinceLastDelinquency', 'monthssincelastdelinquency'),

    ('debtToIncomeRatio', 'debttoincome_ratio'),
    ('creditWorthinessScore', 'creditworthinessscore'),
    ('riskProfile', 'riskprofile'),

    ('yearEstablished', 'year_established'),
    ('employeeCount', 'employee_count'),

    ('freshness_days_late', 'freshness_days_late'),
]


COUNT_COLS = {
    'numberOfAccounts',
    'numberOfInquiries',
    'delinquentAccountCount',
    'collectionsCount',
    'chargeoffCount',
    'judgmentCount',
    'taxLienCount',
    'publicRecordCount',
    'employeeCount',
    'yearEstablished'
}


FLAG_COLS = {
    'hasDelinquency',
    'hasDefaulted',
    'hasBankruptcy'
}


ORACLE_COLUMNS = (
    [o for _, o in COLUMN_MAP]
    + [
        'data_lineage',
        'data_month',
        'batch_id',
        'record_id'
    ]
)


INSERT_SQL = (
    f"INSERT INTO {ORACLE_TABLE} "
    f"({', '.join(ORACLE_COLUMNS)}) "
    f"VALUES "
    f"({', '.join(':' + str(i + 1) for i in range(len(ORACLE_COLUMNS)))})"
)


def _clean(py_col, value):

    if value is None or value is pd.NaT:
        return None

    if isinstance(
        value,
        (float, np.floating)
    ):

        if (
            math.isnan(value)
            or math.isinf(value)
        ):
            return None

        value = float(value)

    elif isinstance(
        value,
        np.integer
    ):

        value = int(value)

    elif isinstance(
        value,
        (np.bool_, bool)
    ):

        value = int(value)

    if py_col in FLAG_COLS:

        return int(
            min(
                1,
                max(
                    0,
                    round(value)
                )
            )
        )

    if py_col in COUNT_COLS:

        v = int(
            round(value)
        )

        return (
            v
            if py_col == 'yearEstablished'
            else max(
                0,
                v
            )
        )

    return value


def build_rows(
    df,
    batch_id,
    data_month,
    data_lineage
):

    py_cols = [
        p
        for p, _ in COLUMN_MAP
    ]

    rows = []

    for record_id, rec in enumerate(
        df[py_cols].itertuples(
            index=False,
            name=None
        ),
        start=1
    ):

        values = [
            _clean(c, v)
            for c, v in zip(
                py_cols,
                rec
            )
        ]

        values += [
            data_lineage,
            data_month,
            batch_id,
            record_id
        ]

        rows.append(
            tuple(values)
        )

    return rows


def load_batch(
    conn,
    df,
    batch_id,
    data_month,
    data_lineage
):

    rows = build_rows(
        df,
        batch_id,
        data_month,
        data_lineage
    )

    cur = conn.cursor()

    try:

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {ORACLE_TABLE}
            WHERE batch_id = :1
            """,
            [batch_id]
        )

        existing = cur.fetchone()[0]

        if existing:

            if REPLACE_EXISTING_BATCH:

                cur.execute(
                    f"""
                    DELETE FROM {ORACLE_TABLE}
                    WHERE batch_id = :1
                    """,
                    [batch_id]
                )

            else:

                raise RuntimeError(
                    f"batch_id {batch_id} already has "
                    f"{existing} rows in {ORACLE_TABLE}. "
                    f"Delete them first or set "
                    f"REPLACE_EXISTING_BATCH = True."
                )

        cur.executemany(
            INSERT_SQL,
            rows
        )

        conn.commit()

        return len(rows)

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()


# ============================================================
# MAIN
# ============================================================

def main():

    try:

        conn = oracledb.connect(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN
        )

    except oracledb.Error as e:

        print(
            f"ERROR: could not connect to Oracle "
            f"({ORACLE_DSN} as {ORACLE_USER}): {e}"
        )

        sys.exit(1)

    print(
        "Connected to Oracle successfully.\n"
    )

    try:

        for (
            month_name,
            month_num,
            df
        ) in generate_monthly_datasets():

            batch_id = (
                f"V5_{GENERATION_YEAR}_{month_num:02d}"
            )

            data_month = (
                f"{GENERATION_YEAR}-{month_num:02d}"
            )

            # IMPORTANT:
            # Assign lineage based on month.
            data_lineage = get_data_lineage(
                month_num
            )

            print(
                f"Loading batch {batch_id} "
                f"({data_month}, {data_lineage})..."
            )

            try:

                print(
                    "\nORACLE COLUMNS:"
                )

                print(
                    ORACLE_COLUMNS
                )

                print(
                    "\nFRESHNESS IN ORACLE COLUMNS:"
                )

                print(
                    "freshness_days_late"
                    in ORACLE_COLUMNS
                )

                print(
                    "\nDATAFRAME FRESHNESS:"
                )

                print(
                    df[
                        "freshness_days_late"
                    ].head()
                )

                n = load_batch(
                    conn,
                    df,
                    batch_id,
                    data_month,
                    data_lineage
                )

            except Exception as e:

                print(
                    "ERROR: insert failed.\n"
                    f"  month   : "
                    f"{month_name} ({data_month})\n"
                    f"  lineage : "
                    f"{data_lineage}\n"
                    f"  batch_id: "
                    f"{batch_id}\n"
                    f"  error   : {e}"
                )

                print(
                    "This month was rolled back. "
                    "Earlier months stay committed. "
                    "Stopping."
                )

                sys.exit(1)

            print(
                f"Inserted {n} records.\n"
            )

            if RUN_JANUARY_ONLY:

                print(
                    "RUN_JANUARY_ONLY = True: "
                    "stopping after January "
                    "(test mode).\n"
                )

                break

    finally:

        conn.close()

    print(
        "Synthetic data generation completed successfully."
    )

    print(
        "All data stored in Oracle."
    )

    print(
        "No CSV files created."
    )

    print(
        "No S3 uploads performed."
    )


if __name__ == "__main__":
    main()