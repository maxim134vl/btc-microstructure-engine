"""Atomic handoff + retry-safe reads for candle_structure_memory parquet."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import parquet_utils

DAEMON_PATH = ROOT / "scripts" / "live" / "run_context_refresh_daemon.py"
spec = importlib.util.spec_from_file_location("ctx_refresh_atomic_test", DAEMON_PATH)
assert spec and spec.loader
daemon = importlib.util.module_from_spec(spec)
sys.modules["ctx_refresh_atomic_test"] = daemon
spec.loader.exec_module(daemon)


def _sample_ohlc(n: int = 5, start: str = "2026-07-01T00:00:00Z") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [10.0 + i for i in range(n)],
            "candle_type": ["body"] * n,
        }
    )


def test_01_writer_uses_temp_in_destination_dir_before_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    seen: list[str] = []
    real_to_parquet = pd.DataFrame.to_parquet

    def tracking_to_parquet(self, path, *args, **kwargs):
        seen.append(str(path))
        # Destination must not exist as a partial write target during to_parquet.
        assert not target.exists() or target.stat().st_size > 0
        return real_to_parquet(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", tracking_to_parquet)
    df = _sample_ohlc()
    parquet_utils.atomic_parquet_write(
        df, str(target), enforce_timestamp_integrity=True
    )

    assert len(seen) == 1
    temp = Path(seen[0])
    assert temp.parent == target.parent
    assert temp.name.startswith(".candle_structure_memory.parquet.tmp.")
    assert target.exists()
    assert not temp.exists()


def test_02_final_destination_replaced_via_os_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def tracking_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(parquet_utils.os, "replace", tracking_replace)
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(), str(target), enforce_timestamp_integrity=True
    )
    assert len(calls) == 1
    assert calls[0][1] == str(target)
    assert Path(calls[0][0]).parent == target.parent


def test_03_reader_never_sees_partial_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(3), str(target), enforce_timestamp_integrity=True
    )
    original = target.read_bytes()

    gate = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    real_replace = os.replace

    def slow_replace(src, dst):
        gate.set()
        release.wait(timeout=2)
        return real_replace(src, dst)

    monkeypatch.setattr(parquet_utils.os, "replace", slow_replace)

    def writer():
        try:
            parquet_utils.atomic_parquet_write(
                _sample_ohlc(4), str(target), enforce_timestamp_integrity=True
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=writer)
    t.start()
    assert gate.wait(timeout=2)
    # During rewrite pause, live destination must still be the previous valid bytes.
    assert target.read_bytes() == original
    pq.ParquetFile(target).read()
    release.set()
    t.join(timeout=5)
    assert errors == []
    assert len(pd.read_parquet(target)) == 4


def test_04_candidate_validated_before_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    order: list[str] = []
    real_validate = parquet_utils.validate_parquet_candidate
    real_replace = parquet_utils._replace_with_retry

    def tracking_validate(*args, **kwargs):
        order.append("validate")
        return real_validate(*args, **kwargs)

    def tracking_replace(*args, **kwargs):
        order.append("replace")
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(parquet_utils, "validate_parquet_candidate", tracking_validate)
    monkeypatch.setattr(parquet_utils, "_replace_with_retry", tracking_replace)
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(), str(target), enforce_timestamp_integrity=True
    )
    assert order == ["validate", "replace"]


def test_05_invalid_candidate_does_not_replace_live(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(2), str(target), enforce_timestamp_integrity=True
    )
    before = target.read_bytes()

    def bad_validate(*_a, **_k):
        raise parquet_utils.WriteCandidateValidationError(
            "WRITE_CANDIDATE_VALIDATION_FAILED forced"
        )

    monkeypatch.setattr(parquet_utils, "validate_parquet_candidate", bad_validate)
    with pytest.raises(parquet_utils.WriteCandidateValidationError):
        parquet_utils.atomic_parquet_write(
            _sample_ohlc(3), str(target), enforce_timestamp_integrity=True
        )
    assert target.read_bytes() == before
    assert len(pd.read_parquet(target)) == 2


def test_06_successful_write_preserves_schema_rows_values_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    df = _sample_ohlc(6)
    parquet_utils.atomic_parquet_write(df, str(target), enforce_timestamp_integrity=True)
    loaded = pd.read_parquet(target)
    assert list(loaded.columns) == list(df.columns)
    assert len(loaded) == len(df)
    pd.testing.assert_frame_equal(
        loaded.reset_index(drop=True),
        df.reset_index(drop=True),
        check_dtype=False,
    )
    series = pd.to_datetime(loaded["timestamp"], utc=True)
    assert bool(series.is_monotonic_increasing)
    assert int(series.duplicated().sum()) == 0


def test_07_normalized_data_equality_vs_direct_write(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    df = _sample_ohlc(8)
    direct = tmp_path / "direct.parquet"
    atomic = tmp_path / "atomic.parquet"
    df.to_parquet(direct, index=False)
    parquet_utils.atomic_parquet_write(df, str(atomic), enforce_timestamp_integrity=True)
    a = pd.read_parquet(direct).sort_values("timestamp").reset_index(drop=True)
    b = pd.read_parquet(atomic).sort_values("timestamp").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_08_transient_read_recovers_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    df = _sample_ohlc(3)
    parquet_utils.atomic_parquet_write(df, str(target), enforce_timestamp_integrity=True)

    calls = {"n": 0}
    real_read = pd.read_parquet

    def flaky_read(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("Invalid column metadata (corrupt file?)")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", flaky_read)
    monkeypatch.setattr(parquet_utils.time, "sleep", lambda *_a, **_k: None)
    out = parquet_utils.read_parquet_with_transient_retry(str(target))
    assert len(out) == 3
    assert calls["n"] == 2


def test_09_multiple_transient_failures_recover(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(2), str(target), enforce_timestamp_integrity=True
    )
    calls = {"n": 0}
    real_read = pd.read_parquet

    def flaky_read(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("Invalid column metadata (corrupt file?)")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", flaky_read)
    monkeypatch.setattr(parquet_utils.time, "sleep", lambda *_a, **_k: None)
    out = parquet_utils.read_parquet_with_transient_retry(str(target))
    assert len(out) == 2
    assert calls["n"] == 3


def test_10_permanent_failure_does_not_infinite_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "broken.parquet"
    target.write_bytes(b"NOT_PARQUET")
    calls = {"n": 0}
    real_read = pd.read_parquet

    def counting_read(path, *args, **kwargs):
        calls["n"] += 1
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", counting_read)
    monkeypatch.setattr(parquet_utils.time, "sleep", lambda *_a, **_k: None)
    with pytest.raises(Exception):
        parquet_utils.read_parquet_with_transient_retry(str(target), attempts=3)
    assert calls["n"] <= 3


def test_11_failed_read_cycle_does_not_write_context_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    final = tmp_path / "final.parquet"
    life = tmp_path / "life.parquet"
    decision = tmp_path / "decision.parquet"
    feed = tmp_path / "feed.parquet"
    candle = tmp_path / "candle.parquet"
    for path, col in (
        (feed, "timestamp"),
        (candle, "timestamp"),
        (final, "timestamp"),
        (life, "timestamp"),
        (decision, "candle_timestamp"),
    ):
        pd.DataFrame({col: pd.to_datetime(["2026-07-01T00:00:00Z"], utc=True)}).to_parquet(
            path, index=False
        )

    monkeypatch.setattr(daemon, "FINAL_PATH", final)
    monkeypatch.setattr(daemon, "LIFECYCLE_PATH", life)
    monkeypatch.setattr(daemon, "DECISION_PATH", decision)
    monkeypatch.setattr(daemon, "LIVE_FEED", feed)
    monkeypatch.setattr(daemon, "CANDLE_PATH", candle)

    before = {
        "final": final.read_bytes(),
        "life": life.read_bytes(),
        "decision": decision.read_bytes(),
    }

    def boom(*_a, **_k):
        raise daemon.UpstreamParquetTemporarilyUnreadable("forced unreadability")

    monkeypatch.setattr(daemon, "read_tips", boom)
    called = {"refresh": 0}
    monkeypatch.setattr(
        daemon,
        "run_refresh_once",
        lambda **_k: called.__setitem__("refresh", called["refresh"] + 1) or {"status": "OK"},
    )

    payload = daemon.run_cycle(
        cycle_id="t-1",
        dry_run=False,
        status_path=tmp_path / "status.json",
    )
    assert payload["result"] == "UPSTREAM_PARQUET_TEMPORARILY_UNREADABLE"
    assert called["refresh"] == 0
    assert final.read_bytes() == before["final"]
    assert life.read_bytes() == before["life"]
    assert decision.read_bytes() == before["decision"]


def test_12_permanent_failure_does_not_kill_daemon_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    sleeps: list[float] = []

    def fake_run_cycle(**kwargs):
        raise daemon.UpstreamParquetTemporarilyUnreadable("still racing")

    monkeypatch.setattr(daemon, "run_cycle", fake_run_cycle)
    code = daemon.daemon_loop(
        interval_s=0.05,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        wait_fn=lambda s: sleeps.append(s) or False,
    )
    assert code == 0
    assert not (tmp_path / "p.pid").exists()


def test_13_next_healthy_cycle_works_after_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    results = [
        {"result": "UPSTREAM_PARQUET_TEMPORARILY_UNREADABLE", "cycle_id": "1"},
        {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": "2"},
    ]
    state = {"i": 0}

    def sequenced(**kwargs):
        idx = state["i"]
        state["i"] += 1
        payload = results[min(idx, len(results) - 1)]
        if state["i"] >= 2:
            daemon._STOP = True
        return payload

    monkeypatch.setattr(daemon, "run_cycle", sequenced)

    code = daemon.daemon_loop(
        interval_s=0.01,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        wait_fn=lambda _s: False,
    )
    assert code == 0
    assert state["i"] >= 2


def test_14_scheduler_not_busy_loop_on_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    sleeps: list[float] = []

    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: {
            "result": "UPSTREAM_PARQUET_TEMPORARILY_UNREADABLE",
            "cycle_id": kwargs["cycle_id"],
        },
    )

    def wait_fn(seconds):
        sleeps.append(float(seconds))
        if len(sleeps) >= 2:
            daemon._STOP = True
            return True
        return False

    code = daemon.daemon_loop(
        interval_s=0.2,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        wait_fn=wait_fn,
    )
    assert code == 0
    assert any(s >= 0.05 for s in sleeps)


def test_15_concurrent_writer_reader_stress(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "candle_structure_memory.parquet"
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(10), str(target), enforce_timestamp_integrity=True
    )

    errors: list[str] = []
    writes = {"n": 0}
    reads = {"n": 0}

    def writer():
        i = 0
        while writes["n"] < 50:
            i += 1
            try:
                parquet_utils.atomic_parquet_write(
                    _sample_ohlc(10 + (i % 3)),
                    str(target),
                    enforce_timestamp_integrity=True,
                )
                writes["n"] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"write:{exc}")
                break

    def reader():
        while reads["n"] < 500:
            try:
                pf = pq.ParquetFile(target)
                table = pf.read()
                _ = pf.schema_arrow
                n = table.num_rows
                if n <= 0:
                    errors.append("row-count-zero")
                    break
                reads["n"] += 1
            except Exception as exc:  # noqa: BLE001
                # Atomic replace must make this impossible; surface for acceptance gate.
                errors.append(f"read:{type(exc).__name__}:{exc}")
                break

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start()
    tr.start()
    tw.join(timeout=60)
    tr.join(timeout=60)

    assert writes["n"] >= 50, writes
    assert reads["n"] >= 500, reads
    assert errors == []


def test_16_candle_engine_uses_atomic_helper():
    src = (ROOT / "candle_structure_engine_v1.py").read_text(encoding="utf-8")
    assert "atomic_parquet_write" in src
    assert "ohlc.to_parquet(" not in src
    assert "enforce_timestamp_integrity=True" in src


def test_17_trading_files_untouched_by_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    trade = tmp_path / "trades.parquet"
    trade.write_bytes(b"ledger-bytes")
    before = trade.read_bytes()
    target = tmp_path / "candle_structure_memory.parquet"
    parquet_utils.atomic_parquet_write(
        _sample_ohlc(2), str(target), enforce_timestamp_integrity=True
    )
    assert trade.read_bytes() == before
