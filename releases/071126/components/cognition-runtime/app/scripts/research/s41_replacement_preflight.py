#!/usr/bin/env python3
"""Preflight: can S4.1 independent TF paper replace LIVE1B cleanly?

Not an A/B vs LIVE1B. Checks blockers for cutover to manager→command→per-TF traders.
Exits 0 only if no hard blockers (or --allow-live1b-running for inspection).

  venv/bin/python scripts/research/s41_replacement_preflight.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.s41_command_relay.contract import (  # noqa: E402
    KINEMATICS,
    PROTOTYPE_ID,
    PRODUCTION_COMMAND_MEMORY,
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pid_alive(pid: int) -> bool:
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _list_pids(pattern: str) -> list[int]:
    import re
    import subprocess

    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    rx = re.compile(pattern)
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        if rx.search(parts[1]):
            try:
                pids.append(int(parts[0]))
            except ValueError:
                pass
    return pids


def check_live1b_paper() -> dict[str, Any]:
    pid_path = ROOT / "run" / "intrabar_paper_manager.pid"
    pids = _list_pids(r"run_intrabar_paper_manager\.py")
    file_pid = None
    if pid_path.exists():
        try:
            file_pid = int(pid_path.read_text().strip())
        except ValueError:
            file_pid = None
    running = bool(pids) or (file_pid is not None and _pid_alive(file_pid))
    return {
        "id": "LIVE1B_PAPER_STOPPED",
        "ok": not running,
        "severity": True,
        "detail": {
            "running": running,
            "pids": pids,
            "pid_file": file_pid,
        },
        "fix": "Stop run_intrabar_paper_manager before S4.1 cutover (no dual paper writers)",
    }


def check_s41_processes_down_for_reset() -> dict[str, Any]:
    """Before fresh books install, manager/traders should be down."""
    roles = {
        "timeframe_manager": r"timeframe_manager_daemon\.py",
        "trader_M15": r"timeframe_trader_daemon\.py --timeframe M15",
        "trader_M30": r"timeframe_trader_daemon\.py --timeframe M30",
        "trader_H1": r"timeframe_trader_daemon\.py --timeframe H1",
        "trader_H4": r"timeframe_trader_daemon\.py --timeframe H4",
    }
    alive = {role: _list_pids(pat) for role, pat in roles.items()}
    any_alive = any(bool(v) for v in alive.values())
    return {
        "id": "S41_PROCESSES_DOWN_FOR_BOOK_RESET",
        "ok": not any_alive,
        "severity": False,
        "detail": alive,
        "fix": "Stop S4.1 via timeframe_trading_ctl.sh before archiving/resetting books",
    }


def check_stuck_opens() -> dict[str, Any]:
    path = ROOT / "data" / "trading" / "manager" / "portfolio_summary.json"
    stuck: dict[str, Any] = {}
    if path.exists():
        port = json.loads(path.read_text(encoding="utf-8"))
        for tf, trader in (port.get("traders") or {}).items():
            op = trader.get("open_position") or {}
            if str(op.get("status") or "").upper() == "OPEN":
                stuck[tf] = {
                    "direction": op.get("direction"),
                    "opened_at": op.get("opened_at"),
                    "position_id": op.get("position_id"),
                }
    return {
        "id": "FRESH_BOOKS_NO_STUCK_OPEN",
        "ok": len(stuck) == 0,
        "severity": True,
        "detail": stuck,
        "fix": "Archive Jul stuck OPEN LONGs and install empty per-TF books before start",
    }


def check_command_memory_not_sole_blocker() -> dict[str, Any]:
    tip = None
    if PRODUCTION_COMMAND_MEMORY.exists():
        df = pd.read_parquet(PRODUCTION_COMMAND_MEMORY, columns=["evaluation_timestamp"])
        tip = str(pd.to_datetime(df["evaluation_timestamp"], utc=True).max())
    return {
        "id": "COMMAND_MEMORY_TIP_INFO",
        "ok": True,
        "severity": False,
        "detail": {"tip": tip, "path": str(PRODUCTION_COMMAND_MEMORY)},
        "fix": "On cutover set activation_boundary >= cutover time; optional archive+new memory",
    }


def check_mtf_availability() -> dict[str, Any]:
    path = ROOT / "data" / "runtime" / "multi_timeframe_availability_latest.json"
    if not path.exists():
        return {
            "id": "MTF_AVAILABILITY_FRESH",
            "ok": False,
            "severity": True,
            "detail": {"missing": str(path)},
            "fix": "MTF availability latest required for manager evaluation clock",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    tip = payload.get("latest_evaluation_timestamp")
    ts = pd.to_datetime(tip, utc=True, errors="coerce")
    age_s = None if pd.isna(ts) else float((pd.Timestamp.now(tz="UTC") - ts).total_seconds())
    # Manager polls ~60s; allow 2h staleness as hard fail (context refresh may lag).
    ok = age_s is not None and age_s < 7200
    return {
        "id": "MTF_AVAILABILITY_FRESH",
        "ok": ok,
        "severity": True,
        "detail": {"latest_evaluation_timestamp": tip, "age_seconds": age_s},
        "fix": "Ensure MTF availability runtime is writing tips",
    }


def check_lifecycle_present() -> dict[str, Any]:
    path = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    if not path.exists():
        return {
            "id": "LIFECYCLE_PRESENT",
            "ok": False,
            "severity": True,
            "detail": {"missing": str(path)},
            "fix": "Lifecycle memory required for per-TF state adapter",
        }
    df = pd.read_parquet(path, columns=["timestamp", "active_market_context"])
    tip = pd.to_datetime(df["timestamp"], utc=True).max()
    return {
        "id": "LIFECYCLE_PRESENT",
        "ok": True,
        "severity": True,
        "detail": {
            "rows": int(len(df)),
            "tip": str(tip),
            "tip_context": str(df.loc[pd.to_datetime(df["timestamp"], utc=True).idxmax(), "active_market_context"]),
        },
        "fix": None,
    }


def check_m15_catchup_clean() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts" / "live"))
    import append_context_decision_log as logger  # noqa: WPS433

    life = logger.load_parquet(logger.LIFECYCLE_PATH)
    dec = logger.load_decision_log(logger.DECISION_LOG_PATH)
    n = len(
        logger.find_confirmation_catchup_timestamps(
            life, dec, from_timestamp="2026-08-01T00:00:00Z"
        )
    )
    return {
        "id": "M15_DECISION_CATCHUP_CLEAN",
        "ok": n == 0,
        "severity": False,
        "detail": {"aug_catchup_candidates": n},
        "fix": "Run confirmation catch-up if candidates remain",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-live1b-running",
        action="store_true",
        help="Do not fail if LIVE1B paper is still up (inspection only)",
    )
    args = parser.parse_args(argv)

    checks = [
        check_live1b_paper(),
        check_s41_processes_down_for_reset(),
        check_stuck_opens(),
        check_command_memory_not_sole_blocker(),
        check_mtf_availability(),
        check_lifecycle_present(),
        check_m15_catchup_clean(),
    ]
    if args.allow_live1b_running:
        for c in checks:
            if c["id"] == "LIVE1B_PAPER_STOPPED":
                c["ok"] = True
                c["waived"] = True

    hard_fails = [c for c in checks if c.get("severity") and not c.get("ok")]
    soft_fails = [c for c in checks if not c.get("severity") and not c.get("ok")]

    payload = {
        "prototype_id": PROTOTYPE_ID,
        "purpose": "LIVE1B_REPLACEMENT_PREFLIGHT",
        "kinematics": KINEMATICS,
        "generated_at": _utc(),
        "ready_for_cutover": len(hard_fails) == 0,
        "hard_failures": [c["id"] for c in hard_fails],
        "soft_failures": [c["id"] for c in soft_fails],
        "checks": checks,
        "next_if_ready": [
            "Archive stuck S4.1 books + install empty books",
            "Stop LIVE1B paper manager",
            "Set activation boundary = cutover UTC",
            "bash scripts/timeframe_trading_ctl.sh start manager && start traders",
            "Watch logs + command intents per TF for 15–30m",
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0 if payload["ready_for_cutover"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
