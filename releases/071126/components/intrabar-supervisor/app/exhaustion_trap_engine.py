import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

print()
print("EXHAUSTION / TRAP ENGINE STARTED")

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

        bybit = pd.read_parquet(
            "bybit_flow.parquet"
        )

        oi = pd.read_parquet(
            "oi_history.parquet"
        )

        # ---------------------------------
        # RECENT
        # ---------------------------------

        flow_last = flow.iloc[-1]

        bybit_last = bybit.iloc[-1]

        oi_recent = oi.tail(20)

        # ---------------------------------
        # FEATURES
        # ---------------------------------

        binance_delta = (
            flow_last['delta']
        )

        bybit_delta = (
            bybit_last['delta']
        )

        efficiency = (
            flow_last['efficiency']
        )

        price_change = (
            flow_last['price_change']
        )

        oi_change = (

            oi_recent[
                'open_interest'
            ].iloc[-1]

            -

            oi_recent[
                'open_interest'
            ].iloc[0]
        )

        # ---------------------------------
        # DETECTION
        # ---------------------------------

        state = "NORMAL"

        # ---------------------------------
        # BULL TRAP
        # ---------------------------------

        if (

            binance_delta > 150

            and

            bybit_delta > 150

            and

            oi_change > 10

            and

            efficiency < 0.05
        ):

            state = (
                "BULL_TRAP"
            )

        # ---------------------------------
        # BEAR TRAP
        # ---------------------------------

        elif (

            binance_delta < -150

            and

            bybit_delta < -150

            and

            oi_change > 10

            and

            efficiency > -0.05
        ):

            state = (
                "BEAR_TRAP"
            )

        # ---------------------------------
        # BUY EXHAUSTION
        # ---------------------------------

        elif (

            binance_delta > 200

            and

            price_change < 20

            and

            efficiency < 0.03
        ):

            state = (
                "BUY_EXHAUSTION"
            )

        # ---------------------------------
        # SELL EXHAUSTION
        # ---------------------------------

        elif (

            binance_delta < -200

            and

            price_change > -20

            and

            efficiency > -0.03
        ):

            state = (
                "SELL_EXHAUSTION"
            )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "MARKET CONDITION:",
            state
        )

        print()

        print(
            "Binance Delta:",
            round(
                binance_delta,
                2
            )
        )

        print(
            "Bybit Delta:",
            round(
                bybit_delta,
                2
            )
        )

        print(
            "OI Change:",
            round(
                oi_change,
                2
            )
        )

        print(
            "Efficiency:",
            round(
                efficiency,
                4
            )
        )

        print(
            "Price Change:",
            round(
                price_change,
                2
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
