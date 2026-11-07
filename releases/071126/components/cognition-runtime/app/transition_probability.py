import pandas as pd
import numpy as np
import time

from collections import defaultdict

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

# ---------------------------------
# STORAGE
# ---------------------------------

state_history = []

transition_counts = defaultdict(int)

print()
print("TRANSITION PROBABILITY ENGINE STARTED")

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
        # RECENT
        # ---------------------------------

        flow_last = flow.iloc[-1]

        bybit_last = bybit.iloc[-1]

        oi_recent = oi.tail(20)

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

        efficiency = (
            flow_last['efficiency']
        )

        imbalance = (
            book_last['imbalance']
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
        # CURRENT STATE
        # ---------------------------------

        current_state = "NEUTRAL"

        # BULLISH

        if (

            binance_delta > 0

            and

            bybit_delta > 0

            and

            imbalance > 0

            and

            oi_change > 0
        ):

            current_state = (
                "BULLISH"
            )

        # BEARISH

        elif (

            binance_delta < 0

            and

            bybit_delta < 0

            and

            imbalance < 0

            and

            oi_change > 0
        ):

            current_state = (
                "BEARISH"
            )

        # ABSORPTION

        elif (

            abs(efficiency) < 0.03

            and

            abs(binance_delta) > 100
        ):

            current_state = (
                "ABSORPTION"
            )

        # COMPRESSION

        elif (

            abs(flow_last['price_change'])
            < 20

            and

            abs(binance_delta)
            < 50
        ):

            current_state = (
                "COMPRESSION"
            )

        # ---------------------------------
        # STORE HISTORY
        # ---------------------------------

        state_history.append(
            current_state
        )

        if len(state_history) > 200:

            state_history.pop(0)

        # ---------------------------------
        # TRANSITIONS
        # ---------------------------------

        if len(state_history) >= 2:

            prev_state = (
                state_history[-2]
            )

            transition = (

                prev_state
                +
                " -> "
                +
                current_state
            )

            transition_counts[
                transition
            ] += 1

        # ---------------------------------
        # TOP TRANSITIONS
        # ---------------------------------

        sorted_transitions = sorted(

            transition_counts.items(),

            key=lambda x: x[1],

            reverse=True
        )

        top_transitions = (
            sorted_transitions[:10]
        )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "CURRENT STATE:",
            current_state
        )

        print()

        print(
            "TOP TRANSITIONS"
        )

        print()

        for t, c in top_transitions:

            print(
                t,
                "| Count:",
                c
            )

        print()

        print(
            "Current Efficiency:",
            round(
                efficiency,
                4
            )
        )

        print(
            "Current Imbalance:",
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
