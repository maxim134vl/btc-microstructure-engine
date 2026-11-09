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
from pathlib import Path
from feed_gap_recovery import FeedRecovery, fetch_closed_rows

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


def _audit_write(*, candle_ts, rows_before: int, rows_after: int, output_path: str, recovery_source=None) -> None:
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
        if recovery_source is not None:
            payload["recovery_source"] = recovery_source
        with open(WRITE_AUDIT_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except Exception as exc:
        _log(f"WRITE AUDIT FAILED: {exc}")


def _taker_buy_volume(kline: dict) -> float:
    """Decode Binance base-asset taker-buy quantity V without rescaling."""
    raw = kline["V"]
    return float(raw)


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

# Recovery state is derived from persisted Feed, never from the greatest WS tick alone.
from storage.path_registry import CANONICAL_LIVE_FEED_PATH, resolve_write
_recovery = FeedRecovery(Path(resolve_write(CANONICAL_LIVE_FEED_PATH)).parent / "feed_recovery_state.json", symbol)

def _feed_opens(frame):
    return [int(pd.Timestamp(t).value // 1_000_000) for t in pd.to_datetime(frame["timestamp"], utc=True)] if len(frame) else []

with _write_lock:
    _recovery.reconcile(_feed_opens(read_live_feed()))

# =====================================
# SAFE SAVE FUNCTION
# =====================================

def safe_append_candle(candle, *, recovery_source=None):

    with _write_lock:
        # A read error must never turn an existing Feed into an empty dataset.
        existing = read_live_feed()
        _recovery.reconcile(_feed_opens(existing))
        if len(existing):
            matches = existing.loc[pd.to_datetime(existing["timestamp"], utc=True) == pd.to_datetime(candle["timestamp"], utc=True)]
            if len(matches):
                fields = ("open", "high", "low", "close", "volume", "taker_buy_volume")
                if len(matches) != 1 or any(float(matches.iloc[0][k]) != float(candle[k]) for k in fields):
                    raise ValueError("FEED_CANDLE_CONTENT_CONFLICT")
                return False  # Exact redelivery: no data or metadata rewrite.
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
            recovery_source=recovery_source,
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

        _recovery.reconcile(_feed_opens(df))
        global _message_count
        _message_count += 1
        _safe_heartbeat(
            status="ALIVE",
            event="candle_saved",
            message_count=_message_count,
            extra={"last_timestamp": str(candle["timestamp"]), "output_path": output_path},
        )
        return True

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

        # Equality/content and duplicates are checked by the single writer below.

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

        inserted = safe_append_candle(candle)
        last_closed_timestamp = max(pd.Timestamp(last_closed_timestamp), pd.Timestamp(timestamp)) if last_closed_timestamp is not None else timestamp
        if not inserted:
            return

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
    """Recover earliest holes first; preserve every already persisted newer bar."""
    global last_closed_timestamp
    with _catch_up_lock:
        with _write_lock:
            _recovery.reconcile(_feed_opens(read_live_feed()))
            now_ms = int(pd.Timestamp.now("UTC").value // 1_000_000)
            bounds = _recovery.next_request(now_ms)
            if bounds is None:
                return
            _recovery.attempted(bounds)
        try:
            rows, source = fetch_closed_rows(symbol, interval, bounds)
            with _write_lock:
                _recovery.attempted(bounds, source=source)
            added = 0
            for row in rows:
                candle = dict(row)
                candle["timestamp"] = pd.to_datetime(candle.pop("open_ms"), unit="ms")
                if safe_append_candle(candle, recovery_source=source):
                    added += 1
                    _log(f"CATCH-UP CLOSED CANDLE: {candle['timestamp']}")
            with _write_lock:
                frame = read_live_feed()
                _recovery.reconcile(_feed_opens(frame))
                last_closed_timestamp = frame.iloc[-1]["timestamp"] if len(frame) else None
                _recovery.attempted(bounds, source=source)
            _log(f"CATCH-UP RESULT added={added} contiguous={_recovery.state['contiguous_open_ms']} max={_recovery.state['max_received_open_ms']} remaining_internal_ranges={_recovery.state['missing_ranges']}")
        except Exception as exc:
            with _write_lock:
                _recovery.attempted(bounds, error=exc)
            _log(f"CATCH-UP REQUEST/SAVE FAILED: {exc}")


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
