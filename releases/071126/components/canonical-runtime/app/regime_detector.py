import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

# ---------------------------------
# STATE HISTORY
# ---------------------------------

state_history = []

print()
print("REGIME DETECTOR STARTED")

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

        book = pd.read_parquet(
            "orderbook.parquet"
        )

        # ---------------------------------
        # RECENT DATA
        # ---------------------------------

        flow_last = flow.iloc[-1]

        bybit_last = bybit.iloc[-1]

        oi_recent = oi.tail(10)

        book_last = book.iloc[-1]

        # ---------------------------------
        # FEATURES
        # ---------------------------------

        binance_delta = (
            flow_last['delta']
        )

        bybit_delta = (
            bybit_last['delta']
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

        imbalance = (
            book_last['imbalance']
        )

        efficiency = (
            flow_last['efficiency']
        )

        # ---------------------------------
        # CURRENT STATE
        # ---------------------------------

        state = "NEUTRAL"

        # BULLISH

        if (

            binance_delta > 0

            and

            bybit_delta > 0

            and

            oi_change > 0

            and

            imbalance > 0
        ):

            state = (
                "BULLISH_CONTINUATION"
            )

        # BEARISH

        elif (

            binance_delta < 0

            and

            bybit_delta < 0

            and

            oi_change > 0

            and

            imbalance < 0
        ):

            state = (
                "BEARISH_CONTINUATION"
            )

        # ABSORPTION

        elif (

            abs(efficiency) < 0.03

            and

            abs(binance_delta) > 100
        ):

            state = (
                "ABSORPTION"
            )

        # ---------------------------------
        # STORE HISTORY
        # ---------------------------------

        state_history.append(state)

        if len(state_history) > 30:

            state_history.pop(0)

        # ---------------------------------
        # COUNTS
        # ---------------------------------

        bullish_count = (
            state_history.count(
                "BULLISH_CONTINUATION"
            )
        )

        bearish_count = (
            state_history.count(
                "BEARISH_CONTINUATION"
            )
        )

        absorption_count = (
            state_history.count(
                "ABSORPTION"
            )
        )

        neutral_count = (
            state_history.count(
                "NEUTRAL"
            )
        )

        # ---------------------------------
        # REGIME DETECTION
        # ---------------------------------

        regime = "MIXED"

        # TREND UP

        if bullish_count >= 10:

            regime = (
                "TREND_UP"
            )

        # TREND DOWN

        elif bearish_count >= 10:

            regime = (
                "TREND_DOWN"
            )

        # RANGE

        elif absorption_count >= 8:

            regime = (
                "RANGE_ABSORPTION"
            )

        # CHOPPY

        elif neutral_count >= 15:

            regime = (
                "CHOPPY_NEUTRAL"
            )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "CURRENT STATE:",
            state
        )

        print()

        print(
            "MARKET REGIME:",
            regime
        )

        print()

        print(
            "Bullish States:",
            bullish_count
        )

        print(
            "Bearish States:",
            bearish_count
        )

        print(
            "Absorption States:",
            absorption_count
        )

        print(
            "Neutral States:",
            neutral_count
        )

        print()

        print(
            "Flow Efficiency:",
            round(
                efficiency,
                4
            )
        )

        print(
            "Orderbook Imbalance:",
            round(
                imbalance,
                4
            )
        )

        print(
            "OI Change:",
            round(
                oi_change,
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
