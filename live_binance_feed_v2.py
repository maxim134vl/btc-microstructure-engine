import websocket
import json
import pandas as pd
import time
import ssl
import os
import sys

sys.path.append(".")

from parquet_writer_v2 import (
    append_parquet
)

from live_feed_paths import (
    read_live_feed,
    write_live_feed_snapshot,
    LEGACY_PARTITION_DIR,
)

from datetime import datetime

from collector_heartbeat import write_heartbeat

print("\nLIVE BINANCE FEED V2 STARTED\n")

COLLECTOR_NAME = "binance_live_feed"
_message_count = 0

# =====================================
# SETTINGS
# =====================================

symbol = "btcusdt"

interval = "15m"

DATASET_PATH = LEGACY_PARTITION_DIR

LATEST_FILE = (
    "live_market_feed.parquet"
)

MAX_ROWS = 50000

socket_url = (

    f"wss://stream.binance.com:9443/ws/"
    f"{symbol}@kline_{interval}"

)

# =====================================
# LOAD LAST TIMESTAMP
# =====================================

last_closed_timestamp = None

try:

    existing = read_live_feed()

    if len(existing) > 0:

        last_closed_timestamp = (
            existing.iloc[-1]["timestamp"]
        )

        print(
            f"LOADED {len(existing)} EXISTING CANDLES\n"
        )

except Exception as e:

    print(
        "NO EXISTING FEED FILE\n"
    )

    print(e)

# =====================================
# SAFE SAVE FUNCTION
# =====================================

def safe_append_candle(candle):

    try:

        existing = read_live_feed()

    except Exception:

        existing = pd.DataFrame()

    new_row = pd.DataFrame(
        [candle]
    )

    df = pd.concat(

        [existing, new_row],

        ignore_index=True

    )

    # =====================================
    # CLEANUP
    # =====================================

    df = df.drop_duplicates(
        subset=["timestamp"]
    )

    df = df.sort_values(
        "timestamp"
    )

    # =====================================
    # LIMIT DATASET SIZE
    # =====================================

    if len(df) > MAX_ROWS:

        df = df.iloc[-MAX_ROWS:]

    # =====================================
    # SAVE PARTITIONED DATASET
    # =====================================

    append_parquet(

        df,

        DATASET_PATH

    )

    # =====================================
    # SAVE LATEST SNAPSHOT
    # =====================================

    # Canonical feed + legacy mirror snapshot.
    write_live_feed_snapshot(df)

    global _message_count
    _message_count += 1
    write_heartbeat(
        COLLECTOR_NAME,
        status="ALIVE",
        event="candle_saved",
        message_count=_message_count,
        extra={"last_timestamp": str(candle["timestamp"])},
    )

# =====================================
# ON MESSAGE
# =====================================

def on_message(ws, message):

    global last_closed_timestamp

    try:

        data = json.loads(message)

        kline = data["k"]

        candle_closed = kline["x"]

        if not candle_closed:
            write_heartbeat(
                COLLECTOR_NAME,
                status="CONNECTED",
                event="kline_tick",
                message_count=_message_count,
            )
            return

        timestamp = pd.to_datetime(

            kline["t"],
            unit="ms"

        )

        # =====================================
        # DUPLICATE PROTECTION
        # =====================================

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

        # =====================================
        # VALIDATION
        # =====================================

        values = [

            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
            candle["volume"]

        ]

        if any(pd.isna(values)):

            print(
                "NAN DETECTED - SKIPPING CANDLE"
            )

            return

        # =====================================
        # SAVE
        # =====================================

        safe_append_candle(
            candle
        )

        last_closed_timestamp = (
            timestamp
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

    except Exception as e:

        print()

        print("MESSAGE PROCESSING ERROR:")

        print(e)

        print()

        write_heartbeat(
            COLLECTOR_NAME,
            status="ERROR",
            event="message_error",
            last_error=str(e),
        )

# =====================================
# ERROR
# =====================================

def on_error(ws, error):

    print()

    print("WEBSOCKET ERROR:")

    print(error)

    print()

    write_heartbeat(
        COLLECTOR_NAME,
        status="ERROR",
        event="websocket_error",
        last_error=str(error),
    )

# =====================================
# CLOSE
# =====================================

def on_close(ws, close_status_code, close_msg):

    print()

    print("WEBSOCKET CLOSED")

    print()

    write_heartbeat(
        COLLECTOR_NAME,
        status="DISCONNECTED",
        event="websocket_closed",
        extra={"code": close_status_code, "msg": close_msg},
    )

# =====================================
# OPEN
# =====================================

def on_open(ws):

    print(
        "CONNECTED TO BINANCE\n"
    )

    write_heartbeat(
        COLLECTOR_NAME,
        status="CONNECTED",
        event="websocket_open",
    )

# =====================================
# MAIN LOOP
# =====================================

write_heartbeat(COLLECTOR_NAME, status="STARTING", event="process_start")

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
