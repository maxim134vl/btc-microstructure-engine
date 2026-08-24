"""Canonical supervision lifecycle for LIVE1A, LIVE1B, and S4.1 timeframe manager."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

ALERT_COGNITION_PROCESS_DOWN = "INTRABAR_COGNITION_PROCESS_DOWN"
ALERT_PAPER_PROCESS_DOWN = "INTRABAR_PAPER_MANAGER_PROCESS_DOWN"
ALERT_MANAGER_PROCESS_DOWN = "TIMEFRAME_MANAGER_PROCESS_DOWN"
ALERT_COGNITION_HEARTBEAT_STALE = "INTRABAR_COGNITION_HEARTBEAT_STALE"
ALERT_PAPER_HEARTBEAT_STALE = "INTRABAR_PAPER_HEARTBEAT_STALE"
ALERT_MANAGER_HEARTBEAT_STALE = "TIMEFRAME_MANAGER_HEARTBEAT_STALE"
ALERT_COGNITION_RESTART_STORM = "INTRABAR_COGNITION_RESTART_STORM"
ALERT_PAPER_RESTART_STORM = "INTRABAR_PAPER_RESTART_STORM"
ALERT_MANAGER_RESTART_STORM = "TIMEFRAME_MANAGER_RESTART_STORM"
ALERT_PAPER_EXECUTION_UNSAFE = "INTRABAR_PAPER_EXECUTION_UNSAFE"

LIVE1B_PROCESS_ALIVE_EXECUTION_STATES = {"HEALTHY", "DEGRADED", "RECOVERING", "UNSAFE"}


class ProcessLifecycleState(str, Enum):
    RUNNING_HEALTHY = "RUNNING_HEALTHY"
    RUNNING_DEGRADED = "RUNNING_DEGRADED"
    STOPPED_EXPECTED = "STOPPED_EXPECTED"
    FAILED = "FAILED"
    RESTARTING = "RESTARTING"
    FAILED_PERMANENT = "FAILED_PERMANENT"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_age_seconds(ts: str | None, *, now: float | None = None) -> float | None:
    if not ts:
        return None
    now = time.time() if now is None else now
    try:
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, now - dt.timestamp())
    except Exception:
        return None


def load_config(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root)
    path = root / "config" / "intrabar_supervision.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass
class ServiceSpec:
    name: str
    display_name: str
    ctl_script: Path
    runner_script: Path
    pid_file: Path
    health_file: Path
    stop_intent_file: Path
    controlled_restart_file: Path
    log_file: Path
    health_stale_seconds: float

    @classmethod
    def from_config(cls, repo_root: Path, name: str, cfg: dict[str, Any]) -> "ServiceSpec":
        services = cfg.get("services") or {}
        raw = services[name]
        stale = float((cfg.get("health_stale_seconds") or {}).get(name, 45))
        return cls(
            name=name,
            display_name=str(raw["display_name"]),
            ctl_script=repo_root / raw["ctl_script"],
            runner_script=repo_root / raw["runner_script"],
            pid_file=repo_root / raw["pid_file"],
            health_file=repo_root / raw["health_file"],
            stop_intent_file=repo_root / raw["stop_intent_file"],
            controlled_restart_file=repo_root / raw["controlled_restart_file"],
            log_file=repo_root / raw["log_file"],
            health_stale_seconds=stale,
        )


@dataclass
class RestartPolicy:
    window_seconds: float = 600.0
    max_attempts_in_window: int = 5
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    stable_runtime_reset_seconds: float = 1800.0
    controlled_restart_grace_seconds: float = 30.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "RestartPolicy":
        raw = cfg.get("restart_policy") or {}
        return cls(
            window_seconds=float(raw.get("window_seconds", 600)),
            max_attempts_in_window=int(raw.get("max_attempts_in_window", 5)),
            max_delay_seconds=float(raw.get("max_delay_seconds", 60)),
            min_delay_seconds=float(raw.get("min_delay_seconds", 2)),
            stable_runtime_reset_seconds=float(raw.get("stable_runtime_reset_seconds", 1800)),
            controlled_restart_grace_seconds=float(raw.get("controlled_restart_grace_seconds", 30)),
        )


def write_stop_intent(path: Path, *, reason: str = "manual", stopped_by: str = "ctl stop") -> None:
    atomic_write_json(
        path,
        {
            "stop_intent": True,
            "stopped_at": utc_now_iso(),
            "stopped_by": stopped_by,
            "reason": reason,
        },
    )


def clear_stop_intent(path: Path) -> None:
    if path.exists():
        path.unlink(missing_ok=True)


def has_stop_intent(path: Path) -> bool:
    data = load_json(path)
    return bool(data.get("stop_intent"))


def mark_controlled_restart(path: Path, *, grace_seconds: float) -> None:
    atomic_write_json(
        path,
        {
            "controlled_restart": True,
            "marked_at": utc_now_iso(),
            "grace_until_epoch": time.time() + grace_seconds,
        },
    )


def controlled_restart_active(path: Path, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    data = load_json(path)
    grace = data.get("grace_until_epoch")
    if grace is None:
        return False
    try:
        return now <= float(grace)
    except Exception:
        return False


def clear_controlled_restart(path: Path) -> None:
    if path.exists():
        path.unlink(missing_ok=True)


@dataclass
class ServiceRestartState:
    attempts: list[float] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    last_restart_reason: str | None = None
    last_restart_at: str | None = None
    last_crash_at: str | None = None
    stable_since_epoch: float | None = None
    restart_count_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "last_restart_reason": self.last_restart_reason,
            "last_restart_at": self.last_restart_at,
            "last_crash_at": self.last_crash_at,
            "stable_since_epoch": self.stable_since_epoch,
            "restart_count_total": self.restart_count_total,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ServiceRestartState":
        raw = raw or {}
        return cls(
            attempts=[float(x) for x in raw.get("attempts", [])],
            blocked=bool(raw.get("blocked")),
            block_reason=raw.get("block_reason"),
            last_restart_reason=raw.get("last_restart_reason"),
            last_restart_at=raw.get("last_restart_at"),
            last_crash_at=raw.get("last_crash_at"),
            stable_since_epoch=raw.get("stable_since_epoch"),
            restart_count_total=int(raw.get("restart_count_total", 0)),
        )


@dataclass
class SupervisorState:
    services: dict[str, ServiceRestartState] = field(default_factory=dict)
    updated_at: str | None = None

    def service(self, name: str) -> ServiceRestartState:
        if name not in self.services:
            self.services[name] = ServiceRestartState()
        return self.services[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "services": {k: v.to_dict() for k, v in self.services.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "SupervisorState":
        raw = raw or {}
        services = {
            name: ServiceRestartState.from_dict(entry)
            for name, entry in (raw.get("services") or {}).items()
        }
        return cls(services=services, updated_at=raw.get("updated_at"))


def load_supervisor_state(path: Path) -> SupervisorState:
    return SupervisorState.from_dict(load_json(path))


def save_supervisor_state(path: Path, state: SupervisorState) -> None:
    state.updated_at = utc_now_iso()
    atomic_write_json(path, state.to_dict())


def prune_restart_attempts(entry: ServiceRestartState, *, policy: RestartPolicy, now: float) -> None:
    entry.attempts = [t for t in entry.attempts if now - t <= policy.window_seconds]


def maybe_reset_stable_runtime(
    entry: ServiceRestartState,
    *,
    policy: RestartPolicy,
    now: float,
    process_healthy: bool,
) -> None:
    if not process_healthy:
        entry.stable_since_epoch = None
        return
    if entry.stable_since_epoch is None:
        entry.stable_since_epoch = now
        return
    if now - entry.stable_since_epoch >= policy.stable_runtime_reset_seconds:
        entry.attempts = []
        entry.blocked = False
        entry.block_reason = None


def restart_allowed(
    entry: ServiceRestartState,
    *,
    policy: RestartPolicy,
    now: float,
) -> tuple[bool, str, float]:
    if entry.blocked:
        return False, str(entry.block_reason or "RESTART_STORM_BLOCKED"), float("inf")
    prune_restart_attempts(entry, policy=policy, now=now)
    if len(entry.attempts) >= policy.max_attempts_in_window:
        entry.blocked = True
        entry.block_reason = "RESTART_STORM_BLOCKED"
        return False, "RESTART_STORM_BLOCKED", float("inf")
    delay = min(policy.max_delay_seconds, policy.min_delay_seconds * (2 ** max(0, len(entry.attempts) - 1)))
    if entry.attempts and (now - entry.attempts[-1]) < delay:
        return False, "RESTART_BACKOFF", delay - (now - entry.attempts[-1])
    return True, "OK", delay


def record_restart_attempt(
    entry: ServiceRestartState,
    *,
    policy: RestartPolicy,
    now: float,
    reason: str,
    count_toward_storm: bool = True,
) -> None:
    entry.last_restart_reason = reason
    entry.last_restart_at = utc_now_iso()
    entry.restart_count_total += 1
    if count_toward_storm:
        prune_restart_attempts(entry, policy=policy, now=now)
        entry.attempts.append(now)


def find_runner_pids(spec: ServiceSpec, *, repo_root: Path | None = None) -> list[int]:
    script_name = spec.runner_script.name
    root = str(repo_root or spec.runner_script.parents[2])
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    found: list[int] = []
    for line in out.splitlines():
        if script_name not in line:
            continue
        if root not in line:
            continue
        if "pytest" in line or "intrabar_process_supervisor" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid_alive(pid):
            found.append(pid)
    return found


def adopt_pid(spec: ServiceSpec, *, repo_root: Path | None = None) -> int | None:
    root = repo_root or spec.runner_script.parents[2]
    pid = read_pid(spec.pid_file)
    if pid_alive(pid):
        return pid
    live = find_runner_pids(spec, repo_root=root)
    if len(live) == 1:
        spec.pid_file.parent.mkdir(parents=True, exist_ok=True)
        spec.pid_file.write_text(f"{live[0]}\n", encoding="utf-8")
        return live[0]
    return live[0] if live else None


_COGNITION_BENIGN_ERRORS = frozenset({"ws:opened"})


def _cognition_actionable_errors(health: dict[str, Any]) -> list[str]:
    return [str(err) for err in (health.get("errors") or []) if str(err) not in _COGNITION_BENIGN_ERRORS]


def _cognition_internal_degraded(health: dict[str, Any]) -> bool:
    queue = health.get("queue") or {}
    if int(queue.get("dropped_total") or 0) > 0:
        return True
    if int(queue.get("enqueue_rejected") or 0) > 0:
        return True
    writer = health.get("writer") or {}
    if writer.get("last_error"):
        return True
    if int(writer.get("write_errors") or 0) > 0:
        return True
    return bool(_cognition_actionable_errors(health))


def _paper_execution_state(health: dict[str, Any]) -> str | None:
    em = health.get("execution_market") or {}
    state = em.get("state") or {}
    raw = state.get("state")
    return str(raw) if raw is not None else None


def _alert_for(service_name: str, *, kind: str) -> str:
    if service_name == "intrabar_cognition":
        return {
            "down": ALERT_COGNITION_PROCESS_DOWN,
            "stale": ALERT_COGNITION_HEARTBEAT_STALE,
            "storm": ALERT_COGNITION_RESTART_STORM,
        }[kind]
    if service_name == "timeframe_manager":
        return {
            "down": ALERT_MANAGER_PROCESS_DOWN,
            "stale": ALERT_MANAGER_HEARTBEAT_STALE,
            "storm": ALERT_MANAGER_RESTART_STORM,
        }[kind]
    return {
        "down": ALERT_PAPER_PROCESS_DOWN,
        "stale": ALERT_PAPER_HEARTBEAT_STALE,
        "storm": ALERT_PAPER_RESTART_STORM,
    }[kind]


def evaluate_service(
    spec: ServiceSpec,
    *,
    restart_entry: ServiceRestartState,
    policy: RestartPolicy,
    now: float | None = None,
    restarting: bool = False,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    alerts: list[str] = []
    pid = adopt_pid(spec)
    alive = pid_alive(pid)
    stop_expected = has_stop_intent(spec.stop_intent_file)
    health = load_json(spec.health_file)
    health_age = _parse_iso_age_seconds(health.get("updated_at"), now=now)
    health_fresh = health_age is not None and health_age <= spec.health_stale_seconds
    health_pid = health.get("pid")
    pid_matches = health_pid is None or pid is None or int(health_pid) == int(pid)

    execution_state = _paper_execution_state(health) if spec.name == "intrabar_paper_manager" else None
    if execution_state == "UNSAFE":
        alerts.append(ALERT_PAPER_EXECUTION_UNSAFE)

    lifecycle = ProcessLifecycleState.FAILED
    detail = "unknown"

    if restarting:
        lifecycle = ProcessLifecycleState.RESTARTING
        detail = "controlled_restart_in_progress"
    elif stop_expected:
        lifecycle = ProcessLifecycleState.STOPPED_EXPECTED
        detail = "manual_stop_intent"
    elif restart_entry.blocked:
        lifecycle = ProcessLifecycleState.FAILED_PERMANENT
        detail = restart_entry.block_reason or "RESTART_STORM_BLOCKED"
        alerts.append(_alert_for(spec.name, kind="storm"))
    elif not alive:
        lifecycle = ProcessLifecycleState.FAILED
        detail = "process_not_running"
        alerts.append(_alert_for(spec.name, kind="down"))
    elif not health_fresh or not pid_matches:
        lifecycle = ProcessLifecycleState.FAILED
        detail = "heartbeat_stale_or_pid_mismatch"
        alerts.append(_alert_for(spec.name, kind="stale"))
    elif spec.name == "intrabar_paper_manager":
        if execution_state in {"DEGRADED", "RECOVERING", "UNSAFE"}:
            lifecycle = ProcessLifecycleState.RUNNING_DEGRADED
            detail = f"execution_state={execution_state}"
        elif execution_state == "HEALTHY" or execution_state is None:
            lifecycle = ProcessLifecycleState.RUNNING_HEALTHY
            detail = f"execution_state={execution_state or 'unknown'}"
        else:
            lifecycle = ProcessLifecycleState.RUNNING_DEGRADED
            detail = f"execution_state={execution_state}"
    elif _cognition_internal_degraded(health):
        lifecycle = ProcessLifecycleState.RUNNING_DEGRADED
        detail = "cognition_internal_degraded"
    else:
        lifecycle = ProcessLifecycleState.RUNNING_HEALTHY
        detail = "process_and_heartbeat_ok"

    process_healthy = lifecycle in {
        ProcessLifecycleState.RUNNING_HEALTHY,
        ProcessLifecycleState.RUNNING_DEGRADED,
    }
    maybe_reset_stable_runtime(restart_entry, policy=policy, now=now, process_healthy=process_healthy)

    needs_restart = lifecycle == ProcessLifecycleState.FAILED and not stop_expected
    return {
        "service": spec.name,
        "display_name": spec.display_name,
        "lifecycle_state": lifecycle.value,
        "detail": detail,
        "pid": pid,
        "alive": alive,
        "stop_expected": stop_expected,
        "health_age_seconds": health_age,
        "health_fresh": health_fresh,
        "health_pid_matches": pid_matches,
        "execution_state": execution_state,
        "paper_epoch_id": health.get("paper_epoch_id"),
        "needs_restart": needs_restart,
        "alerts": alerts,
        "restart_count_total": restart_entry.restart_count_total,
        "restart_attempts_in_window": len(restart_entry.attempts),
        "restart_blocked": restart_entry.blocked,
        "last_restart_reason": restart_entry.last_restart_reason,
        "last_restart_at": restart_entry.last_restart_at,
        "last_crash_at": restart_entry.last_crash_at,
    }


StartCtlFn = Callable[[ServiceSpec], dict[str, Any]]
StopCtlFn = Callable[[ServiceSpec], dict[str, Any]]


def default_start_service(spec: ServiceSpec, *, python: str) -> dict[str, Any]:
    proc = subprocess.run(
        [python, str(spec.ctl_script), "start"],
        cwd=str(spec.ctl_script.parents[2]),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


def default_stop_service(spec: ServiceSpec, *, python: str) -> dict[str, Any]:
    proc = subprocess.run(
        [python, str(spec.ctl_script), "stop"],
        cwd=str(spec.ctl_script.parents[2]),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


@dataclass
class IntrabarSupervisor:
    repo_root: Path
    config: dict[str, Any]
    policy: RestartPolicy
    specs: dict[str, ServiceSpec]
    state_path: Path
    operational_status_path: Path
    state: SupervisorState = field(default_factory=SupervisorState)
    start_fn: StartCtlFn | None = None
    stop_fn: StopCtlFn | None = None
    python: str = "python3"
    _restarting: set[str] = field(default_factory=set)

    @classmethod
    def create(
        cls,
        repo_root: Path | str,
        *,
        start_fn: StartCtlFn | None = None,
        stop_fn: StopCtlFn | None = None,
        python: str | None = None,
    ) -> "IntrabarSupervisor":
        root = Path(repo_root)
        config = load_config(root)
        policy = RestartPolicy.from_config(config)
        specs = {
            name: ServiceSpec.from_config(root, name, config)
            for name in (config.get("services") or {})
        }
        state_path = root / str(config.get("supervisor_state_file", "data/runtime/intrabar_supervision_state.json"))
        ops_path = root / str(config.get("operational_status_file", "data/runtime/intrabar_operational_status.json"))
        sup = cls(
            repo_root=root,
            config=config,
            policy=policy,
            specs=specs,
            state_path=state_path,
            operational_status_path=ops_path,
            state=load_supervisor_state(state_path),
            start_fn=start_fn,
            stop_fn=stop_fn,
            python=python or _resolve_python(root),
        )
        return sup

    def evaluate_all(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        services: dict[str, Any] = {}
        alerts: list[str] = []
        for name, spec in self.specs.items():
            entry = self.state.service(name)
            result = evaluate_service(
                spec,
                restart_entry=entry,
                policy=self.policy,
                now=now,
                restarting=name in self._restarting,
            )
            services[name] = result
            alerts.extend(result.get("alerts") or [])
        payload = {
            "updated_at": utc_now_iso(),
            "supervisor_pid": os.getpid(),
            "services": services,
            "alerts": sorted(set(alerts)),
        }
        atomic_write_json(self.operational_status_path, payload)
        return payload

    def restart_service(
        self,
        name: str,
        *,
        reason: str,
        now: float | None = None,
        count_toward_storm: bool = True,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        spec = self.specs[name]
        entry = self.state.service(name)
        allowed, block_reason, delay = restart_allowed(entry, policy=self.policy, now=now)
        if not allowed:
            entry.blocked = block_reason == "RESTART_STORM_BLOCKED"
            entry.block_reason = block_reason
            save_supervisor_state(self.state_path, self.state)
            return {"ok": False, "reason": block_reason, "delay_seconds": delay}

        self._restarting.add(name)
        try:
            entry.last_crash_at = utc_now_iso()
            if self.stop_fn is not None:
                stop_result = self.stop_fn(spec)
            else:
                stop_result = default_stop_service(spec, python=self.python)
            time.sleep(min(max(delay, self.policy.min_delay_seconds), self.policy.max_delay_seconds))
            if self.start_fn is not None:
                start_result = self.start_fn(spec)
            else:
                start_result = default_start_service(spec, python=self.python)
            ok = bool(start_result.get("ok"))
            if ok:
                record_restart_attempt(
                    entry,
                    policy=self.policy,
                    now=now,
                    reason=reason,
                    count_toward_storm=count_toward_storm,
                )
                clear_controlled_restart(spec.controlled_restart_file)
            save_supervisor_state(self.state_path, self.state)
            return {
                "ok": ok,
                "reason": reason,
                "stop_result": stop_result,
                "start_result": start_result,
                "counted_toward_storm": count_toward_storm,
            }
        finally:
            self._restarting.discard(name)

    def supervise_once(self, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        snapshot = self.evaluate_all(now=now)
        actions: dict[str, Any] = {}
        for name, result in snapshot["services"].items():
            spec = self.specs[name]
            if has_stop_intent(spec.stop_intent_file):
                continue
            if not result.get("needs_restart"):
                continue
            controlled = controlled_restart_active(spec.controlled_restart_file, now=now)
            restart_result = self.restart_service(
                name,
                reason=str(result.get("detail") or "process_failed"),
                now=now,
                count_toward_storm=not controlled,
            )
            actions[name] = restart_result
        if actions:
            snapshot = self.evaluate_all(now=now)
            snapshot["actions"] = actions
        save_supervisor_state(self.state_path, self.state)
        return snapshot


def _resolve_python(root: Path) -> str:
    for cand in (root / "venv" / "bin" / "python", root / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable

