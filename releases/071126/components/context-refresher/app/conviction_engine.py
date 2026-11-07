import pandas as pd
import numpy as np
import time

# ---------------------------------
# CONFIG
# ---------------------------------

SLEEP_INTERVAL = 10

print()
print("CONVICTION ENGINE STARTED")

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
        # CONVICTION SCORE
        # ---------------------------------

        conviction = 0

        # FLOW ALIGNMENT

        if (

            binance_delta > 0

            and

            bybit_delta > 0
        ):

            conviction += 2

        elif (

            binance_delta < 0

            and

            bybit_delta < 0
        ):

            conviction += 2

        # OI

        if abs(oi_change) > 10:

            conviction += 1

        # IMBALANCE

        if abs(imbalance) > 0.25:

            conviction += 1

        # EFFICIENCY

        if abs(efficiency) > 0.5:

            conviction += 1

        # VOL EXPANSION

        if realized_vol > 0.0005:

            conviction += 1

        # ---------------------------------
        # CONTEXT LABEL
        # ---------------------------------

        label = (
            "LOW_CONVICTION"
        )

        if conviction >= 6:

            label = (
                "EXTREME_ALIGNMENT"
            )

        elif conviction >= 4:

            label = (
                "HIGH_CONVICTION"
            )

        elif conviction >= 2:

            label = (
                "MEDIUM_CONVICTION"
            )

        # ---------------------------------
        # DIRECTION
        # ---------------------------------

        direction = "NEUTRAL"

        if (

            binance_delta > 0

            and

            bybit_delta > 0
        ):

            direction = (
                "BULLISH"
            )

        elif (

            binance_delta < 0

            and

            bybit_delta < 0
        ):

            direction = (
                "BEARISH"
            )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "MARKET DIRECTION:",
            direction
        )

        print()

        print(
            "CONVICTION LEVEL:",
            label
        )

        print()

        print(
            "Conviction Score:",
            conviction
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
            "Orderbook Imbalance:",
            round(
                imbalance,
                4
            )
        )

        print(
            "Flow Efficiency:",
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
