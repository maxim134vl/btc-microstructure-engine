import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

WINDOW = 200

FUTURE_WINDOW = 50

OI_THRESHOLD = 5

# ---------------------------------
# LOAD
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

oi = pd.read_parquet(
    "oi_history.parquet"
)

# ---------------------------------
# ALIGN
# ---------------------------------

min_len = min(

    len(flow),

    len(oi)
)

flow = flow.tail(min_len)

oi = oi.tail(min_len)

# ---------------------------------
# FEATURES
# ---------------------------------

returns = (

    flow['avg_price']
    .pct_change()
)

flow['volatility'] = (

    returns
    .rolling(50)
    .std()
)

oi['oi_change'] = (

    oi['open_interest']
    .diff()
)

# ---------------------------------
# OI Z-SCORE
# ---------------------------------

oi['oi_z'] = (

    (
        oi['oi_change']
        -
        oi['oi_change']
        .rolling(WINDOW)
        .mean()
    )

    /

    oi['oi_change']
    .rolling(WINDOW)
    .std()
)

# ---------------------------------
# RESULTS
# ---------------------------------

results = []

print()
print(
    "OI SURPRISE AFTERMATH"
)

print()

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(

    WINDOW,

    min_len - FUTURE_WINDOW
):

    try:

        oi_z = abs(
            oi.iloc[i][
                'oi_z'
            ]
        )

        # ---------------------------------
        # FILTER
        # ---------------------------------

        if oi_z < OI_THRESHOLD:

            continue

        # ---------------------------------
        # CURRENT
        # ---------------------------------

        current_price = (
            flow.iloc[i][
                'avg_price'
            ]
        )

        current_vol = (
            flow.iloc[i][
                'volatility'
            ]
        )

        # ---------------------------------
        # FUTURE
        # ---------------------------------

        future = flow.iloc[

            i :
            i + FUTURE_WINDOW
        ]

        future_last = (
            future.iloc[-1][
                'avg_price'
            ]
        )

        future_max = (
            future['avg_price']
            .max()
        )

        future_min = (
            future['avg_price']
            .min()
        )

        future_vol = (
            future['volatility']
            .mean()
        )

        # ---------------------------------
        # RETURNS
        # ---------------------------------

        future_return = (

            (
                future_last
                -
                current_price
            )

            /

            current_price
        )

        max_upside = (

            (
                future_max
                -
                current_price
            )

            /

            current_price
        )

        max_downside = (

            (
                future_min
                -
                current_price
            )

            /

            current_price
        )

        max_move = max(

            abs(max_upside),

            abs(max_downside)
        )

        vol_change = (
            future_vol
            -
            current_vol
        )

        # ---------------------------------
        # STORE
        # ---------------------------------

        results.append({

            'oi_z':
                oi_z,

            'future_return':
                future_return,

            'max_move':
                max_move,

            'vol_change':
                vol_change
        })

    except:

        continue

# ---------------------------------
# DATAFRAME
# ---------------------------------

results = pd.DataFrame(
    results
)

# ---------------------------------
# EMPTY
# ---------------------------------

if len(results) == 0:

    print(
        "NO OI SURPRISES FOUND"
    )

    exit()

# ---------------------------------
# SUMMARY
# ---------------------------------

print("================================")
print("OI SURPRISE RESULTS")
print("================================")
print()

print(
    "TOTAL EVENTS:",
    len(results)
)

print()

print(
    "AVG OI Z:",
    round(
        results[
            'oi_z'
        ].mean(),
        2
    )
)

print(
    "AVG FUTURE RETURN:",
    round(
        results[
            'future_return'
        ].mean(),
        6
    )
)

print(
    "AVG MAX MOVE:",
    round(
        results[
            'max_move'
        ].mean(),
        6
    )
)

print(
    "AVG VOL CHANGE:",
    round(
        results[
            'vol_change'
        ].mean(),
        8
    )
)

print()

# ---------------------------------
# VOL EXPANSION
# ---------------------------------

vol_expansion = results[

    results[
        'vol_change'
    ] > 0
]

print(
    "VOL EXPANSION RATE:",
    round(
        len(vol_expansion)
        /
        len(results),
        4
    )
)

print()

# ---------------------------------
# LARGE MOVES
# ---------------------------------

large_moves = results[

    results[
        'max_move'
    ] > 0.001
]

print(
    "LARGE MOVE RATE:",
    round(
        len(large_moves)
        /
        len(results),
        4
    )
)

print()

print(
    "ANALYSIS COMPLETE"
)
