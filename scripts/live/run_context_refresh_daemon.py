#!/usr/bin/env python3
"""Dedicated context refresh daemon (Patch 2A.1).

Single recurring owner of context/lifecycle/decision catch-up.
Default activation is via BTC_ML_CONTEXT_REFRESH_DAEMON=1 + ctl script.

Supports:
  --foreground   stay in foreground, line-buffered structured stdout
  --once         one cycle then exit (tests / dry validation)
  --interval-s   cycle sleep (default 900 / CONTEXT_REFRESH_INTERVAL_SECONDS)

Does not import or start paper controller. Does not touch Docker.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Line-buffered stdout for Docker-ready logs.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "live") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "live"))

from run_live_context_refresh_once import (  # noqa: E402
    LIVE_FEED,
    LIFECYCLE_PATH,
    latest_parquet_timestamp,
    run_refresh_once,
)


def _run_script_streaming(script: Path, *, cwd: Path = ROOT, timeout_s: int = 1200) -> dict[str, Any]:
    """Run child without capture_output (avoids OOM on large shadow-chain logs)."""
    import subprocess
    from datetime import datetime, timezone

    if not script.exists():
        raise RuntimeError(f"Missing script: {script}")
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / f"context_refresh_child_{script.stem}.log"
    started = datetime.now(tz=timezone.utc)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== {started.isoformat()} {script.name} =====\n")
        handle.flush()
        proc = subprocess.run(
            [sys.executable, "-u", str(script)],
            cwd=str(cwd),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    ended = datetime.now(tz=timezone.utc)
    try:
        tail = out_path.read_text(encoding="utf-8")[-4000:]
    except Exception:
        tail = ""
    return {
        "script": str(script),
        "returncode": int(proc.returncode),
        "ok": proc.returncode == 0,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "stdout_tail": tail,
        "stderr_tail": "",
        "child_log": str(out_path),
    }

COMPONENT = "context_refresh_daemon"
SERVICE = "model-runtime"
CANDLE_PATH = ROOT / "data" / "cognition" / "candle_structure_memory.parquet"
FINAL_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
DECISION_PATH = ROOT / "data" / "live" / "context_decision_log.parquet"
DEFAULT_LOCK = ROOT / "run" / "context_refresh_daemon.lock"
DEFAULT_PID = ROOT / "run" / "context_refresh_daemon.pid"
DEFAULT_STATUS = ROOT / "data" / "live" / "context_refresh_daemon_status.json"

_STOP = False
_STOP_EVENT = threading.Event()
_LOCK_HELD: Path | None = None

# Injected in tests; production uses monotonic + Event.wait.
MonotonicFn = Callable[[], float]
WaitFn = Callable[[float], bool]


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class ScheduleWaitPlan:
    """Post-cycle wait plan derived from a monotonic deadline grid."""

    sleep_seconds: float
    next_deadline_mono: float
    cycle_duration_seconds: float
    configured_interval_seconds: float
    missed_intervals: int
    overrun: bool
    next_deadline_in_seconds: float


def plan_schedule_wait(
    *,
    cycle_started_mono: float,
    now_mono: float,
    slot_deadline_mono: float,
    interval_s: float,
) -> ScheduleWaitPlan:
    """Advance from the completed slot to the next future monotonic deadline.

    Contract:
    - negative sleep is impossible by construction (sleep_seconds >= 0)
    - missed slots are skipped (no catch-up storm)
    - overrun is non-fatal and reported via fields
    """
    interval = float(interval_s)
    if interval <= 0:
        raise ValueError(f"interval_s must be positive, got {interval_s!r}")

    cycle_duration = max(0.0, float(now_mono) - float(cycle_started_mono))
    next_deadline = float(slot_deadline_mono) + interval
    missed = 0
    # Strict '>' so finishing exactly on the next slot yields sleep_seconds == 0
    # (immediate next iteration) rather than skipping an extra full interval.
    if float(now_mono) > next_deadline:
        missed = int((float(now_mono) - next_deadline) // interval) + 1
        next_deadline += missed * interval

    sleep_seconds = next_deadline - float(now_mono)
    if sleep_seconds < 0:
        # Floating-point guard: snap to a future slot rather than negative sleep.
        missed += 1
        next_deadline += interval
        sleep_seconds = max(0.0, next_deadline - float(now_mono))

    return ScheduleWaitPlan(
        sleep_seconds=float(sleep_seconds),
        next_deadline_mono=float(next_deadline),
        cycle_duration_seconds=float(cycle_duration),
        configured_interval_seconds=interval,
        missed_intervals=int(missed),
        overrun=bool(missed > 0 or cycle_duration > interval),
        next_deadline_in_seconds=max(0.0, float(sleep_seconds)),
    )


def interruptible_wait(
    sleep_seconds: float,
    *,
    stop_event: threading.Event | None = None,
    wait_fn: WaitFn | None = None,
) -> bool:
    """Wait up to sleep_seconds or until stop. Never passes negative timeout.

    Returns True if stop was signaled (or wait_fn reports stopped).
    """
    timeout = float(sleep_seconds)
    if timeout <= 0:
        return bool(stop_event.is_set()) if stop_event is not None else False
    if wait_fn is not None:
        return bool(wait_fn(timeout))
    event = stop_event if stop_event is not None else _STOP_EVENT
    return bool(event.wait(timeout))


def _iso(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        import pandas as pd

        parsed = pd.to_datetime(ts, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return pd.Timestamp(parsed).isoformat().replace("+00:00", "Z")
    except Exception:
        return str(ts)


def emit(
    event: str,
    *,
    level: str = "INFO",
    cycle_id: str | None = None,
    market_timestamp: str | None = None,
    message: str = "",
    **fields: Any,
) -> None:
    """Structured single-line stdout log (Docker-ready)."""
    payload = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "service": SERVICE,
        "component": COMPONENT,
        "level": level,
        "event": event,
        "market_timestamp": market_timestamp,
        "cycle_id": cycle_id,
        "message": message,
    }
    payload.update(fields)
    line = json.dumps(payload, default=str, separators=(",", ":"))
    print(line, flush=True)


def resolve_canonical_python(root: Path | None = None) -> Path:
    """Return repo venv python path string (not bare Cellar)."""
    root = root or ROOT
    override = os.environ.get("BTC_ML_COLLECTOR_PYTHON", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.append(root / "venv" / "bin" / "python")
    candidates.append(root / "venv" / "bin" / "python3")
    root_norm = os.path.abspath(str(root)).replace("\\", "/")
    for path in candidates:
        abs_norm = os.path.abspath(str(path)).replace("\\", "/")
        if not abs_norm.startswith(root_norm + "/venv/"):
            continue
        if path.exists() and os.access(path, os.X_OK):
            return path
    raise RuntimeError(f"canonical venv python missing under {root}/venv/bin")


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class TipSnapshot:
    feed: Any
    candle: Any
    final: Any
    lifecycle: Any
    decision: Any

    @property
    def safe_upstream(self) -> Any:
        """Do not outrun pipeline: min(feed, candle) when both present."""
        import pandas as pd

        tips = [t for t in (self.feed, self.candle) if t is not None]
        if not tips:
            return None
        return min(pd.Timestamp(t) for t in tips)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "feed": _iso(self.feed),
            "candle": _iso(self.candle),
            "safe_upstream": _iso(self.safe_upstream),
            "final": _iso(self.final),
            "lifecycle": _iso(self.lifecycle),
            "decision": _iso(self.decision),
        }


def read_tips(
    *,
    feed_path: Path = LIVE_FEED,
    candle_path: Path = CANDLE_PATH,
    final_path: Path = FINAL_PATH,
    lifecycle_path: Path = LIFECYCLE_PATH,
    decision_path: Path = DECISION_PATH,
) -> TipSnapshot:
    return TipSnapshot(
        feed=latest_parquet_timestamp(feed_path) if feed_path.exists() else None,
        candle=latest_parquet_timestamp(candle_path) if candle_path.exists() else None,
        final=latest_parquet_timestamp(final_path) if final_path.exists() else None,
        lifecycle=latest_parquet_timestamp(lifecycle_path) if lifecycle_path.exists() else None,
        decision=latest_parquet_timestamp(decision_path, col="candle_timestamp")
        if decision_path.exists()
        else None,
    )


def classify_cycle(tips: TipSnapshot) -> str:
    """Return event code for this cycle before any write.

    Safe upstream = min(feed, candle). Daemon must not outrun pipeline:
    if feed > candle and planes already at candle tip → PIPELINE_PENDING.
    """
    import pandas as pd

    safe = tips.safe_upstream
    if safe is None:
        return "PIPELINE_PENDING"

    life = tips.lifecycle
    final = tips.final
    decision = tips.decision
    feed = tips.feed
    candle = tips.candle

    # Partial / incomplete pipeline bar: feed advanced, candle not yet.
    if feed is not None and candle is not None and pd.Timestamp(candle) < pd.Timestamp(feed):
        if life is not None and pd.Timestamp(life) >= pd.Timestamp(candle):
            final_ok = final is None or pd.Timestamp(final) >= pd.Timestamp(candle)
            decision_ok = decision is None or pd.Timestamp(decision) >= pd.Timestamp(candle)
            if final_ok and decision_ok:
                return "PIPELINE_PENDING"

    if life is not None and pd.Timestamp(life) >= pd.Timestamp(safe):
        final_ok = final is None or pd.Timestamp(final) >= pd.Timestamp(life)
        decision_ok = decision is None or pd.Timestamp(decision) >= pd.Timestamp(life)
        if final_ok and decision_ok:
            return "NO_NEW_SAFE_UPSTREAM"
        return "CONTEXT_REFRESH_START"

    return "CONTEXT_REFRESH_START"


def acquire_lock(lock_path: Path, *, pid: int, stale_s: float = 1800.0) -> bool:
    """Exclusive lock. Recover stale lock from dead PID."""
    global _LOCK_HELD
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            raw = lock_path.read_text(encoding="utf-8").strip()
            old_pid = int(raw.split()[0])
        except Exception:
            old_pid = -1
        alive = False
        if old_pid > 0:
            try:
                os.kill(old_pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive and old_pid != pid:
            return False
        # Stale or same pid — reclaim if mtime old or dead.
        age = time.time() - lock_path.stat().st_mtime
        if alive and age < stale_s and old_pid != pid:
            return False
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
    # atomic create
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{pid}\n")
    _LOCK_HELD = lock_path
    return True


def release_lock(lock_path: Path | None = None) -> None:
    global _LOCK_HELD
    path = lock_path or _LOCK_HELD
    if path is None:
        return
    try:
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw.split()[0] == str(os.getpid()):
                path.unlink()
    except Exception:
        pass
    if _LOCK_HELD == path:
        _LOCK_HELD = None


def write_pid(pid_path: Path, pid: int) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = pid_path.with_suffix(pid_path.suffix + ".tmp")
    tmp.write_text(f"{pid}\n", encoding="utf-8")
    os.replace(tmp, pid_path)


def clear_pid(pid_path: Path) -> None:
    try:
        if pid_path.exists():
            raw = pid_path.read_text(encoding="utf-8").strip()
            if raw == str(os.getpid()):
                pid_path.unlink()
    except Exception:
        pass


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _request_stop(signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    _STOP_EVENT.set()
    emit(
        "CONTEXT_REFRESH_STOP",
        level="INFO",
        message=f"signal={signum}",
        signal=signum,
    )


def run_cycle(
    *,
    cycle_id: str,
    dry_run: bool = False,
    status_path: Path = DEFAULT_STATUS,
) -> dict[str, Any]:
    started = _utc_now()
    tips_before = read_tips()
    tip_dict = tips_before.as_dict()
    event = classify_cycle(tips_before)
    hashes_before = {
        "final": file_sha256(FINAL_PATH),
        "lifecycle": file_sha256(LIFECYCLE_PATH),
        "decision": file_sha256(DECISION_PATH),
    }
    rows_before = {}
    try:
        import pandas as pd

        for name, path in (
            ("final", FINAL_PATH),
            ("lifecycle", LIFECYCLE_PATH),
            ("decision", DECISION_PATH),
        ):
            rows_before[name] = int(len(pd.read_parquet(path))) if path.exists() else 0
    except Exception:
        rows_before = {}

    emit(
        event,
        cycle_id=cycle_id,
        market_timestamp=tip_dict.get("safe_upstream"),
        message="cycle_begin",
        upstream_tip=tip_dict.get("safe_upstream"),
        previous_context_tip=tip_dict.get("final"),
        previous_lifecycle_tip=tip_dict.get("lifecycle"),
        previous_decision_tip=tip_dict.get("decision"),
        feed_tip=tip_dict.get("feed"),
        candle_tip=tip_dict.get("candle"),
    )

    result = event
    added_rows = {"final": 0, "lifecycle": 0, "decision": 0}
    refresh_payload: dict[str, Any] | None = None
    error: str | None = None

    if event == "NO_NEW_SAFE_UPSTREAM":
        result = "NO_NEW_SAFE_UPSTREAM"
    elif event == "PIPELINE_PENDING":
        result = "PIPELINE_PENDING"
    elif dry_run:
        result = "DRY_RUN_SKIP_WRITE"
    else:
        try:
            # Cap once-refresh to not chase incomplete pipeline: once script uses feed tip;
            # we only enter when lifecycle < safe_upstream (= min feed,candle), so OK.
            refresh_payload = run_refresh_once(run_script=_run_script_streaming)
            if refresh_payload.get("status") != "OK":
                result = "REFRESH_FAILED"
                error = str(refresh_payload.get("error"))
            else:
                result = "REFRESH_SUCCESS"
        except Exception as exc:  # noqa: BLE001
            result = "REFRESH_FAILED"
            error = str(exc)
            emit(
                "REFRESH_FAILED",
                level="ERROR",
                cycle_id=cycle_id,
                message=str(exc),
                traceback=traceback.format_exc()[-2000:],
            )

    tips_after = read_tips()
    tip_after = tips_after.as_dict()
    hashes_after = {
        "final": file_sha256(FINAL_PATH),
        "lifecycle": file_sha256(LIFECYCLE_PATH),
        "decision": file_sha256(DECISION_PATH),
    }
    try:
        import pandas as pd

        for name, path in (
            ("final", FINAL_PATH),
            ("lifecycle", LIFECYCLE_PATH),
            ("decision", DECISION_PATH),
        ):
            after = int(len(pd.read_parquet(path))) if path.exists() else 0
            added_rows[name] = after - int(rows_before.get(name, 0))
    except Exception:
        pass

    duration_s = (_utc_now() - started).total_seconds()
    payload = {
        "cycle_id": cycle_id,
        "event": event,
        "result": result,
        "error": error,
        "tips_before": tip_dict,
        "tips_after": tip_after,
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
        "hashes_unchanged": hashes_before == hashes_after,
        "added_rows": added_rows,
        "duration_s": round(duration_s, 3),
        "dry_run": dry_run,
        "refresh_status": None if refresh_payload is None else refresh_payload.get("status"),
        "execution_enabled": False,
    }
    write_status(status_path, payload)

    emit(
        result,
        level="ERROR" if result == "REFRESH_FAILED" else "INFO",
        cycle_id=cycle_id,
        market_timestamp=tip_after.get("safe_upstream"),
        message="cycle_end",
        upstream_tip=tip_after.get("safe_upstream"),
        previous_context_tip=tip_dict.get("final"),
        result=result,
        added_rows=added_rows,
        duration_s=round(duration_s, 3),
        final_tip=tip_after.get("final"),
        lifecycle_tip=tip_after.get("lifecycle"),
        decision_tip=tip_after.get("decision"),
        hashes_unchanged=hashes_before == hashes_after,
        error=error,
    )
    return payload


def daemon_loop(
    *,
    interval_s: float,
    foreground: bool,
    once: bool,
    dry_run: bool,
    lock_path: Path,
    pid_path: Path,
    status_path: Path,
    require_flag: bool = True,
    monotonic_fn: MonotonicFn | None = None,
    wait_fn: WaitFn | None = None,
) -> int:
    global _STOP
    flag = os.environ.get("BTC_ML_CONTEXT_REFRESH_DAEMON", "0").strip()
    if require_flag and flag != "1":
        emit(
            "REFUSED",
            level="ERROR",
            message="BTC_ML_CONTEXT_REFRESH_DAEMON must be 1",
            flag=flag,
        )
        return 2

    # Safety rails
    os.environ.setdefault("BTC_ML_CONTINUATION_PROGRESSION", "0")
    os.environ.setdefault("PRICE_GATE", "OFF")

    mono = monotonic_fn or time.monotonic
    _STOP = False
    _STOP_EVENT.clear()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    atexit.register(lambda: release_lock(lock_path))
    atexit.register(lambda: clear_pid(pid_path))

    write_pid(pid_path, os.getpid())
    emit(
        "CONTEXT_REFRESH_START",
        message="daemon_boot",
        pid=os.getpid(),
        foreground=foreground,
        interval_s=interval_s,
        cwd=str(Path.cwd()),
        interpreter=sys.executable,
        argv0=sys.argv[0] if sys.argv else "",
        dry_run=dry_run,
        scheduler="monotonic_deadline",
    )

    cycle_n = 0
    exit_code = 0
    # First cycle runs immediately on the current monotonic slot.
    next_deadline = float(mono())
    while not _STOP:
        now = float(mono())
        if now < next_deadline:
            early_sleep = next_deadline - now
            stopped = interruptible_wait(
                early_sleep,
                stop_event=_STOP_EVENT,
                wait_fn=wait_fn,
            )
            if stopped or _STOP:
                break
            now = float(mono())

        slot_deadline = next_deadline
        cycle_n += 1
        cycle_id = f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}-{cycle_n}"
        cycle_started = float(mono())
        if not acquire_lock(lock_path, pid=os.getpid()):
            emit(
                "LOCK_BUSY",
                level="WARN",
                cycle_id=cycle_id,
                message="another refresh holds the lock; skipping cycle",
            )
        else:
            try:
                payload = run_cycle(cycle_id=cycle_id, dry_run=dry_run, status_path=status_path)
                if payload.get("result") == "REFRESH_FAILED":
                    exit_code = 1
            finally:
                release_lock(lock_path)

        if once or _STOP:
            break

        finished = float(mono())
        try:
            plan = plan_schedule_wait(
                cycle_started_mono=cycle_started,
                now_mono=finished,
                slot_deadline_mono=slot_deadline,
                interval_s=interval_s,
            )
        except Exception as exc:
            emit(
                "SCHEDULER_ERROR",
                level="ERROR",
                cycle_id=cycle_id,
                message="scheduler_calculation_error",
                error=str(exc),
            )
            # Fail closed on scheduler arithmetic: stop rather than busy-loop.
            exit_code = 1
            break

        next_deadline = plan.next_deadline_mono
        if plan.overrun:
            emit(
                "REFRESH_INTERVAL_OVERRUN",
                level="WARN",
                cycle_id=cycle_id,
                message="refresh_exceeded_interval_skipped_missed_slots",
                cycle_duration_seconds=round(plan.cycle_duration_seconds, 6),
                configured_interval_seconds=plan.configured_interval_seconds,
                missed_intervals=plan.missed_intervals,
                next_deadline_in_seconds=round(plan.next_deadline_in_seconds, 6),
            )

        # Negative sleep must be impossible by construction.
        if plan.sleep_seconds < 0:
            emit(
                "SCHEDULER_ERROR",
                level="ERROR",
                cycle_id=cycle_id,
                message="negative_sleep_impossible_violation",
                sleep_seconds=plan.sleep_seconds,
            )
            exit_code = 1
            break

        stopped = interruptible_wait(
            plan.sleep_seconds,
            stop_event=_STOP_EVENT,
            wait_fn=wait_fn,
        )
        if stopped or _STOP:
            break

    emit("CONTEXT_REFRESH_STOP", message="daemon_exit", exit_code=exit_code, cycles=cycle_n)
    clear_pid(pid_path)
    release_lock(lock_path)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated context refresh daemon")
    parser.add_argument("--foreground", action="store_true", help="Foreground mode (stdout logs)")
    parser.add_argument("--once", action="store_true", help="Run a single cycle then exit")
    parser.add_argument("--dry-run", action="store_true", help="Classify only; no writes")
    parser.add_argument(
        "--interval-s",
        type=float,
        default=float(os.environ.get("CONTEXT_REFRESH_INTERVAL_SECONDS", "900")),
    )
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--pid-path", type=Path, default=DEFAULT_PID)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS)
    parser.add_argument(
        "--allow-without-flag",
        action="store_true",
        help="Test helper: skip BTC_ML_CONTEXT_REFRESH_DAEMON=1 requirement",
    )
    args = parser.parse_args(argv)

    # Ensure cwd is repo root for relative data paths.
    os.chdir(ROOT)

    return daemon_loop(
        interval_s=args.interval_s,
        foreground=bool(args.foreground or True),  # always log to stdout
        once=bool(args.once),
        dry_run=bool(args.dry_run),
        lock_path=args.lock_path,
        pid_path=args.pid_path,
        status_path=args.status_path,
        require_flag=not bool(args.allow_without_flag),
    )


if __name__ == "__main__":
    raise SystemExit(main())
