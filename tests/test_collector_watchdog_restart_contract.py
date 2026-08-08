"""Patch 2A — collector watchdog restart contract (no live process kills)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

import collector_watchdog as cw
from collector_heartbeat import evaluate_heartbeat_timestamp


ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / "venv" / "bin" / "python"
CELLAR_PY = (
    "/opt/homebrew/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/"
    "Versions/3.11/Resources/Python.app/Contents/MacOS/Python"
)


def test_01_canonical_venv_selected():
    py = cw.resolve_canonical_python(str(ROOT))
    assert py.endswith("/venv/bin/python") or py.endswith("/venv/bin/python3")
    assert "/venv/" in py
    assert not cw._is_forbidden_interpreter(py, str(ROOT))


def test_02_bare_cellar_interpreter_rejected():
    assert cw._is_forbidden_interpreter(CELLAR_PY, str(ROOT)) is True
    assert cw._is_forbidden_interpreter("/usr/bin/python3", str(ROOT)) is True
    # venv path allowed even though it may resolve into Cellar
    if VENV_PY.exists():
        assert cw._is_forbidden_interpreter(str(VENV_PY), str(ROOT)) is False


def test_03_missing_websocket_dependency_blocks_start(tmp_path):
    script = tmp_path / "live_binance_feed_v2.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    fake_py = tmp_path / "venv" / "bin" / "python"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_py.chmod(0o755)

    with mock.patch.object(cw.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=1, stderr="No module named 'websocket'", stdout="")
        pre = cw.preflight_collector_launch(
            python=str(fake_py),
            root=str(tmp_path),
            script=str(script),
            require_websocket=True,
        )
    assert pre["ok"] is False
    assert any("websocket" in e for e in pre["errors"])


def test_04_zombie_child_classified_dead():
    with mock.patch.object(cw, "_pid_exists", return_value=True), mock.patch.object(
        cw, "_ps_stat_command", return_value=("Z", "<defunct>")
    ):
        assert cw.classify_process_state(12345, expected_script="live_binance_feed_v2.py") == "ZOMBIE"
        assert cw.process_is_live_feed(12345, expected_script="live_binance_feed_v2.py") is False


def test_05_stale_pid_pointing_at_other_process_rejected():
    with mock.patch.object(cw, "_pid_exists", return_value=True), mock.patch.object(
        cw, "_ps_stat_command", return_value=("Ss", "/usr/bin/python3 /tmp/other.py")
    ):
        assert (
            cw.classify_process_state(99, expected_script="live_binance_feed_v2.py")
            == "WRONG_COMMAND"
        )


def test_06_duplicate_feed_process_prevented(tmp_path):
    script = tmp_path / "live_binance_feed_v2.py"
    script.write_text("print(1)\n", encoding="utf-8")
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py.chmod(0o755)

    # Register a fake collector for this temp root by patching COLLECTORS lookup via start_collector spec
    with mock.patch.object(cw, "COLLECTORS", [{"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "kind": "websocket", "required": True}]), \
         mock.patch.object(cw, "preflight_collector_launch", return_value={"ok": True, "errors": []}), \
         mock.patch.object(cw, "list_matching_pids", side_effect=[[111, 222], [333]]), \
         mock.patch.object(cw, "stop_pid", return_value="MISSING") as stop, \
         mock.patch.object(cw.subprocess, "Popen") as popen, \
         mock.patch.object(cw, "write_heartbeat"):
        popen.return_value = mock.Mock(pid=333)
        new_pid = cw.start_collector("binance_live_feed", str(py), str(tmp_path))
    assert new_pid == 333
    assert stop.call_count == 2


def test_07_one_restart_produces_one_child(tmp_path):
    script = tmp_path / "live_binance_feed_v2.py"
    script.write_text("print(1)\n", encoding="utf-8")
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py.chmod(0o755)
    with mock.patch.object(cw, "COLLECTORS", [{"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "kind": "websocket", "required": True}]), \
         mock.patch.object(cw, "preflight_collector_launch", return_value={"ok": True, "errors": []}), \
         mock.patch.object(cw, "list_matching_pids", return_value=[]), \
         mock.patch.object(cw.subprocess, "Popen") as popen, \
         mock.patch.object(cw, "write_heartbeat"):
        popen.return_value = mock.Mock(pid=4242)
        pid = cw.start_collector("binance_live_feed", str(py), str(tmp_path))
    assert pid == 4242
    assert popen.call_count == 1


def test_08_restart_storm_blocked():
    state = {"collectors": {}}
    # Space attempts beyond backoff delays but inside the storm window.
    t = 1_000_000.0
    for _ in range(cw.RESTART_WINDOW_MAX_ATTEMPTS):
        allowed, reason, _ = cw.restart_allowed("binance_live_feed", state, now=t)
        assert allowed is True, reason
        cw.record_restart_attempt("binance_live_feed", state, now=t)
        t += cw.RESTART_MAX_DELAY_S + 1
    allowed, reason, _ = cw.restart_allowed("binance_live_feed", state, now=t)
    assert allowed is False
    assert reason == "RESTART_STORM_BLOCKED"


def test_09_missing_feed_entrypoint_blocked(tmp_path):
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py.chmod(0o755)
    pre = cw.preflight_collector_launch(
        python=str(py),
        root=str(tmp_path),
        script=str(tmp_path / "missing_feed.py"),
        require_websocket=False,
    )
    assert pre["ok"] is False
    assert any("entrypoint missing" in e for e in pre["errors"])


def test_10_valid_running_child_not_restarted():
    audit = {
        "collectors": [
            {
                "name": "binance_live_feed",
                "heartbeat_age_seconds": 5,
                "parquet": {"age_seconds": 10},
                "heartbeat": {"status": "CONNECTED", "event": "kline_tick"},
            }
        ]
    }
    with mock.patch.object(cw, "classify_process_state", return_value="RUNNING"):
        needs, reason = cw._collector_needs_restart(
            name="binance_live_feed",
            spec={"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "required": True},
            pid=1,
            audit=audit,
        )
    assert needs is False
    assert reason == "ok"


def test_11_sigterm_timeout_handled():
    killed = {"sigkill": False}

    def fake_kill(pid, sig):
        if sig == cw.signal.SIGKILL:
            killed["sigkill"] = True

    def fake_classify(pid, **kwargs):
        return "MISSING" if killed["sigkill"] else "RUNNING"

    clock = {"t": 0.0}

    def fake_time():
        return clock["t"]

    def fake_sleep(dt):
        clock["t"] += float(dt) + 10.0  # jump past timeout quickly

    with mock.patch.object(cw, "_pid_exists", return_value=True), \
         mock.patch.object(cw, "classify_process_state", side_effect=fake_classify), \
         mock.patch.object(cw.os, "kill", side_effect=fake_kill) as kill, \
         mock.patch.object(cw, "reap_child_processes", return_value=[]), \
         mock.patch.object(cw.time, "time", side_effect=fake_time), \
         mock.patch.object(cw.time, "sleep", side_effect=fake_sleep):
        final = cw.stop_pid(555, timeout_s=1.0)
    assert final == "MISSING"
    assert killed["sigkill"] is True
    assert kill.call_count >= 2


def test_12_metadata_failure_does_not_affect_restart(tmp_path):
    # write_heartbeat failure must not prevent start_collector returning pid
    script = tmp_path / "live_binance_feed_v2.py"
    script.write_text("print(1)\n", encoding="utf-8")
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py.chmod(0o755)

    def boom(*a, **k):
        raise RuntimeError("metadata/sidecar boom")

    with mock.patch.object(cw, "COLLECTORS", [{"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "kind": "websocket", "required": True}]), \
         mock.patch.object(cw, "preflight_collector_launch", return_value={"ok": True, "errors": []}), \
         mock.patch.object(cw, "list_matching_pids", return_value=[]), \
         mock.patch.object(cw.subprocess, "Popen") as popen, \
         mock.patch.object(cw, "write_heartbeat", side_effect=boom):
        popen.return_value = mock.Mock(pid=777)
        pid = cw.start_collector("binance_live_feed", str(py), str(tmp_path))
    assert pid == 777
    assert popen.call_count == 1


def test_13_watchdog_only_bounce_preserves_collector_architecture():
    # Architectural invariant: watchdog remains parent supervisor; feed is child script.
    feed = next(c for c in cw.COLLECTORS if c["name"] == "binance_live_feed")
    assert feed["script"] == "live_binance_feed_v2.py"
    assert feed.get("required") is True
    # resolve_canonical_python does not use sys.executable as authority
    with mock.patch.object(cw.sys, "executable", CELLAR_PY):
        py = cw.resolve_canonical_python(str(ROOT))
    assert "/venv/" in py


def test_14_utc_heartbeat_age_is_ten_seconds():
    result = evaluate_heartbeat_timestamp(
        "2026-08-08T11:59:50Z",
        now_utc=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert result["valid"] is True
    assert result["age_seconds"] == 10.0


def test_15_timezone_aware_plus_three_represents_same_instant():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    utc_result = evaluate_heartbeat_timestamp("2026-08-08T11:59:50Z", now_utc=now)
    plus_three = evaluate_heartbeat_timestamp("2026-08-08T14:59:50+03:00", now_utc=now)
    assert plus_three["valid"] is True
    assert plus_three["age_seconds"] == utc_result["age_seconds"] == 10.0


def test_16_two_second_future_clock_skew_is_tolerated():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    result = evaluate_heartbeat_timestamp(now + timedelta(seconds=2), now_utc=now)
    assert result["valid"] is True
    assert result["freshness_status"] == "clock_skew_tolerated"
    assert result["age_seconds"] == 0.0


def test_17_three_hour_future_timestamp_is_invalid_not_fresh():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    result = evaluate_heartbeat_timestamp(now + timedelta(hours=3), now_utc=now)
    assert result["valid"] is False
    assert result["freshness_status"] == "future_timestamp"
    assert result["age_seconds"] is None


def test_18_dead_pid_stale_parquet_future_heartbeat_requests_restart():
    audit = {
        "collectors": [
            {
                "name": "binance_live_feed",
                "heartbeat_age_seconds": None,
                "heartbeat_timestamp_valid": False,
                "heartbeat_timestamp_status": "future_timestamp",
                "parquet": {"age_seconds": 600},
                "heartbeat": {"status": "CONNECTED", "event": "kline_tick"},
            }
        ]
    }
    with mock.patch.object(cw, "classify_process_state", return_value="MISSING"):
        needs, reason = cw._collector_needs_restart(
            name="binance_live_feed",
            spec={"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "required": True},
            pid=7678,
            audit=audit,
        )
    assert needs is True
    assert reason == "process_missing"


def test_19_running_pid_with_fresh_valid_heartbeat_holds():
    audit = {
        "collectors": [
            {
                "name": "binance_live_feed",
                "heartbeat_age_seconds": 10,
                "heartbeat_timestamp_valid": True,
                "parquet": {"age_seconds": 600},
                "heartbeat": {"status": "CONNECTED", "event": "kline_tick"},
            }
        ]
    }
    with mock.patch.object(cw, "classify_process_state", return_value="RUNNING"):
        needs, reason = cw._collector_needs_restart(
            name="binance_live_feed",
            spec={"name": "binance_live_feed", "script": "live_binance_feed_v2.py", "required": True},
            pid=42,
            audit=audit,
        )
    assert needs is False
    assert reason == "ok"


def test_20_reset_is_scoped_and_restart_storm_protection_remains():
    now = 1_000_000.0
    state = {
        "collectors": {
            "binance_live_feed": {
                "attempts": [now] * cw.RESTART_WINDOW_MAX_ATTEMPTS,
                "blocked": True,
                "block_reason": "RESTART_STORM_BLOCKED",
            },
            "multi_exchange": {
                "attempts": [123.0],
                "blocked": True,
                "block_reason": "RESTART_STORM_BLOCKED",
            },
        }
    }
    other_before = dict(state["collectors"]["multi_exchange"])
    assert cw.reset_collector_restart_state("binance_live_feed", state) is True
    assert state["collectors"]["multi_exchange"] == other_before
    allowed, reason, _ = cw.restart_allowed("binance_live_feed", state, now=now)
    assert allowed is True
    assert reason == "OK"

    storm = {"collectors": {}}
    for _ in range(cw.RESTART_WINDOW_MAX_ATTEMPTS):
        allowed, reason, _ = cw.restart_allowed("binance_live_feed", storm, now=now)
        assert allowed is True, reason
        cw.record_restart_attempt("binance_live_feed", storm, now=now)
        now += cw.RESTART_MAX_DELAY_S + 1
    allowed, reason, _ = cw.restart_allowed("binance_live_feed", storm, now=now)
    assert allowed is False
    assert reason == "RESTART_STORM_BLOCKED"
