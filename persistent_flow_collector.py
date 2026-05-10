import requests
import pandas as pd
import time
from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

SAVE_INTERVAL = 5

PARQUET_FILE = (
    "intraday_flow.parquet"
)

# ---------------------------------
# STORAGE
# ---------------------------------

history = []

snapshots = []

last_trade_id = None

print("STARTING PERSISTENT FLOW COLLECTOR")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # GET AGG TRADES
        # ---------------------------------

        url = (
            "https://fapi.binance.com/"
            "fapi/v1/aggTrades"
        )

        params = {
            "symbol": "BTCUSDT",
            "limit": 1000
        }

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        trades = response.json()

        if not isinstance(trades, list):

            print("API ERROR")

            print(trades)

            time.sleep(SAVE_INTERVAL)

            continue

        # ---------------------------------
        # FILTER NEW
        # ---------------------------------

        new_trades = []

        for t in trades:

            trade_id = t['a']

            if last_trade_id is None:

                new_trades.append(t)

            elif trade_id > last_trade_id:

                new_trades.append(t)

        if len(new_trades) > 0:

            last_trade_id = (
                new_trades[-1]['a']
            )

        # ---------------------------------
        # PARSE
        # ---------------------------------

        parsed = []

        for t in new_trades:

            parsed.append({

                'timestamp': datetime.fromtimestamp(
                    t['T'] / 1000
                ),

                'price': float(t['p']),

                'qty': float(t['q']),

                'side': (
                    'sell'
                    if t['m']
                    else 'buy'
                )
            })

        if len(parsed) > 0:

            history.extend(parsed)

        # ---------------------------------
        # DATAFRAME
        # ---------------------------------

        df = pd.DataFrame(history)

        if len(df) < 100:

            time.sleep(SAVE_INTERVAL)

            continue

        # ---------------------------------
        # RECENT WINDOW
        # ---------------------------------

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
        # DELTA EFFICIENCY
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

            'timestamp': datetime.utcnow(),

            'buy_volume': buy_volume,

            'sell_volume': sell_volume,

            'delta': delta,

            'trade_count': trade_count,

            'avg_price': avg_price,

            'price_change': price_change,

            'efficiency': efficiency
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
