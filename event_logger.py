import pandas as pd
import numpy as np
import time
import os

from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

EVENT_FILE = (
    "market_events.parquet"
)

SLEEP_INTERVAL = 10

# ---------------------------------
# LOAD EVENTS
# ---------------------------------

if os.path.exists(
    EVENT_FILE
):

    events = pd.read_parquet(
        EVENT_FILE
    )

    events = events.to_dict(
        'records'
    )

    print()
    print(
        "LOADED EVENTS:",
        len(events)
    )

else:

    events = []

print()
print(
    "EVENT LOGGER STARTED"
)

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
        # VOL
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
        # EVENT
        # ---------------------------------

        event = None

        # BULL PRESSURE

        if (

            binance_delta > 100

            and

            bybit_delta > 100

            and

            oi_change > 5
        ):

            event = (
                "BULLISH_PRESSURE"
            )

        # BEAR PRESSURE

        elif (

            binance_delta < -100

            and

            bybit_delta < -100

            and

            oi_change > 5
        ):

            event = (
                "BEARISH_PRESSURE"
            )

        # ABSORPTION

        elif (

            abs(efficiency)
            <
            0.03

            and

            abs(binance_delta)
            >
            100
        ):

            event = (
                "ABSORPTION"
            )

        # VOL EXPANSION

        elif (

            realized_vol
            >
            0.001
        ):

            event = (
                "VOL_EXPANSION"
            )

        # IMBALANCE

        elif (

            abs(imbalance)
            >
            0.4
        ):

            event = (
                "ORDERBOOK_IMBALANCE"
            )

        # ---------------------------------
        # SAVE EVENT
        # ---------------------------------

        if event is not None:

            row = {

                'timestamp':
                    datetime.utcnow(),

                'event':
                    event,

                'binance_delta':
                    binance_delta,

                'bybit_delta':
                    bybit_delta,

                'oi_change':
                    oi_change,

                'efficiency':
                    efficiency,

                'imbalance':
                    imbalance,

                'realized_vol':
                    realized_vol
            }

            events.append(
                row
            )

            df = pd.DataFrame(
                events
            )

            df = df.drop_duplicates()

            df.to_parquet(

                EVENT_FILE,

                index=False
            )

            # ---------------------------------
            # PRINT
            # ---------------------------------

            print()
            print("================================")

            print(
                "EVENT:",
                event
            )

            print()

            print(
                "TOTAL EVENTS:",
                len(df)
            )

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
                "Imbalance:",
                round(
                    imbalance,
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
