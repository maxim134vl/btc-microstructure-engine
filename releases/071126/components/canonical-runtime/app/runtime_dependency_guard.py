"""Runtime dependency guard — skip engines when dependency signatures are unchanged."""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet
from storage.path_registry import resolve_read, resolve_write

STATE_FILE_KEY = "runtime_dependency_state.parquet"
AUDIT_PATH = os.path.join("data", "runtime", "runtime_dependency_guard_audit.jsonl")
MIN_PARQUET_BYTES = 8
LAST_DECISIONS: dict[str, dict[str, Any]] = {}


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
        "dependency": dependency,
        "path": path,
        "error": error,
        "action": "dependency_read_failed_blocked",
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
        f"({path}): {error}; dependent engine blocked"
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


# R04: replay identity for Behavioral is input content, never a rewritten mtime.
# Every other engine retains its existing signature contract.
BEHAVIORAL_CONTENT_ENGINES = frozenset({
    "market_context_engine_v1.py", "behavioral_scoring_engine_v1.py",
    "event_relationship_engine_v1.py", "adaptive_behavioral_weights_v1.py",
    "behavioral_sequence_memory_v1.py", "behavioral_volume_observer_v1.py",
})


# R05 uses the same content identity for the five existing input producers.
STAGE2_INPUT_CONTENT_ENGINES = frozenset({
    "live_volume_flow_engine_v1.py", "liquidity_cluster_engine_v1.py",
    "flow_liquidity_interaction_engine_v3.py", "htf_structure_engine_v1.py",
    "htf_ltf_context_engine_v1.py",
})


# R06: content identity for the restored chain; no clock-only replays.
R06_CONTENT_ENGINES = frozenset(['volume_response_engine_v1.py', 'climactic_behavior_engine_v1.py', 'auction_convergence_engine_v1.py', 'auction_synthesis_engine_v1.py', 'stage2_cognition_runtime_v1.py', 'runtime_cognition_engine_v1.py', 'intermediate_cognition_engine_v1.py', 'auction_reinforcement_engine_v1.py', 'probabilistic_auction_engine_v1.py', 'auction_context_arbitration_engine_v1.py', 'auction_decay_engine_v1.py', 'state_transition_engine_v1.py', 'adaptive_meta_cognition_engine_v1.py'])


def _dependency_signature(path: str, *, engine_name: str | None = None) -> str:
    if not os.path.exists(path):
        return "MISSING"
    if engine_name in (BEHAVIORAL_CONTENT_ENGINES | STAGE2_INPUT_CONTENT_ENGINES | R06_CONTENT_ENGINES):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return "sha256:" + digest.hexdigest()
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
    """Run only with readable mandatory inputs; commit signatures after success."""

    LAST_DECISIONS[engine_name] = {"reason": "INPUT_CHANGED"}
    current_state: dict[str, Any] = {}
    resolved_deps = _resolve_dependencies(dependency_files)

    for dependency, path in resolved_deps:
        if not _dependency_readable(engine_name, dependency, path):
            LAST_DECISIONS[engine_name] = {"reason": "REQUIRED_INPUT_UNAVAILABLE", "dependency": dependency, "path": path}
            return False
        current_state[path] = _dependency_signature(path, engine_name=engine_name)

    if engine_name in (STAGE2_INPUT_CONTENT_ENGINES | R06_CONTENT_ENGINES):
        # Recompute after an actual producer repair without deleting history or
        # forging a changed market input. Other engines retain their contract.
        source = os.path.join(os.path.dirname(__file__), engine_name)
        current_state["__producer_source__"] = _dependency_signature(source, engine_name=engine_name)

    current_signature = str(current_state)
    state_file = resolve_write(STATE_FILE_KEY)

    old = _read_state_file(state_file)
    if not old.empty and "engine" in old.columns and "signature" in old.columns:
        old_engine = old[old["engine"] == engine_name]
        if len(old_engine) > 0:
            previous_signature = str(old_engine.iloc[-1]["signature"])
            if previous_signature == current_signature:
                LAST_DECISIONS[engine_name] = {"reason": "INPUT_UNCHANGED"}
                return False

    LAST_DECISIONS[engine_name]["signature"] = current_signature
    return True


def mark_engine_success(engine_name: str) -> None:
    """A failed attempt must not consume its input signature."""
    decision = LAST_DECISIONS.get(engine_name, {})
    if decision.get("signature") is not None:
        _persist_state_row(resolve_write(STATE_FILE_KEY), engine_name, decision["signature"])
