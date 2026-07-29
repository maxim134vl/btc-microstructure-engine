#!/usr/bin/env python3
"""Control SHADOW-EQCORR1 observe-only service (start/stop/status)."""

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
PID_PATH = REPO / "run" / "shadow_economic_correlation.pid"
LOG_PATH = REPO / "run" / "logs" / "shadow_economic_correlation.log"
HEALTH_PATH = REPO / "data" / "trading" / "shadow_economic_correlation" / "health.json"
RUNNER = REPO / "scripts" / "live" / "run_shadow_economic_correlation.py"


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


def cmd_status() -> int:
    health = None
    if HEALTH_PATH.exists():
        try:
            health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            health = {"error": str(exc)}
    print(
        json.dumps(
            {
                "pid": _read_pid(),
                "alive": _alive(_read_pid()),
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
    # Always stop orphans first to guarantee single writer.
    cmd_stop()
    time.sleep(0.3)
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
    if not _alive(proc.pid):
        print(json.dumps({"status": "start_failed", "pid": proc.pid, "log": str(LOG_PATH)}))
        return 1
    print(json.dumps({"status": "started", "pid": proc.pid, "log": str(LOG_PATH)}))
    return 0


def cmd_stop() -> int:
    pid = _read_pid()
    orphans: list[int] = []
    try:
        out = subprocess.check_output(["pgrep", "-f", str(RUNNER)], text=True)
        orphans = [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        orphans = []
    # Fallback scan via ps when pgrep is restricted.
    if not orphans:
        try:
            out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
            for line in out.splitlines():
                if "run_shadow_economic_correlation.py" in line:
                    parts = line.strip().split(None, 1)
                    if parts and parts[0].isdigit():
                        orphans.append(int(parts[0]))
        except Exception:
            pass
    targets: list[int] = []
    if pid:
        targets.append(pid)
    for o in orphans:
        if o not in targets:
            targets.append(o)
    if not targets:
        PID_PATH.unlink(missing_ok=True)
        print(json.dumps({"status": "not_running"}))
        return 0
    forced = False
    for target in targets:
        if not _alive(target):
            continue
        try:
            os.kill(target, signal.SIGTERM)
        except OSError:
            continue
        for _ in range(30):
            if not _alive(target):
                break
            time.sleep(0.2)
        if _alive(target):
            try:
                os.kill(target, signal.SIGKILL)
                forced = True
            except OSError:
                pass
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped", "pids": targets, "forced_kill": forced}))
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
    cmd_stop()
    time.sleep(0.5)
    return cmd_start()


if __name__ == "__main__":
    raise SystemExit(main())
