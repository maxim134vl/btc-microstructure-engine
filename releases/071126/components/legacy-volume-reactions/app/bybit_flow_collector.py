import requests
import pandas as pd
import time
from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

SAVE_INTERVAL = 5

PARQUET_FILE = (
    "bybit_flow.parquet"
)

# ---------------------------------
# STORAGE
# ---------------------------------

history = []

snapshots = []

print()
print("BYBIT FLOW COLLECTOR STARTED")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # API
        # ---------------------------------

        url = (
            "https://api.bybit.com"
            "/v5/market/recent-trade"
        )

        params = {

            "category": "linear",

            "symbol": "BTCUSDT",

            "limit": 1000
        }

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        data = response.json()

        # ---------------------------------
        # VALIDATE
        # ---------------------------------

        if (
            'result' not in data
            or
            'list' not in data['result']
        ):

            print()
            print("API ERROR")

            print(data)

            time.sleep(SAVE_INTERVAL)

            continue

        trades = (
            data['result']['list']
        )

        # ---------------------------------
        # PARSE
        # ---------------------------------

        parsed = []

        for t in trades:

            parsed.append({

                'timestamp':

                    datetime.fromtimestamp(
                        int(t['time']) / 1000
                    ),

                'price':

                    float(t['price']),

                'qty':

                    float(t['size']),

                'side':

                    t['side'].lower()
            })

        history.extend(parsed)

        # ---------------------------------
        # DATAFRAME
        # ---------------------------------

        df = pd.DataFrame(history)

        recent = df.tail(5000)

        # ---------------------------------
        # FLOW
        # ---------------------------------

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

        trade_count = len(recent)

        avg_price = (
            recent['price']
            .mean()
        )

        price_change = (

            recent['price'].iloc[-1]

            -

            recent['price'].iloc[0]
        )

        # ---------------------------------
        # EFFICIENCY
        # ---------------------------------

        efficiency = 0

        if abs(delta) > 0:

            efficiency = (
                price_change / delta
            )

        # ---------------------------------
        # SNAPSHOT
        # ---------------------------------

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
                trade_count,

            'avg_price':
                avg_price,

            'price_change':
                price_change,

            'efficiency':
                efficiency
        }

        snapshots.append(snapshot)

        # ---------------------------------
        # SAVE
        # ---------------------------------

        snap_df = pd.DataFrame(
            snapshots
        )

        snap_df.to_parquet(
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

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(SAVE_INTERVAL)

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(SAVE_INTERVAL)
