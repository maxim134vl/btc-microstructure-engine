#!/usr/bin/env python3
"""Behavioral validation service loop (observational / non-blocking)."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.behavioral_validation import (  # noqa: E402
    paths,
    run_once,
)

STOPPING = False


def _handle(signum: int, _frame: object) -> None:
    global STOPPING
    STOPPING = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MODEL-1 behavioral validation loop")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pid-file", default=str(ROOT / "run" / "behavioral_validation.pid"))
    args = parser.parse_args(argv)

    pid_path = Path(args.pid_file)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    try:
        while True:
            summary = run_once(repo_root=ROOT)
            print(
                f"[behavioral_validation] status={summary.get('status')} "
                f"eligible={summary.get('eligible_contexts')} "
                f"open={summary.get('open_predictions')} "
                f"evaluated={summary.get('evaluated_outcomes')}",
                flush=True,
            )
            if args.once or STOPPING:
                break
            time.sleep(max(1.0, float(args.interval_seconds)))
    finally:
        if pid_path.exists():
            try:
                if pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
