"""Tests for runtime dependency guard fail-open behavior."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def guard_env(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_dependency_state.parquet"
    audit_path = tmp_path / "runtime_dependency_guard_audit.jsonl"

    import storage.path_registry as path_registry

    monkeypatch.setattr(
        path_registry,
        "resolve_write",
        lambda key: str(state_path),
    )
    monkeypatch.setattr(
        path_registry,
        "resolve_read",
        lambda name: str(tmp_path / name),
    )

    import runtime_dependency_guard

    importlib.reload(runtime_dependency_guard)
    monkeypatch.setattr(runtime_dependency_guard, "AUDIT_PATH", str(audit_path))

    return tmp_path, state_path, audit_path, runtime_dependency_guard


def _write_valid_parquet(path: Path) -> None:
    pd.DataFrame({"timestamp": [1], "value": [1]}).to_parquet(path, index=False)
    os.utime(path, (1_700_000_000, 1_700_000_000))


def test_corrupt_four_byte_parquet_does_not_raise(guard_env) -> None:
    tmp_path, _state_path, audit_path, guard = guard_env
    corrupt = tmp_path / "candle_structure_memory.parquet"
    corrupt.write_bytes(b"bad!")

    result = guard.should_run_engine(
        "stage2_cognition_runtime_v1.py",
        ["candle_structure_memory.parquet"],
    )

    assert result is True
    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert audit_lines
    event = json.loads(audit_lines[-1])
    assert event["action"] == "dependency_read_failed_fail_open"
    assert event["engine"] == "stage2_cognition_runtime_v1.py"


def test_should_run_engine_returns_true_on_corrupt_dependency(guard_env) -> None:
    tmp_path, state_path, _audit_path, guard = guard_env
    dep = tmp_path / "runtime_cognition_memory.parquet"
    dep.write_bytes(b"x" * 4)

    first = guard.should_run_engine(
        "intermediate_cognition_engine_v1.py",
        ["runtime_cognition_memory.parquet"],
    )
    second = guard.should_run_engine(
        "intermediate_cognition_engine_v1.py",
        ["runtime_cognition_memory.parquet"],
    )

    assert first is True
    assert second is True
    assert not state_path.exists()


def test_normal_dependency_behavior_unchanged(guard_env) -> None:
    tmp_path, state_path, _audit_path, guard = guard_env
    dep = tmp_path / "candle_structure_memory.parquet"
    _write_valid_parquet(dep)

    first = guard.should_run_engine(
        "stage2_cognition_runtime_v1.py",
        ["candle_structure_memory.parquet"],
    )
    second = guard.should_run_engine(
        "stage2_cognition_runtime_v1.py",
        ["candle_structure_memory.parquet"],
    )

    assert first is True
    assert second is False
    assert state_path.exists()
    saved = pd.read_parquet(state_path)
    assert len(saved) >= 1
    assert str(saved.iloc[-1]["signature"]) == str({str(dep): str(1_700_000_000.0)})
