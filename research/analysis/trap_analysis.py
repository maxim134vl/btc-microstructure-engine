import pandas as pd
import numpy as np

# ---------------------------------
# LOAD
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
# MERGE
# ---------------------------------

df = pd.merge_asof(
    df.sort_values('timestamp'),
    funding[['timestamp', 'fundingRate']]
    .sort_values('timestamp'),
    on='timestamp',
    direction='backward'
)

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

df['return'] = (
    df['close']
    .pct_change()
)

# VOL

df['realized_vol'] = (
    df['return']
    .rolling(20)
    .std()
)

df['vol_compression'] = (
    df['realized_vol']
    /
    df['realized_vol']
    .rolling(50)
    .mean()
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

# ---------------------------------
# CLEAN
# ---------------------------------

df = df.dropna().reset_index(drop=True)

# ---------------------------------
# CROWD CONDITIONS
# ---------------------------------

crowded = (
    df['oi_zscore'] > 1.5
)

compression = (
    df['vol_compression'] < 0.8
)

# LONG CROWD

long_crowded = (
    df['fundingRate'] > 0
)

# SHORT CROWD

short_crowded = (
    df['fundingRate'] < 0
)

# ---------------------------------
# SETUPS
# ---------------------------------

df['long_trap_setup'] = (
    crowded
    &
    compression
    &
    long_crowded
)

df['short_trap_setup'] = (
    crowded
    &
    compression
    &
    short_crowded
)

# ---------------------------------
# FUTURE RETURNS
# ---------------------------------

LOOKAHEAD = 12

future_returns = []

for i in range(len(df) - LOOKAHEAD):

    current_price = df.iloc[i]['close']

    future_price = df.iloc[
        i + LOOKAHEAD
    ]['close']

    future_return = (
        future_price - current_price
    ) / current_price

    future_returns.append(
        future_return
    )

future_returns += [np.nan] * LOOKAHEAD

df['future_return'] = future_returns

# ---------------------------------
# ANALYSIS
# ---------------------------------

long_df = df[
    df['long_trap_setup']
]

short_df = df[
    df['short_trap_setup']
]

print()
print("LONG CROWD SETUPS")
print("------------------")

print(
    "Count:",
    len(long_df)
)

print(
    "Avg Future Return:",
    round(
        long_df['future_return']
        .mean(),
        4
    )
)

print()

print("SHORT CROWD SETUPS")
print("-------------------")

print(
    "Count:",
    len(short_df)
)

print(
    "Avg Future Return:",
    round(
        short_df['future_return']
        .mean(),
        4
    )
)

# ---------------------------------
# EXTREME EVENTS
# ---------------------------------

print()
print("TOP LONG TRAPS")
print("--------------")

print(
    long_df[
        [
            'timestamp',
            'fundingRate',
            'oi_zscore',
            'future_return'
        ]
    ]
    .sort_values(
        'future_return'
    )
    .head(10)
)

print()
print("TOP SHORT TRAPS")
print("----------------")

print(
    short_df[
        [
            'timestamp',
            'fundingRate',
            'oi_zscore',
            'future_return'
        ]
    ]
    .sort_values(
        'future_return',
        ascending=False
    )
    .head(10)
)
