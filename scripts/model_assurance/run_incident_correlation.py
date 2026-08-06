#!/usr/bin/env python3
"""Incident correlation service loop (MODEL-5)."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.runtime_health import mark_health_stopped  # noqa: E402

from btc_ml.model_assurance.toxic_box.incident_correlation import run_once  # noqa: E402

STOPPING = False
POLL_INTERVAL_SECONDS = 5.0


def _handle(signum: int, _frame: object) -> None:
    global STOPPING
    STOPPING = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MODEL-5 incident correlation loop")
    parser.add_argument("--interval-seconds", type=float, default=POLL_INTERVAL_SECONDS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pid-file", default=str(ROOT / "run" / "incident_correlation.pid"))
    args = parser.parse_args(argv)
    interval = float(args.interval_seconds)
    pid_path = Path(args.pid_file)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    try:
        while True:
            summary = run_once(repo_root=ROOT)
            print(
                f"[incident_correlation] status={summary.get('status')} "
                f"incidents={summary.get('distinct_incidents')} "
                f"cross={summary.get('cross_branch_incidents')} "
                f"harm={summary.get('economic_harm_usd')}",
                flush=True,
            )
            if args.once or STOPPING:
                break
            time.sleep(max(1.0, interval))
    finally:
        try:
            mark_health_stopped(
                health_path=(
                    ROOT / "data" / "model_assurance" / "toxic_box" / "incidents" / "runtime" / "health.json"
                ),
                pid=os.getpid(),
            )
        except Exception:
            pass

        if pid_path.exists():
            try:
                if pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
