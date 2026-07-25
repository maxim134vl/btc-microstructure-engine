#!/usr/bin/env python3
"""Timeframe manager daemon (S4.1). PAPER ONLY / NO REAL EXECUTION.

Deterministic command dispatcher: every cycle it resolves the four independent
timeframe states and appends one explainable command per timeframe to the
append-only command bus. It never executes orders and never writes cognition,
context, decision or paper ledger datasets.

Requires: --approved-timeframe-manager --paper-only --no-real-execution
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import process_lock  # noqa: E402
from btc_ml.trading.timeframe_manager import TimeframeManager, load_feed  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import load_sources  # noqa: E402

ROLE = "timeframe_manager"
AVAILABILITY_LATEST = ROOT / "data" / "runtime" / "multi_timeframe_availability_latest.json"
ACTIVATION_PATH = ROOT / "data" / "trading" / "manager" / "activation.json"

_STOP = False


def _handle_signal(signum, _frame):  # noqa: ANN001
    global _STOP
    _STOP = True
    process_lock.log_line(ROLE, f"signal_received={signum} stopping")


def latest_evaluation_timestamp() -> str | None:
    if not AVAILABILITY_LATEST.exists():
        return None
    try:
        payload = json.loads(AVAILABILITY_LATEST.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("latest_evaluation_timestamp")


def activation_boundary() -> str | None:
    if not ACTIVATION_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("activation_timestamp")


def run_cycle(manager: TimeframeManager, *, boundary: str | None) -> dict[str, Any]:
    evaluation = latest_evaluation_timestamp()
    if evaluation is None:
        process_lock.log_line(ROLE, "cycle_skipped reason=NO_MTF_AVAILABILITY_LATEST")
        return {"skipped": True, "reason": "NO_MTF_AVAILABILITY_LATEST"}
    cycle = manager.run_cycle(
        evaluation_timestamp=evaluation,
        sources=load_sources(),
        feed=load_feed(),
        activation_boundary=boundary,
        persist=True,
    )
    summary = {
        cmd["timeframe"]: f"{cmd['intent']}({json.loads(cmd['reason_codes'])[0]})" for cmd in cycle["commands"]
    }
    process_lock.log_line(
        ROLE,
        "cycle evaluation=%s appended=%d duplicates=%d commands=%s gross_risk=%.2f"
        % (
            evaluation,
            cycle["append_result"]["appended"],
            cycle["append_result"]["duplicates_rejected"],
            json.dumps(summary),
            float(cycle["portfolio"]["gross_open_risk_usd"]),
        ),
    )
    return cycle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-timeframe-manager", action="store_true", required=True)
    parser.add_argument("--paper-only", action="store_true", required=True)
    parser.add_argument("--no-real-execution", action="store_true", required=True)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 = unbounded")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    lock = process_lock.acquire(ROLE)
    if not lock.get("acquired"):
        print(json.dumps(lock))
        return 3
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    manager = TimeframeManager.production()
    boundary = activation_boundary()
    process_lock.log_line(
        ROLE,
        "started pid=%s interval=%.0fs activation_boundary=%s paper_only=True execution_enabled=False"
        % (lock["pid"], args.interval_seconds, boundary),
    )
    cycles = 0
    try:
        while not _STOP:
            run_cycle(manager, boundary=boundary)
            cycles += 1
            if args.once or (args.max_cycles and cycles >= args.max_cycles):
                break
            deadline = time.time() + args.interval_seconds
            while not _STOP and time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
    except Exception as exc:  # pragma: no cover - daemon guard
        process_lock.log_line(ROLE, f"fatal={type(exc).__name__}:{exc}")
        raise
    finally:
        process_lock.release(ROLE)
        process_lock.log_line(ROLE, f"stopped cycles={cycles}")
    print(
        json.dumps(
            {
                "role": ROLE,
                "cycles": cycles,
                "stopped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
