#!/usr/bin/env python3
"""Detached SHADOW-STP1 observe-only service."""

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

from btc_ml.trading.shadow_structural_protection import BLOCKED_NO_EXACT  # noqa: E402
from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine  # noqa: E402

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


def _active_epoch_id(repo: Path | None = None) -> str:
    root = repo or REPO
    path = root / "data" / "trading" / "paper_epochs" / "active.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"ACTIVE_EPOCH_UNREADABLE:{path}:{exc}") from exc

    epoch_id = str(payload.get("paper_epoch_id") or "").strip()
    if not epoch_id:
        raise RuntimeError(f"ACTIVE_EPOCH_ID_MISSING:{path}")
    return epoch_id


def _append_error_once(engine: StructuralProtectionEngine, message: str) -> None:
    if not engine.errors or engine.errors[-1] != message:
        engine.errors.append(message)


def _rollover_if_needed(
    engine: StructuralProtectionEngine,
) -> StructuralProtectionEngine:
    active_epoch = _active_epoch_id()
    if active_epoch == engine.epoch_id:
        return engine

    previous_epoch = engine.epoch_id
    replacement = StructuralProtectionEngine(repo=REPO, strict_epoch=True)
    health = replacement.write_health()

    if not replacement.exact_ok:
        raise RuntimeError(f"{BLOCKED_NO_EXACT}:{replacement.epoch_id}")
    if health.get("baseline_divergence_count"):
        raise RuntimeError(
            f"SHADOW_STP1_BASELINE_DIVERGENCE:{replacement.epoch_id}"
        )

    print(
        json.dumps(
            {
                "status": "SHADOW_STP_EPOCH_ROLLOVER",
                "pid": os.getpid(),
                "previous_epoch_id": previous_epoch,
                "active_epoch_id": replacement.epoch_id,
                "health": health,
            },
            default=str,
        ),
        flush=True,
    )
    return replacement


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=1000)
    ap.add_argument("--health-every-s", type=float, default=2.0)
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    engine = StructuralProtectionEngine(repo=REPO, strict_epoch=True)
    health = engine.write_health()
    if not engine.exact_ok:
        print(json.dumps({"status": BLOCKED_NO_EXACT, "health": health}, default=str), flush=True)
        return 2
    if health.get("baseline_divergence_count"):
        print(json.dumps({"status": "SHADOW_STP1_BASELINE_DIVERGENCE", "health": health}, default=str), flush=True)
        return 3

    pid_path = REPO / "run" / "shadow_structural_protection.pid"
    _write_pid(pid_path)
    print(json.dumps({"status": "STARTED", "pid": os.getpid(), "health": health}, default=str), flush=True)

    last_health = 0.0
    try:
        while not STOP:
            try:
                engine = _rollover_if_needed(engine)
            except Exception as exc:  # noqa: BLE001
                _append_error_once(engine, f"epoch_rollover:{exc}")
                try:
                    engine.write_health()
                    _write_pid(pid_path)
                except Exception as hexc:  # noqa: BLE001
                    _append_error_once(engine, f"health:{hexc}")
                time.sleep(max(0.05, args.poll_ms / 1000.0))
                continue

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
