#!/usr/bin/env python3
"""Detached LIVE1B intrabar paper manager: context journal + execution market WAL."""

from __future__ import annotations

import argparse
import json
import queue
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.process_lock import acquire_shared
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import load_active_epoch
from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor
from btc_ml.trading.intrabar_paper.execution_market_wal_config import load_execution_market_wal_config
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer

STOP = False

FUTURES_PUBLIC_WS_URL = "wss://fstream.binance.com/public/stream?streams={symbol}@bookTicker"
FUTURES_MARKET_WS_URL = "wss://fstream.binance.com/market/stream?streams={symbol}@aggTrade"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _handle_stop(*_args: object) -> None:
    global STOP
    STOP = True


def _start_routed_ws_feed(
    *,
    url: str,
    thread_name: str,
    on_connected: Callable[[], None],
    on_disconnected: Callable[[], None],
    on_payload: Callable[..., None],
    processor: ExecutionMarketProcessor,
    queued_payloads: bool = False,
    connection_session_id: Callable[[], str] | None = None,
) -> threading.Thread | None:
    try:
        import websocket
    except ImportError:
        processor.engine.errors.append(f"websocket-client missing; {thread_name} feed disabled")
        return None

    payload_queue: queue.Queue[tuple[dict, str | None]] | None = (
        queue.Queue() if queued_payloads else None
    )

    if payload_queue is not None:
        def consume_payloads() -> None:
            while not STOP:
                try:
                    payload, session_id = payload_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                try:
                    on_payload(payload, session_id)
                except Exception as exc:  # noqa: BLE001
                    processor.engine.errors.append(f"{thread_name}_worker:{exc}")
                finally:
                    payload_queue.task_done()

        threading.Thread(
            target=consume_payloads,
            name=f"{thread_name}-processor",
            daemon=True,
        ).start()

    def on_open(_ws: object) -> None:
        on_connected()

    def on_close(_ws: object, *_args: object) -> None:
        on_disconnected()

    def on_message(_ws: object, message: str) -> None:
        try:
            payload = json.loads(message)
            if payload_queue is None:
                on_payload(payload)
            else:
                session_id = connection_session_id() if connection_session_id else None
                payload_queue.put((payload, session_id))
        except Exception as exc:  # noqa: BLE001
            processor.engine.errors.append(f"{thread_name}_msg:{exc}")
            if len(processor.engine.errors) > 50:
                processor.engine.errors = processor.engine.errors[-50:]

    def on_error(_ws: object, err: object) -> None:
        processor.engine.errors.append(f"{thread_name}_error:{err}")
        on_disconnected()

    def run() -> None:
        import ssl

        sslopt = {"cert_reqs": ssl.CERT_NONE}
        while not STOP:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=on_message,
                    on_open=on_open,
                    on_close=on_close,
                    on_error=on_error,
                )
                ws.run_forever(sslopt=sslopt, ping_interval=15, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                processor.engine.errors.append(f"{thread_name}_reconnect:{exc}")
            on_disconnected()
            if STOP:
                break
            time.sleep(1.0)

    t = threading.Thread(target=run, name=thread_name, daemon=True)
    t.start()
    return t


def _start_execution_market_feeds(
    processor: ExecutionMarketProcessor,
    *,
    symbol: str = "btcusdt",
) -> list[threading.Thread]:
    public_url = FUTURES_PUBLIC_WS_URL.format(symbol=symbol)
    market_url = FUTURES_MARKET_WS_URL.format(symbol=symbol)
    threads: list[threading.Thread] = []
    public = _start_routed_ws_feed(
        url=public_url,
        thread_name="live1b-futures-public",
        on_connected=processor.on_public_websocket_connected,
        on_disconnected=processor.on_public_websocket_disconnected,
        on_payload=processor.handle_public_ws_payload,
        processor=processor,
    )
    market = _start_routed_ws_feed(
        url=market_url,
        thread_name="live1b-futures-market",
        on_connected=processor.on_market_websocket_connected,
        on_disconnected=processor.on_market_websocket_disconnected,
        on_payload=lambda payload, session_id: processor.handle_market_ws_payload(
            payload,
            connection_session_id=session_id,
        ),
        processor=processor,
        queued_payloads=True,
        connection_session_id=lambda: processor.market_connection_session_id,
    )
    if public is not None:
        threads.append(public)
    if market is not None:
        threads.append(market)
    return threads


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=250)
    ap.add_argument("--health-every-s", type=float, default=2.0)
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional intrabar paper execution JSON (defaults to config/intrabar_paper_execution.json)",
    )
    ap.add_argument(
        "--wal-storage-config",
        type=Path,
        default=REPO / "config" / "execution_market_wal_storage.json",
    )
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    cfg = load_intrabar_paper_config(args.config, repo_root=REPO)
    wal_cfg = load_execution_market_wal_config(args.wal_storage_config)
    epoch = load_active_epoch(cfg.epochs_root)
    if epoch is None or epoch.epoch_status != "ACTIVE":
        print(json.dumps({"error": "no_active_epoch", "epoch": None if epoch is None else epoch.to_dict()}))
        return 2
    if cfg.real_execution_enabled:
        print(json.dumps({"error": "real_execution_must_be_false"}))
        return 3

    writer_lock = acquire_shared(REPO / "data" / "runtime" / "intrabar_paper_manager.lock")
    if not writer_lock.get("acquired"):
        print(
            json.dumps(
                {
                    "error": "paper_manager_already_running",
                    "lock": writer_lock,
                }
            )
        )
        return 4

    engine = IntrabarPaperEngine(cfg=cfg, epoch=epoch)
    epoch_root = cfg.books_root / epoch.paper_epoch_id
    processor = ExecutionMarketProcessor.create(
        engine=engine,
        epoch_root=epoch_root,
        paper_epoch_id=epoch.paper_epoch_id,
        max_bbo_age_ms=cfg.max_bbo_age_ms,
        max_agg_trade_age_ms=cfg.max_agg_trade_age_ms,
        enable_segmented_wal=wal_cfg.segmented_enabled,
        wal_segment_max_bytes=wal_cfg.segment_max_bytes,
        wal_archive_batch_rows=wal_cfg.archive_batch_rows,
        wal_delete_verified_plaintext=wal_cfg.delete_verified_plaintext,
        wal_plaintext_retention_hours=wal_cfg.plaintext_retention_hours,
        wal_warning_size_bytes=wal_cfg.warning_size_bytes,
        wal_critical_size_bytes=wal_cfg.critical_size_bytes,
    )
    engine.attach_execution_market(processor)
    _start_execution_market_feeds(processor)
    engine.write_health()

    s41_consumer: S41CommandConsumer | None = None
    if cfg.entry_source == "s41_command_bus":
        s41_consumer = S41CommandConsumer(
            engine,
            checkpoint_path=epoch_root / "s41_command_cursor.json",
            consume_after=cfg.s41_consume_commands_after,
        )

    pid_path = REPO / "run" / "intrabar_paper_manager.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{__import__('os').getpid()}\n", encoding="utf-8")

    last_health = 0.0
    print(
        json.dumps(
            {
                "status": "STARTED",
                "paper_epoch_id": epoch.paper_epoch_id,
                "paper_only": True,
                "real_execution_enabled": False,
                "entry_source": cfg.entry_source,
                "s41_consume_commands_after": cfg.s41_consume_commands_after,
                "max_bbo_age_ms": cfg.max_bbo_age_ms,
                "max_agg_trade_age_ms": cfg.max_agg_trade_age_ms,
                "execution_market_wal": str(epoch_root / "execution_market_wal"),
                "execution_market_wal_storage_mode": wal_cfg.mode,
                "futures_public_ws_url": FUTURES_PUBLIC_WS_URL.format(symbol="btcusdt"),
                "futures_market_ws_url": FUTURES_MARKET_WS_URL.format(symbol="btcusdt"),
                "pid": __import__("os").getpid(),
            }
        ),
        flush=True,
    )

    try:
        while not STOP:
            try:
                engine.poll_context_journal()
                if s41_consumer is not None:
                    s41_consumer.poll()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"poll:{exc}")
            try:
                processor.wal.maybe_periodic_flush()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"wal_periodic_fsync:{exc}")
            now = time.time()
            if now - last_health >= args.health_every_s:
                engine.write_health()
                last_health = now
            time.sleep(max(0.05, args.poll_ms / 1000.0))
    finally:
        try:
            processor.wal.flush_durable(reason="shutdown")
        except Exception:
            pass
        engine.write_health()
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
