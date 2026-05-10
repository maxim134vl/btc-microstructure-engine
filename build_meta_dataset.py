import pandas as pd
import numpy as np

WINDOW = 64
LOOKAHEAD = 12

# CLEAN MOVE RULES

MOVE_THRESHOLD = 0.015
MAX_DRAWDOWN = 0.007

print("Loading market data...")

# ---------------------------------
# LOAD DATA
# ---------------------------------

df = pd.read_parquet(
    'btc_15m.parquet'
)

funding = pd.read_parquet(
    'btc_funding.parquet'
)

funding = funding.rename(
    columns={
        'fundingTime': 'timestamp'
    }
)

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
# ADVANCED FEATURES
# ---------------------------------

df['return'] = (
    df['close']
    .pct_change()
)

# VOLATILITY

df['realized_vol_20'] = (
    df['return']
    .rolling(20)
    .std()
)

df['realized_vol_50'] = (
    df['return']
    .rolling(50)
    .std()
)

df['vol_compression'] = (
    df['realized_vol_20']
    /
    df['realized_vol_50']
)

# TREND

df['trend_strength'] = (
    (
        df['close']
        - df['close'].rolling(20).mean()
    )
    /
    df['close'].rolling(20).std()
)

# RANGE ENERGY

df['range_20'] = (
    (
        df['high']
        .rolling(20)
        .max()
        -
        df['low']
        .rolling(20)
        .min()
    )
    /
    df['close']
)

# VOLUME PRESSURE

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

df['volume_pressure'] = (
    df['volume']
    - volume_mean
) / volume_std

# FUNDING

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

# OI

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

# INTERACTION

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

    'return',

    'realized_vol_20',
    'realized_vol_50',
    'vol_compression',

    'trend_strength',

    'range_20',

    'volume_pressure',

    'fundingRate',
    'funding_zscore',

    'sumOpenInterest',
    'oi_change',
    'oi_zscore',

    'price_oi_interaction'
]

print("Building meta-label dataset...")

X = []
y = []

# ---------------------------------
# BUILD
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
    # CLEAN MOVE LABEL
    # ---------------------------------

    current_price = df.iloc[i]['close']

    future = df.iloc[
        i+1 : i+LOOKAHEAD+1
    ]

    future_high = future['high'].max()

    future_low = future['low'].min()

    up_move = (
        future_high - current_price
    ) / current_price

    down_move = (
        current_price - future_low
    ) / current_price

    # LONG QUALITY

    long_clean = (
        up_move >= MOVE_THRESHOLD
        and
        down_move <= MAX_DRAWDOWN
    )

    # SHORT QUALITY

    short_clean = (
        down_move >= MOVE_THRESHOLD
        and
        up_move <= MAX_DRAWDOWN
    )

    # META LABEL

    if long_clean or short_clean:

        label = 1

    else:

        label = 0

    y.append(label)

# ---------------------------------
# FINAL
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

np.save('X_meta.npy', X)
np.save('y_meta.npy', y)

print()
print("META DATASET BUILT")
