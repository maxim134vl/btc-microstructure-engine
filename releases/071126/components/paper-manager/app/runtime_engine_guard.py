"""Engine execution guard — timeout, kill, stall detection, persistent worker pool."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Callable

from runtime_config import (
    ENGINE_KILL_GRACE_SECONDS,
    ENGINE_TIMEOUT_SECONDS,
    ENGINE_WORKER_AUDIT_PATH,
    ENGINE_WORKER_MAX_JOBS,
    ENGINE_WORKER_MAX_RSS_MB,
    ENGINE_WORKER_MAX_UPTIME_SEC,
    engine_execution_mode,
)

REPORT_DIR = os.path.join("reports", "runtime_blocking")
_LAST_ENGINE_START: dict[str, float] = {}
_BLOCKING_CHAIN: list[dict[str, Any]] = []
_WORKER_POOL: "PersistentEngineWorkerPool | None" = None


class EngineTimeoutError(RuntimeError):
    """Raised when an engine exceeds its execution budget."""


class EngineStalledError(RuntimeError):
    """Raised when watchdog detects a stalled engine."""


def _ensure_report_dir() -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    return REPORT_DIR


def _ensure_audit_dir() -> None:
    audit_dir = os.path.dirname(ENGINE_WORKER_AUDIT_PATH)
    if audit_dir:
        os.makedirs(audit_dir, exist_ok=True)


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


def _kill_process_group(pid: int) -> None:
    if pid <= 0:
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        time.sleep(0.2)
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return


def _process_rss_mb(pid: int) -> float | None:
    try:
        import psutil

        return float(psutil.Process(pid).memory_info().rss) / (1024 * 1024)
    except Exception:
        pass
    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            return float(output) / 1024.0
    except Exception:
        return None
    return None


def _append_worker_audit(event: dict[str, Any]) -> None:
    _ensure_audit_dir()
    with open(ENGINE_WORKER_AUDIT_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def _worker_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_worker.py")


class PersistentEngineWorkerPool:
    """Manage one long-lived worker process for sequential engine execution."""

    def __init__(self, *, python: str, repo_cwd: str, worker_script: str | None = None) -> None:
        self.python = python
        self.repo_cwd = repo_cwd
        self.worker_script = worker_script or _worker_script_path()
        self._proc: subprocess.Popen[str] | None = None
        self._jobs_run = 0
        self._started_at = 0.0

    def _recycle_reason(self) -> str | None:
        if self._proc is None:
            return None
        if self._jobs_run >= ENGINE_WORKER_MAX_JOBS:
            return f"max_jobs_{ENGINE_WORKER_MAX_JOBS}"
        uptime = time.time() - self._started_at
        if uptime >= ENGINE_WORKER_MAX_UPTIME_SEC:
            return f"max_uptime_{ENGINE_WORKER_MAX_UPTIME_SEC}s"
        rss = _process_rss_mb(self._proc.pid)
        if rss is not None and rss > ENGINE_WORKER_MAX_RSS_MB:
            return f"max_rss_{rss:.0f}mb"
        if self._proc.poll() is not None:
            return "worker_exited"
        return None

    def recycle(self, reason: str) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                self._proc.stdin.flush()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_process_group(self._proc.pid)
            try:
                self._proc.wait(timeout=ENGINE_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_process(self._proc)
        self._proc = None
        self._jobs_run = 0
        self._started_at = 0.0
        _append_worker_audit(
            {
                "timestamp": datetime.now().isoformat(),
                "event": "worker_recycled",
                "recycled": True,
                "recycle_reason": reason,
            }
        )

    def ensure_worker(self) -> None:
        reason = self._recycle_reason()
        if reason:
            self.recycle(reason)
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [self.python, self.worker_script],
            cwd=self.repo_cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._started_at = time.time()
        self._jobs_run = 0

    def run(
        self,
        *,
        script_path: str,
        cwd: str,
        engine_name: str,
        timeout_seconds: int,
        cycle_id: int | None = None,
    ) -> int:
        recycled = False
        recycle_reason = ""
        pre_reason = self._recycle_reason()
        if pre_reason:
            recycled = True
            recycle_reason = pre_reason
            self.recycle(pre_reason)

        self.ensure_worker()
        assert self._proc is not None
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None

        started = time.time()
        _LAST_ENGINE_START[engine_name] = started
        request = {
            "script_path": script_path,
            "cwd": cwd,
            "engine_name": engine_name,
            "timeout_seconds": timeout_seconds,
            "cycle_id": cycle_id,
        }
        worker_pid = self._proc.pid
        status = "error"
        returncode: int | None = None
        error_text = ""
        elapsed_sec = 0.0

        try:
            self._proc.stdin.write(json.dumps(request) + "\n")
            self._proc.stdin.flush()
            deadline = time.time() + timeout_seconds + ENGINE_KILL_GRACE_SECONDS + 5
            response_line = ""
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    stderr = (self._proc.stderr.read() if self._proc.stderr else "") or ""
                    raise RuntimeError(
                        f"worker exited unexpectedly (code {self._proc.returncode}): {stderr[-300:]}"
                    )
                response_line = self._proc.stdout.readline()
                if not response_line:
                    time.sleep(0.05)
                    continue
                try:
                    json.loads(response_line)
                    break
                except json.JSONDecodeError:
                    response_line = ""
                    time.sleep(0.05)
            if not response_line:
                status = "timeout"
                error_text = f"ENGINE TIMEOUT: {engine_name} exceeded {timeout_seconds}s"
                _kill_process_group(self._proc.pid)
                self.recycle("engine_timeout")
                recycled = True
                recycle_reason = "engine_timeout"
                raise EngineTimeoutError(error_text)

            payload = json.loads(response_line)
            elapsed_sec = float(payload.get("elapsed_sec", round(time.time() - started, 2)))
            status = str(payload.get("status", "error"))
            returncode = payload.get("returncode")
            error_text = str(payload.get("error", ""))

            if status == "timeout":
                self.recycle("engine_timeout")
                recycled = True
                recycle_reason = "engine_timeout"
                raise EngineTimeoutError(error_text or f"ENGINE TIMEOUT: {engine_name}")
            if not payload.get("ok"):
                raise RuntimeError(error_text or f"ENGINE FAILED: {engine_name} (exit {returncode})")

            self._jobs_run += 1
            _append_blocking_event(
                {
                    "timestamp": datetime.now().isoformat(),
                    "engine": engine_name,
                    "event": "COMPLETED",
                    "duration_s": elapsed_sec,
                    "returncode": returncode,
                    "mode": "persistent_worker",
                }
            )
            return int(returncode or 0)
        except EngineTimeoutError:
            duration = round(time.time() - started, 2)
            event = {
                "timestamp": datetime.now().isoformat(),
                "engine": engine_name,
                "event": "TIMEOUT",
                "duration_s": duration,
                "timeout_s": timeout_seconds,
                "mode": "persistent_worker",
            }
            _append_blocking_event(event)
            _export_engine_hang_audit(engine_name, event)
            raise
        finally:
            worker_rss = _process_rss_mb(worker_pid) if worker_pid else None
            _append_worker_audit(
                {
                    "timestamp": datetime.now().isoformat(),
                    "cycle_id": cycle_id,
                    "engine": engine_name,
                    "mode": "persistent_worker",
                    "worker_pid": worker_pid,
                    "elapsed_sec": elapsed_sec or round(time.time() - started, 2),
                    "status": status,
                    "returncode": returncode,
                    "error": error_text,
                    "worker_rss_mb": worker_rss,
                    "recycled": recycled,
                    "recycle_reason": recycle_reason,
                }
            )
            post_reason = self._recycle_reason()
            if post_reason and post_reason != recycle_reason:
                self.recycle(post_reason)


def _get_worker_pool(python: str, repo_cwd: str) -> PersistentEngineWorkerPool:
    global _WORKER_POOL
    if _WORKER_POOL is None:
        _WORKER_POOL = PersistentEngineWorkerPool(python=python, repo_cwd=repo_cwd)
    return _WORKER_POOL


def reset_worker_pool_for_tests() -> None:
    global _WORKER_POOL
    if _WORKER_POOL is not None:
        _WORKER_POOL.recycle("test_reset")
    _WORKER_POOL = None


def _run_engine_subprocess_isolated(
    python: str,
    script_path: str,
    cwd: str,
    engine_name: str,
    timeout_seconds: int | None = None,
    *,
    cycle_id: int | None = None,
) -> int:
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
            "mode": "subprocess",
        }
        _append_blocking_event(event)
        _export_engine_hang_audit(engine_name, event)
        _append_worker_audit(
            {
                "timestamp": datetime.now().isoformat(),
                "cycle_id": cycle_id,
                "engine": engine_name,
                "mode": "subprocess",
                "worker_pid": proc.pid,
                "elapsed_sec": duration,
                "status": "timeout",
                "returncode": None,
                "error": f"ENGINE TIMEOUT: {engine_name} exceeded {timeout}s",
                "worker_rss_mb": _process_rss_mb(proc.pid),
                "recycled": False,
                "recycle_reason": "",
            }
        )
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
            "mode": "subprocess",
        }
    )
    _append_worker_audit(
        {
            "timestamp": datetime.now().isoformat(),
            "cycle_id": cycle_id,
            "engine": engine_name,
            "mode": "subprocess",
            "worker_pid": proc.pid,
            "elapsed_sec": duration,
            "status": "ok" if returncode == 0 else "error",
            "returncode": returncode,
            "error": "" if returncode == 0 else f"ENGINE FAILED: {engine_name} (exit {returncode})",
            "worker_rss_mb": _process_rss_mb(proc.pid),
            "recycled": False,
            "recycle_reason": "",
        }
    )

    if returncode != 0:
        raise RuntimeError(f"ENGINE FAILED: {engine_name} (exit {returncode})")

    return returncode


def run_engine_subprocess(
    python: str,
    script_path: str,
    cwd: str,
    engine_name: str,
    timeout_seconds: int | None = None,
    cycle_id: int | None = None,
) -> int:
    """Run engine script with hard timeout. Never blocks indefinitely."""

    mode = engine_execution_mode()
    if mode == "persistent_worker":
        return _get_worker_pool(python, cwd).run(
            script_path=script_path,
            cwd=cwd,
            engine_name=engine_name,
            timeout_seconds=timeout_seconds or ENGINE_TIMEOUT_SECONDS,
            cycle_id=cycle_id,
        )
    return _run_engine_subprocess_isolated(
        python,
        script_path,
        cwd,
        engine_name,
        timeout_seconds,
        cycle_id=cycle_id,
    )


# Raising from SIGALRM inside these frames deadlocks CPython (_sigtramp +
# pandas property_descr_set during DataFrame.__str__). Observed 2026-08-25:
# stage2_cognition_runtime_v1 hung the canonical pipeline for >50 minutes.
_UNSAFE_TIMEOUT_FRAME_NAMES = frozenset(
    {
        "__repr__",
        "__str__",
        "__format__",
        "__setattr__",
        "__delattr__",
        "__getattribute__",
        "__setitem__",
        "__set__",
        "write",
        "to_string",
        "_repr_html_",
    }
)
_TIMEOUT_RETRY_ALARM_S = 1


def _timeout_raise_is_unsafe(frame: Any) -> bool:
    """True if raising EngineTimeoutError here can deadlock the interpreter."""

    while frame is not None:
        code = getattr(frame, "f_code", None)
        if code is not None:
            if code.co_name in _UNSAFE_TIMEOUT_FRAME_NAMES:
                return True
            filename = (code.co_filename or "").replace("\\", "/")
            if "/pandas/" in filename or "site-packages/pandas" in filename:
                return True
        frame = getattr(frame, "f_back", None)
    return False


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

    pending_timeout = False

    def _raise_timeout() -> None:
        raise EngineTimeoutError(
            f"ENGINE TIMEOUT: {engine_name} exceeded {timeout}s"
        )

    def _handler(signum, frame):
        nonlocal pending_timeout
        pending_timeout = True
        if _timeout_raise_is_unsafe(frame):
            # Defer: raising during pandas repr/setattr wedges run.py so no
            # later engine (including candle_structure) can run.
            try:
                signal.alarm(_TIMEOUT_RETRY_ALARM_S)
            except Exception:
                pass
            return
        _raise_timeout()

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(max(1, int(timeout)))
    try:
        result = fn()
        if pending_timeout:
            _raise_timeout()
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
