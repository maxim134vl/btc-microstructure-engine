#!/usr/bin/env python3
"""Control wrapper for LIVE1A intrabar cognition service."""

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
PYTHON = ROOT / "venv" / "bin" / "python"
SERVICE = ROOT / "scripts" / "live" / "run_intrabar_cognition_service.py"
DEFAULT_PID = ROOT / "run" / "intrabar_cognition.pid"
DEFAULT_HEALTH = ROOT / "data" / "runtime" / "intrabar_cognition_health.json"
DEFAULT_STOP_INTENT = ROOT / "run" / "intrabar_cognition.stop_intent.json"
DEFAULT_CONTROLLED_RESTART = ROOT / "run" / "intrabar_cognition.controlled_restart.json"
DEFAULT_JOURNAL = ROOT / "data" / "raw_market_events_v2"
DEFAULT_CONTEXT = ROOT / "data" / "cognition" / "intrabar_context_events"
DEFAULT_LOG = ROOT / "logs" / "intrabar_cognition.log"

sys.path.insert(0, str(ROOT / "src"))
from btc_ml.runtime.intrabar_supervision import (  # noqa: E402
    RestartPolicy,
    clear_stop_intent,
    load_config,
    mark_controlled_restart,
    write_stop_intent,
)


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_status(args: argparse.Namespace) -> int:
    pid = _read_pid(args.pid_file)
    health = {}
    if args.health_path.exists():
        try:
            health = json.loads(args.health_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            health = {"error": "invalid_health_json"}
    print(
        json.dumps(
            {
                "pid": pid,
                "alive": _alive(pid),
                "pid_file": str(args.pid_file),
                "health_path": str(args.health_path),
                "journal_root": str(args.journal_root),
                "context_root": str(args.context_root),
                "health": health,
            },
            indent=2,
        )
    )
    return 0 if _alive(pid) else 1


def _kill_process(args: argparse.Namespace) -> tuple[int | None, bool]:
    pid = _read_pid(args.pid_file)
    if not _alive(pid):
        if args.pid_file.exists():
            args.pid_file.unlink(missing_ok=True)
        return pid, False
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        if not _alive(pid):
            break
        time.sleep(0.5)
    still = _alive(pid)
    if still:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    if args.pid_file.exists() and not _alive(pid):
        args.pid_file.unlink(missing_ok=True)
    return pid, still


def cmd_stop(args: argparse.Namespace) -> int:
    pid = _read_pid(args.pid_file)
    if not _alive(pid):
        print(json.dumps({"stopped": True, "pid": pid, "note": "not_running"}))
        if args.pid_file.exists():
            args.pid_file.unlink(missing_ok=True)
        write_stop_intent(args.stop_intent_file, reason="manual", stopped_by="intrabar_cognition_ctl stop")
        return 0
    pid, still = _kill_process(args)
    write_stop_intent(args.stop_intent_file, reason="manual", stopped_by="intrabar_cognition_ctl stop")
    print(json.dumps({"stopped": not _alive(pid), "pid": pid, "forced_kill": still, "stop_intent": True}))
    return 0 if not _alive(pid) else 1


def cmd_start(args: argparse.Namespace) -> int:
    clear_stop_intent(args.stop_intent_file)
    if _alive(_read_pid(args.pid_file)):
        print(json.dumps({"started": False, "error": "already_running", "pid": _read_pid(args.pid_file)}))
        return 1
    args.journal_root.mkdir(parents=True, exist_ok=True)
    args.context_root.mkdir(parents=True, exist_ok=True)
    args.health_path.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PYTHON),
        str(SERVICE),
        "--journal-root",
        str(args.journal_root),
        "--context-root",
        str(args.context_root),
        "--health-path",
        str(args.health_path),
        "--pid-file",
        str(args.pid_file),
        "--symbol",
        args.symbol,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    log_fh = args.log_file.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    child = None
    for _ in range(50):
        child = _read_pid(args.pid_file)
        if _alive(child):
            break
        time.sleep(0.2)
    print(
        json.dumps(
            {
                "started": _alive(child),
                "launcher_pid": proc.pid,
                "collector_pid": child,
                "journal_root": str(args.journal_root),
                "context_root": str(args.context_root),
                "health_path": str(args.health_path),
                "log_file": str(args.log_file),
            },
            indent=2,
        )
    )
    return 0 if _alive(child) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Intrabar cognition control")
    parser.add_argument("command", choices=["start", "stop", "status", "restart"])
    parser.add_argument("--journal-root", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--context-root", type=Path, default=DEFAULT_CONTEXT)
    parser.add_argument("--health-path", type=Path, default=DEFAULT_HEALTH)
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID)
    parser.add_argument("--stop-intent-file", type=Path, default=DEFAULT_STOP_INTENT)
    parser.add_argument("--controlled-restart-file", type=Path, default=DEFAULT_CONTROLLED_RESTART)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()
    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "restart":
        policy = RestartPolicy.from_config(load_config(ROOT))
        mark_controlled_restart(
            args.controlled_restart_file,
            grace_seconds=policy.controlled_restart_grace_seconds,
        )
        _kill_process(args)
        clear_stop_intent(args.stop_intent_file)
        time.sleep(0.5)
        return cmd_start(args)
    return cmd_status(args)


if __name__ == "__main__":
    raise SystemExit(main())
