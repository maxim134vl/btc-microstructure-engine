#!/usr/bin/env python3
"""PID-1 multiplex for the model assurance suite.

Starts all host MODEL_CTLS assurance runners as children, forwards SIGTERM,
exits non-zero if any critical child dies.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")).resolve()
RUN = REPO / "run"
STATUS = RUN / "assurance_runtime_status.json"
PID_FILE = RUN / "assurance_runtime.pid"

# (name, argv relative to REPO, critical)
CHILDREN_SPEC: list[tuple[str, list[str], bool]] = [
    ("shadow_model", ["scripts/model_assurance/run_shadow_model.py"], True),
    (
        "behavioral_validation",
        ["scripts/model_assurance/run_behavioral_validation.py", "--interval-seconds", "15"],
        True,
    ),
    ("economic_validation", ["scripts/model_assurance/run_economic_validation.py"], True),
    ("external_data_toxicity", ["scripts/model_assurance/run_external_data_toxicity.py"], True),
    ("current_toxicity", ["scripts/model_assurance/run_current_toxicity.py"], True),
    ("incident_correlation", ["scripts/model_assurance/run_incident_correlation.py"], True),
    ("promotion_gate", ["scripts/model_assurance/run_promotion_gate.py"], True),
    ("model_assurance_summary", ["scripts/model_assurance/run_model_assurance_summary.py"], True),
]

CHILDREN: dict[str, subprocess.Popen[str]] = {}
STOP = False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_status(state: str, **fields: object) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    payload = {
        "component": "assurance-runtime",
        "state": state,
        "pid": os.getpid(),
        "updated_at": _utc(),
        "children": {
            name: {
                "pid": proc.pid,
                "returncode": proc.poll(),
                "alive": proc.poll() is None,
            }
            for name, proc in CHILDREN.items()
        },
        **fields,
    }
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(STATUS)


def _stop(*_a: object) -> None:
    global STOP
    STOP = True


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{REPO}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["BTC_ML_REPO_ROOT"] = str(REPO)
    return env


def _spawn(name: str, rel_argv: list[str]) -> subprocess.Popen[str]:
    log_dir = RUN / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"assurance_{name}.log"
    log_fh = log_path.open("a", encoding="utf-8")
    argv = [sys.executable, "-u", str(REPO / rel_argv[0]), *rel_argv[1:]]
    proc = subprocess.Popen(
        argv,
        cwd=str(REPO),
        env=_env(),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    # Child ctl-style runners often write their own pid files; also record ours.
    (RUN / f"{name}.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    print(json.dumps({"event": "child_started", "name": name, "pid": proc.pid, "argv": argv}), flush=True)
    return proc


def main() -> int:
    global STOP
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    for rel in (
        "data/model_assurance",
        "data/model_assurance/shadow",
        "data/model_assurance/behavioral_validation",
        "data/model_assurance/economic_validation",
        "data/model_assurance/toxic_box",
        "data/model_assurance/governance",
        "data/model_assurance/summary",
        "run/logs",
    ):
        (REPO / rel).mkdir(parents=True, exist_ok=True)

    RUN.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")

    for name, argv, _crit in CHILDREN_SPEC:
        CHILDREN[name] = _spawn(name, argv)

    _write_status("RUNNING")
    print(
        json.dumps(
            {
                "status": "ASSURANCE_RUNTIME_STARTED",
                "pid": os.getpid(),
                "children": list(CHILDREN.keys()),
                "mode": "VPS_DEPLOY",
            }
        ),
        flush=True,
    )

    exit_code = 0
    try:
        while not STOP:
            for name, _argv, critical in CHILDREN_SPEC:
                proc = CHILDREN[name]
                rc = proc.poll()
                if rc is None:
                    continue
                print(
                    json.dumps(
                        {
                            "event": "child_exited",
                            "name": name,
                            "returncode": rc,
                            "critical": critical,
                        }
                    ),
                    flush=True,
                )
                if critical:
                    exit_code = 1
                    STOP = True
                    break
            _write_status("RUNNING" if not STOP else "STOPPING")
            time.sleep(1.0)
    finally:
        for name, proc in CHILDREN.items():
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.time() + 20.0
        for name, proc in CHILDREN.items():
            remaining = max(0.1, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        _write_status("STOPPED", exit_code=exit_code)
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
