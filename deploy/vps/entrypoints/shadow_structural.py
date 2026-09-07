#!/usr/bin/env python3
"""VPS Structural Protection entrypoint.

Uses StructuralProtectionEngine with:
  strict_epoch=False          — accept VPS bootstrap epoch from active.json
  allow_start_without_exact=True — allow STARTING when exact intrabar volume
                                   history is not yet available on a fresh volume

Production scripts/live/run_shadow_structural_protection.py exits 2 when
exact_ok is false; that is inappropriate for a clean VPS smoke volume.
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

from btc_ml.trading.shadow_structural_protection.engine import (  # noqa: E402
    StructuralProtectionEngine,
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

    engine = StructuralProtectionEngine(
        repo=REPO,
        strict_epoch=False,
        allow_start_without_exact=True,
    )
    health = engine.write_health()
    pid_path = REPO / "run" / "shadow_structural_protection.pid"
    _write_pid(pid_path)
    readiness = "HEALTHY" if engine.exact_ok else "STARTING"
    print(
        json.dumps(
            {
                "status": "STARTED",
                "mode": "VPS_DEPLOY",
                "readiness": readiness,
                "strict_epoch": False,
                "allow_start_without_exact": True,
                "exact_ok": bool(engine.exact_ok),
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
