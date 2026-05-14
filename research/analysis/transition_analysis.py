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

df['buy_cont'] = (

    (df['delta_zscore'] > HIGH_DELTA)

    &

    (
        abs(df['efficiency'])
        > HIGH_EFF
    )

).astype(int)

df['sell_cont'] = (

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
# TRANSITIONS
# ---------------------------------

WINDOW = 6

transitions = []

for i in range(WINDOW, len(df) - LOOKAHEAD):

    prev = df.iloc[
        i-WINDOW:i
    ]

    current = df.iloc[i]

    # ---------------------------------
    # BUY -> ABSORPTION
    # ---------------------------------

    if (

        prev['buy_cont']
        .sum() >= 4

        and

        current['absorption'] == 1
    ):

        transitions.append({

            'type':
            'BUY_TO_ABSORPTION',

            'timestamp':
            current['timestamp'],

            'future_return':
            current['future_return'],

            'delta':
            current['delta'],

            'efficiency':
            current['efficiency']
        })

    # ---------------------------------
    # SELL -> ABSORPTION
    # ---------------------------------

    if (

        prev['sell_cont']
        .sum() >= 4

        and

        current['absorption'] == 1
    ):

        transitions.append({

            'type':
            'SELL_TO_ABSORPTION',

            'timestamp':
            current['timestamp'],

            'future_return':
            current['future_return'],

            'delta':
            current['delta'],

            'efficiency':
            current['efficiency']
        })

# ---------------------------------
# RESULTS
# ---------------------------------

trans_df = pd.DataFrame(
    transitions
)

print()
print("TRANSITION ANALYSIS")
print("===================")

if len(trans_df) == 0:

    print()
    print("NO TRANSITIONS FOUND")

    exit()

# ---------------------------------
# ANALYZE
# ---------------------------------

for t in trans_df['type'].unique():

    temp = trans_df[
        trans_df['type'] == t
    ]

    print()
    print(t)

    print("-" * len(t))

    print(
        "Count:",
        len(temp)
    )

    avg_return = (
        temp[
            'future_return'
        ]
        .mean()
    )

    print(
        "Avg Future Return:",
        round(avg_return, 6)
    )

    if 'SELL' in t:

        winrate = (
            (
                temp[
                    'future_return'
                ] < 0
            )
            .mean()
        )

    else:

        winrate = (
            (
                temp[
                    'future_return'
                ] > 0
            )
            .mean()
        )

    print(
        "Winrate:",
        round(winrate, 4)
    )

# ---------------------------------
# TOP EVENTS
# ---------------------------------

print()
print("TOP TRANSITIONS")
print("---------------")

print(

    trans_df

    .sort_values(
        'future_return'
    )

    .head(30)
)
