import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE STRUCTURE ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # =================================
        # LOAD
        # =================================

        flow = pd.read_parquet(
            "multi_exchange_flow.parquet"
        )

        # =================================
        # BINANCE MARKET
        # =================================

        market = flow[
            flow['exchange']
            ==
            'BINANCE'
        ].copy()

        market = market.sort_values(
            'timestamp'
        )

        market = market.tail(500)

        # =================================
        # PRICE SERIES
        # =================================

        prices = market[
            'avg_price'
        ].values

        # =================================
        # CURRENT PRICE
        # =================================

        current_price = (
            prices[-1]
        )

        # =================================
        # LOCAL STRUCTURE
        # =================================

        local_high = (
            np.max(prices)
        )

        local_low = (
            np.min(prices)
        )

        # =================================
        # PIVOTS
        # =================================

        rolling_high = (

            market[
                'avg_price'
            ]
            .rolling(20)
            .max()
        )

        rolling_low = (

            market[
                'avg_price'
            ]
            .rolling(20)
            .min()
        )

        resistance = (
            rolling_high.iloc[-1]
        )

        support = (
            rolling_low.iloc[-1]
        )

        # =================================
        # DISTANCE
        # =================================

        resistance_distance = (

            (
                resistance
                -
                current_price
            )

            /

            current_price
        )

        support_distance = (

            (
                current_price
                -
                support
            )

            /

            current_price
        )

        # =================================
        # BREAKOUT LOGIC
        # =================================

        breakout_up = (
            current_price
            >
            resistance
        )

        breakout_down = (
            current_price
            <
            support
        )

        # =================================
        # STRUCTURE STATE
        # =================================

        structure = "RANGE"

        if resistance_distance < 0.001:

            structure = (
                "NEAR_RESISTANCE"
            )

        if support_distance < 0.001:

            structure = (
                "NEAR_SUPPORT"
            )

        if breakout_up:

            structure = (
                "BREAKOUT_UP"
            )

        if breakout_down:

            structure = (
                "BREAKOUT_DOWN"
            )

        # =================================
        # OUTPUT
        # =================================

        print(
            "CURRENT PRICE:",
            round(
                current_price,
                2
            )
        )

        print()

        print(
            "LOCAL HIGH:",
            round(
                local_high,
                2
            )
        )

        print()

        print(
            "LOCAL LOW:",
            round(
                local_low,
                2
            )
        )

        print()

        print(
            "RESISTANCE:",
            round(
                resistance,
                2
            )
        )

        print()

        print(
            "SUPPORT:",
            round(
                support,
                2
            )
        )

        print()

        print(
            "DISTANCE TO RESISTANCE:",
            round(
                resistance_distance,
                5
            )
        )

        print()

        print(
            "DISTANCE TO SUPPORT:",
            round(
                support_distance,
                5
            )
        )

        print()

        print(
            "STRUCTURE:",
            structure
        )

        print()

        # =================================
        # SAVE
        # =================================

        snapshot = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'current_price':
                current_price,

            'resistance':
                resistance,

            'support':
                support,

            'structure':
                structure
        }])

        try:

            old = pd.read_parquet(
                "market_structure.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "market_structure.parquet"
        )

        print(
            "STRUCTURE UPDATED"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(60)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
