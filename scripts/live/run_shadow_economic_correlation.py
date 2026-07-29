#!/usr/bin/env python3
"""Detached SHADOW-EQCORR1 observe-only service."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.shadow_economic_correlation.engine import ShadowEconomicCorrelationEngine  # noqa: E402

STOP = False


def _stop(*_a: object) -> None:
    global STOP
    STOP = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=1000)
    ap.add_argument("--health-every-s", type=float, default=2.0)
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    engine = ShadowEconomicCorrelationEngine(repo=REPO, strict_epoch=True)
    health = engine.write_health()
    pid_path = REPO / "run" / "shadow_economic_correlation.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{__import__('os').getpid()}\n", encoding="utf-8")
    print(json.dumps({"status": "STARTED", "pid": __import__("os").getpid(), "health": health}, default=str), flush=True)

    last_health = 0.0
    try:
        while not STOP:
            try:
                engine.poll_once()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"poll:{exc}")
                engine.write_health()
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
