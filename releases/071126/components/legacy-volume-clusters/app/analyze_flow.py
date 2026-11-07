import pandas as pd
import numpy as np

# ---------------------------------
# LOAD
# ---------------------------------

df = pd.read_parquet(
    'intraday_flow.parquet'
)

print()
print("DATASET")
print("-------")

print(df.head())

print()
print("ROWS:", len(df))

# ---------------------------------
# FUTURE RETURNS
# ---------------------------------

# 12 snapshots = ~1 minute
LOOKAHEAD = 12

future_returns = []

for i in range(len(df) - LOOKAHEAD):

    current_price = (
        df.iloc[i]['avg_price']
    )

    future_price = (
        df.iloc[
            i + LOOKAHEAD
        ]['avg_price']
    )

    future_return = (
        future_price - current_price
    ) / current_price

    future_returns.append(
        future_return
    )

future_returns += [np.nan] * LOOKAHEAD

df['future_return'] = (
    future_returns
)

# ---------------------------------
# DELTA ZSCORE
# ---------------------------------

delta_mean = (
    df['delta']
    .rolling(100)
    .mean()
)

delta_std = (
    df['delta']
    .rolling(100)
    .std()
)

df['delta_zscore'] = (
    df['delta']
    - delta_mean
) / delta_std

# ---------------------------------
# CLEAN
# ---------------------------------

df = df.dropna()

# ---------------------------------
# EXTREME FLOW
# ---------------------------------

extreme_buy = (
    df['delta_zscore'] > 2
)

extreme_sell = (
    df['delta_zscore'] < -2
)

# ---------------------------------
# ANALYSIS
# ---------------------------------

print()
print("EXTREME BUY FLOW")
print("----------------")

buy_df = df[
    extreme_buy
]

print(
    "Count:",
    len(buy_df)
)

print(
    "Avg Future Return:",
    round(
        buy_df[
            'future_return'
        ].mean(),
        5
    )
)

print()

print("EXTREME SELL FLOW")
print("-----------------")

sell_df = df[
    extreme_sell
]

print(
    "Count:",
    len(sell_df)
)

print(
    "Avg Future Return:",
    round(
        sell_df[
            'future_return'
        ].mean(),
        5
    )
)

# ---------------------------------
# LOW EFFICIENCY
# ---------------------------------

low_efficiency = (
    abs(df['efficiency']) < 0.02
)

low_eff_df = df[
    low_efficiency
]

print()
print("LOW EFFICIENCY")
print("--------------")

print(
    "Count:",
    len(low_eff_df)
)

print(
    "Avg Future Return:",
    round(
        low_eff_df[
            'future_return'
        ].mean(),
        5
    )
)

# ---------------------------------
# MOST EXTREME EVENTS
# ---------------------------------

print()
print("TOP DELTA EVENTS")
print("----------------")

print(
    df[
        [
            'timestamp',
            'delta',
            'efficiency',
            'future_return'
        ]
    ]
    .sort_values(
        'delta',
        ascending=False
    )
    .head(20)
)

print()
print("TOP SELL EVENTS")
print("----------------")

print(
    df[
        [
            'timestamp',
            'delta',
            'efficiency',
            'future_return'
        ]
    ]
    .sort_values(
        'delta'
    )
    .head(20)
)
