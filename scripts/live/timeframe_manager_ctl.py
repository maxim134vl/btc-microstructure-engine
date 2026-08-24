#!/usr/bin/env python3
"""Control S4.1 timeframe manager daemon (start/stop/status/restart)."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PID_PATH = REPO / "run" / "timeframe_manager.pid"
LOG_PATH = REPO / "logs" / "timeframe_manager.log"
HEALTH_PATH = REPO / "data" / "runtime" / "timeframe_manager_health.json"
STOP_INTENT_PATH = REPO / "run" / "timeframe_manager.stop_intent.json"
CONTROLLED_RESTART_PATH = REPO / "run" / "timeframe_manager.controlled_restart.json"
RUNNER = REPO / "scripts" / "live" / "timeframe_manager_daemon.py"
SERVICE_MARK = "timeframe_manager_daemon.py"
CTL_MARK = "timeframe_manager_ctl.py"

sys.path.insert(0, str(REPO / "src"))
from btc_ml.runtime.intrabar_supervision import (  # noqa: E402
    RestartPolicy,
    clear_stop_intent,
    load_config,
    mark_controlled_restart,
    write_stop_intent,
)


def _python() -> str:
    for cand in (REPO / "venv" / "bin" / "python", REPO / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _command(pid: int) -> str:
    try:
        return subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _is_runner(pid: int | None) -> bool:
    if not pid:
        return False
    cmd = _command(pid)
    return SERVICE_MARK in cmd and CTL_MARK not in cmd


def _runner_pids() -> list[int]:
    found: list[int] = []
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return found
    for line in out.splitlines():
        if SERVICE_MARK not in line or CTL_MARK in line or "pytest" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if pid != os.getpid() and _alive(pid):
            found.append(pid)
    return found


def _keep_live_runner() -> int | None:
    pid = _read_pid()
    if _alive(pid) and _is_runner(pid):
        return pid
    live = _runner_pids()
    if not live:
        return None
    if pid in live:
        return pid
    return live[0]


def cmd_status() -> int:
    pid = _read_pid()
    health = None
    if HEALTH_PATH.exists():
        try:
            health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            health = {"error": str(exc)}
    print(
        json.dumps(
            {
                "pid": pid,
                "alive": _alive(pid),
                "pid_path": str(PID_PATH),
                "log_path": str(LOG_PATH),
                "health_path": str(HEALTH_PATH),
                "health": health,
            },
            indent=2,
            default=str,
        )
    )
    return 0 if _alive(pid) else 1


def cmd_start() -> int:
    clear_stop_intent(STOP_INTENT_PATH)
    keep = _keep_live_runner()
    if keep is not None:
        stale = _read_pid()
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(f"{keep}\n", encoding="utf-8")
        payload: dict[str, object] = {"status": "already_running", "pid": keep}
        if stale != keep:
            payload["note"] = "adopted"
            payload["replaced_stale_pid"] = stale
        print(json.dumps(payload))
        return 0
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            _python(),
            str(RUNNER),
            "--approved-timeframe-manager",
            "--paper-only",
            "--no-real-execution",
            "--interval-seconds",
            "60",
        ],
        cwd=str(REPO),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
    )
    PID_PATH.write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(1.0)
    print(
        json.dumps(
            {
                "status": "started",
                "pid": proc.pid,
                "python": _python(),
                "log": str(LOG_PATH),
            }
        )
    )
    return 0 if _alive(proc.pid) else 1


def _kill_process() -> tuple[int | None, bool]:
    pid = _read_pid()
    if not _alive(pid):
        extras = _runner_pids()
        pid = extras[0] if extras else pid
    if not _alive(pid):
        if PID_PATH.exists():
            PID_PATH.unlink(missing_ok=True)
        return pid, False
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not _alive(pid):
            break
        time.sleep(0.2)
    forced = False
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
        forced = True
    PID_PATH.unlink(missing_ok=True)
    return pid, forced


def cmd_stop() -> int:
    pid, forced = _kill_process()
    write_stop_intent(STOP_INTENT_PATH, reason="manual", stopped_by="timeframe_manager_ctl stop")
    if pid is None:
        print(json.dumps({"status": "not_running", "stop_intent": True}))
        return 0
    print(json.dumps({"status": "stopped", "pid": pid, "forced_kill": forced, "stop_intent": True}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "status", "restart"))
    args = ap.parse_args()
    if args.action == "status":
        return cmd_status()
    if args.action == "start":
        return cmd_start()
    if args.action == "stop":
        return cmd_stop()
    if args.action == "restart":
        policy = RestartPolicy.from_config(load_config(REPO))
        mark_controlled_restart(
            CONTROLLED_RESTART_PATH,
            grace_seconds=policy.controlled_restart_grace_seconds,
        )
        _kill_process()
        clear_stop_intent(STOP_INTENT_PATH)
        time.sleep(0.5)
        return cmd_start()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
