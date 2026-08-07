#!/usr/bin/env python3
"""Canonical process supervisor for LIVE1A cognition + LIVE1B paper manager."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor, atomic_write_json, utc_now_iso

PID_PATH = ROOT / "run" / "intrabar_process_supervisor.pid"
LOG_PATH = ROOT / "run" / "logs" / "intrabar_process_supervisor.log"

_STOP = False


def _python() -> str:
    for cand in (ROOT / "venv" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _log(msg: str) -> None:
    line = f"{utc_now_iso()} {msg}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
    print(line, flush=True)


def _handle_sig(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True
    _log("supervisor_signal_stopping")


def run_once(*, adopt_only: bool = False) -> dict:
    sup = IntrabarSupervisor.create(ROOT, python=_python())
    if adopt_only:
        return sup.evaluate_all()
    return sup.supervise_once()


def run_loop(interval: int) -> int:
    global _STOP
    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    atexit.register(lambda: PID_PATH.unlink(missing_ok=True))
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    _log(f"supervisor_start pid={os.getpid()} interval={interval}s")
    while not _STOP:
        try:
            snapshot = run_once()
            for name, svc in (snapshot.get("services") or {}).items():
                _log(
                    f"check service={name} lifecycle={svc.get('lifecycle_state')} "
                    f"pid={svc.get('pid')} execution={svc.get('execution_state')}"
                )
            for name, action in (snapshot.get("actions") or {}).items():
                _log(f"action service={name} ok={action.get('ok')} reason={action.get('reason')}")
        except Exception as exc:  # noqa: BLE001
            _log(f"supervisor_loop_error={exc!r}")
        for _ in range(interval):
            if _STOP:
                break
            time.sleep(1)
    PID_PATH.unlink(missing_ok=True)
    _log("supervisor_stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LIVE1A/LIVE1B intrabar process supervisor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--adopt-only", action="store_true", help="Evaluate/adopt without restart actions")
    parser.add_argument("--interval", type=int, default=None)
    args = parser.parse_args()
    interval = args.interval
    if interval is None:
        from btc_ml.runtime.intrabar_supervision import load_config

        interval = int(load_config(ROOT).get("check_interval_seconds", 15))
    if args.once or args.adopt_only:
        snapshot = run_once(adopt_only=args.adopt_only)
        print(json.dumps(snapshot, indent=2, default=str))
        return 0
    return run_loop(interval)


if __name__ == "__main__":
    raise SystemExit(main())
