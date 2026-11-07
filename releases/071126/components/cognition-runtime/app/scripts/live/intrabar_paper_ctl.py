#!/usr/bin/env python3
"""Control LIVE1B intrabar paper manager (start/stop/status)."""

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
PID_PATH = REPO / "run" / "intrabar_paper_manager.pid"
LOG_PATH = REPO / "run" / "logs" / "intrabar_paper_manager.log"
HEALTH_PATH = REPO / "data" / "runtime" / "intrabar_paper_health.json"
STOP_INTENT_PATH = REPO / "run" / "intrabar_paper_manager.stop_intent.json"
CONTROLLED_RESTART_PATH = REPO / "run" / "intrabar_paper_manager.controlled_restart.json"
RUNNER = REPO / "scripts" / "live" / "run_intrabar_paper_manager.py"

sys.path.insert(0, str(REPO / "src"))
from btc_ml.runtime.intrabar_supervision import (  # noqa: E402
    RestartPolicy,
    clear_stop_intent,
    load_config,
    mark_controlled_restart,
    write_stop_intent,
)


def _python() -> str:
    """Prefer repo venv (has websocket-client) over system Python."""
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
    return 0


def cmd_start() -> int:
    clear_stop_intent(STOP_INTENT_PATH)
    pid = _read_pid()
    if _alive(pid):
        print(json.dumps({"status": "already_running", "pid": pid}))
        return 0
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [_python(), str(RUNNER)],
        cwd=str(REPO),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
    )
    PID_PATH.write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(1.0)
    print(json.dumps({"status": "started", "pid": proc.pid, "python": _python(), "log": str(LOG_PATH)}))
    return 0


def _kill_process() -> tuple[int | None, bool]:
    pid = _read_pid()
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
    if pid is None and not PID_PATH.exists():
        write_stop_intent(STOP_INTENT_PATH, reason="manual", stopped_by="intrabar_paper_ctl stop")
        print(json.dumps({"status": "not_running", "stop_intent": True}))
        return 0
    write_stop_intent(STOP_INTENT_PATH, reason="manual", stopped_by="intrabar_paper_ctl stop")
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
