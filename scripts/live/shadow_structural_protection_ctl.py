#!/usr/bin/env python3
"""Control SHADOW-STP1 observe-only service (start/stop/status)."""

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
PID_PATH = REPO / "run" / "shadow_structural_protection.pid"
LOG_PATH = REPO / "run" / "logs" / "shadow_structural_protection.log"
HEALTH_PATH = REPO / "data" / "trading" / "shadow_structural_protection" / "health.json"
RUNNER = REPO / "scripts" / "live" / "run_shadow_structural_protection.py"


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
                "health": health,
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_stop() -> int:
    pid = _read_pid()
    orphans: list[int] = []
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
        for line in out.splitlines():
            if "run_shadow_structural_protection.py" in line:
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


def cmd_start() -> int:
    cmd_stop()
    time.sleep(0.3)
    # Preflight: refuse start if exact data missing / blocking health
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    pre = subprocess.run(
        [
            _python(),
            "-c",
            "from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine;"
            "e=StructuralProtectionEngine(strict_epoch=True); h=e.write_health();"
            "import json; print(json.dumps({'exact': e.exact_ok, 'status': h.get('status'), "
            "'baseline_div': h.get('baseline_divergence_count'), 'lookahead': h.get('lookahead_violation_count'), "
            "'evidence_fail': h.get('evidence_gate_failure_count'), "
            "'isolated': h.get('canonical_economics_isolated')}))",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    if pre.returncode != 0:
        print(json.dumps({"status": "preflight_failed", "stderr": pre.stderr[-2000:]}))
        return 1
    try:
        info = json.loads(pre.stdout.strip().splitlines()[-1])
    except Exception:
        print(json.dumps({"status": "preflight_parse_failed", "stdout": pre.stdout[-1000:]}))
        return 1
    if not info.get("exact"):
        print(json.dumps({"status": "SHADOW_STP1_BLOCKED_NO_EXACT_INTRABAR_VOLUME", "preflight": info}))
        return 2
    if info.get("baseline_div"):
        print(json.dumps({"status": "SHADOW_STP1_1_BASELINE_DIVERGENCE", "preflight": info}))
        return 3
    if info.get("lookahead"):
        print(json.dumps({"status": "SHADOW_STP1_1_LOOKAHEAD_VIOLATION", "preflight": info}))
        return 4
    if info.get("evidence_fail"):
        print(json.dumps({"status": "SHADOW_STP1_1_POLICY_EVIDENCE_GATE_FAILURE", "preflight": info}))
        return 5
    if info.get("isolated") is False:
        print(json.dumps({"status": "SHADOW_STP1_1_CANONICAL_ISOLATION_FAILURE", "preflight": info}))
        return 6

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fh = LOG_PATH.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [_python(), str(RUNNER)],
        cwd=str(REPO),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    PID_PATH.write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(1.5)
    if not _alive(proc.pid):
        print(json.dumps({"status": "start_failed", "pid": proc.pid, "log": str(LOG_PATH)}))
        return 1
    print(json.dumps({"status": "started", "pid": proc.pid, "log": str(LOG_PATH), "preflight": info}))
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
