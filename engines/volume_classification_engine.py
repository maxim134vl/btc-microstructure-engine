import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE VOLUME CLASSIFICATION ENGINE"
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

        clusters = pd.read_parquet(
            "volume_clusters.parquet"
        )

        flow = pd.read_parquet(
            "multi_exchange_flow.parquet"
        )

        # =================================
        # MARKET
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

        local_high = (

            market[
                'avg_price'
            ]
            .max()
        )

        local_low = (

            market[
                'avg_price'
            ]
            .min()
        )

        range_position = (

            (
                current_price
                -
                local_low
            )

            /

            (
                local_high
                -
                local_low
                +
                1e-9
            )
        )

        # =================================
        # TOP CLUSTER
        # =================================

        top_cluster = clusters.sort_values(

            'total_volume',

            ascending=False
        ).iloc[0]

        delta = top_cluster[
            'delta'
        ]

        volume = top_cluster[
            'total_volume'
        ]

        cluster_name = (
            top_cluster.name
        )

        # =================================
        # CLASSIFICATION
        # =================================

        classification = "NEUTRAL"

        # =================================
        # ABSORPTION
        # =================================

        if (

            delta < 0

            and

            range_position < 0.3

            and

            volume > clusters[
                'total_volume'
            ].quantile(0.8)
        ):

            classification = (
                "ABSORPTION_BUYING"
            )

        # =================================
        # DISTRIBUTION
        # =================================

        if (

            delta > 0

            and

            range_position > 0.7

            and

            volume > clusters[
                'total_volume'
            ].quantile(0.8)
        ):

            classification = (
                "DISTRIBUTION_SELLING"
            )

        # =================================
        # BREAKOUT PRESSURE
        # =================================

        if (

            abs(delta) > 300

            and

            volume > clusters[
                'total_volume'
            ].quantile(0.9)
        ):

            classification = (
                "BREAKOUT_PRESSURE"
            )

        # =================================
        # EXHAUSTION
        # =================================

        if (

            abs(delta) > 300

            and

            volume < clusters[
                'total_volume'
            ].median()
        ):

            classification = (
                "EXHAUSTION"
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
            "RANGE POSITION:",
            round(
                range_position,
                4
            )
        )

        print()

        print(
            "TOP CLUSTER:",
            cluster_name
        )

        print()

        print(
            "CLUSTER DELTA:",
            round(
                delta,
                2
            )
        )

        print()

        print(
            "CLUSTER VOLUME:",
            round(
                volume,
                2
            )
        )

        print()

        print(
            "CLASSIFICATION:",
            classification
        )

        print()

        # =================================
        # SAVE
        # =================================

        result = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'classification':
                classification,

            'range_position':
                range_position,

            'delta':
                delta,

            'volume':
                volume
        }])

        try:

            old = pd.read_parquet(
                "volume_classifications.parquet"
            )

            combined = pd.concat([

                old,

                result
            ])

        except:

            combined = result

        combined.to_parquet(
            "volume_classifications.parquet"
        )

        print(
            "CLASSIFICATION UPDATED"
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
