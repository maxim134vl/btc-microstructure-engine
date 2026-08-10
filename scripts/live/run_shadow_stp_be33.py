#!/usr/bin/env python3
"""Independent observe-only runner for STP_BE33."""

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

from btc_ml.trading.shadow_structural_protection.be33 import StpBe33Engine  # noqa: E402

STOP = False


def _stop(*_args: object) -> None:
    global STOP
    STOP = True


def _active_epoch_id() -> str:
    path = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["paper_epoch_id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-ms", type=int, default=1000)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    engine = StpBe33Engine(repo=REPO)
    initial = engine.poll_once()
    print(json.dumps({"status": "STP_BE33_STARTED", "pid": os.getpid(), "health": initial["health"]}), flush=True)
    while not STOP:
        try:
            active_epoch = _active_epoch_id()
            if active_epoch != engine.epoch_id:
                engine = StpBe33Engine(repo=REPO, epoch_id=active_epoch)
                print(json.dumps({"status": "STP_BE33_EPOCH_ROLLOVER", "paper_epoch_id": active_epoch}), flush=True)
            result = engine.poll_once()
            if result["actions"]:
                print(json.dumps(result, default=str), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"status": "STP_BE33_POLL_ERROR", "error": str(exc)}), flush=True)
        time.sleep(max(0.05, args.poll_ms / 1000.0))
    try:
        engine.write_health()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
