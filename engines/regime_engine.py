import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE REGIME ENGINE"
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

        market = market.reset_index(
            drop=True
        )

        # =================================
        # RETURNS
        # =================================

        market['return'] = (

            market[
                'avg_price'
            ]
            .pct_change()
        )

        # =================================
        # VOLATILITY
        # =================================

        market['volatility'] = (

            market[
                'return'
            ]
            .rolling(20)
            .std()
        )

        # =================================
        # PRESSURE
        # =================================

        market['pressure'] = (

            market[
                'delta'
            ]
            .rolling(20)
            .mean()
        )

        # =================================
        # CURRENT VALUES
        # =================================

        current_volatility = (

            market[
                'volatility'
            ]
            .iloc[-1]
        )

        current_pressure = (

            market[
                'pressure'
            ]
            .iloc[-1]
        )

        # =================================
        # REGIME LOGIC
        # =================================

        regime = "NEUTRAL"

        if current_volatility > 0.0005:

            regime = "HIGH_VOL"

        if current_pressure > 5:

            regime = "BULLISH_PRESSURE"

        if current_pressure < -5:

            regime = "BEARISH_PRESSURE"

        if (

            current_volatility > 0.0005

            and

            abs(current_pressure) > 10
        ):

            regime = "EXPANSION"

        # =================================
        # OUTPUT
        # =================================

        print(
            "CURRENT REGIME:",
            regime
        )

        print()

        print(
            "VOLATILITY:",
            round(
                current_volatility,
                6
            )
        )

        print()

        print(
            "PRESSURE:",
            round(
                current_pressure,
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

            'regime':
                regime,

            'volatility':
                current_volatility,

            'pressure':
                current_pressure
        }])

        try:

            old = pd.read_parquet(
                "regime_history.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "regime_history.parquet"
        )

        print(
            "REGIME UPDATED"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(30)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
