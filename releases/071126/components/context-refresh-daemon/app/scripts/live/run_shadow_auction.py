#!/usr/bin/env python3
"""Detached AUCTION_EPISODE_SHADOW process (AES0–AES5).

Observer-only. Independent per-TF auction engines. No canonical coupling.
Fails closed when external SSD is unavailable — never falls back to repo disk.
No full-history backfill on first live start unless --backfill is passed.
"""

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

from btc_ml.trading.shadow_auction import SHADOW_REFUSED  # noqa: E402
from btc_ml.trading.shadow_auction.runtime import (  # noqa: E402
    ShadowAuctionRuntime,
    refuse_without_storage,
)

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
    ap = argparse.ArgumentParser(description="Shadow Auction AES0–AES5 observer")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--poll-s", type=float, default=None)
    ap.add_argument("--health-every-s", type=float, default=None)
    ap.add_argument("--once", action="store_true", help="Bootstrap + one poll and exit")
    ap.add_argument(
        "--backfill",
        action="store_true",
        help="Explicit full incremental replay from source start (off by default)",
    )
    ap.add_argument("--no-aes2", action="store_true", help="Disable AES2 engines (foundation only)")
    ap.add_argument("--no-aes3", action="store_true", help="Disable AES3 hierarchy engine")
    ap.add_argument("--no-aes4", action="store_true", help="Disable AES4 canonical checkpoint linker")
    ap.add_argument("--no-aes5", action="store_true", help="Disable AES5 outcome / post-mortem evaluation")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    gate = refuse_without_storage(repo=REPO, config_path=args.config)
    if not gate.get("ok"):
        print(json.dumps(gate, default=str), flush=True)
        return 2

    try:
        runtime = ShadowAuctionRuntime.bootstrap(
            repo=REPO,
            config_path=args.config,
            enable_aes2=not args.no_aes2,
            enable_aes3=not args.no_aes3,
            enable_aes4=not args.no_aes4,
            enable_aes5=not args.no_aes5,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": SHADOW_REFUSED,
                    "ok": False,
                    "error": str(exc),
                    "canonical_unaffected": True,
                },
                default=str,
            ),
            flush=True,
        )
        return 2

    pid_path = REPO / str(runtime.config.get("pid_file") or "run/shadow_auction.pid")
    _write_pid(pid_path)
    health = runtime.write_health(status="RUNNING")
    print(
        json.dumps(
            {
                "status": "STARTED",
                "pid": os.getpid(),
                "data_root": str(runtime.store.data_root),
                "logic_fingerprint": runtime.contract.logic_fingerprint,
                "observer_only": True,
                "enforcement_enabled": False,
                "aes2_enabled": runtime.aes2_enabled,
                "aes3_enabled": runtime.aes3_enabled,
                "aes4_enabled": runtime.aes4_enabled,
                "aes5_enabled": runtime.aes5_enabled,
                "health_path": str(health),
            },
            default=str,
        ),
        flush=True,
    )

    if args.once:
        try:
            poll = runtime.poll_once(backfill=bool(args.backfill))
            print(json.dumps({"status": "POLL", **poll}, default=str), flush=True)
        finally:
            _clear_own_pid(pid_path)
        return 0

    poll_s = float(args.poll_s if args.poll_s is not None else runtime.config.get("poll_interval_s") or 1.0)
    health_every = float(
        args.health_every_s
        if args.health_every_s is not None
        else runtime.config.get("health_interval_s") or 2.0
    )
    last_health = 0.0
    try:
        while not STOP:
            try:
                runtime.poll_once(backfill=False)
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "status": "DEGRADED_POLL",
                            "error": str(exc),
                            "canonical_unaffected": True,
                        },
                        default=str,
                    ),
                    flush=True,
                )
            now = time.time()
            if now - last_health >= health_every:
                try:
                    from btc_ml.trading.shadow_auction.storage import validate_storage

                    validation = validate_storage(runtime.config, repo=REPO)
                    if not validation.ok:
                        runtime.write_health(status="DEGRADED_STORAGE", source_lag_ms=None)
                        print(
                            json.dumps(
                                {
                                    "status": "DEGRADED_STORAGE",
                                    "error": validation.error,
                                    "canonical_unaffected": True,
                                },
                                default=str,
                            ),
                            flush=True,
                        )
                        return 3
                    runtime.store.validation = validation
                    runtime.write_health(status="RUNNING")
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "status": "DEGRADED",
                                "error": str(exc),
                                "canonical_unaffected": True,
                            },
                            default=str,
                        ),
                        flush=True,
                    )
                    return 3
                last_health = now
            time.sleep(max(0.05, poll_s))
    finally:
        try:
            runtime.write_health(status="STOPPED")
        except Exception:
            pass
        _clear_own_pid(pid_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
