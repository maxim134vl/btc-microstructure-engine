import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

print()
print("VOLATILITY ENGINE STARTED")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # LOAD FLOW
        # ---------------------------------

        flow = pd.read_parquet(
            "intraday_flow.parquet"
        )

        # ---------------------------------
        # RECENT WINDOW
        # ---------------------------------

        recent = flow.tail(100)

        # ---------------------------------
        # RETURNS
        # ---------------------------------

        returns = (

            recent['avg_price']
            .pct_change()
            .dropna()
        )

        # ---------------------------------
        # VOLATILITY
        # ---------------------------------

        realized_vol = (
            returns.std()
        )

        mean_vol = (
            flow['avg_price']
            .pct_change()
            .rolling(100)
            .std()
            .mean()
        )

        # ---------------------------------
        # VOL RATIO
        # ---------------------------------

        vol_ratio = 0

        if mean_vol > 0:

            vol_ratio = (
                realized_vol
                /
                mean_vol
            )

        # ---------------------------------
        # REGIME
        # ---------------------------------

        regime = "NORMAL_VOL"

        if vol_ratio < 0.7:

            regime = (
                "LOW_VOL_COMPRESSION"
            )

        elif vol_ratio > 1.5:

            regime = (
                "HIGH_VOL_EXPANSION"
            )

        elif vol_ratio > 2.5:

            regime = (
                "EXTREME_VOLATILITY"
            )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "VOLATILITY REGIME:",
            regime
        )

        print()

        print(
            "Realized Vol:",
            round(
                realized_vol,
                8
            )
        )

        print(
            "Mean Vol:",
            round(
                mean_vol,
                8
            )
        )

        print(
            "Vol Ratio:",
            round(
                vol_ratio,
                4
            )
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
