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
LEGACY_HEALTH_PATH = REPO / "data" / "trading" / "shadow_structural_protection" / "health.json"
RUNNER = REPO / "scripts" / "live" / "run_shadow_structural_protection.py"
RUNNER_MARK = "run_shadow_structural_protection.py"
CTL_MARK = "shadow_structural_protection_ctl.py"


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


def _command(pid: int) -> str:
    try:
        return subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _is_runner(pid: int | None) -> bool:
    if not pid:
        return False
    cmd = _command(pid)
    return RUNNER_MARK in cmd and CTL_MARK not in cmd


def _runner_pids() -> list[int]:
    found: list[int] = []
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return found
    for line in out.splitlines():
        if RUNNER_MARK not in line or CTL_MARK in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if pid != os.getpid() and _alive(pid):
            found.append(pid)
    return found


def _active_epoch_id() -> str | None:
    path = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    epoch = str(payload.get("paper_epoch_id") or "").strip()
    return epoch or None


def _health_path() -> Path:
    epoch = _active_epoch_id()
    if epoch:
        return (
            REPO
            / "data"
            / "trading"
            / "shadow_structural_protection"
            / "epochs"
            / epoch
            / "health.json"
        )
    return LEGACY_HEALTH_PATH


def _write_pid(pid: int) -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{pid}\n", encoding="utf-8")


def cmd_status() -> int:
    health_path = _health_path()
    health = None
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text(encoding="utf-8"))
        except Exception as exc:
            health = {"error": str(exc)}
    print(
        json.dumps(
            {
                "pid": _read_pid(),
                "alive": _alive(_read_pid()) and _is_runner(_read_pid()),
                "pid_path": str(PID_PATH),
                "log_path": str(LOG_PATH),
                "health_path": str(health_path),
                "health": health,
            },
            indent=2,
            default=str,
        )
    )
    return 0


def _kill_pid(target: int) -> bool:
    if not _alive(target):
        return False
    try:
        os.kill(target, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(30):
        if not _alive(target):
            return False
        time.sleep(0.2)
    if not _alive(target):
        return False
    try:
        os.kill(target, signal.SIGKILL)
        return True
    except OSError:
        return False


def cmd_stop() -> int:
    pid = _read_pid()
    targets: list[int] = []
    if pid:
        targets.append(pid)
    for orphan in _runner_pids():
        if orphan not in targets:
            targets.append(orphan)
    if not targets:
        PID_PATH.unlink(missing_ok=True)
        print(json.dumps({"status": "not_running"}))
        return 0
    forced = False
    for target in targets:
        if _kill_pid(target):
            forced = True
    PID_PATH.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped", "pids": targets, "forced_kill": forced}))
    return 0


def _keep_live_runner() -> int | None:
    """Return the live runner PID to keep, or None if the service is down."""
    pid = _read_pid()
    if _alive(pid) and _is_runner(pid):
        return pid
    live = _runner_pids()
    if not live:
        return None
    if pid in live:
        return pid
    return live[0]


def cmd_start() -> int:
    keep = _keep_live_runner()
    if keep is not None:
        stale = _read_pid()
        extras = [pid for pid in _runner_pids() if pid != keep]
        for extra in extras:
            _kill_pid(extra)
        _write_pid(keep)
        payload: dict[str, object] = {"status": "already_running", "pid": keep}
        if stale != keep:
            payload["note"] = "adopted"
            payload["replaced_stale_pid"] = stale
        print(json.dumps(payload))
        return 0

    stale = _read_pid()
    if stale is not None:
        PID_PATH.unlink(missing_ok=True)

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
    _write_pid(proc.pid)
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
