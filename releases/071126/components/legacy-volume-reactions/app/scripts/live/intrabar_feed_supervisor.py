#!/usr/bin/env python3
"""Supervise paper-only Binance intrabar feed: heartbeat + parquet freshness + recovery.

Does NOT touch paper controller or runtime-stack.
Restarts feed via scripts/intrabar_feed_ctl.sh only.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PID_PATH = ROOT / "run" / "live_binance_intrabar_feed_supervisor.pid"
STATE_PATH = ROOT / "run" / "live_binance_intrabar_feed_supervisor.json"
LOG_PATH = ROOT / "logs" / "live_binance_intrabar_feed_supervisor.log"
FEED_PID_PATH = ROOT / "run" / "live_binance_intrabar_feed.pid"
HEARTBEAT_PATH = ROOT / "run" / "live_binance_intrabar_feed_heartbeat.json"
FEED_PARQUET = ROOT / "data" / "live" / "live_market_intrabar_feed.parquet"
CTL = ROOT / "scripts" / "intrabar_feed_ctl.sh"

DEFAULT_CHECK_INTERVAL = 30
HEARTBEAT_STALE_SECONDS = 180.0
ROW_STALE_SECONDS = 180.0

_STOP = False


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _log(msg: str) -> None:
    line = f"{_iso_now()} {msg}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
    print(line, flush=True)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
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


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{pid}\n", encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age_seconds(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        import pandas as pd

        ts = pd.to_datetime(iso_ts, utc=True, errors="coerce")
        if ts is pd.NaT or ts is None:
            return None
        return float((datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds())
    except Exception:
        return None


def list_feed_pids() -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if "scripts/live/live_binance_intrabar_feed.py" not in line:
            continue
        if "intrabar_feed_ctl" in line or "pytest" in line or "intrabar_feed_supervisor" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            pids.append(int(parts[0]))
        except ValueError:
            continue
    return [p for p in pids if _pid_alive(p)]


def latest_row_age_seconds() -> float | None:
    if not FEED_PARQUET.exists():
        return None
    try:
        import pandas as pd

        df = pd.read_parquet(FEED_PARQUET)
        if df.empty or "observed_at_utc" not in df.columns:
            return None
        ts = pd.to_datetime(df["observed_at_utc"], utc=True, errors="coerce").dropna()
        if ts.empty:
            return None
        latest = ts.max().to_pydatetime()
        return float((datetime.now(timezone.utc) - latest).total_seconds())
    except Exception:
        return None


def classify_feed() -> dict[str, Any]:
    feed_pid = _read_pid(FEED_PID_PATH)
    live = list_feed_pids()
    alive = _pid_alive(feed_pid)
    duplicate_count = max(0, len(live) - 1) if live else 0
    orphan_count = 0
    if live:
        if not alive:
            orphan_count = len(live)
        else:
            orphan_count = sum(1 for p in live if p != feed_pid)
    hb = _load_json(HEARTBEAT_PATH)
    hb_age = _age_seconds(hb.get("heartbeat_at_utc"))
    row_age = latest_row_age_seconds()

    if len(live) > 1:
        status = "DUPLICATE_RUNNING"
    elif len(live) == 1 and not alive:
        status = "ORPHAN_RUNNING"
    elif len(live) == 1 and alive:
        status = "RUNNING"
    elif feed_pid and not alive:
        status = "STALE_PID"
    else:
        status = "STOPPED"

    stale = False
    reasons: list[str] = []
    if status in {"STOPPED", "STALE_PID", "DUPLICATE_RUNNING", "ORPHAN_RUNNING"}:
        stale = True
        reasons.append(f"feed_status={status}")
    if hb_age is None or hb_age > HEARTBEAT_STALE_SECONDS:
        stale = True
        reasons.append("heartbeat_stale_or_missing")
    if row_age is None or row_age > ROW_STALE_SECONDS:
        stale = True
        reasons.append("latest_row_stale_or_missing")

    return {
        "feed_pid": feed_pid,
        "feed_status": status,
        "heartbeat_age_seconds": hb_age,
        "latest_row_age_seconds": row_age,
        "duplicate_count": duplicate_count,
        "orphan_count": orphan_count,
        "live_pids": live,
        "needs_recovery": stale,
        "recovery_reason": ",".join(reasons) if reasons else None,
    }


def attempt_recovery(reason: str) -> dict[str, Any]:
    _log(f"recovery_attempt reason={reason}")
    try:
        proc = subprocess.run(
            ["bash", str(CTL), "restart"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        ok = proc.returncode == 0
        _log(f"recovery_ctl_rc={proc.returncode} ok={ok}")
        return {
            "recovery_attempted": True,
            "recovery_success": ok,
            "recovery_reason": reason,
            "ctl_stdout": (proc.stdout or "")[-2000:],
            "ctl_stderr": (proc.stderr or "")[-2000:],
        }
    except Exception as exc:  # noqa: BLE001
        _log(f"recovery_failed={exc!r}")
        return {
            "recovery_attempted": True,
            "recovery_success": False,
            "recovery_reason": reason,
            "error": repr(exc),
        }


def write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_once(*, recover: bool = True) -> dict[str, Any]:
    info = classify_feed()
    recovery = {
        "recovery_attempted": False,
        "recovery_success": False,
        "recovery_reason": info.get("recovery_reason"),
    }
    if recover and info.get("needs_recovery"):
        recovery = attempt_recovery(str(info.get("recovery_reason") or "stale_or_dead"))
        info = classify_feed()
    state = {
        "supervisor_pid": os.getpid(),
        "checked_at_utc": _iso_now(),
        "feed_pid": info.get("feed_pid"),
        "feed_status": info.get("feed_status"),
        "heartbeat_age_seconds": info.get("heartbeat_age_seconds"),
        "latest_row_age_seconds": info.get("latest_row_age_seconds"),
        "recovery_attempted": bool(recovery.get("recovery_attempted")),
        "recovery_success": bool(recovery.get("recovery_success")),
        "recovery_reason": recovery.get("recovery_reason"),
        "duplicate_count": info.get("duplicate_count"),
        "orphan_count": info.get("orphan_count"),
        "live_pids": info.get("live_pids"),
        "paper_controller_untouched": True,
        "runtime_stack_untouched": True,
        "execution_enabled": False,
        "paper_only": True,
    }
    write_state(state)
    return state


def _handle_sig(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    _log("supervisor_signal_stopping")


def run_loop(interval: int = DEFAULT_CHECK_INTERVAL) -> int:
    global _STOP
    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except Exception:
        pass
    atexit.register(lambda: PID_PATH.unlink(missing_ok=True))
    _write_pid(PID_PATH, os.getpid())
    _log(f"supervisor_start interval={interval}s pid={os.getpid()}")
    while not _STOP:
        try:
            state = check_once(recover=True)
            _log(
                "check "
                f"feed_status={state.get('feed_status')} "
                f"hb_age={state.get('heartbeat_age_seconds')} "
                f"row_age={state.get('latest_row_age_seconds')} "
                f"recovery={state.get('recovery_attempted')}/{state.get('recovery_success')}"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"supervisor_loop_error={exc!r}")
        for _ in range(int(interval)):
            if _STOP:
                break
            time.sleep(1)
    PID_PATH.unlink(missing_ok=True)
    _log("supervisor_stopped")
    return 0


def daemonize() -> None:
    """Double-fork then re-exec --foreground."""
    if os.fork() > 0:
        time.sleep(0.5)
        return
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "rb", 0) as devnull:
        os.dup2(devnull.fileno(), 0)
    log = open(LOG_PATH, "a", encoding="utf-8")
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), "--foreground"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Intrabar feed supervisor (paper-only)")
    parser.add_argument("--daemonize", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="Classify without recovery")
    parser.add_argument("--interval", type=int, default=DEFAULT_CHECK_INTERVAL)
    args = parser.parse_args(argv)

    if args.daemonize and not args.foreground and not args.once:
        daemonize()
        return 0
    if args.once or args.check_only:
        state = check_once(recover=not args.check_only)
        print(json.dumps(state, indent=2))
        return 0
    return run_loop(interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
