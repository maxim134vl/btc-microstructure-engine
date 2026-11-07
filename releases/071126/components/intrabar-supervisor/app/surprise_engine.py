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
# Z-SCORES
# ---------------------------------

WINDOW = 200

flow['delta_z'] = (

    (
        flow['delta_smooth']
        -
        flow['delta_smooth']
        .rolling(WINDOW)
        .mean()
    )

    /

    flow['delta_smooth']
    .rolling(WINDOW)
    .std()
)

book['imbalance_z'] = (

    (
        book['imbalance_smooth']
        -
        book['imbalance_smooth']
        .rolling(WINDOW)
        .mean()
    )

    /

    book['imbalance_smooth']
    .rolling(WINDOW)
    .std()
)

flow['vol_z'] = (

    (
        flow['volatility']
        -
        flow['volatility']
        .rolling(WINDOW)
        .mean()
    )

    /

    flow['volatility']
    .rolling(WINDOW)
    .std()
)

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
# DETECT SURPRISE
# ---------------------------------

surprises = []

print()
print(
    "SURPRISE ENGINE"
)

print()

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(

    WINDOW,

    min_len
):

    try:

        delta_z = abs(
            flow.iloc[i][
                'delta_z'
            ]
        )

        imbalance_z = abs(
            book.iloc[i][
                'imbalance_z'
            ]
        )

        vol_z = abs(
            flow.iloc[i][
                'vol_z'
            ]
        )

        oi_z = abs(
            oi.iloc[i][
                'oi_z'
            ]
        )

        # ---------------------------------
        # SURPRISE SCORE
        # ---------------------------------

        surprise_score = (

            delta_z
            +
            imbalance_z
            +
            vol_z
            +
            oi_z
        )

        # ---------------------------------
        # EXTREME
        # ---------------------------------

        if surprise_score < 8:

            continue

        surprises.append({

            'timestamp':
                flow.iloc[i][
                    'timestamp'
                ],

            'price':
                flow.iloc[i][
                    'avg_price'
                ],

            'delta_z':
                delta_z,

            'imbalance_z':
                imbalance_z,

            'vol_z':
                vol_z,

            'oi_z':
                oi_z,

            'surprise_score':
                surprise_score
        })

    except:

        continue

# ---------------------------------
# DATAFRAME
# ---------------------------------

surprises = pd.DataFrame(
    surprises
)

# ---------------------------------
# EMPTY
# ---------------------------------

if len(surprises) == 0:

    print(
        "NO SURPRISE STATES FOUND"
    )

    exit()

# ---------------------------------
# SUMMARY
# ---------------------------------

print("================================")
print("SURPRISE STATES")
print("================================")
print()

print(
    "TOTAL:",
    len(surprises)
)

print()

# ---------------------------------
# TOP STATES
# ---------------------------------

top = surprises.sort_values(

    'surprise_score',

    ascending=False
)

for _, row in (

    top.head(20)
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
        "SURPRISE SCORE:",
        round(
            row[
                'surprise_score'
            ],
            2
        )
    )

    print(
        "DELTA Z:",
        round(
            row['delta_z'],
            2
        )
    )

    print(
        "IMBALANCE Z:",
        round(
            row['imbalance_z'],
            2
        )
    )

    print(
        "VOL Z:",
        round(
            row['vol_z'],
            2
        )
    )

    print(
        "OI Z:",
        round(
            row['oi_z'],
            2
        )
    )

    print()

print(
    "SURPRISE ANALYSIS COMPLETE"
)
