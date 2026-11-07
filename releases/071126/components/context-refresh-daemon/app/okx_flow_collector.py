import requests
import pandas as pd
import time
import urllib3

from datetime import datetime

urllib3.disable_warnings()

SAVE_INTERVAL = 5

PARQUET_FILE = (
    "okx_flow.parquet"
)

history = []

snapshots = []

print()
print("OKX FLOW COLLECTOR STARTED")

while True:

    try:

        url = (
            "https://www.okx.com"
            "/api/v5/market/trades"
        )

        params = {

            "instId": "BTC-USDT-SWAP",

            "limit": "100"
        }

        response = requests.get(
            url,
            params=params,
            timeout=30,
            verify=False
        )

        data = response.json()

        if 'data' not in data:

            print()
            print("API ERROR")

            print(data)

            time.sleep(SAVE_INTERVAL)

            continue

        trades = data['data']

        parsed = []

        for t in trades:

            parsed.append({

                'timestamp':

                    datetime.fromtimestamp(
                        int(t['ts']) / 1000
                    ),

                'price':

                    float(t['px']),

                'qty':

                    float(t['sz']),

                'side':

                    t['side']
            })

        history.extend(parsed)

        df = pd.DataFrame(history)

        recent = df.tail(5000)

        buy_volume = (

            recent[
                recent['side'] == 'buy'
            ]['qty']
            .sum()
        )

        sell_volume = (

            recent[
                recent['side'] == 'sell'
            ]['qty']
            .sum()
        )

        delta = (
            buy_volume - sell_volume
        )

        avg_price = (
            recent['price']
            .mean()
        )

        price_change = (

            recent['price'].iloc[-1]

            -

            recent['price'].iloc[0]
        )

        efficiency = 0

        if abs(delta) > 0:

            efficiency = (
                price_change / delta
            )

        snapshot = {

            'timestamp':
                datetime.utcnow(),

            'buy_volume':
                buy_volume,

            'sell_volume':
                sell_volume,

            'delta':
                delta,

            'trade_count':
                len(recent),

            'avg_price':
                avg_price,

            'price_change':
                price_change,

            'efficiency':
                efficiency
        }

        snapshots.append(snapshot)

        snap_df = pd.DataFrame(
            snapshots
        )

        snap_df.to_parquet(
            PARQUET_FILE,
            index=False
        )

        print()
        print("================================")

        print(
            "Snapshots:",
            len(snap_df)
        )

        print(
            "Delta:",
            round(delta, 2)
        )

        print(
            "Price Change:",
            round(price_change, 2)
        )

        print(
            "Efficiency:",
            round(efficiency, 4)
        )

        time.sleep(SAVE_INTERVAL)

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(SAVE_INTERVAL)
