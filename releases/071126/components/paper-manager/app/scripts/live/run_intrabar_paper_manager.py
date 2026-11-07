#!/usr/bin/env python3
"""Detached LIVE1B intrabar paper manager: context journal + execution market WAL."""

from __future__ import annotations

import argparse
import json
import os
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

from ops_owner_projections import write_paper_health_with_ops

from btc_ml.runtime.financial_trend_environment import configure_environment, command_bus, load_paper_trend
from btc_ml.runtime.trading_application import TradingApplication
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor, ReplayInterrupted
from btc_ml.trading.intrabar_paper.execution_market_backfill import ResumeCaptureTransport
from btc_ml.trading.intrabar_paper.execution_market_wal_config import load_execution_market_wal_config
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer

STOP = False

MARKET_PAYLOAD_QUEUE_MAXSIZE = 1024

FUTURES_PUBLIC_WS_URL = "wss://fstream.binance.com/public/stream?streams={symbol}@bookTicker"
FUTURES_MARKET_WS_URL = "wss://fstream.binance.com/market/stream?streams={symbol}@aggTrade"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _handle_stop(*_args: object) -> None:
    global STOP
    STOP = True



def _enqueue_market_payload(payload_queue, item, *, stop_requested):
    """Never wait for the consumer from the WebSocket reader."""
    if stop_requested():
        return False
    try:
        payload_queue.put_nowait(item)
        return True
    except queue.Full:
        return False


def _ack_market_queue_continuity(processor, results):
    # Only the sole MARKET consumer can acknowledge the overflow fence, after
    # the existing WAL/checkpoint and recovery barrier have completed.
    if (not processor._halted and results and results[-1].get("status") in {
        "AGG_TRADE_DISPATCHED", "DUPLICATE_AGG_TRADE_SKIPPED",
    }):
        processor.state.ack_market_queue_continuity(
            confirmed_id=processor.checkpoint.last_processed_agg_trade_id,
        )


def _record_market_overflow_stack(processor, payload_queue, agg_id):
    # One normal failure record, not a sampler or a second worker.
    if getattr(processor, '_overflow_stack_emitted', False):
        return
    processor._overflow_stack_emitted = True
    import traceback
    frames = sys._current_frames()
    stacks = {}
    for thread in threading.enumerate()[:16]:
        frame = frames.get(thread.ident)
        if frame is not None:
            stacks[thread.name] = ''.join(traceback.format_stack(frame, limit=16))
    print(json.dumps({'MARKET_OVERFLOW_DIAGNOSTIC': {
        'at': _utc(), 'monotonic_ns': time.monotonic_ns(),
        'rejected_agg_id': agg_id, 'queue_depth': payload_queue.qsize(),
        'processed_cursor': processor.checkpoint.last_processed_agg_trade_id,
        'wal_confirmed_id': processor.wal.last_confirmed_agg_trade_id,
        'wal_lock_held': processor.wal._lock.locked(), 'stacks': stacks,
    }}), flush=True)


