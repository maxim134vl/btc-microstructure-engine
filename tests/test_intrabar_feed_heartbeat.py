#!/usr/bin/env python3
"""Tests for intrabar feed heartbeat + transient error resilience."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "live" / "live_binance_intrabar_feed.py"

spec = importlib.util.spec_from_file_location("live_binance_intrabar_feed", MOD)
assert spec and spec.loader
feed = importlib.util.module_from_spec(spec)
sys.modules["live_binance_intrabar_feed"] = feed
spec.loader.exec_module(feed)


def test_heartbeat_file_is_written(tmp_path: Path, monkeypatch):
    hb = tmp_path / "heartbeat.json"
    monkeypatch.setattr(feed, "HEARTBEAT_PATH", hb)
    feed.write_heartbeat(
        latest_observed_at_utc="2026-07-21T19:00:00Z",
        latest_price=65000.0,
        latest_m15_bucket_open_ts="2026-07-21T18:45:00Z",
        rows_written=3,
        consecutive_errors=0,
        last_error=None,
        last_success_at_utc="2026-07-21T19:00:00Z",
        feed_status="RUNNING",
    )
    assert hb.exists()
    payload = json.loads(hb.read_text(encoding="utf-8"))
    assert payload["feed_status"] == "RUNNING"
    assert payload["rows_written"] == 3
    assert "heartbeat_at_utc" in payload
    assert payload["source"] == "BINANCE_PUBLIC"


def test_transient_error_does_not_kill_loop(tmp_path: Path, monkeypatch):
    hb = tmp_path / "heartbeat.json"
    log = tmp_path / "feed.log"
    pid = tmp_path / "feed.pid"
    out = tmp_path / "out.parquet"
    status = tmp_path / "status.json"
    monkeypatch.setattr(feed, "HEARTBEAT_PATH", hb)
    monkeypatch.setattr(feed, "LOG_PATH", log)
    monkeypatch.setattr(feed, "PID_PATH", pid)
    monkeypatch.setattr(feed, "OUT_PATH", out)
    monkeypatch.setattr(feed, "STATUS_PATH", status)

    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient_rest_error")
        # Stop after success path writes heartbeat.
        feed._STOP = True
        return {
            "observed_at_utc": "2026-07-21T19:01:00.000000Z",
            "price": 65001.0,
            "bid": 65000.0,
            "ask": 65002.0,
            "m15_bucket_open_ts": "2026-07-21T18:45:00Z",
            "m15_bucket_close_ts": "2026-07-21T19:00:00Z",
            "symbol": "BTCUSDT",
            "source": "BINANCE_PUBLIC",
        }

    monkeypatch.setattr(feed, "fetch_snapshot", _fetch)
    monkeypatch.setattr(feed, "append_row", lambda row: 1)
    monkeypatch.setattr(feed, "write_status", lambda *a, **k: None)
    # Avoid sleeping full backoff.
    with mock.patch.object(feed.time, "sleep", return_value=None):
        feed._STOP = False
        rc = feed.run_loop(interval=1)
    assert rc == 0
    assert calls["n"] >= 1
    assert hb.exists()
    payload = json.loads(hb.read_text(encoding="utf-8"))
    # After success reset, or at least loop survived error.
    assert payload["feed_status"] in {"RUNNING", "STOPPED", "DEGRADED"}
    assert "consecutive_errors" in payload
