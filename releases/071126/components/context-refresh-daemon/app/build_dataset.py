import pandas as pd
import numpy as np

WINDOW = 64
LOOKAHEAD = 12

TP = 0.015
SL = 0.01

print("Loading market data...")

# ---------------------------------
# LOAD OHLCV
# ---------------------------------

df = pd.read_parquet(
    'btc_15m.parquet'
)

# ---------------------------------
# LOAD FUNDING
# ---------------------------------

funding = pd.read_parquet(
    'btc_funding.parquet'
)

funding = funding.rename(
    columns={
        'fundingTime': 'timestamp'
    }
)

# ---------------------------------
# LOAD OI
# ---------------------------------

oi = pd.read_parquet(
    'btc_oi.parquet'
)

# ---------------------------------
# MERGE FUNDING
# ---------------------------------

df = pd.merge_asof(
    df.sort_values('timestamp'),
    funding[['timestamp', 'fundingRate']]
    .sort_values('timestamp'),
    on='timestamp',
    direction='backward'
)

# ---------------------------------
# MERGE OI
# ---------------------------------

df = pd.merge_asof(
    df.sort_values('timestamp'),
    oi[['timestamp', 'sumOpenInterest']]
    .sort_values('timestamp'),
    on='timestamp',
    direction='backward'
)

# ---------------------------------
# FILL
# ---------------------------------

df['fundingRate'] = (
    df['fundingRate']
    .fillna(0)
)

df['sumOpenInterest'] = (
    df['sumOpenInterest']
    .ffill()
)

# ---------------------------------
# BASIC FEATURES
# ---------------------------------

df['return'] = (
    df['close']
    .pct_change()
)

df['volatility'] = (
    df['high'] - df['low']
) / df['close']

df['body'] = (
    df['close'] - df['open']
) / df['open']

df['upper_wick'] = (
    df['high']
    - np.maximum(df['open'], df['close'])
) / df['close']

df['lower_wick'] = (
    np.minimum(df['open'], df['close'])
    - df['low']
) / df['close']

df['range'] = (
    df['high'] - df['low']
) / df['open']

# ---------------------------------
# VOLUME FEATURES
# ---------------------------------

volume_mean = (
    df['volume']
    .rolling(20)
    .mean()
)

volume_std = (
    df['volume']
    .rolling(20)
    .std()
)

df['volume_zscore'] = (
    df['volume'] - volume_mean
) / volume_std

# ---------------------------------
# FUNDING FEATURES
# ---------------------------------

funding_mean = (
    df['fundingRate']
    .rolling(50)
    .mean()
)

funding_std = (
    df['fundingRate']
    .rolling(50)
    .std()
)

df['funding_zscore'] = (
    df['fundingRate']
    - funding_mean
) / funding_std

# ---------------------------------
# OI FEATURES
# ---------------------------------

df['oi_change'] = (
    df['sumOpenInterest']
    .pct_change()
)

oi_mean = (
    df['sumOpenInterest']
    .rolling(50)
    .mean()
)

oi_std = (
    df['sumOpenInterest']
    .rolling(50)
    .std()
)

df['oi_zscore'] = (
    df['sumOpenInterest']
    - oi_mean
) / oi_std

# PRICE + OI INTERACTION

df['price_oi_interaction'] = (
    df['return']
    * df['oi_change']
)

# ---------------------------------
# CLEAN
# ---------------------------------

df = df.dropna().reset_index(drop=True)

# ---------------------------------
# FEATURES
# ---------------------------------

FEATURE_COLUMNS = [

    'open',
    'high',
    'low',
    'close',
    'volume',

    'return',
    'volatility',
    'body',
    'upper_wick',
    'lower_wick',
    'volume_zscore',
    'range',

    'fundingRate',
    'funding_zscore',

    'sumOpenInterest',
    'oi_change',
    'oi_zscore',
    'price_oi_interaction'
]

print("Building dataset...")

X = []
y = []

# ---------------------------------
# BUILD DATASET
# ---------------------------------

for i in range(WINDOW, len(df) - LOOKAHEAD):

    window = df.iloc[i-WINDOW:i]

    features = window[
        FEATURE_COLUMNS
    ].values.astype(np.float32)

    features = np.nan_to_num(
        features,
        nan=0.0,
        posinf=0.0,
        neginf=0.0
    )

    X.append(features)

    # ---------------------------------
    # LABELS
    # ---------------------------------

    current_price = df.iloc[i]['close']

    future = df.iloc[
        i+1 : i+LOOKAHEAD+1
    ]

    label = 0

    for _, row in future.iterrows():

        high_move = (
            row['high']
            - current_price
        ) / current_price

        low_move = (
            row['low']
            - current_price
        ) / current_price

        # LONG

        if high_move >= TP:

            label = 1

            break

        # SHORT

        if low_move <= -SL:

            label = -1

            break

    y.append(label)

# ---------------------------------
# FINAL ARRAYS
# ---------------------------------

X = np.array(
    X,
    dtype=np.float32
)

y = np.array(
    y,
    dtype=np.int8
)

print("X shape:", X.shape)
print("y shape:", y.shape)

unique, counts = np.unique(
    y,
    return_counts=True
)

print()
print("Label distribution:")

for u, c in zip(unique, counts):

    print(u, c)

# ---------------------------------
# SAVE
# ---------------------------------

np.save('X.npy', X)
np.save('y.npy', y)

print()
print("DATASET BUILT")
