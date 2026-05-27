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
# STRATEGY PARAMETERS
# ---------------------------------

OI_THRESHOLD = 1.5

VOL_COMPRESSION = 0.8

TP = 0.015
SL = 0.007

MAX_HOLD = 12

FEE = 0.0008

# ---------------------------------
# RESULTS
# ---------------------------------

trades = []

# ---------------------------------
# BACKTEST
# ---------------------------------

for i in range(len(df) - MAX_HOLD):

    row = df.iloc[i]

    # ---------------------------------
    # ENTRY CONDITIONS
    # ---------------------------------

    short_crowded = (
        row['fundingRate'] < 0
    )

    crowded = (
        row['oi_zscore']
        > OI_THRESHOLD
    )

    compressed = (
        row['vol_compression']
        < VOL_COMPRESSION
    )

    entry_signal = (
        short_crowded
        and crowded
        and compressed
    )

    if not entry_signal:
        continue

    # ---------------------------------
    # ENTRY
    # ---------------------------------

    entry_price = row['close']

    future = df.iloc[
        i+1 : i+MAX_HOLD+1
    ]

    trade_return = 0

    exit_reason = "TIME"

    # ---------------------------------
    # FORWARD LOOP
    # ---------------------------------

    for _, future_row in future.iterrows():

        high_move = (
            future_row['high']
            - entry_price
        ) / entry_price

        low_move = (
            future_row['low']
            - entry_price
        ) / entry_price

        # TAKE PROFIT

        if high_move >= TP:

            trade_return = TP - FEE

            exit_reason = "TP"

            break

        # STOP LOSS

        if low_move <= -SL:

            trade_return = -SL - FEE

            exit_reason = "SL"

            break

    # ---------------------------------
    # TIME EXIT
    # ---------------------------------

    if exit_reason == "TIME":

        final_price = future.iloc[-1]['close']

        trade_return = (
            (final_price - entry_price)
            / entry_price
        ) - FEE

    trades.append({
        'timestamp': row['timestamp'],
        'return': trade_return,
        'exit': exit_reason
    })

# ---------------------------------
# RESULTS
# ---------------------------------

trades_df = pd.DataFrame(trades)

print()
print("SHORT SQUEEZE STRATEGY")
print("----------------------")

print(
    "Trades:",
    len(trades_df)
)

if len(trades_df) > 0:

    winrate = (
        trades_df['return'] > 0
    ).mean()

    total_return = (
        trades_df['return']
        .sum()
    )

    avg_return = (
        trades_df['return']
        .mean()
    )

    print(
        "Winrate:",
        round(winrate, 4)
    )

    print(
        "Total Return:",
        round(total_return, 4)
    )

    print(
        "Average Trade:",
        round(avg_return, 4)
    )

    print()
    print("Exit Distribution")
    print("-----------------")

    print(
        trades_df['exit']
        .value_counts()
    )

    print()
    print("Top Trades")
    print("-----------")

    print(
        trades_df
        .sort_values(
            'return',
            ascending=False
        )
        .head(20)
    )
