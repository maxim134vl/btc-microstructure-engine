import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

# ---------------------------------
# MEMORY
# ---------------------------------

state_memory = []

vol_memory = []

print()
print("MARKET MEMORY ENGINE STARTED")

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
        # VOLATILITY
        # ---------------------------------

        returns = (

            flow.tail(100)[
                'avg_price'
            ]
            .pct_change()
            .dropna()
        )

        realized_vol = (
            returns.std()
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

        # ---------------------------------
        # STORE MEMORY
        # ---------------------------------

        state_memory.append(
            current_state
        )

        vol_memory.append(
            realized_vol
        )

        # LIMIT MEMORY

        if len(state_memory) > 100:

            state_memory.pop(0)

        if len(vol_memory) > 100:

            vol_memory.pop(0)

        # ---------------------------------
        # CONTEXT ANALYSIS
        # ---------------------------------

        bullish_count = (
            state_memory.count(
                "BULLISH"
            )
        )

        bearish_count = (
            state_memory.count(
                "BEARISH"
            )
        )

        absorption_count = (
            state_memory.count(
                "ABSORPTION"
            )
        )

        avg_vol = np.mean(
            vol_memory
        )

        # ---------------------------------
        # MEMORY STATES
        # ---------------------------------

        memory_state = (
            "BALANCED_CONTEXT"
        )

        # TREND BUILDUP

        if bullish_count > 30:

            memory_state = (
                "EXTENDED_BULLISH_PRESSURE"
            )

        elif bearish_count > 30:

            memory_state = (
                "EXTENDED_BEARISH_PRESSURE"
            )

        # ABSORPTION CLUSTER

        elif absorption_count > 20:

            memory_state = (
                "PROLONGED_ABSORPTION"
            )

        # VOL COMPRESSION

        elif realized_vol < (
            avg_vol * 0.6
        ):

            memory_state = (
                "VOLATILITY_COMPRESSION"
            )

        # VOL EXPANSION

        elif realized_vol > (
            avg_vol * 1.8
        ):

            memory_state = (
                "VOLATILITY_EXPANSION"
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
            "MEMORY CONTEXT:",
            memory_state
        )

        print()

        print(
            "Bullish Memory:",
            bullish_count
        )

        print(
            "Bearish Memory:",
            bearish_count
        )

        print(
            "Absorption Memory:",
            absorption_count
        )

        print()

        print(
            "Current Vol:",
            round(
                realized_vol,
                8
            )
        )

        print(
            "Average Vol:",
            round(
                avg_vol,
                8
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
