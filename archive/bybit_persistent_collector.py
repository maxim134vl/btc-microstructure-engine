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
    "BYBIT PERSISTENT COLLECTOR"
)
print()

# =================================
# LOOP
# =================================

while True:

    try:

        # =================================
        # REQUEST TRADES
        # =================================

        url = (

            "https://api.bybit.com"
            "/v5/market/recent-trade"
            "?category=linear"
            "&symbol=BTCUSDT"
            "&limit=1000"
        )

        response = requests.get(

            url,

            timeout=30
        )

        data = (

            response.json()
        )

        trades = data[
            'result'
        ][
            'list'
        ]

        # =================================
        # BUILD DATAFRAME
        # =================================

        rows = []

        for trade in trades:

            try:

                rows.append({

                    'timestamp':
                        datetime.utcnow(),

                    'exchange':
                        'BYBIT',

                    'price':
                        float(
                            trade[
                                'price'
                            ]
                        ),

                    'size':
                        float(
                            trade[
                                'size'
                            ]
                        ),

                    'side':
                        trade[
                            'side'
                        ]
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
                'BYBIT',

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
                "bybit_flow.parquet"
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
            "bybit_flow.parquet"
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
