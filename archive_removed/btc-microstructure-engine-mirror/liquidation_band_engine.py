import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

RANGE_WINDOW = 200

VOL_THRESHOLD = 0.0004

# ---------------------------------
# LEVERAGE MAP
# ---------------------------------

LEVERAGES = {

    "x20": 0.05,
    "x10": 0.10,
    "x5": 0.20,
    "x2": 0.50
}

print()
print("LIQUIDATION BAND ENGINE STARTED")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # LOAD DATA
        # ---------------------------------

        flow = pd.read_parquet(
            "intraday_flow.parquet"
        )

        # ---------------------------------
        # RECENT WINDOW
        # ---------------------------------

        recent = flow.tail(
            RANGE_WINDOW
        )

        # ---------------------------------
        # VOLATILITY
        # ---------------------------------

        returns = (

            recent[
                'avg_price'
            ]
            .pct_change()
            .dropna()
        )

        realized_vol = (
            returns.std()
        )

        # ---------------------------------
        # RANGE DETECTION
        # ---------------------------------

        range_detected = (
            realized_vol
            <
            VOL_THRESHOLD
        )

        # ---------------------------------
        # POSITIONING
        # ---------------------------------

        positive = recent[
            recent['delta'] > 100
        ]

        negative = recent[
            recent['delta'] < -100
        ]

        positive_levels = list(

            positive[
                'avg_price'
            ].values
        )

        negative_levels = list(

            negative[
                'avg_price'
            ].values
        )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "RANGE DETECTED:",
            range_detected
        )

        print()

        print(
            "Realized Vol:",
            round(
                realized_vol,
                8
            )
        )

        print()

        # ---------------------------------
        # LONG LIQUIDATIONS
        # ---------------------------------

        print(
            "LONG LIQUIDATION BANDS"
        )

        print()

        for level in (

            positive_levels[-5:]
        ):

            print(
                "ENTRY:",
                round(level, 2)
            )

            for lev, dist in (

                LEVERAGES.items()
            ):

                liq = (
                    level
                    *
                    (1 - dist)
                )

                print(
                    lev,
                    "->",
                    round(liq, 2)
                )

            print()

        # ---------------------------------
        # SHORT LIQUIDATIONS
        # ---------------------------------

        print(
            "SHORT LIQUIDATION BANDS"
        )

        print()

        for level in (

            negative_levels[-5:]
        ):

            print(
                "ENTRY:",
                round(level, 2)
            )

            for lev, dist in (

                LEVERAGES.items()
            ):

                liq = (
                    level
                    *
                    (1 + dist)
                )

                print(
                    lev,
                    "->",
                    round(liq, 2)
                )

            print()

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(
            SLEEP_INTERVAL
        )

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(
            SLEEP_INTERVAL
        )
