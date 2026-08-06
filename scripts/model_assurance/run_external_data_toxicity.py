#!/usr/bin/env python3
"""External Data Toxicity service loop (observational / non-blocking)."""

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

from btc_ml.model_assurance.toxic_box.external_data import (  # noqa: E402
    evaluate_external_sources,
    load_external_source_registry,
)

STOPPING = False


def _handle(signum: int, _frame: object) -> None:
    global STOPPING
    STOPPING = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MODEL-2 external data toxicity loop")
    parser.add_argument("--interval-seconds", type=float, default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pid-file", default=str(ROOT / "run" / "external_data_toxicity.pid"))
    args = parser.parse_args(argv)

    cfg = load_external_source_registry(ROOT)
    interval = float(args.interval_seconds if args.interval_seconds is not None else cfg.get("check_interval_seconds", 5))

    pid_path = Path(args.pid_file)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    try:
        while True:
            result = evaluate_external_sources(repo_root=ROOT)
            summary = result.get("summary") or {}
            print(
                f"[external_data_toxicity] status={summary.get('status')} "
                f"healthy={summary.get('healthy_sources')} "
                f"degraded={summary.get('degraded_sources')} "
                f"open={summary.get('open_events')}",
                flush=True,
            )
            if args.once or STOPPING:
                break
            time.sleep(max(1.0, interval))
    finally:
        try:
            mark_health_stopped(
                health_path=(
                    ROOT / "data" / "model_assurance" / "toxic_box" / "external_data" / "runtime" / "health.json"
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
