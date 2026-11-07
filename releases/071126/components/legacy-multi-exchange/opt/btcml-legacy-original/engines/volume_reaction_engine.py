import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE VOLUME REACTION ENGINE"
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

        market = market.reset_index(
            drop=True
        )

        # =================================
        # PRICE CHANGE
        # =================================

        market['price_change'] = (

            market[
                'avg_price'
            ]
            .diff()
        )

        # =================================
        # TOTAL VOLUME
        # =================================

        market['total_volume'] = (

            market[
                'buy_volume'
            ]

            +

            market[
                'sell_volume'
            ]
        )

        # =================================
        # EFFICIENCY
        # =================================

        market['delta_efficiency'] = (

            market[
                'price_change'
            ]

            /

            (
                market[
                    'delta'
                ]
                .abs()
                +
                1e-9
            )
        )

        market['volume_efficiency'] = (

            market[
                'price_change'
            ]

            /

            (
                market[
                    'total_volume'
                ]
                +
                1e-9
            )
        )

        # =================================
        # CURRENT STATE
        # =================================

        latest = market.iloc[-1]

        price_change = (
            latest[
                'price_change'
            ]
        )

        delta = (
            latest[
                'delta'
            ]
        )

        total_volume = (
            latest[
                'total_volume'
            ]
        )

        delta_efficiency = (
            latest[
                'delta_efficiency'
            ]
        )

        volume_efficiency = (
            latest[
                'volume_efficiency'
            ]
        )

        # =================================
        # CLASSIFICATION
        # =================================

        reaction = "NEUTRAL"

        # =================================
        # ABSORPTION
        # =================================

        if (

            abs(delta) > 100

            and

            abs(price_change) < 2
        ):

            reaction = (
                "ABSORPTION"
            )

        # =================================
        # INITIATIVE
        # =================================

        if (

            abs(price_change) > 10

            and

            abs(delta) > 100
        ):

            reaction = (
                "INITIATIVE_MOVE"
            )

        # =================================
        # TRAP
        # =================================

        if (

            delta > 100

            and

            price_change < 0
        ):

            reaction = (
                "BULL_TRAP"
            )

        if (

            delta < -100

            and

            price_change > 0
        ):

            reaction = (
                "BEAR_TRAP"
            )

        # =================================
        # EXHAUSTION
        # =================================

        if (

            total_volume > market[
                'total_volume'
            ].quantile(0.9)

            and

            abs(price_change) < 1
        ):

            reaction = (
                "EXHAUSTION"
            )

        # =================================
        # OUTPUT
        # =================================

        print(
            "PRICE CHANGE:",
            round(
                price_change,
                2
            )
        )

        print()

        print(
            "DELTA:",
            round(
                delta,
                2
            )
        )

        print()

        print(
            "TOTAL VOLUME:",
            round(
                total_volume,
                2
            )
        )

        print()

        print(
            "DELTA EFFICIENCY:",
            round(
                delta_efficiency,
                6
            )
        )

        print()

        print(
            "VOLUME EFFICIENCY:",
            round(
                volume_efficiency,
                6
            )
        )

        print()

        print(
            "REACTION:",
            reaction
        )

        print()

        # =================================
        # SAVE
        # =================================

        snapshot = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'reaction':
                reaction,

            'price_change':
                price_change,

            'delta':
                delta,

            'volume':
                total_volume,

            'delta_efficiency':
                delta_efficiency,

            'volume_efficiency':
                volume_efficiency
        }])

        try:

            old = pd.read_parquet(
                "volume_reactions.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "volume_reactions.parquet"
        )

        print(
            "REACTION UPDATED"
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
