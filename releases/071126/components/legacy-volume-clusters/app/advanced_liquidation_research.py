import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

RANGE_WINDOW = 200

FUTURE_WINDOW = 300

VOL_THRESHOLD = 0.0004

OI_THRESHOLD = 2

EFFICIENCY_THRESHOLD = 0.05

DELTA_THRESHOLD = 50

PERSISTENCE_THRESHOLD = 2

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

oi = pd.read_parquet(
    "oi_history.parquet"
)

# ---------------------------------
# ALIGN
# ---------------------------------

flow = flow.reset_index(drop=True)

oi = oi.reset_index(drop=True)

min_len = min(
    len(flow),
    len(oi)
)

flow = flow.iloc[:min_len]

oi = oi.iloc[:min_len]

# ---------------------------------
# RESULTS
# ---------------------------------

results = []

print()
print("ADVANCED LIQUIDATION RESEARCH")
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
        # WINDOWS
        # ---------------------------------

        window = flow.iloc[
            i - RANGE_WINDOW : i
        ]

        current = flow.iloc[i]

        future = flow.iloc[
            i : i + FUTURE_WINDOW
        ]

        oi_window = oi.iloc[
            i - RANGE_WINDOW : i
        ]

        # ---------------------------------
        # RANGE
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

        if realized_vol > VOL_THRESHOLD:

            continue

        # ---------------------------------
        # FEATURES
        # ---------------------------------

        delta = current['delta']

        efficiency = (
            current['efficiency']
        )

        price = (
            current['avg_price']
        )

        # ---------------------------------
        # OI
        # ---------------------------------

        oi_change = (

            oi_window[
                'open_interest'
            ].iloc[-1]

            -

            oi_window[
                'open_interest'
            ].iloc[0]
        )

        # ---------------------------------
        # PERSISTENCE
        # ---------------------------------

        recent_delta = (

            window[
                'delta'
            ]
            .tail(5)
        )

        positive_persistence = (

            (recent_delta > 0)
            .sum()
        )

        negative_persistence = (

            (recent_delta < 0)
            .sum()
        )

        # ---------------------------------
        # LONG SETUP
        # ---------------------------------

        long_setup = (

            delta > DELTA_THRESHOLD

            and

            oi_change > OI_THRESHOLD

            and

            abs(efficiency)
            <
            EFFICIENCY_THRESHOLD

            and

            positive_persistence
            >=
            PERSISTENCE_THRESHOLD
        )

        # ---------------------------------
        # SHORT SETUP
        # ---------------------------------

        short_setup = (

            delta < -DELTA_THRESHOLD

            and

            oi_change > OI_THRESHOLD

            and

            abs(efficiency)
            <
            EFFICIENCY_THRESHOLD

            and

            negative_persistence
            >=
            PERSISTENCE_THRESHOLD
        )

        # ---------------------------------
        # FILTER
        # ---------------------------------

        if not long_setup and not short_setup:

            continue

        # ---------------------------------
        # DIRECTION
        # ---------------------------------

        if long_setup:

            direction = "LONG"

        else:

            direction = "SHORT"

        # ---------------------------------
        # FUTURE
        # ---------------------------------

        future_min = (
            future['avg_price'].min()
        )

        future_max = (
            future['avg_price'].max()
        )

        # ---------------------------------
        # TEST LEVERAGE
        # ---------------------------------

        for lev, dist in (

            LEVERAGES.items()
        ):

            # LONG

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

            # SHORT

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

                'direction':
                    direction,

                'leverage':
                    lev,

                'hit':
                    hit
            })

    except:

        continue

# ---------------------------------
# EMPTY
# ---------------------------------

if len(results) == 0:

    print()
    print("NO SETUPS FOUND")
    exit()

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

# ---------------------------------
# LEVERAGE
# ---------------------------------

for lev in LEVERAGES.keys():

    subset = results[

        results['leverage']
        ==
        lev
    ]

    hitrate = (
        subset['hit'].mean()
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
# DIRECTION
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

    hitrate = (
        subset['hit'].mean()
    )

    print(
        direction,
        "| Hit Rate:",
        round(hitrate, 4),
        "| Count:",
        len(subset)
    )

print()
print("RESEARCH COMPLETE")
