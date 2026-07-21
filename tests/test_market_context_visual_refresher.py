"""Tests for Market Context Visual Auto-Refresh (Stage 12)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import run_market_context_visual_refresher as refresher  # noqa: E402


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    status = tmp_path / "status.json"
    log = tmp_path / "refresher.log"
    pid = tmp_path / "refresher.pid"
    lock = tmp_path / "refresher.lock"
    visual = tmp_path / "lifecycle_latest.json"
    monkeypatch.setattr(refresher, "STATUS_PATH", status)
    monkeypatch.setattr(refresher, "LOG_PATH", log)
    monkeypatch.setattr(refresher, "PID_PATH", pid)
    monkeypatch.setattr(refresher, "LOCK_PATH", lock)
    monkeypatch.setattr(refresher, "LIFECYCLE_LATEST", visual)
    monkeypatch.setattr(refresher, "read_latest_live_timestamp", lambda: "2026-07-13T05:45:00Z")
    return {
        "status": status,
        "log": log,
        "pid": pid,
        "lock": lock,
        "visual": visual,
        "tmp": tmp_path,
    }


def test_once_calls_builder_once(isolated):
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        isolated["visual"].write_text(
            json.dumps({"timestamp": "2026-07-13T05:45:00Z"}),
            encoding="utf-8",
        )
        return 0

    code = refresher.run_loop(
        interval_seconds=180,
        stale_threshold_minutes=30,
        once=True,
        builder=builder,
    )
    assert code == 0
    assert calls["n"] == 1
    payload = json.loads(isolated["status"].read_text(encoding="utf-8"))
    for field in refresher.REQUIRED_STATUS_FIELDS:
        assert field in payload
    assert payload["status"] == "PASS"
    assert payload["runs_success"] == 1
    assert payload["runs_total"] == 1
    assert payload["last_success_at"]
    assert payload["shadow_only"] is True


def test_builder_failure_records_fail_and_loop_continues(isolated):
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        isolated["visual"].write_text(
            json.dumps({"timestamp": "2026-07-13T05:40:00Z"}),
            encoding="utf-8",
        )
        return 0

    sleeps: list[float] = []

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)

    code = refresher.run_loop(
        interval_seconds=12,
        stale_threshold_minutes=30,
        once=False,
        builder=builder,
        sleep_fn=sleep_fn,
        max_iterations=2,
    )
    assert code == 0
    assert calls["n"] == 2
    assert sleeps == [12.0]
    payload = json.loads(isolated["status"].read_text(encoding="utf-8"))
    # Final iteration succeeded.
    assert payload["status"] in {"PASS", "RUNNING"}
    assert payload["runs_failed"] == 1
    assert payload["runs_success"] == 1
    assert payload["last_error"] is None or payload["status"] == "PASS"


def test_lock_prevents_overlapping_runs(isolated, monkeypatch):
    isolated["lock"].write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(refresher, "_pid_alive", lambda pid: pid == 1)

    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return 0

    code = refresher.run_loop(
        interval_seconds=180,
        stale_threshold_minutes=30,
        once=True,
        builder=builder,
    )
    assert code == 2
    assert calls["n"] == 0


def test_stale_calculation_boundary():
    lag, stale = refresher.compute_visual_stale(
        "2026-07-13T05:45:00Z",
        "2026-07-13T05:15:00Z",
        stale_threshold_minutes=30,
    )
    assert lag == 30.0
    assert stale is False  # boundary-safe: lag == threshold => not stale

    lag2, stale2 = refresher.compute_visual_stale(
        "2026-07-13T05:45:00Z",
        "2026-07-13T05:00:00Z",
        stale_threshold_minutes=30,
    )
    assert lag2 == 45.0
    assert stale2 is True


def test_success_updates_status_fields(isolated):
    isolated["visual"].write_text(
        json.dumps({"timestamp": "2026-07-13T05:30:00Z"}),
        encoding="utf-8",
    )

    def builder():
        isolated["visual"].write_text(
            json.dumps({"timestamp": "2026-07-13T05:45:00Z"}),
            encoding="utf-8",
        )
        return 0

    status = refresher.default_status(interval_seconds=180, stale_threshold_minutes=30)
    out = refresher.refresh_once(status, stale_threshold_minutes=30, builder=builder)
    assert out["status"] == "PASS"
    assert out["runs_success"] == 1
    assert out["last_success_at"]
    assert out["latest_visual_timestamp"] == "2026-07-13T05:45:00Z"
    assert out["latest_live_timestamp"] == "2026-07-13T05:45:00Z"
    assert out["visual_data_stale"] is False


def test_generated_gitignore_patterns():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "logs/",
        "runtime*.pid",
        "runtime_context_visual_refresher.pid",
        "runtime_context_visual_refresher.lock",
        "data/cognition/market_context_visual_refresher_status.json",
        "apps/context_visualizer/public/data/",
    ):
        assert pattern in text


def test_lifecycle_app_fetch_cache_bust():
    js = (
        ROOT
        / "apps"
        / "context_visualizer"
        / "public"
        / "lifecycle_app.js"
    ).read_text(encoding="utf-8")
    assert 'cache: "no-store"' in js
    assert "Date.now()" in js
    assert "cacheBust" in js
    assert "POLL_INTERVAL_MS" in js
    assert "VISUAL DATA STALE" in js
    assert "LIVE SNAPSHOT / AUTO-REFRESH" in js
    assert "lifecycle_latest.json" in js
