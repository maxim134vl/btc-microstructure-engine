"""Monotonic overrun-safe scheduler contract for context refresh daemon."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAEMON_PATH = ROOT / "scripts" / "live" / "run_context_refresh_daemon.py"

spec = importlib.util.spec_from_file_location("run_context_refresh_daemon_sched", DAEMON_PATH)
assert spec and spec.loader
daemon = importlib.util.module_from_spec(spec)
sys.modules["run_context_refresh_daemon_sched"] = daemon
spec.loader.exec_module(daemon)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)
        self.wait_calls: list[float] = []
        self.wall = 1_700_000_000.0  # unrelated wall clock

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.wall

    def advance(self, dt: float) -> None:
        self.t += float(dt)

    def wait(self, timeout: float) -> bool:
        assert timeout >= 0, f"negative wait timeout: {timeout}"
        self.wait_calls.append(float(timeout))
        self.t += float(timeout)
        return daemon._STOP_EVENT.is_set()


def test_01_cycle_shorter_than_interval_sleeps_remaining():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=100.0,
        now_mono=130.0,
        slot_deadline_mono=100.0,
        interval_s=60.0,
    )
    assert plan.sleep_seconds == pytest.approx(30.0)
    assert plan.missed_intervals == 0
    assert plan.overrun is False
    assert plan.cycle_duration_seconds == pytest.approx(30.0)


def test_02_cycle_exactly_equal_interval_no_negative_sleep():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=60.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    assert plan.sleep_seconds >= 0.0
    assert plan.sleep_seconds == pytest.approx(0.0)
    assert plan.missed_intervals == 0
    assert plan.next_deadline_mono == pytest.approx(60.0)


def test_03_cycle_longer_than_interval_does_not_raise():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=90.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    assert plan.sleep_seconds >= 0.0
    assert plan.overrun is True
    assert plan.missed_intervals >= 1


def test_04_one_missed_interval_schedules_next_future_deadline():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=75.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    # slot+interval=60 missed → jump to 120; sleep 45
    assert plan.next_deadline_mono == pytest.approx(120.0)
    assert plan.sleep_seconds == pytest.approx(45.0)
    assert plan.missed_intervals == 1


def test_05_several_missed_intervals_no_catch_up_storm():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=301.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    # next after slot is 60; behind by many → single jump to 360
    assert plan.missed_intervals == 5
    assert plan.next_deadline_mono == pytest.approx(360.0)
    assert plan.sleep_seconds == pytest.approx(59.0)
    # Plan is one sleep, not N catch-up cycles
    assert plan.missed_intervals == 5


def test_06_wall_clock_jump_does_not_affect_monotonic_scheduler():
    clock = FakeClock(1000.0)
    clock.wall += 3600.0  # wall jumps one hour
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=clock.monotonic(),
        now_mono=clock.monotonic() + 10.0,
        slot_deadline_mono=clock.monotonic(),
        interval_s=60.0,
    )
    assert plan.sleep_seconds == pytest.approx(50.0)
    # Scheduler helpers must not call time.time in source
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "end = time.time()" not in src
    assert "plan_schedule_wait" in src
    assert "time.monotonic" in src


def test_07_monotonic_clock_advancement_deterministic():
    clock = FakeClock(500.0)
    t0 = clock.monotonic()
    clock.advance(12.5)
    assert clock.monotonic() - t0 == pytest.approx(12.5)


def test_08_negative_sleep_never_passed_to_wait():
    sleeps: list[float] = []

    def track(timeout: float) -> bool:
        assert timeout >= 0
        sleeps.append(timeout)
        return True

    assert daemon.interruptible_wait(-1.0, wait_fn=track) is False
    assert sleeps == []
    assert daemon.interruptible_wait(0.0, wait_fn=track) is False
    assert sleeps == []
    daemon.interruptible_wait(0.25, wait_fn=track)
    assert sleeps == [0.25]

    for now in (59.999, 60.0, 60.001, 120.0, 1000.0):
        plan = daemon.plan_schedule_wait(
            cycle_started_mono=0.0,
            now_mono=now,
            slot_deadline_mono=0.0,
            interval_s=60.0,
        )
        assert plan.sleep_seconds >= 0.0


def test_09_overrun_warning_fields():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=10.0,
        now_mono=140.0,
        slot_deadline_mono=10.0,
        interval_s=60.0,
    )
    assert plan.overrun is True
    assert plan.cycle_duration_seconds == pytest.approx(130.0)
    assert plan.missed_intervals >= 1
    assert plan.configured_interval_seconds == 60.0
    assert "REFRESH_INTERVAL_OVERRUN" in DAEMON_PATH.read_text(encoding="utf-8")


def test_10_scheduler_does_not_busy_loop_after_overrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    clock = FakeClock(0.0)
    calls = {"n": 0}

    def slow_cycle(**kwargs):
        calls["n"] += 1
        clock.advance(90.0)  # > interval 60
        if calls["n"] >= 2:
            daemon._STOP = True
            daemon._STOP_EVENT.set()
        return {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]}

    monkeypatch.setattr(daemon, "run_cycle", slow_cycle)
    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    code = daemon.daemon_loop(
        interval_s=60.0,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=clock.wait,
    )
    assert code == 0
    assert calls["n"] == 2
    assert clock.wait_calls, "expected a positive wait after overrun"
    assert all(w >= 0 for w in clock.wait_calls)
    assert min(clock.wait_calls) > 0


def test_11_sigterm_interrupts_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    clock = FakeClock(0.0)
    calls = {"n": 0}

    def one_cycle(**kwargs):
        calls["n"] += 1
        clock.advance(1.0)
        return {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]}

    monkeypatch.setattr(daemon, "run_cycle", one_cycle)

    def wait_then_stop(timeout: float) -> bool:
        assert timeout > 0
        daemon._request_stop(15, None)
        return True

    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    code = daemon.daemon_loop(
        interval_s=30.0,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=wait_then_stop,
    )
    assert code == 0
    assert calls["n"] == 1
    assert daemon._STOP is True


def test_12_shutdown_during_wait_exits_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    clock = FakeClock(0.0)

    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: (
            clock.advance(0.5)
            or {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]}
        ),
    )

    def stop_wait(timeout: float) -> bool:
        daemon._STOP = True
        daemon._STOP_EVENT.set()
        return True

    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    code = daemon.daemon_loop(
        interval_s=10.0,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=stop_wait,
    )
    assert code == 0
    assert not (tmp_path / "l.lock").exists()
    assert not (tmp_path / "p.pid").exists()


def test_13_refresh_called_once_per_scheduled_iteration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    clock = FakeClock(0.0)
    calls = {"n": 0}

    def cycle(**kwargs):
        calls["n"] += 1
        clock.advance(5.0)
        if calls["n"] >= 3:
            daemon._STOP = True
            daemon._STOP_EVENT.set()
        return {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]}

    monkeypatch.setattr(daemon, "run_cycle", cycle)
    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    daemon.daemon_loop(
        interval_s=20.0,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=clock.wait,
    )
    assert calls["n"] == 3
    assert len(clock.wait_calls) == 2  # wait between 1→2 and 2→3; stop after 3


def test_14_once_behavior_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    calls = {"n": 0}
    clock = FakeClock(0.0)

    def cycle(**kwargs):
        calls["n"] += 1
        return {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]}

    monkeypatch.setattr(daemon, "run_cycle", cycle)
    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    code = daemon.daemon_loop(
        interval_s=60.0,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=clock.wait,
    )
    assert code == 0
    assert calls["n"] == 1
    assert clock.wait_calls == []


def test_15_refresh_output_schema_markers_unchanged():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    for token in (
        "REFRESH_SUCCESS",
        "NO_NEW_SAFE_UPSTREAM",
        "PIPELINE_PENDING",
        "CONTEXT_REFRESH_START",
        "hashes_unchanged",
        "added_rows",
    ):
        assert token in src
    assert "time.sleep(min(0.5, end - time.time()))" not in src


def test_16_plan_never_schedules_duplicate_catchup_cycles():
    # Many missed intervals → one next deadline, one sleep
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=1000.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    assert plan.missed_intervals == 16
    assert plan.next_deadline_mono == pytest.approx(1020.0)
    assert 0 <= plan.sleep_seconds < 60.0


def test_17_context_timestamp_helpers_still_utc_aware():
    ts = daemon._iso("2026-07-25T17:45:00Z")
    assert ts is not None
    assert ts.endswith("Z")


def test_18_natural_next_cycle_writes_once_semantics_via_once_flag(tmp_path, monkeypatch):
    # --once remains single-iteration write owner; scheduler does not multiply calls
    test_14_once_behavior_unchanged(tmp_path, monkeypatch)


def test_19_interruptible_wait_uses_stop_event():
    event = threading.Event()
    event.set()
    assert daemon.interruptible_wait(5.0, stop_event=event) is True


def test_20_other_runtime_pids_not_referenced_by_scheduler_patch():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "timeframe_manager_daemon" not in src
    assert "timeframe_trader_daemon" not in src
    assert "live_binance_intrabar_feed" not in src


def test_21_bounded_overrun_daemon_stays_alive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    clock = FakeClock(0.0)
    n = {"c": 0}

    def overrun_cycle(**kwargs):
        n["c"] += 1
        clock.advance(125.0)
        if n["c"] >= 2:
            daemon._STOP = True
            daemon._STOP_EVENT.set()
        return {"result": "REFRESH_SUCCESS", "cycle_id": kwargs["cycle_id"]}

    monkeypatch.setattr(daemon, "run_cycle", overrun_cycle)
    daemon._STOP = False
    daemon._STOP_EVENT.clear()
    code = daemon.daemon_loop(
        interval_s=60.0,
        foreground=True,
        once=False,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
        monotonic_fn=clock.monotonic,
        wait_fn=clock.wait,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "REFRESH_INTERVAL_OVERRUN" in out
    lines = [json.loads(ln) for ln in out.splitlines() if "REFRESH_INTERVAL_OVERRUN" in ln]
    assert lines
    assert "cycle_duration_seconds" in lines[0]
    assert "missed_intervals" in lines[0]
    assert n["c"] == 2


def test_22_exact_boundary_sleep_non_negative():
    plan = daemon.plan_schedule_wait(
        cycle_started_mono=0.0,
        now_mono=60.0,
        slot_deadline_mono=0.0,
        interval_s=60.0,
    )
    assert plan.sleep_seconds >= 0
    assert plan.next_deadline_mono == pytest.approx(60.0)
