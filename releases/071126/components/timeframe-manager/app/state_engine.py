import pandas as pd
import numpy as np
import time

SLEEP_INTERVAL = 10

print()
print("STATE ENGINE STARTED")

while True:

    try:

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

        flow_last = flow.iloc[-1]

        bybit_last = bybit.iloc[-1]

        oi_recent = oi.tail(10)

        book_last = book.iloc[-1]

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

        state = "NEUTRAL"

        # ---------------------------------
        # BULLISH CONTINUATION
        # ---------------------------------

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
                "BULLISH CONTINUATION"
            )

        # ---------------------------------
        # BEARISH CONTINUATION
        # ---------------------------------

        if (

            binance_delta < 0

            and

            bybit_delta < 0

            and

            oi_change > 0

            and

            imbalance < 0
        ):

            state = (
                "BEARISH CONTINUATION"
            )

        # ---------------------------------
        # ABSORPTION
        # ---------------------------------

        if (

            abs(
                flow_last['efficiency']
            ) < 0.03

            and

            abs(binance_delta) > 100
        ):

            state = (
                "ABSORPTION"
            )

        print()
        print("================================")

        print(
            "MARKET STATE:",
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
            "Orderbook Imbalance:",
            round(
                imbalance,
                4
            )
        )

        print(
            "Flow Efficiency:",
            round(
                flow_last['efficiency'],
                4
            )
        )

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
