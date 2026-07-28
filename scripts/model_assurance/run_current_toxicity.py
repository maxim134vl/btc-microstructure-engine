#!/usr/bin/env python3
"""Current context/trade toxicity service loop."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.toxic_box.current_toxicity import load_config, run_once  # noqa: E402

STOPPING = False


def _handle(signum: int, _frame: object) -> None:
    global STOPPING
    STOPPING = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MODEL-4 current toxicity loop")
    parser.add_argument("--interval-seconds", type=float, default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pid-file", default=str(ROOT / "run" / "current_toxicity.pid"))
    args = parser.parse_args(argv)
    cfg = load_config(ROOT)
    interval = float(
        args.interval_seconds if args.interval_seconds is not None else cfg.get("poll_interval_seconds", 5)
    )
    pid_path = Path(args.pid_file)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    try:
        while True:
            summary = run_once(repo_root=ROOT)
            print(
                f"[current_toxicity] status={summary.get('status')} "
                f"ctx_eval={summary.get('context_predictions_evaluable')} "
                f"trd_eval={summary.get('trades_evaluable')} "
                f"candidates={int(summary.get('context_toxic_candidates') or 0)+int(summary.get('trade_toxic_candidates') or 0)}",
                flush=True,
            )
            if args.once or STOPPING:
                break
            time.sleep(max(1.0, interval))
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
