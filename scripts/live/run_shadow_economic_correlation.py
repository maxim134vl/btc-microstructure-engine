#!/usr/bin/env python3
"""Detached SHADOW-EQCORR1 observe-only service."""

from __future__ import annotations

import argparse
import json
import os
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


def _write_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _clear_own_pid(path: Path) -> None:
    if not path.exists():
        return
    try:
        if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
            path.unlink(missing_ok=True)
    except Exception:
        return


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
    _write_pid(pid_path)
    print(json.dumps({"status": "STARTED", "pid": os.getpid(), "health": health}, default=str), flush=True)

    last_health = 0.0
    try:
        while not STOP:
            try:
                engine.poll_once()
            except Exception as exc:  # noqa: BLE001
                engine.errors.append(f"poll:{exc}")
                try:
                    engine.write_health()
                except Exception as hexc:  # noqa: BLE001
                    engine.errors.append(f"health:{hexc}")
            now = time.time()
            if now - last_health >= args.health_every_s:
                try:
                    engine.write_health()
                    _write_pid(pid_path)
                except Exception as hexc:  # noqa: BLE001
                    engine.errors.append(f"health:{hexc}")
                last_health = now
            time.sleep(max(0.05, args.poll_ms / 1000.0))
    finally:
        try:
            engine.write_health()
        except Exception:
            pass
        _clear_own_pid(pid_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
