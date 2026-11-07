#!/usr/bin/env python3
"""VPS EQCORR entrypoint (always-on).

Uses the canonical ShadowEconomicCorrelationEngine with strict_epoch=False so a
newly bootstrapped VPS paper epoch (active.json) is accepted. Production
scripts/live/run_shadow_economic_correlation.py hardcodes strict_epoch=True
against a research epoch id and must not be inventively flag-patched.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")).resolve()
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from btc_ml.trading.shadow_economic_correlation.engine import (  # noqa: E402
    ShadowEconomicCorrelationEngine,
)

STOP = False


def _stop(*_a: object) -> None:
    global STOP
    STOP = True


def _write_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{os.getpid()}\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=1000)
    ap.add_argument("--health-every-s", type=float, default=2.0)
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    active = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    if not active.is_file():
        print(json.dumps({"error": "no_active_epoch", "path": str(active)}), flush=True)
        return 2

    engine = ShadowEconomicCorrelationEngine(repo=REPO, strict_epoch=False)
    health = engine.write_health()
    pid_path = REPO / "run" / "shadow_economic_correlation.pid"
    _write_pid(pid_path)
    print(
        json.dumps(
            {
                "status": "STARTED",
                "mode": "VPS_DEPLOY",
                "strict_epoch": False,
                "pid": os.getpid(),
                "epoch_id": engine.epoch_id,
                "health": health,
            },
            default=str,
        ),
        flush=True,
    )

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
