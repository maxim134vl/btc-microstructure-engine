"""Tests for manual live context refresh once-mode orchestrator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "live" / "run_live_context_refresh_once.py"

spec = importlib.util.spec_from_file_location("run_live_context_refresh_once", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["run_live_context_refresh_once"] = mod
spec.loader.exec_module(mod)


def _write_ts(path: Path, timestamps: list[str]) -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, utc=True),
            "close": [100.0 + i for i in range(len(timestamps))],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def test_lifecycle_is_stale_detection():
    live = pd.Timestamp("2026-07-19T13:00:00Z")
    life = pd.Timestamp("2026-07-19T12:30:00Z")
    assert mod.lifecycle_is_stale(live, life) is True
    assert mod.lifecycle_is_stale(live, live) is False
    assert mod.lag_seconds(live, life) == 1800.0


def test_refresh_runs_rebuild_when_stale(tmp_path: Path):
    live = tmp_path / "live.parquet"
    life = tmp_path / "life.parquet"
    _write_ts(live, ["2026-07-19T12:00:00Z", "2026-07-19T12:45:00Z"])
    _write_ts(life, ["2026-07-19T12:00:00Z", "2026-07-19T12:30:00Z"])
    status = tmp_path / "status.json"
    log = tmp_path / "refresh.log"
    calls: list[str] = []

    def fake_run(script: Path, **_kwargs):
        calls.append(Path(script).name)
        # Simulate rebuild catching up.
        if Path(script).name.startswith("build_market_context_shadow_chain"):
            _write_ts(life, ["2026-07-19T12:00:00Z", "2026-07-19T12:45:00Z"])
        return {
            "script": str(script),
            "returncode": 0,
            "ok": True,
            "started_at_utc": "2026-07-19T14:00:00Z",
            "ended_at_utc": "2026-07-19T14:00:01Z",
            "stdout_tail": "ok",
            "stderr_tail": "",
        }

    payload = mod.run_refresh_once(
        live_path=live,
        lifecycle_path=life,
        shadow_script=tmp_path / "build_market_context_shadow_chain.py",
        decision_script=tmp_path / "append_context_decision_log.py",
        status_path=status,
        log_path=log,
        run_script=fake_run,
    )
    assert payload["status"] == "OK"
    assert payload["shadow_chain_rebuild_ran"] is True
    assert payload["decision_logger_ran"] is True
    assert calls == ["build_market_context_shadow_chain.py", "append_context_decision_log.py"]
    assert status.exists()
    assert "START live_context_refresh_once" in log.read_text(encoding="utf-8")
    assert payload["execution_enabled"] is False
    assert payload["orders_created"] is False


def test_refresh_runs_decision_logger_when_shadow_chain_ok_after_visual_skip(tmp_path: Path):
    """Step 1 contract: shadow chain PASS (visual EROFS skipped) still appends decision log."""
    live = tmp_path / "live.parquet"
    life = tmp_path / "life.parquet"
    _write_ts(live, ["2026-07-19T12:00:00Z", "2026-07-19T12:45:00Z"])
    _write_ts(life, ["2026-07-19T12:00:00Z", "2026-07-19T12:30:00Z"])
    calls: list[str] = []

    def fake_run(script: Path, **_kwargs):
        calls.append(Path(script).name)
        if Path(script).name.startswith("build_market_context_shadow_chain"):
            _write_ts(life, ["2026-07-19T12:00:00Z", "2026-07-19T12:45:00Z"])
            return {
                "script": str(script),
                "returncode": 0,
                "ok": True,
                "started_at_utc": "2026-07-19T14:00:00Z",
                "ended_at_utc": "2026-07-19T14:00:01Z",
                "stdout_tail": "WARN skip display-only lifecycle_visual_data: visualizer output is read-only",
                "stderr_tail": "",
            }
        return {
            "script": str(script),
            "returncode": 0,
            "ok": True,
            "started_at_utc": "2026-07-19T14:00:00Z",
            "ended_at_utc": "2026-07-19T14:00:01Z",
            "stdout_tail": "ok",
            "stderr_tail": "",
        }

    payload = mod.run_refresh_once(
        live_path=live,
        lifecycle_path=life,
        shadow_script=tmp_path / "build_market_context_shadow_chain.py",
        decision_script=tmp_path / "append_context_decision_log.py",
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "refresh.log",
        run_script=fake_run,
    )
    assert payload["status"] == "OK"
    assert payload["shadow_chain_rebuild_ok"] is True
    assert payload["decision_logger_ran"] is True
    assert calls == ["build_market_context_shadow_chain.py", "append_context_decision_log.py"]
    assert payload["execution_enabled"] is False
    assert payload["orders_created"] is False


def test_refresh_skips_rebuild_when_fresh(tmp_path: Path):
    live = tmp_path / "live.parquet"
    life = tmp_path / "life.parquet"
    _write_ts(live, ["2026-07-19T12:45:00Z"])
    _write_ts(life, ["2026-07-19T12:45:00Z"])
    calls: list[str] = []

    def fake_run(script: Path, **_kwargs):
        calls.append(Path(script).name)
        return {
            "script": str(script),
            "returncode": 0,
            "ok": True,
            "started_at_utc": "2026-07-19T14:00:00Z",
            "ended_at_utc": "2026-07-19T14:00:01Z",
            "stdout_tail": "ok",
            "stderr_tail": "",
        }

    payload = mod.run_refresh_once(
        live_path=live,
        lifecycle_path=life,
        shadow_script=tmp_path / "build_market_context_shadow_chain.py",
        decision_script=tmp_path / "append_context_decision_log.py",
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "refresh.log",
        run_script=fake_run,
    )
    assert payload["status"] == "OK"
    assert payload["shadow_chain_rebuild_ran"] is False
    assert calls == ["append_context_decision_log.py"]


def test_refresh_errors_when_rebuild_fails(tmp_path: Path):
    live = tmp_path / "live.parquet"
    life = tmp_path / "life.parquet"
    _write_ts(live, ["2026-07-19T12:45:00Z"])
    _write_ts(life, ["2026-07-19T12:00:00Z"])

    def fake_run(script: Path, **_kwargs):
        name = Path(script).name
        if name.startswith("build_"):
            return {
                "script": str(script),
                "returncode": 1,
                "ok": False,
                "started_at_utc": "x",
                "ended_at_utc": "y",
                "stdout_tail": "",
                "stderr_tail": "boom",
            }
        return {
            "script": str(script),
            "returncode": 0,
            "ok": True,
            "started_at_utc": "x",
            "ended_at_utc": "y",
            "stdout_tail": "ok",
            "stderr_tail": "",
        }

    payload = mod.run_refresh_once(
        live_path=live,
        lifecycle_path=life,
        shadow_script=tmp_path / "build_market_context_shadow_chain.py",
        decision_script=tmp_path / "append_context_decision_log.py",
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "refresh.log",
        run_script=fake_run,
    )
    assert payload["status"] == "ERROR"
    assert "Shadow chain rebuild failed" in (payload.get("error") or "")
    assert payload["decision_logger_ran"] is False
    written = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert written["status"] == "ERROR"
    assert written["execution_enabled"] is False


def test_missing_live_feed_fails_safely(tmp_path: Path):
    with pytest.raises(mod.RefreshError, match="Missing required artifact"):
        mod.latest_parquet_timestamp(tmp_path / "missing.parquet")


def test_latest_lifecycle_timestamp_uses_m15_when_tagged(tmp_path: Path):
    path = tmp_path / "life.parquet"
    pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-01T15:45:00Z", "2026-07-01T12:00:00Z", "2026-07-01T16:00:00Z"],
                utc=True,
            ),
            "timeframe": ["M15", "H4", "H4"],
            "close": [1.0, 2.0, 3.0],
        }
    ).to_parquet(path, index=False)
    tip = mod.latest_parquet_timestamp(path)
    assert tip == pd.Timestamp("2026-07-01T15:45:00Z")


def test_script_is_shadow_only_and_does_not_start_servers():
    src = MODULE_PATH.read_text(encoding="utf-8")
    assert "execution_enabled" in src
    assert "Does NOT" in src or "does not enable execution" in src.lower()
    assert "runtime_stack" not in src.lower() or "runtime_stack_modified" in src
    assert "start_dashboard" not in src
    assert "visual server" in src.lower() or "visual_server_started" in src
    assert "orders_created" in src
