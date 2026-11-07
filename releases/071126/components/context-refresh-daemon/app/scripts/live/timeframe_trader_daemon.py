#!/usr/bin/env python3
"""Independent timeframe trader daemon (S4.1). PAPER ONLY / NO REAL EXECUTION.

One process per timeframe (M15 / M30 / H1 / H4). Each process consumes only its
own command-bus slice, applies the shared paper execution core, and writes only
its own book. D1 is refused: no live Stage-2 writer exists.

Requires: --approved-timeframe-trader --paper-only --no-real-execution
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import process_lock  # noqa: E402
from btc_ml.trading.timeframe_manager import load_feed  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import SUPPORTED_TIMEFRAMES, UNSUPPORTED_TIMEFRAMES  # noqa: E402
from btc_ml.trading.timeframe_trader import TimeframeTrader  # noqa: E402

ACTIVATION_PATH = ROOT / "data" / "trading" / "manager" / "activation.json"

_STOP = False


def _handle_signal(signum, _frame):  # noqa: ANN001
    global _STOP
    _STOP = True


def activation_boundary() -> str | None:
    if not ACTIVATION_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("activation_timestamp")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--approved-timeframe-trader", action="store_true", required=True)
    parser.add_argument("--paper-only", action="store_true", required=True)
    parser.add_argument("--no-real-execution", action="store_true", required=True)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    timeframe = str(args.timeframe).upper()
    if timeframe in UNSUPPORTED_TIMEFRAMES:
        print(
            json.dumps(
                {
                    "timeframe": timeframe,
                    "refused": True,
                    "availability_status": "TIMEFRAME_NOT_LIVE",
                    "availability_reason": "NO_LIVE_STAGE2_WRITER",
                }
            )
        )
        return 4
    if timeframe not in SUPPORTED_TIMEFRAMES:
        print(json.dumps({"timeframe": timeframe, "refused": True, "reason": "TIMEFRAME_NOT_SUPPORTED"}))
        return 4

    role = f"trader_{timeframe}"
    lock = process_lock.acquire(role)
    if not lock.get("acquired"):
        print(json.dumps(lock))
        return 3
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    trader = TimeframeTrader.production(timeframe)
    boundary = activation_boundary()
    process_lock.log_line(
        role,
        "started pid=%s book=%s activation_boundary=%s paper_only=True execution_enabled=False"
        % (lock["pid"], trader.book.root, boundary),
    )
    cycles = 0
    try:
        while not _STOP:
            result = trader.run_once(feed=load_feed(), activation_boundary=boundary)
            applied = [
                f"{o.get('intent')}:{o.get('result')}({o.get('reason')})" for o in result["outcomes"]
            ]
            status = result["runtime_status"]
            position = status.get("open_position") or {}
            process_lock.log_line(
                role,
                "cycle applied=%s position=%s/%s realized=%.2f unrealized=%.2f open_risk=%.2f"
                % (
                    json.dumps(applied),
                    position.get("direction") or "FLAT",
                    position.get("status") or "NONE",
                    float(status.get("realized_pnl_usd") or 0.0),
                    float(status.get("unrealized_pnl_usd") or 0.0),
                    float(status.get("open_risk_usd") or 0.0),
                ),
            )
            cycles += 1
            if args.once or (args.max_cycles and cycles >= args.max_cycles):
                break
            deadline = time.time() + args.interval_seconds
            while not _STOP and time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
    except Exception as exc:  # pragma: no cover - daemon guard
        process_lock.log_line(role, f"fatal={type(exc).__name__}:{exc}")
        raise
    finally:
        process_lock.release(role)
        process_lock.log_line(role, f"stopped cycles={cycles}")
    print(
        json.dumps(
            {
                "role": role,
                "timeframe": timeframe,
                "cycles": cycles,
                "stopped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
