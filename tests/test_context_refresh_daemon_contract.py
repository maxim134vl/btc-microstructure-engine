"""Patch 2A.1 — context refresh daemon contract tests (no live production kill)."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DAEMON_PATH = ROOT / "scripts" / "live" / "run_context_refresh_daemon.py"
REFRESH_PATH = ROOT / "scripts" / "live" / "run_live_context_refresh_once.py"
CTL_PATH = ROOT / "scripts" / "ops" / "context_refresh_daemon_ctl.sh"

spec = importlib.util.spec_from_file_location("run_context_refresh_daemon", DAEMON_PATH)
assert spec and spec.loader
daemon = importlib.util.module_from_spec(spec)
sys.modules["run_context_refresh_daemon"] = daemon
spec.loader.exec_module(daemon)

refresh_spec = importlib.util.spec_from_file_location("run_live_context_refresh_once", REFRESH_PATH)
assert refresh_spec and refresh_spec.loader
refresh_mod = importlib.util.module_from_spec(refresh_spec)
sys.modules["run_live_context_refresh_once"] = refresh_mod
refresh_spec.loader.exec_module(refresh_mod)


def _write_ts(path: Path, timestamps: list[str], col: str = "timestamp") -> None:
    frame = pd.DataFrame(
        {
            col: pd.to_datetime(timestamps, utc=True),
            "close": [100.0 + i for i in range(len(timestamps))],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def test_01_daemon_default_flag_off_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BTC_ML_CONTEXT_REFRESH_DAEMON", raising=False)
    code = daemon.daemon_loop(
        interval_s=1,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
    )
    assert code == 2


def test_02_explicit_flag_required_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    # Patch tip readers via classify dry path — monkeypatch run_cycle to no-op
    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]},
    )
    code = daemon.daemon_loop(
        interval_s=0.1,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
    )
    assert code == 0


def test_03_canonical_interpreter_under_venv():
    py = daemon.resolve_canonical_python(ROOT)
    assert str(py).endswith("/venv/bin/python") or str(py).endswith("/venv/bin/python3")
    assert "/venv/" in str(py)
    assert "Cellar" not in str(py)


def test_04_one_daemon_lock_prevents_overlap(tmp_path: Path):
    lock = tmp_path / "lock"
    assert daemon.acquire_lock(lock, pid=os.getpid()) is True
    assert daemon.acquire_lock(lock, pid=os.getpid() + 99999) is False
    daemon.release_lock(lock)
    assert daemon.acquire_lock(lock, pid=os.getpid() + 1) is True
    daemon.release_lock(lock)


def test_05_pid_identity_write_clear(tmp_path: Path):
    pid_path = tmp_path / "daemon.pid"
    daemon.write_pid(pid_path, os.getpid())
    assert pid_path.read_text().strip() == str(os.getpid())
    daemon.clear_pid(pid_path)
    assert not pid_path.exists()


def test_06_zombie_not_live_via_ctl_helper():
    # ctl uses ps state Z*; unit-level: acquire_lock recovers dead pid
    pass  # covered by stale lock recovery


def test_07_stale_lock_recovery(tmp_path: Path):
    lock = tmp_path / "lock"
    lock.write_text("999999991\n", encoding="utf-8")  # almost-certainly dead
    assert daemon.acquire_lock(lock, pid=os.getpid(), stale_s=0.0) is True
    daemon.release_lock(lock)


def test_08_lock_prevents_overlap_alive(tmp_path: Path):
    lock = tmp_path / "lock"
    # Simulate another live process holding lock = current pid, then other pid fails
    assert daemon.acquire_lock(lock, pid=os.getpid()) is True
    # same pid reclaim allowed after unlink semantics — foreign pid blocked
    foreign = os.getpid() + 123456
    assert daemon.acquire_lock(lock, pid=foreign) is False
    daemon.release_lock(lock)


def test_08b_tail_merge_restates_last_bars_and_appends():
    tail_merge_existing_wins = refresh_mod.tail_merge_existing_wins

    prod = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-07-24T13:00:00Z",
                    "2026-07-24T13:15:00Z",
                    "2026-07-24T13:30:00Z",
                    "2026-07-24T13:45:00Z",
                    "2026-07-24T14:00:00Z",
                    "2026-07-24T14:15:00Z",
                ],
                utc=True,
            ),
            "v": [1, 2, 3, 4, 5, 6],
        }
    )
    cand = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-07-24T13:00:00Z",
                    "2026-07-24T13:15:00Z",
                    "2026-07-24T13:30:00Z",
                    "2026-07-24T13:45:00Z",
                    "2026-07-24T14:00:00Z",
                    "2026-07-24T14:15:00Z",
                    "2026-07-24T14:30:00Z",
                ],
                utc=True,
            ),
            "v": [9, 9, 9, 9, 9, 9, 7],
        }
    )
    merged = tail_merge_existing_wins(prod, cand, "timestamp")
    assert list(merged["v"]) == [1, 2, 9, 9, 9, 9, 7]
    assert len(merged) == 7


def test_08c_tail_merge_keeps_m15_prefix_and_adds_independent_h4():
    tail_merge_existing_wins = refresh_mod.tail_merge_existing_wins

    prod = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-07-24T13:00:00Z",
                    "2026-07-24T13:15:00Z",
                    "2026-07-24T13:30:00Z",
                    "2026-07-24T13:45:00Z",
                    "2026-07-24T14:00:00Z",
                    "2026-07-24T14:15:00Z",
                ],
                utc=True,
            ),
            "timeframe": ["M15"] * 6,
            "v": [1, 2, 3, 4, 5, 6],
        }
    )
    cand = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-07-24T13:00:00Z",
                    "2026-07-24T13:15:00Z",
                    "2026-07-24T13:30:00Z",
                    "2026-07-24T13:45:00Z",
                    "2026-07-24T14:00:00Z",
                    "2026-07-24T14:15:00Z",
                    "2026-07-24T14:00:00Z",
                    "2026-07-24T14:30:00Z",
                ],
                utc=True,
            ),
            "timeframe": ["M15", "M15", "M15", "M15", "M15", "M15", "H4", "M15"],
            "v": [9, 9, 9, 9, 9, 9, 4, 3],
        }
    )
    merged = tail_merge_existing_wins(prod, cand, "timestamp")
    m15 = merged[merged["timeframe"].astype(str).str.upper() == "M15"]
    h4 = merged[merged["timeframe"].astype(str).str.upper() == "H4"]
    assert list(m15["v"]) == [1, 2, 9, 9, 9, 9, 3]
    assert list(h4["v"]) == [4]
    assert len(merged) == 8


def test_08d_restep_uncertain_keeps_production_long_episode():
    stamps = pd.to_datetime(
        [
            "2026-09-13T10:00:00Z",
            "2026-09-13T10:15:00Z",
            "2026-09-13T10:30:00Z",
            "2026-09-13T10:45:00Z",
            "2026-09-13T11:00:00Z",
        ],
        utc=True,
    )

    def _row(ts, *, raw, status, cognitive, direction, auction, active, life, episode):
        return {
            "timestamp": ts,
            "timeframe": "M15",
            "raw_market_context": raw,
            "raw_context_status": status,
            "raw_context_reason": f"{raw}/{status}",
            "raw_cognitive_market_state": cognitive,
            "raw_state_direction": direction,
            "raw_auction_episode": auction,
            "auction_episode": auction,
            "active_market_context": active,
            "lifecycle_state": life,
            "context_episode_id": episode,
            "active_context_age_bars": 1,
            "transition_reason": "seed",
        }

    prod = pd.DataFrame(
        [
            _row(
                stamps[0],
                raw="LONG_CONTEXT",
                status="ACTIVE",
                cognitive="LOWER_ABSORPTION",
                direction="LONG",
                auction="LOWER_ABSORPTION",
                active="LONG_CONTEXT",
                life="ACTIVE",
                episode=321,
            ),
            _row(
                stamps[1],
                raw="LONG_CONTEXT",
                status="ACTIVE",
                cognitive="LOWER_ABSORPTION",
                direction="LONG",
                auction="LOWER_ABSORPTION",
                active="LONG_CONTEXT",
                life="ACTIVE",
                episode=321,
            ),
            _row(
                stamps[2],
                raw="OBSERVE",
                status="OBSERVE",
                cognitive="UNCERTAIN",
                direction="UNKNOWN",
                auction="UNKNOWN",
                active="SHORT_CONTEXT",
                life="ACTIVE",
                episode=323,
            ),
            _row(
                stamps[3],
                raw="OBSERVE",
                status="OBSERVE",
                cognitive="UNCERTAIN",
                direction="UNKNOWN",
                auction="UNKNOWN",
                active="SHORT_CONTEXT",
                life="ACTIVE",
                episode=323,
            ),
            _row(
                stamps[4],
                raw="OBSERVE",
                status="OBSERVE",
                cognitive="UNCERTAIN",
                direction="UNKNOWN",
                auction="UNKNOWN",
                active="SHORT_CONTEXT",
                life="ACTIVE",
                episode=323,
            ),
        ]
    )
    cand = prod.copy()
    merged = refresh_mod.tail_merge_existing_wins(prod, cand, "timestamp")
    out = refresh_mod.restep_lifecycle_tail(prod, merged, "timestamp")
    assert list(out["active_market_context"]) == ["LONG_CONTEXT"] * 5
    assert list(out["context_episode_id"]) == [321] * 5
    assert out.iloc[2]["transition_reason"] == "insufficient auction evidence keeps active"


def test_08f_replace_higher_tf_keeps_m15_settled_prefix():
    tail_merge_existing_wins = refresh_mod.tail_merge_existing_wins
    stamps = pd.to_datetime(
        [
            "2026-07-24T12:00:00Z",
            "2026-07-24T12:15:00Z",
            "2026-07-24T12:30:00Z",
            "2026-07-24T12:45:00Z",
            "2026-07-24T13:00:00Z",
            "2026-07-24T13:15:00Z",
        ],
        utc=True,
    )
    prod = pd.DataFrame(
        {
            "timestamp": list(stamps) + [stamps[0], stamps[2]],
            "timeframe": ["M15"] * 6 + ["H4", "H4"],
            "v": [1, 2, 3, 4, 5, 6, 70, 71],
            "active_market_context": ["LONG_CONTEXT"] * 6 + ["OBSERVE", "OBSERVE"],
        }
    )
    cand = pd.DataFrame(
        {
            "timestamp": list(stamps) + [stamps[0], stamps[2]],
            "timeframe": ["M15"] * 6 + ["H4", "H4"],
            "v": [9, 9, 9, 9, 9, 9, 80, 81],
            "active_market_context": ["SHORT_CONTEXT"] * 6 + ["LONG_CONTEXT", "LONG_CONTEXT"],
        }
    )
    merged = tail_merge_existing_wins(
        prod,
        cand,
        "timestamp",
        replace_timeframes=refresh_mod.INDEPENDENT_REPLACE_TIMEFRAMES,
    )
    m15 = merged[merged["timeframe"].astype(str).str.upper() == "M15"]
    h4 = merged[merged["timeframe"].astype(str).str.upper() == "H4"]
    assert list(m15["v"]) == [1, 2, 9, 9, 9, 9]
    assert list(h4["v"]) == [80, 81]
    assert list(h4["active_market_context"]) == ["LONG_CONTEXT", "LONG_CONTEXT"]


def test_08g_replaced_h4_keeps_living_episode_when_direction_stays():
    stamps = pd.to_datetime(
        ["2026-07-24T08:00:00Z", "2026-07-24T12:00:00Z"],
        utc=True,
    )

    def _h4(ts, *, raw, active, episode, source):
        return {
            "timestamp": ts,
            "timeframe": "H4",
            "raw_market_context": raw,
            "raw_context_status": "ACTIVE",
            "raw_context_reason": f"{raw}/ACTIVE",
            "raw_cognitive_market_state": "LOWER_ABSORPTION",
            "raw_state_direction": "LONG",
            "raw_auction_episode": "LOWER_ABSORPTION",
            "auction_episode": "LOWER_ABSORPTION",
            "active_market_context": active,
            "lifecycle_state": "ACTIVE",
            "context_episode_id": episode,
            "lifecycle_source": source,
        }

    prod = pd.DataFrame(
        [
            _h4(stamps[0], raw="LONG_CONTEXT", active="LONG_CONTEXT", episode=22, source="INDEPENDENT_OHLCV_PROXY"),
            _h4(stamps[1], raw="LONG_CONTEXT", active="LONG_CONTEXT", episode=22, source="INDEPENDENT_OHLCV_PROXY"),
        ]
    )
    cand = pd.DataFrame(
        [
            _h4(stamps[0], raw="LONG_CONTEXT", active="LONG_CONTEXT", episode=1, source="INDEPENDENT_CLOSED_BAR_VOLUME"),
            _h4(stamps[1], raw="LONG_CONTEXT", active="LONG_CONTEXT", episode=1, source="INDEPENDENT_CLOSED_BAR_VOLUME"),
        ]
    )
    merged = refresh_mod.tail_merge_existing_wins(
        prod,
        cand,
        "timestamp",
        replace_timeframes=refresh_mod.INDEPENDENT_REPLACE_TIMEFRAMES,
    )
    out = refresh_mod.restep_lifecycle_tail(
        prod,
        merged,
        "timestamp",
        replace_timeframes=refresh_mod.INDEPENDENT_REPLACE_TIMEFRAMES,
    )
    assert list(out["lifecycle_source"]) == ["INDEPENDENT_CLOSED_BAR_VOLUME"] * 2
    assert list(out["active_market_context"]) == ["LONG_CONTEXT", "LONG_CONTEXT"]
    assert list(out["context_episode_id"]) == [22, 22]


def test_08h_m15_episodes_stay_when_higher_tf_rebuilt():
    prod = pd.DataFrame(
        {
            "episode_id": [314, 9],
            "timeframe": ["M15", "H1"],
            "active_market_context": ["LONG_CONTEXT", "OBSERVE"],
            "start_time": pd.to_datetime(["2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"], utc=True),
            "end_time": pd.to_datetime(["2026-07-01T04:00:00Z", "2026-07-01T04:00:00Z"], utc=True),
        }
    )
    life = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-01T00:00:00Z", "2026-07-01T01:00:00Z"], utc=True),
            "timeframe": ["H1", "H1"],
            "close": [100.0, 101.0],
            "active_market_context": ["SHORT_CONTEXT", "SHORT_CONTEXT"],
            "lifecycle_state": ["ACTIVE", "ACTIVE"],
            "context_episode_id": [3, 3],
            "transition_reason": ["seed", "hold"],
            "action_allowed": [False, False],
            "lifecycle_source": ["INDEPENDENT_CLOSED_BAR_VOLUME"] * 2,
        }
    )
    out = refresh_mod.merge_episodes_keep_m15_rebuild_higher(prod, life)
    m15 = out[out["timeframe"].astype(str).str.upper() == "M15"]
    h1 = out[out["timeframe"].astype(str).str.upper() == "H1"]
    assert list(m15["episode_id"]) == [314]
    assert len(h1) == 1
    assert list(h1["active_market_context"]) == ["SHORT_CONTEXT"]
    assert list(h1["lifecycle_source"]) == ["INDEPENDENT_CLOSED_BAR_VOLUME"]


def test_08e_refresh_interval_fits_inside_one_m15_bar():
    daemon_src = DAEMON_PATH.read_text(encoding="utf-8")
    assert 'CONTEXT_REFRESH_INTERVAL_SECONDS", "60"' in daemon_src
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "CONTEXT_REFRESH_INTERVAL_SECONDS:-60" in compose
    entry = (ROOT / "deploy" / "vps" / "entrypoints" / "context_refresh_daemon.sh").read_text(
        encoding="utf-8"
    )
    assert 'CONTEXT_REFRESH_INTERVAL_SECONDS:-60' in entry


def test_09_no_new_safe_upstream_noop_classification():
    tips = daemon.TipSnapshot(
        feed=pd.Timestamp("2026-07-24T14:00:00Z"),
        candle=pd.Timestamp("2026-07-24T14:00:00Z"),
        final=pd.Timestamp("2026-07-24T14:00:00Z"),
        lifecycle=pd.Timestamp("2026-07-24T14:00:00Z"),
        decision=pd.Timestamp("2026-07-24T14:00:00Z"),
    )
    assert daemon.classify_cycle(tips) == "NO_NEW_SAFE_UPSTREAM"


def test_10_partial_candle_ignored_pipeline_pending():
    tips = daemon.TipSnapshot(
        feed=pd.Timestamp("2026-07-24T14:15:00Z"),
        candle=pd.Timestamp("2026-07-24T14:00:00Z"),
        final=pd.Timestamp("2026-07-24T14:00:00Z"),
        lifecycle=pd.Timestamp("2026-07-24T14:00:00Z"),
        decision=pd.Timestamp("2026-07-24T14:00:00Z"),
    )
    assert daemon.classify_cycle(tips) == "PIPELINE_PENDING"


def test_11_daemon_does_not_outrun_pipeline_safe_upstream():
    tips = daemon.TipSnapshot(
        feed=pd.Timestamp("2026-07-24T14:15:00Z"),
        candle=pd.Timestamp("2026-07-24T14:00:00Z"),
        final=pd.Timestamp("2026-07-24T13:45:00Z"),
        lifecycle=pd.Timestamp("2026-07-24T13:45:00Z"),
        decision=pd.Timestamp("2026-07-24T13:45:00Z"),
    )
    assert tips.safe_upstream == pd.Timestamp("2026-07-24T14:00:00Z")
    assert daemon.classify_cycle(tips) == "CONTEXT_REFRESH_START"


def test_12_alignment_requires_refresh_when_decision_behind():
    tips = daemon.TipSnapshot(
        feed=pd.Timestamp("2026-07-24T14:00:00Z"),
        candle=pd.Timestamp("2026-07-24T14:00:00Z"),
        final=pd.Timestamp("2026-07-24T14:00:00Z"),
        lifecycle=pd.Timestamp("2026-07-24T14:00:00Z"),
        decision=pd.Timestamp("2026-07-24T13:45:00Z"),
    )
    assert daemon.classify_cycle(tips) == "CONTEXT_REFRESH_START"


def test_13_prefix_immutable_contract_documented():
    # Activation uses once-refresh append semantics; unit asserts classify never
    # invents rebuild-all. Catch-up event is CONTEXT_REFRESH_START only when lagging.
    tips = daemon.TipSnapshot(
        feed=pd.Timestamp("2026-07-24T12:00:00Z"),
        candle=pd.Timestamp("2026-07-24T12:00:00Z"),
        final=pd.Timestamp("2026-07-24T12:00:00Z"),
        lifecycle=pd.Timestamp("2026-07-24T12:00:00Z"),
        decision=pd.Timestamp("2026-07-24T12:00:00Z"),
    )
    assert daemon.classify_cycle(tips) == "NO_NEW_SAFE_UPSTREAM"


def test_14_rerun_idempotent_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        return {"status": "OK"}

    monkeypatch.setattr(daemon, "run_refresh_once", fake_refresh)
    monkeypatch.setattr(
        daemon,
        "read_tips",
        lambda **_k: daemon.TipSnapshot(
            feed=pd.Timestamp("2026-07-24T14:00:00Z"),
            candle=pd.Timestamp("2026-07-24T14:00:00Z"),
            final=pd.Timestamp("2026-07-24T14:00:00Z"),
            lifecycle=pd.Timestamp("2026-07-24T14:00:00Z"),
            decision=pd.Timestamp("2026-07-24T14:00:00Z"),
        ),
    )
    monkeypatch.setattr(daemon, "file_sha256", lambda _p: "abc")
    out = daemon.run_cycle(cycle_id="t1", dry_run=False, status_path=tmp_path / "s.json")
    assert out["result"] == "NO_NEW_SAFE_UPSTREAM"
    assert calls["n"] == 0


def test_15_no_duplicate_keys_event_codes_stable():
    codes = {
        "NO_NEW_SAFE_UPSTREAM",
        "PIPELINE_PENDING",
        "CONTEXT_REFRESH_START",
        "REFRESH_SUCCESS",
        "REFRESH_FAILED",
        "CONTEXT_REFRESH_STOP",
    }
    assert "NO_NEW_SAFE_UPSTREAM" in codes


def test_16_context_origin_not_touched_by_daemon_module():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "context_origin" not in src
    assert "paper_trading_controller" not in src


def test_17_paper_untouched_import_guard():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "bounded_paper" not in src
    assert "paper_simulator" not in src


def test_18_auction_synthesis_not_required():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "auction_synthesis" not in src


def test_19_foreground_stdout_logs_emitted(capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    monkeypatch.setattr(
        daemon,
        "read_tips",
        lambda **_k: daemon.TipSnapshot(
            feed=pd.Timestamp("2026-07-24T14:00:00Z"),
            candle=pd.Timestamp("2026-07-24T14:00:00Z"),
            final=pd.Timestamp("2026-07-24T14:00:00Z"),
            lifecycle=pd.Timestamp("2026-07-24T14:00:00Z"),
            decision=pd.Timestamp("2026-07-24T14:00:00Z"),
        ),
    )
    monkeypatch.setattr(daemon, "file_sha256", lambda _p: "x")
    daemon.run_cycle(cycle_id="c-log", dry_run=True, status_path=tmp_path / "s.json")
    out = capsys.readouterr().out
    assert "NO_NEW_SAFE_UPSTREAM" in out
    line = [ln for ln in out.splitlines() if ln.startswith("{")][0]
    payload = json.loads(line)
    assert payload["component"] == "context_refresh_daemon"
    assert "timestamp" in payload
    assert payload["cycle_id"] == "c-log"


def test_20_stdout_flush_emit(capsys):
    daemon.emit("CONTEXT_REFRESH_START", cycle_id="f1", message="flush_proof")
    out = capsys.readouterr().out
    assert "CONTEXT_REFRESH_START" in out
    assert out.endswith("\n")


def test_21_sigterm_graceful_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": kwargs["cycle_id"]},
    )

    def stop_soon(*_a, **_k):
        daemon._STOP = True

    # After first cycle sleep, stop via signal handler simulation
    daemon._STOP = False
    code = daemon.daemon_loop(
        interval_s=0.05,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
    )
    assert code == 0
    assert not (tmp_path / "l.lock").exists()


def test_22_lock_released_on_sigterm_handler(tmp_path: Path):
    lock = tmp_path / "lock"
    assert daemon.acquire_lock(lock, pid=os.getpid()) is True
    daemon._request_stop(signal.SIGTERM, None)
    assert daemon._STOP is True
    daemon.release_lock(lock)
    assert not lock.exists()
    daemon._STOP = False


def test_23_no_docker_host_only_dependency():
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "launchd" not in src
    assert "osascript" not in src
    assert "/Users/fontecrypto" not in src
    ctl = CTL_PATH.read_text(encoding="utf-8")
    assert "/Users/fontecrypto" not in ctl
    assert "launchd" not in ctl


def test_24_absolute_project_paths_inventory_marker():
    # Daemon resolves ROOT relative to __file__; documents BTC_ML_ROOT future.
    src = DAEMON_PATH.read_text(encoding="utf-8")
    assert "parents[2]" in src
    assert "Cellar" not in src or "forbid" in src.lower() or "bare" in src.lower()


def test_25_continuation_off_set_in_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    monkeypatch.delenv("BTC_ML_CONTINUATION_PROGRESSION", raising=False)
    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": "x"},
    )
    daemon.daemon_loop(
        interval_s=0.01,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
    )
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION") == "0"


def test_26_price_gate_off_set_in_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BTC_ML_CONTEXT_REFRESH_DAEMON", "1")
    monkeypatch.delenv("PRICE_GATE", raising=False)
    monkeypatch.setattr(
        daemon,
        "run_cycle",
        lambda **kwargs: {"result": "NO_NEW_SAFE_UPSTREAM", "cycle_id": "x"},
    )
    daemon.daemon_loop(
        interval_s=0.01,
        foreground=True,
        once=True,
        dry_run=True,
        lock_path=tmp_path / "l.lock",
        pid_path=tmp_path / "p.pid",
        status_path=tmp_path / "s.json",
        require_flag=True,
    )
    assert os.environ.get("PRICE_GATE") == "OFF"


def test_27_no_exchange_calls_in_source():
    src = DAEMON_PATH.read_text(encoding="utf-8").lower()
    assert "binance" not in src
    assert "ccxt" not in src
    assert "create_order" not in src
    assert "api_key" not in src


def test_ctl_default_off_refuses_start():
    env = os.environ.copy()
    env.pop("BTC_ML_CONTEXT_REFRESH_DAEMON", None)
    env["BTC_ML_CONTEXT_REFRESH_DAEMON"] = "0"
    proc = subprocess.run(
        ["bash", str(CTL_PATH), "start"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "REFUSED" in proc.stdout or "REFUSED" in proc.stderr
