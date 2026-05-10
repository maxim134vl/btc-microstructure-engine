import pandas as pd
import numpy as np

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
# DETECT RUPTURES
# ---------------------------------

ruptures = []

print()
print(
    "REGIME RUPTURE ENGINE"
)

print()

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(

    100,

    len(flow)
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
        # CHANGES
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
        # RUPTURE LOGIC
        # ---------------------------------

        rupture = False

        reasons = []

        # DELTA IGNITION

        if delta_shift > 50:

            rupture = True

            reasons.append(
                "DELTA_SHIFT"
            )

        # IMBALANCE COLLAPSE

        if imbalance_shift > 0.2:

            rupture = True

            reasons.append(
                "IMBALANCE_SHIFT"
            )

        # VOL WAKEUP

        if vol_shift > 0.0002:

            rupture = True

            reasons.append(
                "VOL_WAKEUP"
            )

        # OI SHIFT

        if oi_shift > 5:

            rupture = True

            reasons.append(
                "OI_SHIFT"
            )

        # ---------------------------------
        # STORE
        # ---------------------------------

        if rupture:

            ruptures.append({

                'timestamp':
                    flow.iloc[i][
                        'timestamp'
                    ],

                'price':
                    flow.iloc[i][
                        'avg_price'
                    ],

                'delta_shift':
                    delta_shift,

                'imbalance_shift':
                    imbalance_shift,

                'vol_shift':
                    vol_shift,

                'oi_shift':
                    oi_shift,

                'reasons':
                    ",".join(reasons)
            })

    except:

        continue

# ---------------------------------
# DATAFRAME
# ---------------------------------

ruptures = pd.DataFrame(
    ruptures
)

# ---------------------------------
# EMPTY
# ---------------------------------

if len(ruptures) == 0:

    print(
        "NO RUPTURES FOUND"
    )

    exit()

# ---------------------------------
# SUMMARY
# ---------------------------------

print("================================")
print("RUPTURE SUMMARY")
print("================================")
print()

print(
    "TOTAL RUPTURES:",
    len(ruptures)
)

print()

# ---------------------------------
# RECENT
# ---------------------------------

print("================================")
print("RECENT RUPTURES")
print("================================")
print()

for _, row in (

    ruptures.tail(20)
    .iterrows()
):

    print(
        row['timestamp']
    )

    print(
        "PRICE:",
        round(
            row['price'],
            2
        )
    )

    print(
        "REASONS:",
        row['reasons']
    )

    print(
        "DELTA SHIFT:",
        round(
            row['delta_shift'],
            2
        )
    )

    print(
        "IMBALANCE SHIFT:",
        round(
            row['imbalance_shift'],
            4
        )
    )

    print(
        "VOL SHIFT:",
        round(
            row['vol_shift'],
            6
        )
    )

    print(
        "OI SHIFT:",
        round(
            row['oi_shift'],
            2
        )
    )

    print()

print(
    "RUPTURE ANALYSIS COMPLETE"
)
