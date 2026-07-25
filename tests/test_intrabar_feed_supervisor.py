#!/usr/bin/env python3
"""Tests for intrabar feed supervisor classification + recovery attempt."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "live" / "intrabar_feed_supervisor.py"

spec = importlib.util.spec_from_file_location("intrabar_feed_supervisor", MOD)
assert spec and spec.loader
sup = importlib.util.module_from_spec(spec)
sys.modules["intrabar_feed_supervisor"] = sup
spec.loader.exec_module(sup)


def test_supervisor_detects_stale_dead_feed(tmp_path: Path, monkeypatch):
    state = tmp_path / "supervisor.json"
    monkeypatch.setattr(sup, "STATE_PATH", state)
    monkeypatch.setattr(sup, "FEED_PID_PATH", tmp_path / "feed.pid")
    monkeypatch.setattr(sup, "HEARTBEAT_PATH", tmp_path / "hb.json")
    monkeypatch.setattr(sup, "FEED_PARQUET", tmp_path / "missing.parquet")
    monkeypatch.setattr(sup, "list_feed_pids", lambda: [])
    monkeypatch.setattr(sup, "_read_pid", lambda _p: 999999)
    monkeypatch.setattr(sup, "_pid_alive", lambda _p: False)
    monkeypatch.setattr(sup, "latest_row_age_seconds", lambda: 999.0)
    monkeypatch.setattr(sup, "_age_seconds", lambda _ts: 999.0)

    info = sup.classify_feed()
    assert info["feed_status"] in {"STOPPED", "STALE_PID"}
    assert info["needs_recovery"] is True
    assert info["duplicate_count"] == 0


def test_supervisor_attempts_recovery(tmp_path: Path, monkeypatch):
    state = tmp_path / "supervisor.json"
    monkeypatch.setattr(sup, "STATE_PATH", state)
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "sup.log")
    monkeypatch.setattr(sup, "classify_feed", lambda: {
        "feed_pid": None,
        "feed_status": "STOPPED",
        "heartbeat_age_seconds": 999,
        "latest_row_age_seconds": 999,
        "duplicate_count": 0,
        "orphan_count": 0,
        "live_pids": [],
        "needs_recovery": True,
        "recovery_reason": "feed_status=STOPPED,heartbeat_stale_or_missing",
    })

    called = {"n": 0}

    def _rec(reason: str):
        called["n"] += 1
        return {
            "recovery_attempted": True,
            "recovery_success": True,
            "recovery_reason": reason,
        }

    monkeypatch.setattr(sup, "attempt_recovery", _rec)
    out = sup.check_once(recover=True)
    assert called["n"] == 1
    assert out["recovery_attempted"] is True
    assert state.exists()


def test_duplicate_feed_processes_detected(monkeypatch):
    monkeypatch.setattr(sup, "list_feed_pids", lambda: [101, 102])
    monkeypatch.setattr(sup, "_read_pid", lambda _p: 101)
    monkeypatch.setattr(sup, "_pid_alive", lambda p: True)
    monkeypatch.setattr(sup, "latest_row_age_seconds", lambda: 10.0)
    monkeypatch.setattr(sup, "_load_json", lambda _p: {"heartbeat_at_utc": "2026-07-21T19:00:00Z"})
    monkeypatch.setattr(sup, "_age_seconds", lambda _ts: 10.0)
    info = sup.classify_feed()
    assert info["feed_status"] == "DUPLICATE_RUNNING"
    assert info["duplicate_count"] == 1
