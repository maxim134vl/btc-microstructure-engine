import websocket
import threading
import json
import pandas as pd
import time
from datetime import datetime

# ---------------------------------
# STORAGE
# ---------------------------------

exchange_data = {
    'binance': [],
    'bybit': [],
    'okx': []
}

# ---------------------------------
# HELPERS
# ---------------------------------

def print_stats():

    print()
    print("================================")

    for exchange in exchange_data:

        df = pd.DataFrame(
            exchange_data[exchange]
        )

        if len(df) == 0:

            print()
            print(exchange.upper())
            print("NO DATA")

            continue

        recent = df.tail(500)

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

        print()
        print(exchange.upper())

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

# ---------------------------------
# BINANCE
# ---------------------------------

def on_binance_message(ws, message):

    try:

        data = json.loads(message)

        trade = {
            'timestamp': datetime.fromtimestamp(
                data['T'] / 1000
            ),
            'price': float(data['p']),
            'qty': float(data['q']),
            'side': 'sell' if data['m'] else 'buy'
        }

        exchange_data['binance'].append(
            trade
        )

    except Exception as e:

        print("BINANCE ERROR:", e)

def start_binance():

    socket = (
        "wss://fstream.binance.com/ws/"
        "btcusdt@aggTrade"
    )

    ws = websocket.WebSocketApp(
        socket,
        on_message=on_binance_message
    )

    print("BINANCE CONNECTED")

    ws.run_forever()

# ---------------------------------
# BYBIT
# ---------------------------------

def on_bybit_message(ws, message):

    try:

        data = json.loads(message)

        if 'data' not in data:
            return

        for t in data['data']:

            trade = {
                'timestamp': datetime.fromtimestamp(
                    t['T'] / 1000
                ),
                'price': float(t['p']),
                'qty': float(t['v']),
                'side': t['S'].lower()
            }

            exchange_data['bybit'].append(
                trade
            )

    except Exception as e:

        print("BYBIT ERROR:", e)

def start_bybit():

    socket = (
        "wss://stream.bybit.com/v5/public/linear"
    )

    def on_open(ws):

        print("BYBIT CONNECTED")

        sub = {
            "op": "subscribe",
            "args": [
                "publicTrade.BTCUSDT"
            ]
        }

        ws.send(json.dumps(sub))

    ws = websocket.WebSocketApp(
        socket,
        on_open=on_open,
        on_message=on_bybit_message
    )

    ws.run_forever()

# ---------------------------------
# OKX
# ---------------------------------

def on_okx_message(ws, message):

    try:

        data = json.loads(message)

        if 'data' not in data:
            return

        for t in data['data']:

            trade = {
                'timestamp': datetime.fromtimestamp(
                    int(t['ts']) / 1000
                ),
                'price': float(t['px']),
                'qty': float(t['sz']),
                'side': t['side']
            }

            exchange_data['okx'].append(
                trade
            )

    except Exception as e:

        print("OKX ERROR:", e)

def start_okx():

    socket = (
        "wss://ws.okx.com:8443/ws/v5/public"
    )

    def on_open(ws):

        print("OKX CONNECTED")

        sub = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "trades",
                    "instId": "BTC-USDT-SWAP"
                }
            ]
        }

        ws.send(json.dumps(sub))

    ws = websocket.WebSocketApp(
        socket,
        on_open=on_open,
        on_message=on_okx_message
    )

    ws.run_forever()

# ---------------------------------
# START THREADS
# ---------------------------------

threading.Thread(
    target=start_binance,
    daemon=True
).start()

threading.Thread(
    target=start_bybit,
    daemon=True
).start()

threading.Thread(
    target=start_okx,
    daemon=True
).start()

# ---------------------------------
# MAIN LOOP
# ---------------------------------

while True:

    print_stats()

    time.sleep(5)
