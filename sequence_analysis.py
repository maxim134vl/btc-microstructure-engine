import pandas as pd
import numpy as np

# ---------------------------------
# LOAD
# ---------------------------------

df = pd.read_parquet(
    'intraday_flow.parquet'
)

# ---------------------------------
# FUTURE RETURNS
# ---------------------------------

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
# NORMALIZATION
# ---------------------------------

df['delta_zscore'] = (

    (
        df['delta']
        -
        df['delta']
        .rolling(100)
        .mean()
    )

    /

    df['delta']
    .rolling(100)
    .std()
)

# ---------------------------------
# STATES
# ---------------------------------

HIGH_DELTA = 2
LOW_DELTA = -2

HIGH_EFF = 0.25
LOW_EFF = 0.05

df['continuation_buy'] = (

    (df['delta_zscore'] > HIGH_DELTA)

    &

    (
        abs(df['efficiency'])
        > HIGH_EFF
    )

).astype(int)

df['continuation_sell'] = (

    (df['delta_zscore'] < LOW_DELTA)

    &

    (
        abs(df['efficiency'])
        > HIGH_EFF
    )

).astype(int)

df['absorption'] = (

    (
        abs(df['delta_zscore']) > 2
    )

    &

    (
        abs(df['efficiency'])
        < LOW_EFF
    )

).astype(int)

# ---------------------------------
# SEQUENCE FEATURES
# ---------------------------------

WINDOW = 12

df['buy_persistence'] = (
    df['continuation_buy']
    .rolling(WINDOW)
    .sum()
)

df['sell_persistence'] = (
    df['continuation_sell']
    .rolling(WINDOW)
    .sum()
)

df['absorption_persistence'] = (
    df['absorption']
    .rolling(WINDOW)
    .sum()
)

# ---------------------------------
# CLEAN
# ---------------------------------

df = df.dropna()

# ---------------------------------
# HIGH PERSISTENCE
# ---------------------------------

buy_trend = df[
    df['buy_persistence'] >= 5
]

sell_trend = df[
    df['sell_persistence'] >= 5
]

absorption_zone = df[
    df['absorption_persistence'] >= 3
]

# ---------------------------------
# ANALYZE
# ---------------------------------

def analyze(name, state_df, short=False):

    print()
    print(name)

    print("-" * len(name))

    print(
        "Count:",
        len(state_df)
    )

    if len(state_df) == 0:

        return

    avg_return = (
        state_df[
            'future_return'
        ]
        .mean()
    )

    if short:

        winrate = (
            (
                state_df[
                    'future_return'
                ] < 0
            )
            .mean()
        )

    else:

        winrate = (
            (
                state_df[
                    'future_return'
                ] > 0
            )
            .mean()
        )

    print(
        "Avg Future Return:",
        round(avg_return, 6)
    )

    print(
        "Winrate:",
        round(winrate, 4)
    )

# ---------------------------------
# RESULTS
# ---------------------------------

print()
print("SEQUENCE ANALYSIS")
print("=================")

analyze(
    "BUY PERSISTENCE",
    buy_trend
)

analyze(
    "SELL PERSISTENCE",
    sell_trend,
    short=True
)

analyze(
    "ABSORPTION ZONES",
    absorption_zone
)

# ---------------------------------
# TOP EVENTS
# ---------------------------------

print()
print("TOP BUY PERSISTENCE")
print("-------------------")

print(

    buy_trend[
        [
            'timestamp',
            'buy_persistence',
            'delta',
            'efficiency',
            'future_return'
        ]
    ]

    .sort_values(
        'buy_persistence',
        ascending=False
    )

    .head(20)
)

print()
print("TOP SELL PERSISTENCE")
print("--------------------")

print(

    sell_trend[
        [
            'timestamp',
            'sell_persistence',
            'delta',
            'efficiency',
            'future_return'
        ]
    ]

    .sort_values(
        'sell_persistence',
        ascending=False
    )

    .head(20)
)
