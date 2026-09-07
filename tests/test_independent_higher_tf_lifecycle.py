"""Independent closed-bar lifecycle for M30/H1/H4 — no M15 leak."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.rebuild_context import (  # noqa: E402
    extend_m15_lifecycle_with_independent_higher_timeframes,
    load_m15_closed_bars_for_resample,
)
from btc_ml.external_traders.tf_market_pack import resample_m15_feed_to_tf
from btc_ml.trading.timeframe_state_adapter import (
    TimeframeSources,
    _scoped_lifecycle,
    resolve_timeframe_state,
)


def _m15_feed(n: int = 64) -> pd.DataFrame:
    ts = pd.date_range("2026-07-01", periods=n, freq="15min", tz="UTC")
    close = []
    price = 100.0
    for i in range(n):
        price = price - 0.4 if i < n // 2 else price + 0.5
        close.append(price)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [c - 0.05 for c in close],
            "high": [c + 0.2 for c in close],
            "low": [c - 0.2 for c in close],
            "close": close,
            "volume": [10.0 + (i % 5) for i in range(n)],
        }
    )


def _m15_lifecycle(feed: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": feed["timestamp"],
            "close": feed["close"],
            "active_market_context": ["LONG_CONTEXT"] * len(feed),
            "lifecycle_state": ["ACTIVE"] * len(feed),
            "context_episode_id": [547] * len(feed),
            "active_context_started_at": [feed["timestamp"].iloc[0]] * len(feed),
            "context_origin_price": [100.0] * len(feed),
            "action_allowed": [False] * len(feed),
            "shadow_only": [True] * len(feed),
        }
    )


def _m15_episodes(feed: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "episode_id": [547],
            "active_market_context": ["LONG_CONTEXT"],
            "start_time": [feed["timestamp"].iloc[0]],
            "end_time": [feed["timestamp"].iloc[-1]],
            "action_allowed_any": [False],
            "shadow_only": [True],
        }
    )


def _fake_independent_builder(feed: pd.DataFrame, *, timeframe: str):
    n = len(feed)
    episode = {"M30": 11, "H1": 22, "H4": 33}[timeframe]
    ctx = {"M30": "SHORT_CONTEXT", "H1": "OBSERVE", "H4": "SHORT_CONTEXT"}[timeframe]
    life = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(feed["timestamp"], utc=True),
            "close": list(feed["close"]),
            "active_market_context": [ctx] * n,
            "lifecycle_state": ["ACTIVE"] * n,
            "context_episode_id": [episode] * n,
            "active_context_started_at": [feed["timestamp"].iloc[0]] * n,
            "context_origin_price": [float(feed["close"].iloc[0])] * n,
            "action_allowed": [False] * n,
            "shadow_only": [True] * n,
            "timeframe": [timeframe] * n,
        }
    )
    episodes = pd.DataFrame(
        {
            "episode_id": [episode],
            "active_market_context": [ctx],
            "start_time": [feed["timestamp"].iloc[0]],
            "end_time": [feed["timestamp"].iloc[-1]],
            "action_allowed_any": [False],
            "shadow_only": [True],
            "timeframe": [timeframe],
        }
    )
    return life, episodes


def _availability(ts: str, timeframe: str, bar_open: str, bar_close: str) -> dict:
    return {
        "evaluation_timestamp": ts,
        "timeframe": timeframe,
        "source_bar_open": bar_open,
        "source_bar_close": bar_close,
        "source_state_timestamp": bar_open,
        "source_event_timestamp": bar_open,
        "availability_status": "FRESH_EVENT",
        "availability_reason": "completed_bar_closed_at_or_before_evaluation",
        "is_new_event": True,
        "writer_state": "RUNNING",
    }


@pytest.fixture
def patched_builder(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "btc_ml.external_traders.rebuild_context.build_independent_tf_lifecycle",
        _fake_independent_builder,
    )


def test_resample_higher_tf_has_fewer_bars_not_copied_m15_rows():
    feed = _m15_feed(64)
    m30 = resample_m15_feed_to_tf(feed, "M30")
    h1 = resample_m15_feed_to_tf(feed, "H1")
    h4 = resample_m15_feed_to_tf(feed, "H4")
    assert len(m30) == 32
    assert len(h1) == 16
    assert len(h4) == 4
    assert len(m30) != len(feed)
    assert list(m30["close"]) != list(feed["close"][: len(m30)])


def test_extend_keeps_m15_rows_and_tags_timeframe(patched_builder):
    feed = _m15_feed(64)
    before = _m15_lifecycle(feed)
    extended, extended_ep = extend_m15_lifecycle_with_independent_higher_timeframes(
        m15_lifecycle=before,
        m15_episodes=_m15_episodes(feed),
        feed_m15=feed,
    )
    m15 = extended[extended["timeframe"].astype(str).str.upper() == "M15"]
    assert len(m15) == 64
    compared = [c for c in before.columns if c in m15.columns]
    pd.testing.assert_frame_equal(
        m15[compared].reset_index(drop=True),
        before[compared].reset_index(drop=True),
        check_dtype=False,
    )
    assert set(extended["timeframe"].astype(str).str.upper()) == {"M15", "M30", "H1", "H4"}
    counts = extended["timeframe"].astype(str).str.upper().value_counts().to_dict()
    assert counts["M30"] == 32
    assert counts["H1"] == 16
    assert counts["H4"] == 4
    h4 = extended[extended["timeframe"].astype(str).str.upper() == "H4"]
    assert set(h4["active_market_context"].astype(str)) == {"SHORT_CONTEXT"}
    assert set(m15["active_market_context"].astype(str)) == {"LONG_CONTEXT"}
    assert "H4" in set(extended_ep["timeframe"].astype(str).str.upper())
    assert "M15" in set(extended_ep["timeframe"].astype(str).str.upper())


def test_missing_feed_tags_m15_only_and_does_not_fail():
    feed = _m15_feed(8)
    before = _m15_lifecycle(feed)
    extended, extended_ep = extend_m15_lifecycle_with_independent_higher_timeframes(
        m15_lifecycle=before,
        m15_episodes=_m15_episodes(feed),
        feed_m15=None,
    )
    assert set(extended["timeframe"].astype(str).str.upper()) == {"M15"}
    assert len(extended) == 8
    assert set(extended_ep["timeframe"].astype(str).str.upper()) == {"M15"}


def test_higher_tf_does_not_inherit_m15_episode_or_direction(patched_builder):
    feed = _m15_feed(64)
    extended, _ = extend_m15_lifecycle_with_independent_higher_timeframes(
        m15_lifecycle=_m15_lifecycle(feed),
        m15_episodes=_m15_episodes(feed),
        feed_m15=feed,
    )
    eval_ts = "2026-07-01T16:00:00Z"
    availability = pd.DataFrame(
        [
            _availability(eval_ts, "M15", "2026-07-01T15:45:00Z", "2026-07-01T16:00:00Z"),
            _availability(eval_ts, "H4", "2026-07-01T12:00:00Z", "2026-07-01T16:00:00Z"),
            _availability(eval_ts, "H1", "2026-07-01T15:00:00Z", "2026-07-01T16:00:00Z"),
            _availability(eval_ts, "M30", "2026-07-01T15:30:00Z", "2026-07-01T16:00:00Z"),
        ]
    )
    sources = TimeframeSources(availability=availability, lifecycle=extended, lifecycle_source="parquet")
    m15 = resolve_timeframe_state(timeframe="M15", evaluation_timestamp=eval_ts, sources=sources)
    h4 = resolve_timeframe_state(timeframe="H4", evaluation_timestamp=eval_ts, sources=sources)
    assert m15["lifecycle_episode_id"] == "M15:547"
    assert m15["timeframe_direction"] == "LONG"
    assert h4["no_action_reason"] != "NO_LIFECYCLE_ROW_AT_OR_BEFORE_BAR_CLOSE"
    assert h4["lifecycle_episode_id"] == "H4:33"
    assert h4["timeframe_direction"] == "SHORT"
    assert h4["lifecycle_episode_id"] != m15["lifecycle_episode_id"]


def test_one_tf_builder_error_keeps_m15_and_other_tfs(monkeypatch: pytest.MonkeyPatch):
    def boom(feed, *, timeframe):
        if timeframe == "H4":
            raise RuntimeError("h4 boom")
        return _fake_independent_builder(feed, timeframe=timeframe)

    monkeypatch.setattr(
        "btc_ml.external_traders.rebuild_context.build_independent_tf_lifecycle",
        boom,
    )
    feed = _m15_feed(64)
    extended, _ = extend_m15_lifecycle_with_independent_higher_timeframes(
        m15_lifecycle=_m15_lifecycle(feed),
        m15_episodes=_m15_episodes(feed),
        feed_m15=feed,
    )
    tfs = set(extended["timeframe"].astype(str).str.upper())
    assert tfs == {"M15", "M30", "H1"}
    assert int((extended["timeframe"].astype(str).str.upper() == "M15").sum()) == 64


def test_untagged_parquet_still_does_not_leak():
    untagged = pd.DataFrame(
        {
            "timestamp": ["2026-07-01T15:45:00Z"],
            "active_market_context": ["LONG_CONTEXT"],
            "lifecycle_state": ["ACTIVE"],
            "context_episode_id": [547],
        }
    )
    assert len(_scoped_lifecycle(untagged, "M15")) == 1
    assert len(_scoped_lifecycle(untagged, "H4")) == 0


def test_load_m15_closed_bars_prefers_candle_structure(tmp_path: Path):
    cognition = tmp_path / "data" / "cognition"
    live = tmp_path / "data" / "live"
    cognition.mkdir(parents=True)
    live.mkdir(parents=True)
    candle = _m15_feed(4)
    candle["marker"] = "candle"
    live_feed = _m15_feed(4)
    live_feed["marker"] = "live"
    candle.to_parquet(cognition / "candle_structure_memory.parquet", index=False)
    live_feed.to_parquet(live / "live_market_feed.parquet", index=False)
    loaded = load_m15_closed_bars_for_resample(tmp_path)
    assert list(loaded["marker"]) == ["candle"] * 4


def test_load_m15_closed_bars_falls_back_to_live_feed(tmp_path: Path):
    live = tmp_path / "data" / "live"
    live.mkdir(parents=True)
    live_feed = _m15_feed(3)
    live_feed.to_parquet(live / "live_market_feed.parquet", index=False)
    loaded = load_m15_closed_bars_for_resample(tmp_path)
    assert len(loaded) == 3
