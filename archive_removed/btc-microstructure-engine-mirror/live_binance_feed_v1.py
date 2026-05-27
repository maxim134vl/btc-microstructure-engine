import json
import websocket
import pandas as pd
from datetime import datetime

print("\nLIVE BINANCE FEED STARTED\n")

# =====================================
# STORAGE
# =====================================

live_candles = []

# =====================================
# SAVE FUNCTION
# =====================================

def save_candle(candle):

    global live_candles

    live_candles.append(candle)

    df = pd.DataFrame(live_candles)

    df.to_parquet(
        "live_market_feed.parquet"
    )

# =====================================
# MESSAGE HANDLER
# =====================================

def on_message(ws, message):

    data = json.loads(message)

    candle = data["k"]

    # only closed candles

    if candle["x"] == False:

        return

    parsed = {

        "timestamp": datetime.fromtimestamp(
            candle["t"] / 1000
        ),

        "open": float(candle["o"]),

        "high": float(candle["h"]),

        "low": float(candle["l"]),

        "close": float(candle["c"]),

        "volume": float(candle["v"])

    }

    save_candle(parsed)

    print("=" * 50)

    print(
        f"CLOSED CANDLE: {parsed['timestamp']}"
    )

    print()

    print(
        f"O: {parsed['open']}"
    )

    print(
        f"H: {parsed['high']}"
    )

    print(
        f"L: {parsed['low']}"
    )

    print(
        f"C: {parsed['close']}"
    )

    print(
        f"V: {parsed['volume']}"
    )

    print()

# =====================================
# ERROR
# =====================================

def on_error(ws, error):

    print("ERROR:")
    print(error)

# =====================================
# CLOSE
# =====================================

def on_close(ws, close_status_code, close_msg):

    print("\nWEBSOCKET CLOSED\n")

# =====================================
# OPEN
# =====================================

def on_open(ws):

    print(
        "\nCONNECTED TO BINANCE\n"
    )

# =====================================
# SOCKET
# =====================================

socket = (
    "wss://stream.binance.com:9443/ws/"
    "btcusdt@kline_15m"
)

ws = websocket.WebSocketApp(

    socket,

    on_open=on_open,

    on_message=on_message,

    on_error=on_error,

    on_close=on_close

)

# =====================================
# START
# =====================================

ws.run_forever(
    sslopt={"cert_reqs": 0}
)
