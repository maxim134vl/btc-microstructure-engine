#!/usr/bin/env python3
"""Start, stop, and inspect the TRD-OUTCOME2 dashboard refresh loop."""

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
RUNNER = REPO / "scripts" / "live" / "run_trd_outcome2_refresh.py"
PID_PATH = REPO / "run" / "trd_outcome2_refresh.pid"
LOG_PATH = REPO / "run" / "logs" / "trd_outcome2_refresh.log"
LATEST = REPO / "output" / "audits" / "trd_outcome2" / "latest.json"


def _python() -> str:
    for candidate in (REPO / "venv" / "bin" / "python", REPO / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _pid() -> int | None:
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    return True


def status() -> int:
    latest = None
    if LATEST.exists():
        try:
            latest = json.loads(LATEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            latest = {"error": "unreadable"}
    print(
        json.dumps(
            {
                "pid": _pid(),
                "alive": _alive(_pid()),
                "runner": str(RUNNER),
                "latest_path": str(LATEST),
                "latest_generated_at": None if not isinstance(latest, dict) else latest.get("generated_at"),
                "latest_status": None if not isinstance(latest, dict) else latest.get("status"),
            },
            indent=2,
            default=str,
        )
    )
    return 0


def stop() -> int:
    pid = _pid()
    if not _alive(pid):
        PID_PATH.unlink(missing_ok=True)
        print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_NOT_RUNNING"}))
        return 0
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    if _alive(pid):
        raise RuntimeError(f"TRD_OUTCOME2_REFRESH_STOP_TIMEOUT:{pid}")
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_STOPPED", "pid": pid}))
    return 0


def start() -> int:
    if _alive(_pid()):
        print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_ALREADY_RUNNING", "pid": _pid()}))
        return 0
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src") + os.pathsep + str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    with LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [_python(), str(RUNNER)],
            cwd=REPO,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    time.sleep(1.0)
    if not _alive(process.pid):
        print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_START_FAILED", "pid": process.pid, "log": str(LOG_PATH)}))
        return 1
    print(json.dumps({"status": "TRD_OUTCOME2_REFRESH_STARTED", "pid": process.pid, "log": str(LOG_PATH)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status", "restart"))
    action = parser.parse_args().action
    if action == "status":
        return status()
    if action == "stop":
        return stop()
    if action == "start":
        return start()
    stop()
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
