#!/usr/bin/env python3
"""Periodic read-only refresh of TRD-OUTCOME2 latest.json for the OPS dashboard."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "live" / "audit_all_closed_trades_cross_layer.py"
PID_PATH = REPO / "run" / "trd_outcome2_refresh.pid"
LATEST = REPO / "output" / "audits" / "trd_outcome2" / "latest.json"
STOP = False


def _stop(*_args: object) -> None:
    global STOP
    STOP = True


def _python() -> str:
    for candidate in (REPO / "venv" / "bin" / "python", REPO / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=int, default=900)
    args = parser.parse_args()
    interval = max(60, int(args.interval_seconds))
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src") + os.pathsep + str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_STARTED", "pid": os.getpid(), "interval_seconds": interval}), flush=True)
    while not STOP:
        started = time.time()
        latest_age = None
        if LATEST.exists():
            latest_age = started - LATEST.stat().st_mtime
        if latest_age is not None and latest_age < interval * 0.8:
            print(
                json.dumps(
                    {
                        "status": "TRD_OUTCOME2_REFRESH_SKIPPED_FRESH",
                        "latest_age_seconds": round(latest_age, 1),
                        "interval_seconds": interval,
                    }
                ),
                flush=True,
            )
        else:
            result = subprocess.run(
                [_python(), str(AUDIT)],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
            )
            print(
                json.dumps(
                    {
                        "status": "TRD_OUTCOME2_REFRESH_CYCLE",
                        "returncode": result.returncode,
                        "elapsed_seconds": round(time.time() - started, 3),
                        "stdout_tail": (result.stdout or "")[-1500:],
                        "stderr_tail": (result.stderr or "")[-1500:],
                    },
                    default=str,
                ),
                flush=True,
            )
        for _ in range(interval):
            if STOP:
                break
            time.sleep(1)
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_STOPPED"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
