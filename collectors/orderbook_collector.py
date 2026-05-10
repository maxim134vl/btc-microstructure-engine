import requests
import pandas as pd
import time
import urllib3

from datetime import datetime

urllib3.disable_warnings()

# ---------------------------------
# CONFIG
# ---------------------------------

SAVE_INTERVAL = 5

PARQUET_FILE = (
    "orderbook.parquet"
)

# ---------------------------------
# STORAGE
# ---------------------------------

snapshots = []

print()
print("ORDERBOOK COLLECTOR STARTED")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # API
        # ---------------------------------

        url = (
            "https://fapi.binance.com"
            "/fapi/v1/depth"
        )

        params = {

            "symbol": "BTCUSDT",

            "limit": 20
        }

        response = requests.get(
            url,
            params=params,
            timeout=30,
            verify=False
        )

        data = response.json()

        bids = data['bids']

        asks = data['asks']

        # ---------------------------------
        # LIQUIDITY
        # ---------------------------------

        bid_liquidity = 0

        ask_liquidity = 0

        for b in bids:

            bid_liquidity += (
                float(b[0])
                *
                float(b[1])
            )

        for a in asks:

            ask_liquidity += (
                float(a[0])
                *
                float(a[1])
            )

        imbalance = 0

        total = (
            bid_liquidity
            +
            ask_liquidity
        )

        if total > 0:

            imbalance = (

                (
                    bid_liquidity
                    -
                    ask_liquidity
                )

                /

                total
            )

        # ---------------------------------
        # MID PRICE
        # ---------------------------------

        best_bid = float(
            bids[0][0]
        )

        best_ask = float(
            asks[0][0]
        )

        mid_price = (
            best_bid + best_ask
        ) / 2

        # ---------------------------------
        # SNAPSHOT
        # ---------------------------------

        snapshot = {

            'timestamp':
                datetime.utcnow(),

            'bid_liquidity':
                bid_liquidity,

            'ask_liquidity':
                ask_liquidity,

            'imbalance':
                imbalance,

            'mid_price':
                mid_price
        }

        snapshots.append(snapshot)

        # ---------------------------------
        # SAVE
        # ---------------------------------

        df = pd.DataFrame(
            snapshots
        )

        df.to_parquet(
            PARQUET_FILE,
            index=False
        )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "Snapshots:",
            len(df)
        )

        print(
            "Bid Liquidity:",
            round(
                bid_liquidity,
                2
            )
        )

        print(
            "Ask Liquidity:",
            round(
                ask_liquidity,
                2
            )
        )

        print(
            "Imbalance:",
            round(
                imbalance,
                4
            )
        )

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(SAVE_INTERVAL)

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(SAVE_INTERVAL)
