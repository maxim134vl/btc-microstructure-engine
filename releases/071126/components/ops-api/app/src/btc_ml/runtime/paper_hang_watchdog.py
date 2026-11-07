"""Paper-manager hang detector.

The VPS compose supervisor is told not to spawn paper (compose owns the
container). Docker healthcheck previously treated a *present* health.json as
healthy even when `updated_at` froze. A futex-stuck paper process then sat
"healthy" while TP/SL ticks and S4.1 CLOSEs were not consumed.

This module is the in-container monitor:
- evaluate heartbeat age (execution_market HEALTHY on a frozen file is not
  liveness)
- docker healthcheck fails on stale `updated_at`
- parent supervisor SIGKILLs the hung child so compose `restart: unless-stopped`
  brings paper back
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_S = 45.0
DEFAULT_POLL_S = 5.0
DEFAULT_TERM_GRACE_S = 5.0
INCIDENT_LOG = "data/runtime/paper_hang_incidents.jsonl"
INCIDENT_LATEST = "data/runtime/paper_hang_watchdog.json"


def paper_health_max_age_s() -> float:
    raw = os.environ.get("VPS_PAPER_HEALTH_MAX_AGE_S") or os.environ.get(
        "PAPER_HEALTH_MAX_AGE_S"
    )
    if raw is None or str(raw).strip() == "":
        return DEFAULT_MAX_AGE_S
    return float(raw)


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def heartbeat_age_s(payload: dict[str, Any], *, now: datetime | None = None) -> float | None:
    stamp = parse_iso(payload.get("updated_at"))
    if stamp is None:
        return None
    clock = now or datetime.now(timezone.utc)
    return (clock - stamp).total_seconds()


def _execution_state(payload: dict[str, Any]) -> str | None:
    em = payload.get("execution_market") or {}
    state = em.get("state") or {}
    raw = state.get("state")
    return str(raw) if raw is not None else None


@dataclass(frozen=True)
class PaperHeartbeat:
    ok: bool
    phase: str
    reason: str
    age_s: float | None
    health_path: str | None
    updated_at: str | None
    execution_state: str | None

    def message(self) -> str:
        age = "none" if self.age_s is None else f"{self.age_s:.1f}s"
        return (
            f"{self.phase}: {self.reason} age={age} "
            f"execution_state={self.execution_state or 'unknown'} "
            f"path={self.health_path or '-'}"
        )


def evaluate_paper_heartbeat(
    payload: dict[str, Any] | None,
    *,
    health_path: Path | str | None = None,
    now: datetime | None = None,
    max_age_s: float | None = None,
    expected_pid: int | None = None,
) -> PaperHeartbeat:
    """Liveness is `updated_at` freshness. Frozen HEALTHY tape is a hang."""

    limit = DEFAULT_MAX_AGE_S if max_age_s is None else float(max_age_s)
    path_s = str(health_path) if health_path is not None else None
    if payload is None:
        return PaperHeartbeat(
            ok=False,
            phase="STARTING",
            reason="missing_health",
            age_s=None,
            health_path=path_s,
            updated_at=None,
            execution_state=None,
        )
    if expected_pid is not None:
        try:
            health_pid = int(payload["pid"]) if payload.get("pid") is not None else None
        except (TypeError, ValueError):
            health_pid = None
        if health_pid != int(expected_pid):
            return PaperHeartbeat(
                ok=False,
                phase="STARTING",
                reason="pid_mismatch",
                age_s=heartbeat_age_s(payload, now=now),
                health_path=path_s,
                updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
                execution_state=_execution_state(payload),
            )
    age = heartbeat_age_s(payload, now=now)
    updated_at = payload.get("updated_at")
    execution_state = _execution_state(payload)
    if age is None:
        return PaperHeartbeat(
            ok=False,
            phase="UNHEALTHY",
            reason="missing_updated_at",
            age_s=None,
            health_path=path_s,
            updated_at=str(updated_at) if updated_at is not None else None,
            execution_state=execution_state,
        )
    if age > limit:
        return PaperHeartbeat(
            ok=False,
            phase="UNHEALTHY",
            reason="heartbeat_stale",
            age_s=age,
            health_path=path_s,
            updated_at=str(updated_at),
            execution_state=execution_state,
        )
    return PaperHeartbeat(
        ok=True,
        phase="HEALTHY",
        reason="heartbeat_fresh",
        age_s=age,
        health_path=path_s,
        updated_at=str(updated_at),
        execution_state=execution_state,
    )


def resolve_health_path(repo: Path) -> Path | None:
    active = repo / "data" / "trading" / "paper_epochs" / "active.json"
    epoch_id = None
    if active.is_file():
        try:
            epoch_id = json.loads(active.read_text(encoding="utf-8")).get("paper_epoch_id")
        except (OSError, json.JSONDecodeError):
            epoch_id = None
    candidates: list[Path] = []
    if epoch_id:
        candidates.append(repo / "data" / "trading" / "intrabar_paper" / str(epoch_id) / "health.json")
        candidates.append(
            repo / "data" / "trading" / "intrabar_paper" / str(epoch_id) / "books" / "health.json"
        )
    candidates.append(repo / "data" / "runtime" / "intrabar_paper_health.json")
    return next((p for p in candidates if p.is_file()), None)


def load_health_payload(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def evaluate_repo(
    repo: Path,
    *,
    now: datetime | None = None,
    max_age_s: float | None = None,
    expected_pid: int | None = None,
) -> PaperHeartbeat:
    path = resolve_health_path(repo)
    return evaluate_paper_heartbeat(
        load_health_payload(path),
        health_path=path,
        now=now,
        max_age_s=max_age_s if max_age_s is not None else paper_health_max_age_s(),
        expected_pid=expected_pid,
    )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_incident(repo: Path, payload: dict[str, Any]) -> None:
    runtime = repo / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_iso(), **payload}
    encoded = json.dumps(row, sort_keys=True, default=str)
    (runtime / Path(INCIDENT_LATEST).name).write_text(encoded + "\n", encoding="utf-8")
    with (repo / INCIDENT_LOG).open("a", encoding="utf-8") as fh:
        fh.write(encoded + "\n")


def _terminate_child(proc: subprocess.Popen[Any], *, grace_s: float) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
    except OSError:
        pass
    deadline = time.time() + grace_s
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.2)
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            pass


def supervise_child(
    child_argv: list[str],
    *,
    repo: Path,
    max_age_s: float | None = None,
    poll_s: float = DEFAULT_POLL_S,
    term_grace_s: float = DEFAULT_TERM_GRACE_S,
    start_grace_s: float = 60.0,
    sleep_fn=time.sleep,
) -> int:
    """Run paper as a child. Kill it if health.json stops advancing."""

    limit = paper_health_max_age_s() if max_age_s is None else float(max_age_s)
    proc = subprocess.Popen(child_argv, cwd=str(repo))
    started = time.time()
    saw_health = False
    try:
        while proc.poll() is None:
            verdict = evaluate_repo(repo, max_age_s=limit, expected_pid=proc.pid)
            if verdict.phase == "STARTING":
                if time.time() - started > start_grace_s:
                    write_incident(
                        repo,
                        {
                            "action": "SIGKILL",
                            "pid": proc.pid,
                            "reason": "health_missing_past_start_grace",
                            "age_s": verdict.age_s,
                            "execution_state": verdict.execution_state,
                            "health_path": verdict.health_path,
                        },
                    )
                    _terminate_child(proc, grace_s=term_grace_s)
                    return 1
            elif not verdict.ok:
                if saw_health or time.time() - started > start_grace_s:
                    write_incident(
                        repo,
                        {
                            "action": "SIGKILL",
                            "pid": proc.pid,
                            "reason": verdict.reason,
                            "age_s": verdict.age_s,
                            "execution_state": verdict.execution_state,
                            "updated_at": verdict.updated_at,
                            "health_path": verdict.health_path,
                        },
                    )
                    _terminate_child(proc, grace_s=term_grace_s)
                    return 1
            else:
                saw_health = True
            sleep_fn(poll_s)
    except KeyboardInterrupt:
        _terminate_child(proc, grace_s=term_grace_s)
        raise
    return int(proc.returncode or 0)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Paper hang watchdog")
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")))
    parser.add_argument("--max-age-s", type=float, default=None)
    parser.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S)
    parser.add_argument("--check", action="store_true", help="Evaluate once and exit (healthcheck)")
    parser.add_argument("child", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    limit = args.max_age_s if args.max_age_s is not None else paper_health_max_age_s()
    child = list(args.child)
    if child and child[0] == "--":
        child = child[1:]
    if args.check or not child:
        verdict = evaluate_repo(args.repo, max_age_s=limit)
        print(verdict.message())
        if verdict.phase == "STARTING":
            return 1
        return 0 if verdict.ok else 1
    return supervise_child(
        child,
        repo=args.repo,
        max_age_s=limit,
        poll_s=args.poll_s,
    )


if __name__ == "__main__":
    raise SystemExit(main())
