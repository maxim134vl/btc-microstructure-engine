"""Engine execution guard — timeout, kill, stall detection."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from typing import Any, Callable

from runtime_config import ENGINE_KILL_GRACE_SECONDS, ENGINE_TIMEOUT_SECONDS

REPORT_DIR = os.path.join("reports", "runtime_blocking")
_LAST_ENGINE_START: dict[str, float] = {}
_BLOCKING_CHAIN: list[dict[str, Any]] = []


class EngineTimeoutError(RuntimeError):
    """Raised when an engine exceeds its execution budget."""


class EngineStalledError(RuntimeError):
    """Raised when watchdog detects a stalled engine."""


def _ensure_report_dir() -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    return REPORT_DIR


def _append_blocking_event(event: dict[str, Any]) -> None:
    _BLOCKING_CHAIN.append(event)
    if len(_BLOCKING_CHAIN) > 500:
        del _BLOCKING_CHAIN[:-500]


def _kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=ENGINE_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=ENGINE_KILL_GRACE_SECONDS)


def run_engine_subprocess(
    python: str,
    script_path: str,
    cwd: str,
    engine_name: str,
    timeout_seconds: int | None = None,
) -> int:
    """Run engine script with hard timeout. Never blocks indefinitely."""

    timeout = timeout_seconds or ENGINE_TIMEOUT_SECONDS
    started = time.time()
    _LAST_ENGINE_START[engine_name] = started

    proc = subprocess.Popen(
        [python, script_path],
        cwd=cwd,
        stdout=None,
        stderr=None,
        text=True,
    )

    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        duration = round(time.time() - started, 2)
        _kill_process(proc)
        event = {
            "timestamp": datetime.now().isoformat(),
            "engine": engine_name,
            "event": "TIMEOUT",
            "duration_s": duration,
            "timeout_s": timeout,
        }
        _append_blocking_event(event)
        _export_engine_hang_audit(engine_name, event)
        raise EngineTimeoutError(
            f"ENGINE TIMEOUT: {engine_name} exceeded {timeout}s"
        ) from error

    duration = round(time.time() - started, 2)
    _append_blocking_event(
        {
            "timestamp": datetime.now().isoformat(),
            "engine": engine_name,
            "event": "COMPLETED",
            "duration_s": duration,
            "returncode": returncode,
        }
    )

    if returncode != 0:
        raise RuntimeError(f"ENGINE FAILED: {engine_name} (exit {returncode})")

    return returncode


def run_inprocess_with_timeout(
    engine_name: str,
    fn: Callable[[], Any],
    timeout_seconds: int | None = None,
) -> Any:
    """Run in-process engine with SIGALRM timeout (Unix)."""

    timeout = timeout_seconds or ENGINE_TIMEOUT_SECONDS
    started = time.time()
    _LAST_ENGINE_START[engine_name] = started

    if not hasattr(signal, "SIGALRM"):
        return fn()

    def _handler(signum, frame):
        raise EngineTimeoutError(
            f"ENGINE TIMEOUT: {engine_name} exceeded {timeout}s"
        )

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(max(1, int(timeout)))
    try:
        result = fn()
    except EngineTimeoutError:
        duration = round(time.time() - started, 2)
        event = {
            "timestamp": datetime.now().isoformat(),
            "engine": engine_name,
            "event": "TIMEOUT",
            "duration_s": duration,
            "timeout_s": timeout,
            "mode": "in-process",
        }
        _append_blocking_event(event)
        _export_engine_hang_audit(engine_name, event)
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    duration = round(time.time() - started, 2)
    _append_blocking_event(
        {
            "timestamp": datetime.now().isoformat(),
            "engine": engine_name,
            "event": "COMPLETED",
            "duration_s": duration,
            "mode": "in-process",
        }
    )
    return result


def detect_stalled_engine(engine_name: str, elapsed_s: float, limit_s: int | None = None) -> None:
    limit = limit_s or ENGINE_TIMEOUT_SECONDS
    if elapsed_s > limit:
        event = {
            "timestamp": datetime.now().isoformat(),
            "engine": engine_name,
            "event": "STALL_DETECTED",
            "elapsed_s": round(elapsed_s, 2),
            "limit_s": limit,
        }
        _append_blocking_event(event)
        _export_pipeline_stall_audit(event)
        raise EngineStalledError(
            f"ENGINE STALLED: {engine_name} running {elapsed_s:.1f}s > {limit}s"
        )


def _export_engine_hang_audit(engine_name: str, event: dict[str, Any]) -> str:
    report_dir = _ensure_report_dir()
    payload = {
        "generated_at": datetime.now().isoformat(),
        "engine": engine_name,
        "event": event,
        "recent_chain": _BLOCKING_CHAIN[-20:],
    }
    path = os.path.join(report_dir, "engine_hang_audit.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def _export_pipeline_stall_audit(event: dict[str, Any]) -> str:
    report_dir = _ensure_report_dir()
    payload = {
        "generated_at": datetime.now().isoformat(),
        "stall_event": event,
        "blocking_chain": _BLOCKING_CHAIN[-50:],
    }
    path = os.path.join(report_dir, "pipeline_stall_audit.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def export_runtime_blocking_chain() -> str:
    report_dir = _ensure_report_dir()
    payload = {
        "generated_at": datetime.now().isoformat(),
        "last_engine_starts": _LAST_ENGINE_START,
        "blocking_chain": _BLOCKING_CHAIN,
    }
    path = os.path.join(report_dir, "runtime_blocking_chain.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def export_all_blocking_audits() -> dict[str, str]:
    _ensure_report_dir()
    export_runtime_blocking_chain()
    return {
        "engine_hang_audit": os.path.join(REPORT_DIR, "engine_hang_audit.json"),
        "pipeline_stall_audit": os.path.join(REPORT_DIR, "pipeline_stall_audit.json"),
        "runtime_blocking_chain": os.path.join(REPORT_DIR, "runtime_blocking_chain.json"),
    }
