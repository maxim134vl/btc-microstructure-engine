import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE VOLUME CLUSTER ENGINE"
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
        # BINANCE ONLY
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
        # PRICE BINS
        # =================================

        bins = pd.cut(

            market[
                'avg_price'
            ],

            bins=25
        )

        # =================================
        # STRING LABELS
        # =================================

        market['price_cluster'] = [

            f"{round(x.left, 0)}-{round(x.right, 0)}"

            for x in bins
        ]

        # =================================
        # PROFILE
        # =================================

        profile = market.groupby(
            'price_cluster'
        ).agg({

            'buy_volume':
                'sum',

            'sell_volume':
                'sum',

            'delta':
                'sum',

            'trade_count':
                'sum'
        })

        # =================================
        # TOTAL VOLUME
        # =================================

        profile['total_volume'] = (

            profile[
                'buy_volume'
            ]

            +

            profile[
                'sell_volume'
            ]
        )

        # =================================
        # HVN / LVN
        # =================================

        hvn = profile[
            'total_volume'
        ].idxmax()

        lvn = profile[
            'total_volume'
        ].idxmin()

        # =================================
        # DELTA CLUSTERS
        # =================================

        positive_delta = profile[
            profile[
                'delta'
            ]
            >
            0
        ]

        negative_delta = profile[
            profile[
                'delta'
            ]
            <
            0
        ]

        # =================================
        # CURRENT MARKET
        # =================================

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
            "RANGE POSITION:",
            round(
                range_position,
                4
            )
        )

        print()

        print(
            "HVN:",
            hvn
        )

        print()

        print(
            "LVN:",
            lvn
        )

        print()

        print(
            "POSITIVE DELTA CLUSTERS"
        )

        print()

        print(

            positive_delta[
                [
                    'delta',
                    'total_volume'
                ]
            ]
            .tail(5)
        )

        print()

        print(
            "NEGATIVE DELTA CLUSTERS"
        )

        print()

        print(

            negative_delta[
                [
                    'delta',
                    'total_volume'
                ]
            ]
            .tail(5)
        )

        print()

        # =================================
        # SAVE
        # =================================

        profile.to_parquet(
            "volume_clusters.parquet"
        )

        print(
            "CLUSTERS UPDATED"
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
