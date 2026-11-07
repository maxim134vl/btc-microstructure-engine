import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE ACCEPTANCE ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

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

        market = market.reset_index(
            drop=True
        )

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
        # RECENT RANGE
        # =================================

        recent_high = (

            market[
                'avg_price'
            ]
            .tail(50)
            .max()
        )

        recent_low = (

            market[
                'avg_price'
            ]
            .tail(50)
            .min()
        )

        midpoint = (

            recent_high
            +
            recent_low
        ) / 2

        # =================================
        # PRICE ROTATION
        # =================================

        market['distance_to_mid'] = (

            market[
                'avg_price'
            ]
            -
            midpoint
        ).abs()

        avg_rotation = (

            market[
                'distance_to_mid'
            ]
            .mean()
        )

        # =================================
        # VOLUME
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

        avg_volume = (

            market[
                'total_volume'
            ]
            .mean()
        )

        current_volume = (

            market[
                'total_volume'
            ]
            .iloc[-1]
        )

        # =================================
        # ACCEPTANCE LOGIC
        # =================================

        state = (
            "NEUTRAL"
        )

        confidence = 0.0

        # =================================
        # ACCEPTANCE
        # =================================

        if (

            avg_rotation < 15

            and

            avg_volume > 20
        ):

            state = (
                "PRICE_ACCEPTANCE"
            )

            confidence = 0.7

        # =================================
        # REJECTION
        # =================================

        if (

            abs(
                current_price
                -
                recent_high
            )
            < 5

            and

            current_volume > avg_volume
        ):

            state = (
                "REJECTION_FROM_HIGH"
            )

            confidence = 0.8

        if (

            abs(
                current_price
                -
                recent_low
            )
            < 5

            and

            current_volume > avg_volume
        ):

            state = (
                "REJECTION_FROM_LOW"
            )

            confidence = 0.8

        # =================================
        # FAILED ACCEPTANCE
        # =================================

        if (

            avg_rotation > 25

            and

            current_volume > avg_volume
        ):

            state = (
                "FAILED_ACCEPTANCE"
            )

            confidence = 0.75

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
            "RECENT HIGH:",
            round(
                recent_high,
                2
            )
        )

        print()

        print(
            "RECENT LOW:",
            round(
                recent_low,
                2
            )
        )

        print()

        print(
            "MIDPOINT:",
            round(
                midpoint,
                2
            )
        )

        print()

        print(
            "AVG ROTATION:",
            round(
                avg_rotation,
                2
            )
        )

        print()

        print(
            "CURRENT VOLUME:",
            round(
                current_volume,
                2
            )
        )

        print()

        print(
            "STATE:",
            state
        )

        print()

        print(
            "CONFIDENCE:",
            round(
                confidence,
                2
            )
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

            'state':
                state,

            'confidence':
                confidence,

            'rotation':
                avg_rotation
        }])

        try:

            old = pd.read_parquet(
                "acceptance_states.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "acceptance_states.parquet"
        )

        print(
            "ACCEPTANCE UPDATED"
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
