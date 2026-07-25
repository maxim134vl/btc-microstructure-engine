import websocket
import json
import pandas as pd
import time
import ssl
import os
import sys
import threading

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

print("\nLIVE BINANCE FEED V2 STARTED\n", flush=True)

COLLECTOR_NAME = "binance_live_feed"
_message_count = 0
_write_lock = threading.Lock()
_catch_up_lock = threading.Lock()
WRITE_AUDIT_PATH = os.path.join(
    "reports", "collector_health", "logs", "live_feed_write_audit.jsonl"
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _safe_heartbeat(**kwargs) -> None:
    try:
        write_heartbeat(COLLECTOR_NAME, **kwargs)
    except Exception as exc:
        _log(f"HEARTBEAT WRITE FAILED: {exc}")


def _audit_write(*, candle_ts, rows_before: int, rows_after: int, output_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(WRITE_AUDIT_PATH), exist_ok=True)
        payload = {
            "audit_timestamp": datetime.now().isoformat(),
            "candle_timestamp": str(candle_ts),
            "rows_before": rows_before,
            "rows_after": rows_after,
            "output_path": output_path,
            "symbol": symbol,
            "interval": interval,
        }
        with open(WRITE_AUDIT_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except Exception as exc:
        _log(f"WRITE AUDIT FAILED: {exc}")


def _taker_buy_volume(kline: dict) -> float:
    """Binance kline fields are strings — coerce before arithmetic."""
    raw = kline.get("V", kline.get("v", 0))
    return float(raw) / 2.0


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
            f"LOADED {len(existing)} EXISTING CANDLES\n",
            flush=True,
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

    with _write_lock:
        try:

            existing = read_live_feed()

        except Exception:

            existing = pd.DataFrame()

        rows_before = len(existing)

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
        from storage.path_registry import CANONICAL_LIVE_FEED_PATH, resolve_write

        output_path = resolve_write(CANONICAL_LIVE_FEED_PATH)
        write_live_feed_snapshot(df)
        _audit_write(
            candle_ts=candle["timestamp"],
            rows_before=rows_before,
            rows_after=len(df),
            output_path=output_path,
        )
        # Patch 1: metadata sidecar only (activates after feed process restart).
        try:
            from pathlib import Path as _Path

            _root = _Path(__file__).resolve().parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            from runtime_dataset_metadata import emit_metadata_for_path

            emit_metadata_for_path(
                "data/live/live_market_feed.parquet",
                root=_root,
                metadata_origin="LIVE_WRITER",
            )
        except Exception:
            pass

        global _message_count
        _message_count += 1
        _safe_heartbeat(
            status="ALIVE",
            event="candle_saved",
            message_count=_message_count,
            extra={"last_timestamp": str(candle["timestamp"]), "output_path": output_path},
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
            _safe_heartbeat(
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

        if last_closed_timestamp is not None and pd.Timestamp(timestamp) == pd.Timestamp(last_closed_timestamp):

            return

        candle = {

            "timestamp": timestamp,

            "open": float(kline["o"]),

            "high": float(kline["h"]),

            "low": float(kline["l"]),

            "close": float(kline["c"]),

            "volume": float(kline["v"]),

            "taker_buy_volume": _taker_buy_volume(kline),

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

            _log(
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

        _log("=" * 60)

        _log(
            f"CLOSED CANDLE: "
            f"{timestamp}"
        )

        _log("")

        _log(
            f"O: {candle['open']}"
        )

        _log(
            f"H: {candle['high']}"
        )

        _log(
            f"L: {candle['low']}"
        )

        _log(
            f"C: {candle['close']}"
        )

        _log(
            f"V: {candle['volume']}"
        )

        _log("")

    except Exception as e:

        _log("")

        _log("MESSAGE PROCESSING ERROR:")

        _log(str(e))

        _log("")

        _safe_heartbeat(
            status="ERROR",
            event="message_error",
            last_error=str(e),
        )

# =====================================
# ERROR
# =====================================

def on_error(ws, error):

    _log("")

    _log("WEBSOCKET ERROR:")

    _log(str(error))

    _log("")

    _safe_heartbeat(
        status="ERROR",
        event="websocket_error",
        last_error=str(error),
    )


def on_close(ws, close_status_code, close_msg):

    _log("")

    _log("WEBSOCKET CLOSED")

    _log("")

    _safe_heartbeat(
        status="DISCONNECTED",
        event="websocket_closed",
        extra={"code": close_status_code, "msg": close_msg},
    )


def on_open(ws):

    _log(
        "CONNECTED TO BINANCE\n"
    )

    _safe_heartbeat(
        status="CONNECTED",
        event="websocket_open",
    )

# =====================================
# MAIN LOOP
# =====================================

write_heartbeat(COLLECTOR_NAME, status="STARTING", event="process_start")


def catch_up_closed_klines() -> None:
    """Backfill closed 15m candles since last parquet row via Binance REST."""
    global last_closed_timestamp

    with _catch_up_lock:
        import urllib.request

        start_ms = None
        if last_closed_timestamp is not None:
            start_ms = int(pd.Timestamp(last_closed_timestamp).timestamp() * 1000) + 1

        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol.upper()}&interval={interval}&limit=1000"
        )
        if start_ms is not None:
            url += f"&startTime={start_ms}"

        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(url, timeout=20, context=ctx) as response:
                rows = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            _log(f"CATCH-UP REQUEST FAILED: {exc}")
            return

        now_utc = pd.Timestamp.now("UTC").tz_convert(None)
        added = 0
        for row in rows:
            # REST kline: [open_time, o, h, l, c, v, close_time, ..., taker_buy_base, ...]
            open_time = pd.to_datetime(row[0], unit="ms")
            close_time = pd.to_datetime(row[6], unit="ms")
            # Only persist fully closed candles (close_time in the past).
            if close_time >= now_utc:
                continue
            if last_closed_timestamp is not None and pd.Timestamp(open_time) <= pd.Timestamp(last_closed_timestamp):
                continue
            candle = {
                "timestamp": open_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "taker_buy_volume": float(row[9]) if len(row) > 9 else float(row[5]) / 2.0,
            }
            try:
                safe_append_candle(candle)
                last_closed_timestamp = open_time
                added += 1
                _log(f"CATCH-UP CLOSED CANDLE: {open_time}")
            except Exception as exc:
                _log(f"CATCH-UP SAVE FAILED for {open_time}: {exc}")
                break

        _log(f"CATCH-UP COMPLETE added={added} last={last_closed_timestamp}")


def _periodic_catch_up_loop(interval_s: int = 90) -> None:
    """REST backfill safety net — keeps parquet current even if websocket is flaky."""
    while True:
        time.sleep(interval_s)
        try:
            catch_up_closed_klines()
        except Exception as exc:
            _log(f"PERIODIC CATCH-UP FAILED: {exc}")


catch_up_closed_klines()
threading.Thread(target=_periodic_catch_up_loop, daemon=True, name="feed-catch-up").start()

while True:

    try:
        catch_up_closed_klines()

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

            ping_interval=45,

            ping_timeout=25

        )

    except Exception as e:

        _log("")

        _log("RECONNECT ERROR:")

        _log(str(e))

        _log("")

    _log(
        "RECONNECTING IN 5 SECONDS...\n"
    )

    time.sleep(5)