def _start_routed_ws_feed(
    *,
    url: str,
    thread_name: str,
    on_connected: Callable[[], None],
    on_disconnected: Callable[[], None],
    on_payload: Callable[..., None],
    processor: ExecutionMarketProcessor,
    queued_payloads: bool = False,
    verified_tls: bool = False,
    connection_session_id: Callable[[], str] | None = None,
) -> threading.Thread | None:
    try:
        import websocket
    except ImportError:
        processor.engine.errors.append(f"websocket-client missing; {thread_name} feed disabled")
        return None

    payload_queue: queue.Queue[tuple[dict, str | None]] | None = (
        queue.Queue(maxsize=MARKET_PAYLOAD_QUEUE_MAXSIZE) if queued_payloads else None
    )

    if payload_queue is not None:
        def consume_payloads() -> None:
            while not STOP:
                try:
                    payload, session_id = payload_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                try:
                    results = on_payload(payload, session_id)
                    _ack_market_queue_continuity(processor, results)
                    for result in results or []:
                        if result.get("status") in {"BACKFILL_FAILED", "BACKFILL_INCOMPLETE"}:
                            message = f"{thread_name}:{result.get('status')}:{result.get('error')}"
                            if not processor.engine.errors or processor.engine.errors[-1] != message:
                                processor.engine.errors.append(message)
                                processor.engine.errors[:] = processor.engine.errors[-50:]
                                print(message, file=sys.stderr, flush=True)
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
                accepted = _enqueue_market_payload(
                    payload_queue, (payload, session_id), stop_requested=lambda: STOP,
                )
                if not accepted and not STOP:
                    data = payload.get("data") or payload
                    try:
                        agg_id = int(data["a"])
                    except (KeyError, TypeError, ValueError):
                        agg_id = None
                    processor.state.on_market_queue_overflow(aggregate_trade_id=agg_id)
                    try:
                        _record_market_overflow_stack(processor, payload_queue, agg_id)
                    except Exception as diagnostic_error:
                        processor.engine.errors.append(f"{thread_name}_overflow_diagnostic:{diagnostic_error}")
                    detail = (f"{thread_name}:MARKET_QUEUE_OVERFLOW:"
                              f"agg_trade_id={agg_id}:session={session_id}:REST_RECOVERY_REQUIRED")
                    processor.engine.errors.append(detail)
                    processor.engine.errors[:] = processor.engine.errors[-50:]
                    print(detail, file=sys.stderr, flush=True)
                    # Keep every queued event. The next session's forward ID
                    # invokes the existing gap/WAL/REST path for this event.
                    _ws.close()
        except Exception as exc:  # noqa: BLE001
            processor.engine.errors.append(f"{thread_name}_msg:{exc}")
            if len(processor.engine.errors) > 50:
                processor.engine.errors = processor.engine.errors[-50:]

    def on_error(_ws: object, err: object) -> None:
        processor.engine.errors.append(f"{thread_name}_error:{err}")
        on_disconnected()

    def run() -> None:
        import ssl

        sslopt = {"cert_reqs": ssl.CERT_REQUIRED if verified_tls else ssl.CERT_NONE}
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
        on_connected=getattr(getattr(processor, "fresh_live_boundary", None), "on_public_websocket_connected", processor.on_public_websocket_connected),
        on_disconnected=getattr(getattr(processor, "fresh_live_boundary", None), "on_public_websocket_disconnected", processor.on_public_websocket_disconnected),
        on_payload=(processor.fresh_live_boundary.handle_public if hasattr(processor, "fresh_live_boundary") else processor.handle_public_ws_payload),
        processor=processor,
        verified_tls=hasattr(processor, "fresh_live_boundary"),
    )
    market = _start_routed_ws_feed(
        url=market_url,
        thread_name="live1b-futures-market",
        on_connected=getattr(getattr(processor, "fresh_live_boundary", None), "on_market_websocket_connected", processor.on_market_websocket_connected),
        on_disconnected=getattr(getattr(processor, "fresh_live_boundary", None), "on_market_websocket_disconnected", processor.on_market_websocket_disconnected),
        on_payload=lambda payload, session_id: (processor.fresh_live_boundary.handle_market if hasattr(processor, "fresh_live_boundary") else processor.handle_market_ws_payload)(
            payload,
            connection_session_id=session_id,
        ),
        processor=processor,
        verified_tls=hasattr(processor, "fresh_live_boundary"),
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
    ap.add_argument("--fresh-live-domain", default=None, help="Explicit new Linux-backed continuity domain; preserves old WAL/checkpoint")
    ap.add_argument("--continuity-mode", choices=("FLAT_START", "OPEN_POSITION_RESUME_V1"), default="FLAT_START")
    ap.add_argument("--resume-previous-domain", default=None)
    ap.add_argument("--resume-position-id", action="append", default=[])
    ap.add_argument('--preflight-only',action='store_true',help='Read-only attachment validation; never starts engine')
    ap.add_argument('--test-only-financial-attachment',action='store_true',help='Only with --preflight-only and separate Linux research storage')
    args = ap.parse_args()
    if args.test_only_financial_attachment and not args.preflight_only:
        raise RuntimeError('TEST_ATTACHMENT_CANNOT_START_SERVICE')
    if args.preflight_only:
        from btc_ml.runtime.container_preflight import inspect_attachment
        result=inspect_attachment(REPO,role='paper-manager',isolated_test_only=args.test_only_financial_attachment)
        print(json.dumps(result,sort_keys=True))
        return 0
    resume = args.continuity_mode == "OPEN_POSITION_RESUME_V1"
    if resume and (not args.fresh_live_domain or not args.resume_previous_domain or not args.resume_position_id):
        raise RuntimeError("EXPLICIT_RESUME_ARGUMENTS_REQUIRED")
    if args.resume_previous_domain and not __import__("re").fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.resume_previous_domain):
        raise RuntimeError("INVALID_RESUME_PREVIOUS_DOMAIN")

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    cfg, epoch = configure_environment(REPO, config_path=args.config)
    wal_cfg = load_execution_market_wal_config(args.wal_storage_config)
    if epoch is None or epoch.epoch_status != "ACTIVE":
        print(json.dumps({"error": "no_active_epoch", "epoch": None if epoch is None else epoch.to_dict()}))
        return 2
    if cfg.real_execution_enabled:
        print(json.dumps({"error": "real_execution_must_be_false"}))
        return 3

    # The ownership lock lives on the shared epoch volume, before any writer
    # (books, cursor, WAL or feed) is initialized. Keep its inode for restart.
    if args.fresh_live_domain:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.fresh_live_domain):
            raise RuntimeError("INVALID_FRESH_LIVE_DOMAIN")
        from btc_ml.trading.intrabar_paper.execution_storage_contract import verify_execution_filesystem
        verify_execution_filesystem(cfg.books_root / epoch.paper_epoch_id)
    from btc_ml.runtime.single_instance import acquire_pid_lock, AlreadyRunningError
    try:
        execution_owner = acquire_pid_lock(cfg.books_root / epoch.paper_epoch_id / ".execution_owner.lock")
    except AlreadyRunningError as exc:
        print(json.dumps({"error": "execution_owner_already_running", "detail": str(exc)}), flush=True)
        return 4
    if resume:
        from btc_ml.trading.intrabar_paper.open_position_resume import validate_resume_startup
        validate_resume_startup(cfg.books_root / epoch.paper_epoch_id,
            cfg.books_root / epoch.paper_epoch_id / "live_continuity_v1" / args.fresh_live_domain,
            epoch.paper_epoch_id, args.resume_position_id)
    from btc_ml.runtime.r08_service import start_owned_source
    t0_mode = bool(os.environ.get("BTC_ML_START_T0"))
    r08_owner = None if t0_mode else start_owned_source()
    r08_started = not t0_mode
    engine = IntrabarPaperEngine(cfg=cfg, epoch=epoch)
    epoch_root = cfg.books_root / epoch.paper_epoch_id
    try:
        processor = ExecutionMarketProcessor.create(
            # Existing native transport: one lazy persistent HTTPS connection
            # for this processor's serial post-T0 gap worker. No added requests.
            fetch_agg_trades=ResumeCaptureTransport(),
            engine=engine,
            epoch_root=(epoch_root / "live_continuity_v1" / args.fresh_live_domain if args.fresh_live_domain else epoch_root),
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
            stop_requested=lambda: STOP,
            defer_economic_dispatch=resume,
        )
    except ReplayInterrupted:
        print(json.dumps({"status": "STOPPED_DURING_STARTUP_REPLAY", "paper_epoch_id": epoch.paper_epoch_id}), flush=True)
        return 0

    engine.attach_execution_market(processor)


    s41_consumer: S41CommandConsumer | None = None
    startup_fence = None
    if cfg.entry_source == "s41_command_bus":
        s41_consumer = S41CommandConsumer(
            engine,
            checkpoint_path=epoch_root / "s41_command_cursor.json",
            consume_after=cfg.s41_consume_commands_after,
            bus=command_bus(REPO),
            paper_trend_integration=load_paper_trend(REPO),
        )
        if not resume:
            if t0_mode and args.fresh_live_domain and not engine.positions:
                from btc_ml.trading.intrabar_paper.quarantine_barrier import read_current
                # The native checked committed fence already describes retained
                # history. T0's current cutoff is persisted in the live boundary
                # before WS startup; do not repeat historical DISPOSE while flat.
                existing_fence = read_current(engine.books)
                if existing_fence["status"] == "COMPLETED":
                    startup_fence = existing_fence
            if startup_fence is None:
                startup_fence = s41_consumer.quarantine_recovery_backlog()
        processor.recovery_barrier = s41_consumer.quarantine_recovery_backlog

    if args.fresh_live_domain:
        if s41_consumer is None:
            raise RuntimeError("FRESH_LIVE_REQUIRES_S41_CONSUMER")
        from btc_ml.trading.intrabar_paper.fresh_live_continuity import FreshLiveContinuity
        if resume:
            from btc_ml.trading.intrabar_paper.open_position_resume import OpenPositionResume
            fresh_boundary = OpenPositionResume(processor, s41_consumer,
                epoch_root / "live_continuity_v1" / args.fresh_live_domain,
                previous_domain_root=epoch_root / "live_continuity_v1" / args.resume_previous_domain,
                expected_position_ids=args.resume_position_id)
            fresh_boundary.diagnostic.execution_owner = execution_owner
        else:
            fresh_boundary = FreshLiveContinuity(processor, s41_consumer,
                epoch_root / "live_continuity_v1" / args.fresh_live_domain,
                startup_fence=startup_fence if os.environ.get("BTC_ML_START_T0") else None)
            if t0_mode:
                processor.recovery_barrier = fresh_boundary.finish_t0_flat_gap
                if fresh_boundary.proof is not None:
                    fresh_boundary.finish_t0_flat_gap()

    if resume:
        fresh_boundary.start_convergence(lambda: STOP)

    # Observer collection is independent of Futures entry freshness. Native
    # books and command fence above are already durable; OPEN guards unchanged.
    if (t0_mode and os.environ.get("BTC_ML_R08_OBSERVER_ONLY") == "1"
            and not r08_started):
        r08_owner = start_owned_source()
        r08_started = True

    # Consumer fence is durable before any WS can make the market admissible.
    _start_execution_market_feeds(processor)
    write_paper_health_with_ops(engine, REPO, lease_seconds=args.health_every_s)

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
                "execution_market_wal": str(processor.wal.root),
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
                if args.fresh_live_domain:
                    fresh_ready = fresh_boundary.try_activate()
                    if t0_mode and fresh_ready and not r08_started:
                        # Source bootstrap starts only after native books and
                        # the fresh market boundary are ready; still one owner.
                        r08_owner = start_owned_source()
                        r08_started = True
                if not resume or fresh_boundary.complete:
                    engine.poll_context_journal()
                    if s41_consumer is not None:
                        if r08_owner is not None:
                            r08_owner.poll()
                            binding=load_paper_trend(REPO)
                            s41_consumer.paper_trend_integration=binding
                            engine._paper_trend_integration=binding
                        TradingApplication.consume_cycle(s41_consumer)
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"poll:{exc}")
            try:
                processor.wal.maybe_periodic_flush()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"wal_periodic_fsync:{exc}")
            now = time.time()
            if now - last_health >= args.health_every_s:
                write_paper_health_with_ops(engine, REPO, lease_seconds=args.health_every_s)
                last_health = now
            time.sleep(max(0.05, args.poll_ms / 1000.0))
    finally:
        if r08_owner is not None:r08_owner.close()
        if resume:
            fresh_boundary.stop_convergence()
        try:
            processor.wal.flush_durable(reason="shutdown")
        except Exception:
            pass
        write_paper_health_with_ops(engine, REPO, lease_seconds=args.health_every_s, stopped=True)
        try:
            processor.wal.release_append_handle()
        except OSError:
            pass
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
