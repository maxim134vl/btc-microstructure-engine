#!/usr/bin/env python3
"""Control MODEL-6 drift monitoring service."""

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
PID_PATH = REPO / "run" / "drift_monitoring.pid"
LOG_PATH = REPO / "run" / "logs" / "drift_monitoring.log"
HEALTH_PATH = REPO / "data" / "model_assurance" / "drift" / "runtime" / "health.json"
SUMMARY_PATH = REPO / "data" / "model_assurance" / "drift" / "snapshots" / "latest_summary.json"
RUNNER = REPO / "scripts" / "model_assurance" / "run_drift_monitoring.py"


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
            "summary_status": (summary or {}).get("status"),
            "input_drift_status": (summary or {}).get("input_drift_status"),
            "feature_drift_status": (summary or {}).get("feature_drift_status"),
            "context_drift_status": (summary or {}).get("context_drift_status"),
            "performance_drift_status": (summary or {}).get("performance_drift_status"),
            "observations_by_branch": (summary or {}).get("observations_by_branch"),
            "frozen_baselines": (summary or {}).get("frozen_baselines"),
            "watch_metrics": (summary or {}).get("watch_metrics"),
            "warning_metrics": (summary or {}).get("warning_metrics"),
            "critical_metrics": (summary or {}).get("critical_metrics"),
            "not_evaluable_metrics": (summary or {}).get("not_evaluable_metrics"),
            "suppressed_metrics": (summary or {}).get("suppressed_metrics"),
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
    time.sleep(1.5)
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
    from btc_ml.model_assurance.drift.monitor import run_once

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
