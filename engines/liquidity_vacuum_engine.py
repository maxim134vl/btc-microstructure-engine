import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE LIQUIDITY VACUUM ENGINE"
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

        current_price = (

            market[
                'avg_price'
            ]
            .iloc[-1]
        )

        # =================================
        # LOW VOLUME NODES
        # =================================

        low_volume_threshold = (

            clusters[
                'total_volume'
            ]
            .quantile(0.2)
        )

        lvn = clusters[

            clusters[
                'total_volume'
            ]
            <
            low_volume_threshold
        ]

        # =================================
        # PARSE ZONES
        # =================================

        def parse_zone(zone):

            left, right = zone.split('-')

            return (

                float(left),

                float(right)
            )

        # =================================
        # VACUUM DETECTION
        # =================================

        vacuum_state = (
            "NORMAL_LIQUIDITY"
        )

        nearest_vacuum = None

        nearest_distance = 999999

        for zone in lvn.index:

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

                nearest_vacuum = zone

        # =================================
        # CLASSIFICATION
        # =================================

        if nearest_distance < 20:

            vacuum_state = (
                "APPROACHING_VACUUM"
            )

        if nearest_distance < 10:

            vacuum_state = (
                "INSIDE_VACUUM"
            )

        if nearest_distance < 5:

            vacuum_state = (
                "VACUUM_ACCELERATION_RISK"
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
            "NEAREST VACUUM:",
            nearest_vacuum
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
            "VACUUM STATE:",
            vacuum_state
        )

        print()

        print(
            "LOW VOLUME ZONES"
        )

        print()

        print(

            lvn[
                [
                    'delta',
                    'total_volume'
                ]
            ]
            .sort_values(
                'total_volume'
            )
            .head(10)
        )

        print()

        # =================================
        # SAVE
        # =================================

        snapshot = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'price':
                current_price,

            'nearest_vacuum':
                nearest_vacuum,

            'distance':
                nearest_distance,

            'vacuum_state':
                vacuum_state
        }])

        try:

            old = pd.read_parquet(
                "liquidity_vacuums.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "liquidity_vacuums.parquet"
        )

        print(
            "VACUUM UPDATED"
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
