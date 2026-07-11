"""Tests for safe atomic parquet writes and fail-open runtime state updates."""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import parquet_utils
import runtime_state_manager


def test_atomic_parquet_write_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "nested" / "deep" / "state.parquet"
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    parquet_utils.atomic_parquet_write(df, str(target))

    assert target.exists()
    assert target.stat().st_size > 0
    loaded = pd.read_parquet(target)
    assert list(loaded["a"]) == [1, 2]


def test_atomic_parquet_write_uses_unique_temp_not_shared_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "state.parquet"
    seen: list[str] = []
    real_to_parquet = pd.DataFrame.to_parquet

    def tracking_to_parquet(self, path, *args, **kwargs):
        seen.append(str(path))
        return real_to_parquet(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", tracking_to_parquet)
    parquet_utils.atomic_parquet_write(pd.DataFrame({"v": [1]}), str(target))

    assert len(seen) == 1
    temp = Path(seen[0])
    assert temp.name.startswith(".state.parquet.tmp.")
    assert temp.name.endswith(".parquet")
    assert not str(temp).endswith("state.parquet.tmp")
    assert not (tmp_path / "state.parquet.tmp").exists()
    assert target.exists()


def test_two_rapid_writes_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "shared.parquet"
    errors: list[BaseException] = []

    def write_one(value: int) -> None:
        try:
            parquet_utils.atomic_parquet_write(
                pd.DataFrame({"value": [value], "thread": [threading.get_ident()]}),
                str(target),
            )
        except BaseException as exc:  # noqa: BLE001 — collect any collision failure
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_one, range(24)))

    assert errors == []
    assert target.exists()
    loaded = pd.read_parquet(target)
    assert "value" in loaded.columns
    assert len(loaded) == 1


def test_stale_unrelated_tmp_files_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "state.parquet"
    stale_shared = tmp_path / "state.parquet.tmp"
    stale_unique = tmp_path / ".state.parquet.tmp.999.1.deadbeef.parquet"
    stale_shared.write_bytes(b"stale-shared")
    stale_unique.write_bytes(b"stale-unique")

    parquet_utils.atomic_parquet_write(pd.DataFrame({"ok": [1]}), str(target))

    assert target.exists()
    assert pd.read_parquet(target)["ok"].tolist() == [1]
    assert stale_shared.exists()
    assert stale_shared.read_bytes() == b"stale-shared"
    assert stale_unique.exists()
    assert stale_unique.read_bytes() == b"stale-unique"


def test_failed_write_before_replace_leaves_existing_target(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "state.parquet"
    parquet_utils.atomic_parquet_write(pd.DataFrame({"ok": [1]}), str(target))
    original = target.read_bytes()

    def boom_replace(src, dst):
        raise FileNotFoundError(src)

    monkeypatch.setattr(parquet_utils.os, "replace", boom_replace)

    with pytest.raises(RuntimeError, match="atomic parquet replace failed"):
        parquet_utils.atomic_parquet_write(pd.DataFrame({"ok": [2]}), str(target))

    assert target.read_bytes() == original
    assert pd.read_parquet(target)["ok"].tolist() == [1]


def test_update_runtime_state_does_not_raise_on_replace_failure(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime_engine_state.parquet"
    monkeypatch.setattr(runtime_state_manager, "STATE_FILE", str(state_file))
    monkeypatch.chdir(tmp_path)

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("simulated missing tmp")

    monkeypatch.setattr(runtime_state_manager, "atomic_parquet_write", boom)

    # Must not raise even when the atomic write path fails hard.
    runtime_state_manager.update_runtime_state("engine_x.py", "FAILED", 1.23)

    audit = tmp_path / "reports" / "runtime_loop" / "runtime_state_write_failures.jsonl"
    assert audit.exists()
    assert "engine_x.py" in audit.read_text(encoding="utf-8")


def test_no_deterministic_shared_tmp_in_modules():
    parquet_src = (ROOT / "parquet_utils.py").read_text(encoding="utf-8")
    state_src = (ROOT / "runtime_state_manager.py").read_text(encoding="utf-8")
    assert 'resolved + ".tmp"' not in parquet_src
    assert 'STATE_FILE + ".tmp"' not in state_src
    assert ".tmp." in parquet_src  # unique token pattern
