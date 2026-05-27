import requests
import pandas as pd
import numpy as np
import time

from datetime import datetime

# =================================
# START
# =================================

print()
print(
    "HYPERLIQUID PERSISTENT COLLECTOR"
)
print()

# =================================
# LOOP
# =================================

while True:

    try:

        # =================================
        # REQUEST
        # =================================

        url = (
            "https://api.hyperliquid.xyz/info"
        )

        payload = {

            "type":
                "recentTrades",

            "coin":
                "BTC"
        }

        response = requests.post(

            url,

            json=payload,

            timeout=30
        )

        trades = response.json()

        # =================================
        # BUILD DATAFRAME
        # =================================

        rows = []

        for trade in trades:

            try:

                side = 'Buy'

                if trade.get('side') == 'A':

                    side = 'Sell'

                rows.append({

                    'timestamp':
                        datetime.utcnow(),

                    'exchange':
                        'HYPERLIQUID',

                    'price':
                        float(
                            trade[
                                'px'
                            ]
                        ),

                    'size':
                        float(
                            trade[
                                'sz'
                            ]
                        ),

                    'side':
                        side
                })

            except:

                continue

        trades_df = pd.DataFrame(
            rows
        )

        # =================================
        # FEATURES
        # =================================

        buy_volume = (

            trades_df[
                trades_df[
                    'side'
                ]
                ==
                'Buy'
            ][
                'size'
            ]
            .sum()
        )

        sell_volume = (

            trades_df[
                trades_df[
                    'side'
                ]
                ==
                'Sell'
            ][
                'size'
            ]
            .sum()
        )

        delta = (

            buy_volume

            -

            sell_volume
        )

        avg_price = (

            trades_df[
                'price'
            ]
            .mean()
        )

        price_change = (

            trades_df[
                'price'
            ]
            .iloc[-1]

            -

            trades_df[
                'price'
            ]
            .iloc[0]
        )

        total_volume = (

            buy_volume

            +

            sell_volume
        )

        efficiency = (

            abs(
                price_change
            )

            /

            (
                total_volume
                +
                1
            )
        )

        # =================================
        # SNAPSHOT
        # =================================

        snapshot = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'exchange':
                'HYPERLIQUID',

            'buy_volume':
                buy_volume,

            'sell_volume':
                sell_volume,

            'delta':
                delta,

            'trade_count':
                len(trades_df),

            'avg_price':
                avg_price,

            'price_change':
                price_change,

            'efficiency':
                efficiency
        }])

        # =================================
        # LOAD OLD
        # =================================

        try:

            old = pd.read_parquet(
                "hyperliquid_flow.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        # =================================
        # SAVE
        # =================================

        combined.to_parquet(
            "hyperliquid_flow.parquet"
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")

        print(
            datetime.utcnow()
        )

        print("================================")

        print()

        print(
            "TOTAL ROWS:",
            len(combined)
        )

        print()

        print(
            "BUY VOLUME:",
            round(
                buy_volume,
                2
            )
        )

        print(
            "SELL VOLUME:",
            round(
                sell_volume,
                2
            )
        )

        print(
            "DELTA:",
            round(
                delta,
                2
            )
        )

        print(
            "PRICE CHANGE:",
            round(
                price_change,
                2
            )
        )

        print(
            "EFFICIENCY:",
            round(
                efficiency,
                6
            )
        )

        print()

        print(
            "UPDATED SUCCESSFULLY"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(5)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
