import requests
import pandas as pd
import time
from datetime import datetime

# ---------------------------------
# STORAGE
# ---------------------------------

history = []

# ---------------------------------
# LAST TRADE ID
# ---------------------------------

last_trade_id = None

print("STARTING INTRADAY COLLECTOR")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # BINANCE AGG TRADES
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
            timeout=10
        )

        trades = response.json()

        if not isinstance(trades, list):

            print("API ERROR")
            print(trades)

            time.sleep(5)

            continue

        # ---------------------------------
        # FILTER NEW TRADES
        # ---------------------------------

        new_trades = []

        for t in trades:

            trade_id = t['a']

            if last_trade_id is None:

                new_trades.append(t)

            elif trade_id > last_trade_id:

                new_trades.append(t)

        if len(new_trades) > 0:

            last_trade_id = new_trades[-1]['a']

        # ---------------------------------
        # BUILD DATAFRAME
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
        # ANALYTICS
        # ---------------------------------

        df = pd.DataFrame(history)

        if len(df) > 0:

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

            price_change = (
                recent['price'].iloc[-1]
                -
                recent['price'].iloc[0]
            )

            print()
            print("================================")

            print(
                "Trades:",
                len(recent)
            )

            print(
                "Buy Vol:",
                round(buy_volume, 2)
            )

            print(
                "Sell Vol:",
                round(sell_volume, 2)
            )

            print(
                "Delta:",
                round(delta, 2)
            )

            print(
                "Price Change:",
                round(price_change, 2)
            )

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(5)

    except Exception as e:

        print()
        print("ERROR")
        print(e)

        time.sleep(5)
