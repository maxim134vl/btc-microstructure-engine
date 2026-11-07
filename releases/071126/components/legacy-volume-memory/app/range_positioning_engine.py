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
# STORAGE
# ---------------------------------

positive_delta_zones = []

negative_delta_zones = []

print()
print("RANGE POSITIONING ENGINE STARTED")

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
        # RETURNS
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

        range_detected = False

        if realized_vol < VOL_THRESHOLD:

            range_detected = True

        # ---------------------------------
        # POSITIONING
        # ---------------------------------

        if range_detected:

            # POSITIVE DELTA

            positive = recent[
                recent['delta'] > 100
            ]

            # NEGATIVE DELTA

            negative = recent[
                recent['delta'] < -100
            ]

            # STORE LEVELS

            positive_delta_zones = list(

                positive[
                    'avg_price'
                ].values
            )

            negative_delta_zones = list(

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

        if range_detected:

            print(
                "POSITIVE DELTA ZONES"
            )

            print()

            for level in (

                positive_delta_zones[-10:]
            ):

                print(
                    round(level, 2)
                )

            print()

            print(
                "NEGATIVE DELTA ZONES"
            )

            print()

            for level in (

                negative_delta_zones[-10:]
            ):

                print(
                    round(level, 2)
                )

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
