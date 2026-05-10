import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

FUTURE_WINDOW = 50

# ---------------------------------
# LOAD
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

oi = pd.read_parquet(
    "oi_history.parquet"
)

book = pd.read_parquet(
    "orderbook.parquet"
)

# ---------------------------------
# ALIGN
# ---------------------------------

min_len = min(

    len(flow),

    len(oi),

    len(book)
)

flow = flow.tail(min_len)

oi = oi.tail(min_len)

book = book.tail(min_len)

# ---------------------------------
# FEATURES
# ---------------------------------

flow['delta_smooth'] = (

    flow['delta']
    .rolling(50)
    .mean()
)

book['imbalance_smooth'] = (

    book['imbalance']
    .rolling(50)
    .mean()
)

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
# RESULTS
# ---------------------------------

results = []

print()
print(
    "RUPTURE AFTERMATH ANALYSIS"
)

print()

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(

    100,

    len(flow) - FUTURE_WINDOW
):

    try:

        # ---------------------------------
        # CURRENT
        # ---------------------------------

        delta_now = (
            flow.iloc[i][
                'delta_smooth'
            ]
        )

        delta_prev = (
            flow.iloc[i - 10][
                'delta_smooth'
            ]
        )

        imbalance_now = (
            book.iloc[i][
                'imbalance_smooth'
            ]
        )

        imbalance_prev = (
            book.iloc[i - 10][
                'imbalance_smooth'
            ]
        )

        vol_now = (
            flow.iloc[i][
                'volatility'
            ]
        )

        vol_prev = (
            flow.iloc[i - 10][
                'volatility'
            ]
        )

        oi_now = (
            oi.iloc[i][
                'oi_change'
            ]
        )

        oi_prev = (
            oi.iloc[i - 10][
                'oi_change'
            ]
        )

        # ---------------------------------
        # SHIFTS
        # ---------------------------------

        delta_shift = abs(
            delta_now
            -
            delta_prev
        )

        imbalance_shift = abs(
            imbalance_now
            -
            imbalance_prev
        )

        vol_shift = (
            vol_now
            -
            vol_prev
        )

        oi_shift = abs(
            oi_now
            -
            oi_prev
        )

        # ---------------------------------
        # DETECT RUPTURE
        # ---------------------------------

        rupture = False

        if delta_shift > 50:

            rupture = True

        if imbalance_shift > 0.2:

            rupture = True

        if vol_shift > 0.0002:

            rupture = True

        if oi_shift > 5:

            rupture = True

        if rupture is False:

            continue

        # ---------------------------------
        # FUTURE
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

        max_move = max(

            abs(
                (
                    future_max
                    -
                    current_price
                )
                /
                current_price
            ),

            abs(
                (
                    future_min
                    -
                    current_price
                )
                /
                current_price
            )
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
        "NO RUPTURES FOUND"
    )

    exit()

# ---------------------------------
# SUMMARY
# ---------------------------------

print("================================")
print("AFTERMATH SUMMARY")
print("================================")
print()

print(
    "TOTAL RUPTURES:",
    len(results)
)

print()

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

print(
    "ANALYSIS COMPLETE"
)
