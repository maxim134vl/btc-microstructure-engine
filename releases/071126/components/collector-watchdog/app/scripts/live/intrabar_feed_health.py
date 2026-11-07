#!/usr/bin/env python3
"""Intrabar feed health checks for paper controller entry gate (paper-only).

Does not start/stop processes. Public market-data feed diagnostics only.
No exchange order APIs.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PID_FILE = ROOT / "run" / "live_binance_intrabar_feed.pid"
DEFAULT_PARQUET = ROOT / "data" / "live" / "live_market_intrabar_feed.parquet"
MAX_AGE_SECONDS = 150.0

ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY = "ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY"
EXIT_CLOCK_INTRABAR_FEED_UNHEALTHY_FALLBACK = "EXIT_CLOCK_INTRABAR_FEED_UNHEALTHY_FALLBACK"


def _pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _list_feed_pids() -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if "scripts/live/live_binance_intrabar_feed.py" not in line:
            continue
        if "intrabar_feed_ctl" in line or "grep" in line or "pytest" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            pids.append(int(parts[0]))
        except Exception:
            continue
    return pids


def _seconds_since_latest_row(parquet: Path) -> float | None:
    if not parquet.exists():
        return None
    try:
        df = pd.read_parquet(parquet)
    except Exception:
        return None
    if df.empty or "observed_at_utc" not in df.columns:
        return None
    ts = pd.to_datetime(df["observed_at_utc"], utc=True, errors="coerce").dropna().sort_values()
    if not len(ts):
        return None
    latest = ts.iloc[-1].to_pydatetime()
    return float((datetime.now(timezone.utc) - latest).total_seconds())


def check_intrabar_feed_health(
    *,
    root: Path | None = None,
    pid_file: Path | None = None,
    parquet: Path | None = None,
    max_age_seconds: float = MAX_AGE_SECONDS,
    # Test overrides (skip live process/ps when provided)
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return health snapshot used by paper entry gate."""
    if override is not None:
        status = str(override.get("status") or "STOPPED")
        age = override.get("seconds_since_latest_row")
        try:
            age_f = float(age) if age is not None else None
        except Exception:
            age_f = None
        dup = int(override.get("duplicate_count") or 0)
        orphan = int(override.get("orphan_count") or 0)
        healthcheck_pass = bool(override.get("healthcheck_pass", False))
        if "healthcheck_pass" not in override:
            healthcheck_pass = (
                status == "RUNNING"
                and age_f is not None
                and age_f <= max_age_seconds
                and dup == 0
                and orphan == 0
            )
        ok = bool(healthcheck_pass)
        reasons: list[str] = []
        if not ok:
            reasons.append(ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY)
            if status != "RUNNING":
                reasons.append(f"intrabar_status={status}")
            if age_f is None:
                reasons.append("intrabar_rows_missing")
            elif age_f > max_age_seconds:
                reasons.append(f"intrabar_stale_age={age_f:.1f}s")
            if dup:
                reasons.append(f"intrabar_duplicate_count={dup}")
            if orphan:
                reasons.append(f"intrabar_orphan_count={orphan}")
        return {
            "intrabar_feed_status": status,
            "intrabar_seconds_since_latest_row": age_f,
            "intrabar_healthcheck_pass": ok,
            "intrabar_duplicate_count": dup,
            "intrabar_orphan_count": orphan,
            "entry_health_gate_pass": ok,
            "entry_health_gate_block_reason": (
                None if ok else ",".join(reasons) or ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY
            ),
            "execution_enabled": False,
            "paper_only": True,
        }

    root = root or ROOT
    pid_file = pid_file or (root / "run" / "live_binance_intrabar_feed.pid")
    parquet = parquet or (root / "data" / "live" / "live_market_intrabar_feed.parquet")

    pid = _read_pid(pid_file)
    alive = _pid_alive(pid)
    live_pids = [p for p in _list_feed_pids() if _pid_alive(p)]
    if not live_pids and alive and pid is not None:
        live_pids = [pid]

    live_count = len(live_pids)
    duplicate_count = max(0, live_count - 1)
    orphan_count = 0
    if live_count == 1 and (pid is None or not alive or (pid not in live_pids)):
        orphan_count = 1
    elif live_count > 1:
        orphan_count = sum(1 for p in live_pids if p != pid)

    if live_count > 1:
        status = "DUPLICATE_RUNNING"
    elif live_count == 1 and (pid is None or not alive or pid not in live_pids):
        status = "ORPHAN_RUNNING"
    elif live_count == 1 and alive:
        status = "RUNNING"
    elif pid is not None and not alive:
        status = "STALE_PID"
    else:
        status = "STOPPED"

    age_f = _seconds_since_latest_row(parquet)
    ok = (
        status == "RUNNING"
        and age_f is not None
        and age_f <= max_age_seconds
        and duplicate_count == 0
        and orphan_count == 0
    )
    reasons = []
    if not ok:
        reasons.append(ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY)
        if status != "RUNNING":
            reasons.append(f"intrabar_status={status}")
        if age_f is None:
            reasons.append("intrabar_rows_missing")
        elif age_f > max_age_seconds:
            reasons.append(f"intrabar_stale_age={age_f:.1f}s")
        if duplicate_count:
            reasons.append(f"intrabar_duplicate_count={duplicate_count}")
        if orphan_count:
            reasons.append(f"intrabar_orphan_count={orphan_count}")

    return {
        "intrabar_feed_status": status,
        "intrabar_pid": pid,
        "intrabar_live_pids": live_pids,
        "intrabar_seconds_since_latest_row": age_f,
        "intrabar_healthcheck_pass": ok,
        "intrabar_duplicate_count": duplicate_count,
        "intrabar_orphan_count": orphan_count,
        "entry_health_gate_pass": ok,
        "entry_health_gate_block_reason": (
            None if ok else ",".join(reasons) or ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY
        ),
        "execution_enabled": False,
        "paper_only": True,
    }


__all__ = [
    "ENTRY_BLOCKED_INTRABAR_FEED_UNHEALTHY",
    "EXIT_CLOCK_INTRABAR_FEED_UNHEALTHY_FALLBACK",
    "MAX_AGE_SECONDS",
    "check_intrabar_feed_health",
]
