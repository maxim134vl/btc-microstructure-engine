#!/usr/bin/env python3
"""Control wrapper for LIVE1A/LIVE1B process supervisor."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PID_PATH = ROOT / "run" / "intrabar_process_supervisor.pid"
SUPERVISOR = ROOT / "scripts" / "live" / "intrabar_process_supervisor.py"
OPS_STATUS = ROOT / "data" / "runtime" / "intrabar_operational_status.json"


def _python() -> str:
    for cand in (ROOT / "venv" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
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
    ops = {}
    if OPS_STATUS.exists():
        try:
            ops = json.loads(OPS_STATUS.read_text(encoding="utf-8"))
        except Exception as exc:
            ops = {"error": str(exc)}
    print(
        json.dumps(
            {
                "supervisor_pid": pid,
                "supervisor_alive": _alive(pid),
                "operational_status": ops,
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_start() -> int:
    pid = _read_pid()
    if _alive(pid):
        print(json.dumps({"status": "already_running", "pid": pid}))
        return 0
    log_path = ROOT / "run" / "logs" / "intrabar_process_supervisor.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [_python(), str(SUPERVISOR)],
        cwd=str(ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
    )
    time.sleep(1.0)
    adopted = _read_pid()
    print(
        json.dumps(
            {
                "status": "started",
                "launcher_pid": proc.pid,
                "supervisor_pid": adopted,
                "log": str(log_path),
            }
        )
    )
    return 0 if _alive(adopted) else 1


def cmd_stop() -> int:
    pid = _read_pid()
    if not _alive(pid):
        PID_PATH.unlink(missing_ok=True)
        print(json.dumps({"status": "not_running"}))
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not _alive(pid):
            break
        time.sleep(0.25)
    forced = False
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
        forced = True
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped", "pid": pid, "forced_kill": forced}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "status", "restart", "once"))
    args = ap.parse_args()
    if args.action == "status":
        return cmd_status()
    if args.action == "start":
        return cmd_start()
    if args.action == "stop":
        return cmd_stop()
    if args.action == "restart":
        cmd_stop()
        time.sleep(0.5)
        return cmd_start()
    if args.action == "once":
        proc = subprocess.run(
            [_python(), str(SUPERVISOR), "--once"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            check=False,
        )
        return proc.returncode
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
