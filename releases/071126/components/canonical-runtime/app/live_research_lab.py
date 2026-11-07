import pandas as pd
import numpy as np
import time
import os

# =================================
# LOOP
# =================================

while True:

    try:

        # =================================
        # CLEAR SCREEN
        # =================================

        os.system("clear")

        # =================================
        # LOAD DATA
        # =================================

        print()
        print("LOADING DATA")
        print()

        flow = pd.read_parquet(
            "intraday_flow.parquet"
        )

        oi = pd.read_parquet(
            "oi_history.parquet"
        )

        book = pd.read_parquet(
            "orderbook.parquet"
        )

        events = pd.read_parquet(
            "market_events.parquet"
        )

        # =================================
        # ALIGN
        # =================================

        min_len = min(

            len(flow),

            len(oi),

            len(book)
        )

        flow = flow.tail(min_len)

        oi = oi.tail(min_len)

        book = book.tail(min_len)

        # =================================
        # FEATURES
        # =================================

        print("BUILDING FEATURES")
        print()

        # DELTA

        flow['delta_smooth'] = (

            flow['delta']
            .rolling(50)
            .mean()
        )

        # VOL

        returns = (

            flow['avg_price']
            .pct_change()
        )

        flow['volatility'] = (

            returns
            .rolling(50)
            .std()
        )

        # OI

        oi['oi_change'] = (

            oi['open_interest']
            .diff()
        )

        # IMBALANCE

        book['imbalance_smooth'] = (

            book['imbalance']
            .rolling(50)
            .mean()
        )

        # =================================
        # OI Z-SCORE
        # =================================

        WINDOW = 200

        oi['oi_z'] = (

            (
                oi['oi_change']
                -
                oi['oi_change']
                .rolling(WINDOW)
                .mean()
            )

            /

            oi['oi_change']
            .rolling(WINDOW)
            .std()
        )

        # =================================
        # CURRENT STATE
        # =================================

        latest_price = (
            flow.iloc[-1][
                'avg_price'
            ]
        )

        latest_delta = (
            flow.iloc[-1][
                'delta_smooth'
            ]
        )

        latest_vol = (
            flow.iloc[-1][
                'volatility'
            ]
        )

        latest_oi = (
            oi.iloc[-1][
                'oi_change'
            ]
        )

        latest_imbalance = (
            book.iloc[-1][
                'imbalance_smooth'
            ]
        )

        latest_oi_z = abs(

            oi.iloc[-1][
                'oi_z'
            ]
        )

        # =================================
        # MARKET REGIME
        # =================================

        market_state = "UNDEFINED"

        # QUIET

        if (

            latest_vol < 0.00001

            and

            abs(latest_delta) < 10
        ):

            market_state = (
                "QUIET_COMPRESSION"
            )

        # IMBALANCE

        elif (

            latest_vol < 0.00001

            and

            abs(latest_imbalance) > 0.1
        ):

            market_state = (
                "PASSIVE_IMBALANCE"
            )

        # LEVERAGE

        elif (

            latest_oi_z > 5

            and

            latest_vol < 0.00005
        ):

            market_state = (
                "LEVERAGE_BUILDUP"
            )

        # VOL EXPANSION

        elif (

            latest_vol > 0.00005

            and

            abs(latest_delta) > 50
        ):

            market_state = (
                "VOLATILITY_EXPANSION"
            )

        # TREND

        elif (

            abs(latest_delta) > 100
        ):

            market_state = (
                "AGGRESSIVE_TREND"
            )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print("LIVE MARKET STATE")
        print("================================")
        print()

        print(
            "PRICE:",
            round(
                latest_price,
                2
            )
        )

        print(
            "DELTA PRESSURE:",
            round(
                latest_delta,
                2
            )
        )

        print(
            "VOLATILITY:",
            round(
                latest_vol,
                8
            )
        )

        print(
            "OI CHANGE:",
            round(
                latest_oi,
                2
            )
        )

        print(
            "OI Z-SCORE:",
            round(
                latest_oi_z,
                2
            )
        )

        print(
            "IMBALANCE:",
            round(
                latest_imbalance,
                4
            )
        )

        print()

        print(
            "CURRENT STATE:",
            market_state
        )

        print()

        # =================================
        # EVENT DISTRIBUTION
        # =================================

        print("================================")
        print("EVENTS")
        print("================================")
        print()

        print(

            events['event']
            .value_counts()
        )

        print()

        # =================================
        # INTERPRETATION
        # =================================

        print("================================")
        print("INTERPRETATION")
        print("================================")
        print()

        if latest_vol < 0.00001:

            print(
                "- Low volatility regime"
            )

        else:

            print(
                "- Elevated volatility"
            )

        if abs(latest_imbalance) > 0.2:

            print(
                "- Persistent liquidity skew"
            )

        if latest_oi_z > 5:

            print(
                "- Extreme leverage anomaly"
            )

        if abs(latest_delta) > 50:

            print(
                "- Aggressive directional pressure"
            )

        print()

        print(
            "NEXT UPDATE: 60 SECONDS"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(60)

    except Exception as e:

        print()
        print("ERROR")
        print(e)
        print()

        time.sleep(10)
