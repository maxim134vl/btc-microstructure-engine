#!/usr/bin/env python3
"""Detached LIVE1B intrabar paper manager: context journal + causal BBO WS."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import load_active_epoch, mark_epoch_status

STOP = False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _handle_stop(*_args: object) -> None:
    global STOP
    STOP = True


def _start_bbo_feed(engine: IntrabarPaperEngine, symbol: str = "btcusdt") -> threading.Thread | None:
    try:
        import websocket
    except ImportError:
        engine.errors.append("websocket-client missing; BBO feed disabled (context-event BBO only)")
        return None

    streams = f"{symbol}@bookTicker/{symbol}@aggTrade"
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    def on_message(_ws: object, message: str) -> None:
        try:
            payload = json.loads(message)
            data = payload.get("data") or payload
            mono = time.monotonic_ns()
            ts = _utc()
            stream = str(payload.get("stream") or "")
            if "bookTicker" in stream or ("b" in data and "a" in data and "T" in data):
                bid = float(data.get("b") or data.get("bidPrice") or 0)
                ask = float(data.get("a") or data.get("askPrice") or 0)
                if bid > 0 and ask > 0:
                    engine.update_bbo_from_market(
                        best_bid=bid,
                        best_ask=ask,
                        receive_monotonic_ns=mono,
                        receive_timestamp=ts,
                        book_update_id=str(data.get("u") or data.get("updateId") or ""),
                        source_event_id=f"bbo_{data.get('u') or mono}",
                    )
            if "aggTrade" in stream or data.get("e") == "aggTrade":
                px = float(data.get("p") or 0)
                if px > 0:
                    engine.update_from_trade(
                        price=px,
                        receive_monotonic_ns=mono,
                        receive_timestamp=ts,
                        source_event_id=f"agg_{data.get('a') or mono}",
                    )
        except Exception as exc:  # noqa: BLE001
            engine.errors.append(f"ws_msg:{exc}")
            if len(engine.errors) > 50:
                engine.errors = engine.errors[-50:]

    def on_error(_ws: object, err: object) -> None:
        engine.errors.append(f"ws_error:{err}")

    def run() -> None:
        import ssl

        sslopt = {"cert_reqs": ssl.CERT_NONE}
        while not STOP:
            try:
                ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error)
                ws.run_forever(sslopt=sslopt, ping_interval=15, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"ws_reconnect:{exc}")
            if STOP:
                break
            time.sleep(1.0)

    t = threading.Thread(target=run, name="live1b-bbo", daemon=True)
    t.start()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=250)
    ap.add_argument("--health-every-s", type=float, default=2.0)
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    cfg = load_intrabar_paper_config(repo_root=REPO)
    epoch = load_active_epoch(cfg.epochs_root)
    if epoch is None or epoch.epoch_status != "ACTIVE":
        print(json.dumps({"error": "no_active_epoch", "epoch": None if epoch is None else epoch.to_dict()}))
        return 2
    if cfg.real_execution_enabled:
        print(json.dumps({"error": "real_execution_must_be_false"}))
        return 3

    engine = IntrabarPaperEngine(cfg=cfg, epoch=epoch)
    _start_bbo_feed(engine)
    engine.write_health()

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
                "max_bbo_age_ms": cfg.max_bbo_age_ms,
                "pid": __import__("os").getpid(),
            }
        ),
        flush=True,
    )

    try:
        while not STOP:
            try:
                engine.poll_context_journal()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"poll:{exc}")
            now = time.time()
            if now - last_health >= args.health_every_s:
                engine.write_health()
                last_health = now
            time.sleep(max(0.05, args.poll_ms / 1000.0))
    finally:
        engine.write_health()
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
