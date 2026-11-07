import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

print()
print("MARKET PRESSURE ENGINE STARTED")

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
        # PRESSURE SCORE
        # ---------------------------------

        bullish_pressure = 0

        bearish_pressure = 0

        # FLOW

        if (

            binance_delta > 0

            and

            bybit_delta > 0
        ):

            bullish_pressure += 2

        elif (

            binance_delta < 0

            and

            bybit_delta < 0
        ):

            bearish_pressure += 2

        # OI

        if oi_change > 10:

            if binance_delta > 0:

                bullish_pressure += 1

            elif binance_delta < 0:

                bearish_pressure += 1

        # IMBALANCE

        if imbalance > 0.2:

            bullish_pressure += 1

        elif imbalance < -0.2:

            bearish_pressure += 1

        # EFFICIENCY

        if efficiency > 0.5:

            bullish_pressure += 1

        elif efficiency < -0.5:

            bearish_pressure += 1

        # VOLATILITY

        if realized_vol > 0.0005:

            bullish_pressure += 1

            bearish_pressure += 1

        # ---------------------------------
        # STATE
        # ---------------------------------

        state = (
            "NEUTRAL_PRESSURE"
        )

        if bullish_pressure >= 5:

            state = (
                "BULLISH_PRESSURE_BUILDING"
            )

        elif bearish_pressure >= 5:

            state = (
                "BEARISH_PRESSURE_BUILDING"
            )

        elif (

            bullish_pressure >= 3

            and

            bearish_pressure >= 3
        ):

            state = (
                "PRESSURE_CONFLICT"
            )

        elif (

            bullish_pressure >= 4

            and

            efficiency < 0.1
        ):

            state = (
                "BULLISH_PRESSURE_EXHAUSTION"
            )

        elif (

            bearish_pressure >= 4

            and

            efficiency > -0.1
        ):

            state = (
                "BEARISH_PRESSURE_EXHAUSTION"
            )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "PRESSURE STATE:",
            state
        )

        print()

        print(
            "Bullish Pressure:",
            bullish_pressure
        )

        print(
            "Bearish Pressure:",
            bearish_pressure
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
            "Imbalance:",
            round(
                imbalance,
                4
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
            "Realized Vol:",
            round(
                realized_vol,
                8
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
