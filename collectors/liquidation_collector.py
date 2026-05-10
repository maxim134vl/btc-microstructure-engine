import websocket
import json
import pandas as pd
import time
import ssl

from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

WS_URL = (
    "wss://fstream.binance.com/ws/"
    "!forceOrder@arr"
)

PARQUET_FILE = (
    "liquidations.parquet"
)

SAVE_INTERVAL = 25

# ---------------------------------
# STORAGE
# ---------------------------------

liquidations = []

last_save = time.time()

print()
print("LIQUIDATION COLLECTOR STARTED")

# ---------------------------------
# CALLBACK
# ---------------------------------

def on_message(ws, message):

    global last_save

    data = json.loads(message)

    if not data:

        return

    for item in data:

        if 'o' not in item:

            continue

        order = item['o']

        symbol = order['s']

        side = order['S']

        price = float(order['p'])

        qty = float(order['q'])

        value = (
            price * qty
        )

        liquidations.append({

            'timestamp':
                datetime.utcnow(),

            'symbol':
                symbol,

            'side':
                side,

            'price':
                price,

            'qty':
                qty,

            'value':
                value
        })

        print()
        print("================================")

        print(
            "Symbol:",
            symbol
        )

        print(
            "Side:",
            side
        )

        print(
            "Value:",
            round(value, 2)
        )

        print(
            "Price:",
            price
        )

    # ---------------------------------
    # SAVE
    # ---------------------------------

    if (
        time.time() - last_save
        > SAVE_INTERVAL
    ):

        df = pd.DataFrame(
            liquidations
        )

        df.to_parquet(
            PARQUET_FILE,
            index=False
        )

        print()
        print(
            "SAVED:",
            len(df)
        )

        last_save = time.time()

# ---------------------------------
# ERROR
# ---------------------------------

def on_error(ws, error):

    print()
    print("ERROR")

    print(error)

# ---------------------------------
# CLOSE
# ---------------------------------

def on_close(ws, close_status_code, close_msg):

    print()
    print("CONNECTION CLOSED")

# ---------------------------------
# OPEN
# ---------------------------------

def on_open(ws):

    print()
    print("CONNECTED")

# ---------------------------------
# START
# ---------------------------------

ws = websocket.WebSocketApp(

    WS_URL,

    on_open=on_open,

    on_message=on_message,

    on_error=on_error,

    on_close=on_close
)

ws.run_forever(

    sslopt={
        "cert_reqs": ssl.CERT_NONE
    }
)
