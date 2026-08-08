#!/usr/bin/env python3
"""Start, stop, and inspect only the independent STP_BE33 shadow runner."""

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
RUNNER = REPO / "scripts" / "live" / "run_shadow_stp_be33.py"
PID_PATH = REPO / "run" / "shadow_stp_be33.pid"
LOG_PATH = REPO / "run" / "logs" / "shadow_stp_be33.log"


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


def _active_epoch_id() -> str | None:
    try:
        payload = json.loads((REPO / "data/trading/paper_epochs/active.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return str(payload.get("paper_epoch_id") or "") or None


def status() -> int:
    epoch_id = _active_epoch_id()
    health_path = REPO / "data/trading/shadow_structural_protection/stp_be33/epochs" / str(epoch_id) / "health.json"
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        health = None
    print(json.dumps({
        "pid": _pid(),
        "alive": _alive(_pid()),
        "runner": str(RUNNER),
        "paper_epoch_id": epoch_id,
        "health_path": str(health_path),
        "health": health,
    }, indent=2, default=str))
    return 0


def stop() -> int:
    pid = _pid()
    if not _alive(pid):
        PID_PATH.unlink(missing_ok=True)
        print(json.dumps({"status": "STP_BE33_NOT_RUNNING"}))
        return 0
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    if _alive(pid):
        raise RuntimeError(f"STP_BE33_STOP_TIMEOUT:{pid}")
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "STP_BE33_STOPPED", "pid": pid}))
    return 0


def start() -> int:
    if _alive(_pid()):
        print(json.dumps({"status": "STP_BE33_ALREADY_RUNNING", "pid": _pid()}))
        return 0
    env = {**os.environ, "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    preflight = subprocess.run(
        [_python(), "-c", (
            "from pathlib import Path; "
            "from btc_ml.trading.shadow_structural_protection.be33 import StpBe33Engine; "
            f"e=StpBe33Engine(repo=Path({str(REPO)!r})); "
            "import json; print(json.dumps(e.write_health()))"
        )],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    if preflight.returncode != 0:
        print(json.dumps({"status": "STP_BE33_PREFLIGHT_FAILED", "stderr": preflight.stderr[-2000:]}))
        return 1
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        print(json.dumps({"status": "STP_BE33_START_FAILED", "pid": process.pid, "log": str(LOG_PATH)}))
        return 1
    print(json.dumps({"status": "STP_BE33_STARTED", "pid": process.pid, "log": str(LOG_PATH)}))
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
