#!/usr/bin/env python3
"""Container PID-1 orchestrator for the existing BTC-ML runtime processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "run"
BOOT = RUN / "docker_boot.json"
STATUS = RUN / "docker_model_runtime_status.json"
CHILDREN: list[subprocess.Popen[str]] = []
STOP = False

LIVE1B_INITIAL_GRACE_S = float(os.environ.get("LIVE1B_INITIAL_GRACE_S", "180"))
LIVE1B_STALL_TIMEOUT_S = float(os.environ.get("LIVE1B_STALL_TIMEOUT_S", "180"))
LIVE1B_HARD_TIMEOUT_S = float(os.environ.get("LIVE1B_HARD_TIMEOUT_S", "3600"))
LIVE1B_HEALTH_MAX_AGE_S = float(os.environ.get("LIVE1B_HEALTH_MAX_AGE_S", "30"))
STP_INITIAL_GRACE_S = float(os.environ.get("STP_INITIAL_GRACE_S", "30"))
STP_STALL_TIMEOUT_S = float(os.environ.get("STP_STALL_TIMEOUT_S", "30"))
STP_HARD_TIMEOUT_S = float(os.environ.get("STP_HARD_TIMEOUT_S", "120"))
STP_HEALTH_MAX_AGE_S = float(os.environ.get("STP_HEALTH_MAX_AGE_S", "30"))


def log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def write_status(state: str, **fields: object) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    payload = {
        "component": "model-runtime",
        "state": state,
        "pid": os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **fields,
    }
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=str) + "\n")
    tmp.replace(STATUS)


def read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def timestamp_age(payload: dict[str, object]) -> float | None:
    stamp = payload.get("updated_at") or payload.get("last_heartbeat_at") or payload.get("heartbeat_at_utc")
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (TypeError, ValueError):
        return None


def live1b_safety_error(payload: dict[str, object]) -> str | None:
    if payload.get("paper_only") is not True:
        return "paper_only_not_true"
    if payload.get("real_execution_enabled") is not False:
        return "real_execution_enabled_not_false"
    state = ((payload.get("execution_market") or {}).get("state") or {}) if isinstance(payload.get("execution_market"), dict) else {}
    if state.get("wal_write_failures", 0) != 0:
        return "wal_write_failure"
    return None


def live1b_ready(payload: dict[str, object], *, pid: int) -> bool:
    if payload.get("pid") != pid or timestamp_age(payload) is None or timestamp_age(payload) > LIVE1B_HEALTH_MAX_AGE_S:
        return False
    state = ((payload.get("execution_market") or {}).get("state") or {}) if isinstance(payload.get("execution_market"), dict) else {}
    return (
        live1b_safety_error(payload) is None
        and payload.get("manager_status") == "CONNECTED"
        and state.get("state") == "HEALTHY"
        and state.get("unresolved_gap") is False
        and state.get("book_ticker_stream_fresh") is True
        and state.get("agg_trade_stream_fresh") is True
        and state.get("entry_allowed") is True
    )


def live1b_checkpoint_path() -> Path:
    cfg = read_json(ROOT / "config/intrabar_paper_execution.json")
    active = read_json(ROOT / str(cfg["epochs_root"]) / "active.json")
    epoch_id = active.get("paper_epoch_id")
    if not epoch_id:
        raise ValueError("active paper epoch is missing or corrupt")
    return ROOT / str(cfg["books_root"]) / str(epoch_id) / "execution_market_checkpoint.json"


def recovery_signal(health_path: Path, checkpoint_path: Path, *, pid: int) -> tuple[object, ...]:
    health = read_json(health_path)
    health_stamp = health.get("updated_at") if health.get("pid") == pid else None
    checkpoint = read_json(checkpoint_path)
    return (
        health_stamp,
        checkpoint.get("last_processed_wal_offset"),
        checkpoint.get("last_processed_agg_trade_id"),
        checkpoint_path.stat().st_mtime_ns if checkpoint_path.exists() else None,
    )


def wait_live1b_recovery(process: subprocess.Popen[str]) -> tuple[bool, str]:
    health_path = ROOT / "data/runtime/intrabar_paper_health.json"
    try:
        checkpoint_path = live1b_checkpoint_path()
    except (KeyError, OSError, ValueError):
        return False, "corrupted_recovery_state"
    started = time.monotonic()
    last_progress = started
    previous_signal = recovery_signal(health_path, checkpoint_path, pid=process.pid)
    while not STOP:
        now = time.monotonic()
        elapsed = now - started
        if process.poll() is not None:
            return False, "process_exited"
        health = read_json(health_path)
        if health.get("pid") == process.pid:
            safety_error = live1b_safety_error(health)
            if safety_error:
                return False, safety_error
            if live1b_ready(health, pid=process.pid):
                write_status("STARTING", component_state={"live1b": "HEALTHY"}, elapsed_s=round(elapsed, 1))
                return True, "healthy"
        signal_value = recovery_signal(health_path, checkpoint_path, pid=process.pid)
        progressed = signal_value != previous_signal
        if progressed:
            previous_signal = signal_value
            last_progress = now
        progress_signal = {
            "health_updated_at": signal_value[0],
            "checkpoint_wal_offset": signal_value[1],
            "checkpoint_agg_trade_id": signal_value[2],
        }
        log(
            "component_progress", component="live1b", state="RECOVERING",
            elapsed_s=round(elapsed, 1), progress_signal=progress_signal,
        )
        write_status(
            "STARTING", component_state={"live1b": "RECOVERING"},
            elapsed_s=round(elapsed, 1), progress_signal=progress_signal,
        )
        if elapsed >= LIVE1B_HARD_TIMEOUT_S:
            return False, "hard_recovery_timeout"
        if elapsed >= LIVE1B_INITIAL_GRACE_S and now - last_progress >= LIVE1B_STALL_TIMEOUT_S:
            return False, "recovery_stalled"
        time.sleep(2)
    return False, "stopped"


def stp_health_path() -> Path:
    cfg = read_json(ROOT / "config/intrabar_paper_execution.json")
    active = read_json(ROOT / str(cfg["epochs_root"]) / "active.json")
    epoch_id = active.get("paper_epoch_id")
    if not epoch_id:
        raise ValueError("active paper epoch is missing or corrupt")
    return ROOT / "data/trading/shadow_structural_protection/stp_be33/epochs" / str(epoch_id) / "health.json"


def stp_ready(payload: dict[str, object], *, pid: int, epoch_id: str, policy_fingerprint: str) -> bool:
    age = timestamp_age(payload)
    return (
        payload.get("pid") == pid and age is not None and 0 <= age <= STP_HEALTH_MAX_AGE_S
        and payload.get("status") == "STP_BE33_RUNNING_SHADOW_ONLY"
        and payload.get("paper_epoch_id") == epoch_id
        and payload.get("policy_fingerprint") == policy_fingerprint
        and payload.get("canonical_write_capability") is False
        and payload.get("live1b_command_capability") is False
        and payload.get("real_execution_capability") is False
    )


def wait_stp_recovery(process: subprocess.Popen[str]) -> tuple[bool, str]:
    try:
        health_path = stp_health_path()
        cfg = read_json(ROOT / "config/intrabar_paper_execution.json")
        active = read_json(ROOT / str(cfg["epochs_root"]) / "active.json")
        manifest = read_json(ROOT / "data/trading/shadow_structural_protection/stp_be33/policy_manifest.json")
        epoch_id = str(active["paper_epoch_id"])
        policy_fingerprint = str(manifest["policy_fingerprint"])
    except (KeyError, OSError, ValueError):
        return False, "stp_binding_state_corrupt"
    started = time.monotonic()
    last_progress = started
    previous_signal: tuple[object, ...] | None = None
    while not STOP:
        now = time.monotonic()
        elapsed = now - started
        if process.poll() is not None:
            return False, "process_exited"
        health = read_json(health_path)
        if stp_ready(health, pid=process.pid, epoch_id=epoch_id, policy_fingerprint=policy_fingerprint):
            write_status("STARTING", component_state={"stp_be33": "HEALTHY"}, elapsed_s=round(elapsed, 1))
            return True, "healthy"
        signal_value = (
            health.get("updated_at") if health.get("pid") == process.pid else None,
            health.get("last_processed_wal_offset") if health.get("pid") == process.pid else None,
            health.get("startup_wal_bytes_scanned") if health.get("pid") == process.pid else None,
        )
        if previous_signal is None or signal_value != previous_signal:
            previous_signal = signal_value
            last_progress = now
        write_status("STARTING", component_state={"stp_be33": "RECOVERING"}, elapsed_s=round(elapsed, 1), progress_signal={"health": signal_value})
        if elapsed >= STP_HARD_TIMEOUT_S:
            return False, "stp_hard_recovery_timeout"
        if elapsed >= STP_INITIAL_GRACE_S and now - last_progress >= STP_STALL_TIMEOUT_S:
            return False, "stp_recovery_stalled"
        time.sleep(1)
    return False, "stopped"


def spawn(name: str, *args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}"}
    process = subprocess.Popen(
        [sys.executable, *args], cwd=ROOT, env=env, text=True,
        stdout=sys.stdout, stderr=sys.stderr,
    )
    CHILDREN.append(process)
    log("component_started", component=name, pid=process.pid, command=list(args))
    return process


def terminate_children() -> None:
    for process in reversed(CHILDREN):
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 25
    for process in reversed(CHILDREN):
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                process.kill()


def handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def fresh_boot_state() -> None:
    """Clear process residue only; never touch authoritative or paper data."""
    RUN.mkdir(parents=True, exist_ok=True)
    for name in (
        "intrabar_cognition.pid", "intrabar_paper_manager.pid",
        "intrabar_process_supervisor.pid", "live_binance_intrabar_feed.pid",
        "live_binance_intrabar_feed.lock", "live_binance_intrabar_feed_supervisor.pid",
        "shadow_stp_be33.pid",
    ):
        (RUN / name).unlink(missing_ok=True)
    state = ROOT / "data/runtime/intrabar_supervision_state.json"
    if state.exists():
        archived = state.with_name(f"{state.stem}.pre_docker_boot.{int(time.time())}.json")
        state.replace(archived)
    BOOT.write_text(json.dumps({"pid": os.getpid(), "started_at": time.time()}) + "\n")
    write_status("STARTING", component_state={})


def wait_file_fresh(path: Path, timeout: float, max_age: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline and not STOP:
        try:
            payload = json.loads(path.read_text())
            stamp = (
                payload.get("updated_at")
                or payload.get("last_heartbeat_at")
                or payload.get("heartbeat_at_utc")
            )
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - dt).total_seconds() <= max_age:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> int:
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    fresh_boot_state()

    execution_cfg = read_json(ROOT / "config/intrabar_paper_execution.json")
    if execution_cfg.get("paper_only") is not True or execution_cfg.get("real_execution_enabled") is not False:
        log("startup_failed", component="safety", reason="paper_execution_safety_flags")
        write_status("FAILED", reason="paper_execution_safety_flags")
        return 19

    feed_supervisor = spawn("binance-feed-supervisor", "scripts/live/intrabar_feed_supervisor.py", "--foreground")
    if not wait_file_fresh(ROOT / "run/live_binance_intrabar_feed_heartbeat.json", 120, 90):
        log("startup_failed", component="binance-feed", reason="heartbeat_not_ready")
        terminate_children()
        return 20

    canonical = spawn("canonical-runtime", "run.py", "--skip-hardening")
    live1a = spawn("live1a", "scripts/live/run_intrabar_cognition_service.py")
    if not wait_file_fresh(ROOT / "data/runtime/intrabar_cognition_health.json", 120):
        log("startup_failed", component="live1a", reason="health_not_ready")
        terminate_children()
        return 21

    live1b = spawn("live1b", "scripts/live/run_intrabar_paper_manager.py")
    live1b_ok, live1b_reason = wait_live1b_recovery(live1b)
    if not live1b_ok:
        log("startup_failed", component="live1b", reason=live1b_reason)
        write_status("FAILED", component_state={"live1b": "FAILED"}, reason=live1b_reason)
        terminate_children()
        return 22

    supervisor = spawn("intrabar-supervisor", "scripts/live/intrabar_process_supervisor.py")
    stp = spawn("stp-be33", "scripts/live/run_shadow_stp_be33.py")
    stp_ok, stp_reason = wait_stp_recovery(stp)
    if not stp_ok:
        log("startup_failed", component="stp-be33", reason=stp_reason)
        write_status("FAILED", component_state={"stp_be33": "FAILED"}, reason=stp_reason)
        terminate_children()
        return 23
    log("model_runtime_ready", paper_only=True, real_execution=False)
    write_status("READY", paper_only=True, real_execution_enabled=False)

    critical = (feed_supervisor, canonical, live1a, live1b, supervisor, stp)
    try:
        while not STOP:
            for process in critical:
                rc = process.poll()
                if rc is not None:
                    log("critical_component_exited", pid=process.pid, returncode=rc)
                    write_status("FAILED", reason="critical_component_exited", child_pid=process.pid, returncode=rc)
                    return 30
            time.sleep(2)
        return 0
    finally:
        terminate_children()
        BOOT.unlink(missing_ok=True)
        if STOP:
            write_status("STOPPED")


if __name__ == "__main__":
    raise SystemExit(main())
