import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE INVENTORY ENGINE"
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
        # ROLLING PRESSURE
        # =================================

        market['rolling_delta'] = (

            market[
                'delta'
            ]
            .rolling(10)
            .sum()
        )

        market['rolling_move'] = (

            market[
                'price_change'
            ]
            .rolling(10)
            .sum()
        )

        # =================================
        # CURRENT STATE
        # =================================

        latest = market.iloc[-1]

        rolling_delta = (
            latest[
                'rolling_delta'
            ]
        )

        rolling_move = (
            latest[
                'rolling_move'
            ]
        )

        total_volume = (
            latest[
                'total_volume'
            ]
        )

        current_price = (
            latest[
                'avg_price'
            ]
        )

        # =================================
        # INVENTORY LOGIC
        # =================================

        inventory_state = (
            "BALANCED"
        )

        confidence = 0.0

        # =================================
        # TRAPPED LONGS
        # =================================

        if (

            rolling_delta > 200

            and

            rolling_move <= 0
        ):

            inventory_state = (
                "TRAPPED_LONGS"
            )

            confidence = 0.8

        # =================================
        # TRAPPED SHORTS
        # =================================

        if (

            rolling_delta < -200

            and

            rolling_move >= 0
        ):

            inventory_state = (
                "TRAPPED_SHORTS"
            )

            confidence = 0.8

        # =================================
        # SHORT SQUEEZE RISK
        # =================================

        if (

            rolling_delta < -300

            and

            rolling_move > 5
        ):

            inventory_state = (
                "SHORT_SQUEEZE_RISK"
            )

            confidence = 0.9

        # =================================
        # LONG LIQUIDATION RISK
        # =================================

        if (

            rolling_delta > 300

            and

            rolling_move < -5
        ):

            inventory_state = (
                "LONG_LIQUIDATION_RISK"
            )

            confidence = 0.9

        # =================================
        # WEAK BREAKOUT
        # =================================

        if (

            abs(rolling_delta) > 200

            and

            abs(rolling_move) < 2
        ):

            inventory_state = (
                "WEAK_CONVICTION"
            )

            confidence = 0.7

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
            "ROLLING DELTA:",
            round(
                rolling_delta,
                2
            )
        )

        print()

        print(
            "ROLLING MOVE:",
            round(
                rolling_move,
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
            "INVENTORY STATE:",
            inventory_state
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

            'rolling_delta':
                rolling_delta,

            'rolling_move':
                rolling_move,

            'inventory_state':
                inventory_state,

            'confidence':
                confidence
        }])

        try:

            old = pd.read_parquet(
                "inventory_states.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "inventory_states.parquet"
        )

        print(
            "INVENTORY UPDATED"
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
