"""Runtime dependency guard — skip engines when dependency signatures are unchanged."""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime
from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet
from storage.path_registry import resolve_read, resolve_write

STATE_FILE_KEY = "runtime_dependency_state.parquet"
AUDIT_PATH = os.path.join("data", "runtime", "runtime_dependency_guard_audit.jsonl")
MIN_PARQUET_BYTES = 8


def _is_temp_dependency(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.endswith(".tmp")
        or ".parquet.tmp" in lowered
        or lowered.endswith(".part")
        or lowered.endswith(".lock")
    )


def _resolve_dependencies(dependency_files: list[str]) -> list[tuple[str, str]]:
    resolved: list[tuple[str, str]] = []
    for path in dependency_files:
        if _is_temp_dependency(path):
            continue
        resolved.append((path, resolve_read(path)))
    return resolved


def _ensure_audit_dir() -> None:
    audit_dir = os.path.dirname(AUDIT_PATH)
    if audit_dir:
        os.makedirs(audit_dir, exist_ok=True)


def _append_audit(
    *,
    engine: str,
    dependency: str,
    path: str,
    error: str,
) -> None:
    _ensure_audit_dir()
    event = {
        "timestamp": datetime.now().isoformat(),
        "engine": engine,
        "dependency": dependency,
        "path": path,
        "error": error,
        "action": "dependency_read_failed_fail_open",
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def _dependency_read_failed(
    engine_name: str,
    dependency: str,
    path: str,
    error: str,
) -> None:
    message = (
        f"runtime_dependency_guard: cannot read parquet for {engine_name} "
        f"({path}): {error}; forcing engine run"
    )
    warnings.warn(message, RuntimeWarning, stacklevel=2)
    _append_audit(engine=engine_name, dependency=dependency, path=path, error=error)


def _dependency_readable(
    engine_name: str,
    dependency: str,
    path: str,
) -> bool:
    if not os.path.exists(path):
        _dependency_read_failed(engine_name, dependency, path, "missing dependency parquet")
        return False
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        _dependency_read_failed(engine_name, dependency, path, str(exc))
        return False
    if size < MIN_PARQUET_BYTES:
        _dependency_read_failed(
            engine_name,
            dependency,
            path,
            f"parquet too small ({size} bytes)",
        )
        return False
    try:
        frame = safe_read_parquet(path)
    except Exception as exc:
        _dependency_read_failed(engine_name, dependency, path, str(exc))
        return False
    if frame.empty:
        _dependency_read_failed(engine_name, dependency, path, "empty or unreadable parquet")
        return False
    return True


def _dependency_signature(path: str) -> str:
    if not os.path.exists(path):
        return "MISSING"
    return str(os.path.getmtime(path))


def _read_state_file(state_file: str) -> pd.DataFrame:
    if not os.path.exists(state_file):
        return pd.DataFrame()
    try:
        if os.path.getsize(state_file) < MIN_PARQUET_BYTES:
            return pd.DataFrame()
    except OSError:
        return pd.DataFrame()
    return safe_read_parquet(state_file)


def _persist_state_row(state_file: str, engine_name: str, signature: str) -> None:
    row = pd.DataFrame(
        [
            {
                "engine": engine_name,
                "signature": signature,
            }
        ]
    )
    old = _read_state_file(state_file)
    if not old.empty and {"engine", "signature"}.issubset(old.columns):
        row = pd.concat([old, row], ignore_index=True)
    try:
        row.to_parquet(state_file, index=False)
    except Exception as exc:
        warnings.warn(
            f"runtime_dependency_guard: failed to persist state for {engine_name}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


def should_run_engine(engine_name: str, dependency_files: list[str]) -> bool:
    """Return True when the engine should run; never raise on unreadable dependency parquet."""

    current_state: dict[str, Any] = {}
    resolved_deps = _resolve_dependencies(dependency_files)

    for dependency, path in resolved_deps:
        if not _dependency_readable(engine_name, dependency, path):
            return True
        current_state[path] = _dependency_signature(path)

    current_signature = str(current_state)
    state_file = resolve_write(STATE_FILE_KEY)

    old = _read_state_file(state_file)
    if not old.empty and "engine" in old.columns and "signature" in old.columns:
        old_engine = old[old["engine"] == engine_name]
        if len(old_engine) > 0:
            previous_signature = str(old_engine.iloc[-1]["signature"])
            if previous_signature == current_signature:
                return False

    _persist_state_row(state_file, engine_name, current_signature)
    return True
