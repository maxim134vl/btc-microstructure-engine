import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

RANGE_WINDOW = 200

VOL_THRESHOLD = 0.0004

FUTURE_WINDOW = 300

DELTA_THRESHOLD = 100

# ---------------------------------
# LEVERAGE MAP
# ---------------------------------

LEVERAGES = {

    "x20": 0.05,
    "x10": 0.10,
    "x5": 0.20,
    "x2": 0.50
}

# ---------------------------------
# LOAD DATA
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

# ---------------------------------
# RESULTS
# ---------------------------------

results = []

print()
print("STARTING HISTORICAL TEST")
print()

# ---------------------------------
# MAIN LOOP
# ---------------------------------

for i in range(

    RANGE_WINDOW,

    len(flow) - FUTURE_WINDOW
):

    try:

        # ---------------------------------
        # WINDOW
        # ---------------------------------

        window = flow.iloc[

            i - RANGE_WINDOW : i
        ]

        current = flow.iloc[i]

        future = flow.iloc[

            i : i + FUTURE_WINDOW
        ]

        # ---------------------------------
        # VOLATILITY
        # ---------------------------------

        returns = (

            window[
                'avg_price'
            ]
            .pct_change()
            .dropna()
        )

        realized_vol = (
            returns.std()
        )

        # ---------------------------------
        # RANGE
        # ---------------------------------

        range_detected = (

            realized_vol
            <
            VOL_THRESHOLD
        )

        if not range_detected:

            continue

        # ---------------------------------
        # DELTA
        # ---------------------------------

        delta = current['delta']

        price = current['avg_price']

        # ---------------------------------
        # LONG POSITIONING
        # ---------------------------------

        if delta > DELTA_THRESHOLD:

            direction = "LONG"

        # ---------------------------------
        # SHORT POSITIONING
        # ---------------------------------

        elif delta < -DELTA_THRESHOLD:

            direction = "SHORT"

        else:

            continue

        # ---------------------------------
        # FUTURE
        # ---------------------------------

        future_min = (

            future[
                'avg_price'
            ].min()
        )

        future_max = (

            future[
                'avg_price'
            ].max()
        )

        # ---------------------------------
        # TEST LEVERAGES
        # ---------------------------------

        for lev, dist in (

            LEVERAGES.items()
        ):

            # LONGS

            if direction == "LONG":

                liq = (
                    price
                    *
                    (1 - dist)
                )

                hit = (
                    future_min
                    <=
                    liq
                )

            # SHORTS

            else:

                liq = (
                    price
                    *
                    (1 + dist)
                )

                hit = (
                    future_max
                    >=
                    liq
                )

            # ---------------------------------
            # STORE
            # ---------------------------------

            results.append({

                'timestamp':
                    current['timestamp'],

                'direction':
                    direction,

                'entry':
                    price,

                'leverage':
                    lev,

                'liquidation':
                    liq,

                'hit':
                    hit
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
# SUMMARY
# ---------------------------------

print()
print("================================")
print("SUMMARY")
print("================================")
print()

for lev in LEVERAGES.keys():

    subset = results[

        results['leverage']
        ==
        lev
    ]

    if len(subset) == 0:

        continue

    hitrate = (

        subset['hit']
        .mean()
    )

    print(
        lev,
        "| Hit Rate:",
        round(hitrate, 4),
        "| Count:",
        len(subset)
    )

print()

# ---------------------------------
# LONG / SHORT
# ---------------------------------

for direction in [

    "LONG",
    "SHORT"
]:

    subset = results[

        results['direction']
        ==
        direction
    ]

    if len(subset) == 0:

        continue

    hitrate = (

        subset['hit']
        .mean()
    )

    print(
        direction,
        "| Overall Hit Rate:",
        round(hitrate, 4),
        "| Count:",
        len(subset)
    )

print()
print("TEST COMPLETE")
