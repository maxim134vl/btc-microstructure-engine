import pandas as pd
import numpy as np

# ---------------------------------
# LOAD
# ---------------------------------

df = pd.read_parquet(
    'intraday_flow.parquet'
)

# ---------------------------------
# FUTURE RETURN
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
# CLEAN
# ---------------------------------

df = df.dropna()

# ---------------------------------
# STATE CONDITIONS
# ---------------------------------

HIGH_DELTA = 2
LOW_DELTA = -2

LOW_EFF = 0.05
HIGH_EFF = 0.25

# ---------------------------------
# STATES
# ---------------------------------

absorption_buy = df[

    (df['delta_zscore'] > HIGH_DELTA)

    &

    (
        abs(df['efficiency'])
        < LOW_EFF
    )
]

absorption_sell = df[

    (df['delta_zscore'] < LOW_DELTA)

    &

    (
        abs(df['efficiency'])
        < LOW_EFF
    )
]

continuation_buy = df[

    (df['delta_zscore'] > HIGH_DELTA)

    &

    (
        abs(df['efficiency'])
        > HIGH_EFF
    )
]

continuation_sell = df[

    (df['delta_zscore'] < LOW_DELTA)

    &

    (
        abs(df['efficiency'])
        > HIGH_EFF
    )
]

# ---------------------------------
# FUNCTION
# ---------------------------------

def analyze(name, state_df):

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
# RUN
# ---------------------------------

print()
print("STATE ANALYSIS")
print("==============")

analyze(
    "ABSORPTION BUY",
    absorption_buy
)

analyze(
    "ABSORPTION SELL",
    absorption_sell
)

analyze(
    "CONTINUATION BUY",
    continuation_buy
)

analyze(
    "CONTINUATION SELL",
    continuation_sell
)

# ---------------------------------
# TOP EVENTS
# ---------------------------------

print()
print("TOP ABSORPTION SELL EVENTS")
print("--------------------------")

print(

    absorption_sell[
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
