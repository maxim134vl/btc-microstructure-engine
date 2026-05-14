import pandas as pd
import numpy as np

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
# FEATURES
# ---------------------------------

# RETURNS

df['return'] = (
    df['close']
    .pct_change()
)

# VOLATILITY

df['realized_vol'] = (
    df['return']
    .rolling(20)
    .std()
)

# VOL COMPRESSION

df['vol_compression'] = (
    df['realized_vol']
    /
    df['realized_vol']
    .rolling(50)
    .mean()
)

# OI CHANGE

df['oi_change'] = (
    df['sumOpenInterest']
    .pct_change()
)

# OI ZSCORE

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

# FUNDING ZSCORE

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
# CLEAN
# ---------------------------------

df = df.dropna().reset_index(drop=True)

# ---------------------------------
# SQUEEZE CONDITIONS
# ---------------------------------

# CROWDING

crowded = (
    df['oi_zscore'] > 1.5
)

# EXTREME FUNDING

funding_extreme = (
    df['funding_zscore']
    .abs() > 1.5
)

# VOL COMPRESSION

compression = (
    df['vol_compression'] < 0.8
)

# FINAL SETUP

df['squeeze_setup'] = (
    crowded
    &
    funding_extreme
    &
    compression
)

# ---------------------------------
# FUTURE MOVE
# ---------------------------------

LOOKAHEAD = 12

future_moves = []

for i in range(len(df) - LOOKAHEAD):

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

    max_move = max(
        up_move,
        down_move
    )

    future_moves.append(max_move)

future_moves += [np.nan] * LOOKAHEAD

df['future_move'] = future_moves

# ---------------------------------
# ANALYSIS
# ---------------------------------

squeeze_df = df[
    df['squeeze_setup']
]

normal_df = df[
    ~df['squeeze_setup']
]

print()
print("SQUEEZE EVENTS")
print("--------------")

print(len(squeeze_df))

print()
print("AVG FUTURE MOVE")
print("----------------")

print(
    "Squeeze:",
    round(
        squeeze_df['future_move']
        .mean(),
        4
    )
)

print(
    "Normal:",
    round(
        normal_df['future_move']
        .mean(),
        4
    )
)

print()
print("TOP SQUEEZE EVENTS")
print("------------------")

top = squeeze_df[
    [
        'timestamp',
        'fundingRate',
        'oi_zscore',
        'vol_compression',
        'future_move'
    ]
].sort_values(
    'future_move',
    ascending=False
)

print(top.head(20))
