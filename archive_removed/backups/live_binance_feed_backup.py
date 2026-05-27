import websocket
import json
import pandas as pd
import time
import ssl
from datetime import datetime

print("\nLIVE BINANCE FEED V2 STARTED\n")

# =====================================
# SETTINGS
# =====================================

symbol = "btcusdt"

interval = "15m"

feed_file = "live_market_feed.parquet"

socket_url = (

    f"wss://stream.binance.com:9443/ws/"
    f"{symbol}@kline_{interval}"

)

# =====================================
# STORAGE
# =====================================

market_data = []

# =====================================
# LOAD EXISTING
# =====================================

try:

    existing = pd.read_parquet(
        feed_file
    )

    market_data = (
        existing.to_dict(
            "records"
        )
    )

    print(
        f"LOADED "
        f"{len(existing)} "
        f"EXISTING CANDLES\n"
    )

except:

    print(
        "NO EXISTING FEED FILE\n"
    )

# =====================================
# LAST CLOSED CANDLE
# =====================================

last_closed_timestamp = None

if len(market_data) > 0:

    last_closed_timestamp = (

        market_data[-1]["timestamp"]

    )

# =====================================
# ON MESSAGE
# =====================================

def on_message(ws, message):

    global market_data
    global last_closed_timestamp

    data = json.loads(message)

    kline = data["k"]

    candle_closed = kline["x"]

    # ignore live forming candle

    if not candle_closed:

        return

    timestamp = pd.to_datetime(
        kline["t"],
        unit="ms"
    )

    # duplicate protection

    if timestamp == last_closed_timestamp:

        return

    candle = {

        "timestamp": timestamp,

        "open": float(kline["o"]),

        "high": float(kline["h"]),

        "low": float(kline["l"]),

        "close": float(kline["c"]),

        "volume": float(kline["v"])

    }

    market_data.append(
        candle
    )

    last_closed_timestamp = (
        timestamp
    )

    # =====================================
    # SAVE
    # =====================================

    df = pd.DataFrame(
        market_data
    )

    df.to_parquet(
        feed_file,
        index=False
    )

    # =====================================
    # DEBUG
    # =====================================

    print("=" * 60)

    print(
        f"CLOSED CANDLE: "
        f"{timestamp}"
    )

    print()

    print(
        f"O: {candle['open']}"
    )

    print(
        f"H: {candle['high']}"
    )

    print(
        f"L: {candle['low']}"
    )

    print(
        f"C: {candle['close']}"
    )

    print(
        f"V: {candle['volume']}"
    )

    print()

# =====================================
# ERROR
# =====================================

def on_error(ws, error):

    print()

    print("WEBSOCKET ERROR:")

    print(error)

    print()

# =====================================
# CLOSE
# =====================================

def on_close(ws, close_status_code, close_msg):

    print()

    print("WEBSOCKET CLOSED")

    print()

# =====================================
# OPEN
# =====================================

def on_open(ws):

    print(
        "CONNECTED TO BINANCE\n"
    )

# =====================================
# MAIN LOOP
# =====================================

while True:

    try:

        ws = websocket.WebSocketApp(

            socket_url,

            on_message=on_message,

            on_error=on_error,

            on_close=on_close

        )

        ws.on_open = on_open

        ws.run_forever(

            sslopt={
                "cert_reqs": ssl.CERT_NONE
            },

            ping_interval=20,

            ping_timeout=10

        )

    except Exception as e:

        print()

        print("RECONNECT ERROR:")

        print(e)

        print()

    print(
        "RECONNECTING IN 5 SECONDS...\n"
    )

    time.sleep(5)
