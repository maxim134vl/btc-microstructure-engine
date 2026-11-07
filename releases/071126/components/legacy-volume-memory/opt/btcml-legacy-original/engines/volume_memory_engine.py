import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE VOLUME MEMORY ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # =================================
        # LOAD CLUSTERS
        # =================================

        clusters = pd.read_parquet(
            "volume_clusters.parquet"
        )

        # =================================
        # LOAD FLOW
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
        # CURRENT PRICE
        # =================================

        current_price = (

            market[
                'avg_price'
            ]
            .iloc[-1]
        )

        # =================================
        # TOP MEMORY ZONES
        # =================================

        top_zones = clusters.sort_values(

            'total_volume',

            ascending=False
        ).head(5)

        # =================================
        # ZONE PARSER
        # =================================

        def parse_zone(zone):

            left, right = zone.split('-')

            return (

                float(left),

                float(right)
            )

        # =================================
        # MEMORY ANALYSIS
        # =================================

        memory_state = (
            "NO_INTERACTION"
        )

        nearest_zone = None

        nearest_distance = 999999

        for zone in top_zones.index:

            left, right = parse_zone(
                zone
            )

            center = (
                left
                +
                right
            ) / 2

            distance = abs(

                current_price
                -
                center
            )

            if distance < nearest_distance:

                nearest_distance = distance

                nearest_zone = zone

        # =================================
        # INTERACTION LOGIC
        # =================================

        if nearest_distance < 10:

            memory_state = (
                "RETURN_TO_HVN"
            )

        if nearest_distance < 5:

            memory_state = (
                "DIRECT_MEMORY_TEST"
            )

        # =================================
        # REJECTION CHECK
        # =================================

        recent_high = (

            market[
                'avg_price'
            ]
            .tail(20)
            .max()
        )

        recent_low = (

            market[
                'avg_price'
            ]
            .tail(20)
            .min()
        )

        if (

            abs(
                recent_high
                -
                current_price
            )
            < 3
        ):

            memory_state = (
                "REJECTION_FROM_MEMORY"
            )

        if (

            abs(
                recent_low
                -
                current_price
            )
            < 3
        ):

            memory_state = (
                "DEFENSE_AT_MEMORY"
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
            "NEAREST MEMORY ZONE:",
            nearest_zone
        )

        print()

        print(
            "DISTANCE:",
            round(
                nearest_distance,
                2
            )
        )

        print()

        print(
            "MEMORY STATE:",
            memory_state
        )

        print()

        print(
            "TOP MEMORY ZONES"
        )

        print()

        print(

            top_zones[
                [
                    'delta',
                    'total_volume'
                ]
            ]
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

            'nearest_zone':
                nearest_zone,

            'distance':
                nearest_distance,

            'memory_state':
                memory_state
        }])

        try:

            old = pd.read_parquet(
                "volume_memory.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "volume_memory.parquet"
        )

        print(
            "MEMORY UPDATED"
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
