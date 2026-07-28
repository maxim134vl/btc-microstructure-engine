#!/usr/bin/env python3
"""Control MODEL-9 unified Model Assurance summary service."""

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
PID_PATH = REPO / "run" / "model_assurance_summary.pid"
LOG_PATH = REPO / "run" / "logs" / "model_assurance_summary.log"
HEALTH_PATH = REPO / "data" / "model_assurance" / "summary" / "runtime" / "health.json"
SUMMARY_PATH = REPO / "data" / "model_assurance" / "summary" / "latest_summary.json"
RUNNER = REPO / "scripts" / "model_assurance" / "run_model_assurance_summary.py"


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


def _print(payload: dict) -> int:
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str))
    return 0


def cmd_status() -> int:
    summary = None
    if SUMMARY_PATH.exists():
        try:
            summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            summary = {"error": str(exc)}
    return _print(
        {
            "pid": _read_pid(),
            "alive": _alive(_read_pid()),
            "overall_assurance_status": (summary or {}).get("overall_assurance_status"),
            "overall_cause": (summary or {}).get("overall_cause"),
            "runtime_safety_status": (summary or {}).get("runtime_safety_status"),
            "runtime_impact": (summary or {}).get("runtime_impact"),
            "promotion_control": (summary or {}).get("promotion_control"),
            "environment_blockers": (summary or {}).get("environment_blockers"),
            "missing_sources": (summary or {}).get("missing_sources"),
            "stale_sources": (summary or {}).get("stale_sources"),
            "log_path": str(LOG_PATH),
        }
    )


def cmd_health() -> int:
    health = None
    if HEALTH_PATH.exists():
        try:
            health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            health = {"error": str(exc)}
    return _print({"pid": _read_pid(), "alive": _alive(_read_pid()), "health": health})


def cmd_start() -> int:
    pid = _read_pid()
    if _alive(pid):
        return _print({"status": "already_running", "pid": pid})
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
    time.sleep(1.2)
    return _print({"status": "started", "pid": proc.pid, "alive": _alive(proc.pid), "log": str(LOG_PATH)})


def cmd_stop() -> int:
    pid = _read_pid()
    if not _alive(pid):
        PID_PATH.unlink(missing_ok=True)
        return _print({"status": "not_running"})
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pid):
            break
        time.sleep(0.2)
    forced = False
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
        forced = True
    PID_PATH.unlink(missing_ok=True)
    return _print({"status": "stopped", "pid": pid, "forced_kill": forced})


def cmd_run_once() -> int:
    sys.path.insert(0, str(REPO / "src"))
    from btc_ml.model_assurance.summary import run_once

    return _print({"status": "ok", "summary": run_once(repo_root=REPO)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "status", "health", "run-once"))
    args = ap.parse_args()
    return {
        "status": cmd_status,
        "health": cmd_health,
        "start": cmd_start,
        "stop": cmd_stop,
        "run-once": cmd_run_once,
    }[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
