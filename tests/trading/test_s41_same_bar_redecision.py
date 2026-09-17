"""S4.1 same-bar rules.

Unchanged parquet on a bar still HOLDs. Opposite restatement on the same bar
without OBSERVE must not ATOMIC_FLIP. Forming-bar lifecycle rows are tradable
before that TF bar closes. Protective SL/TP CLOSE is not blocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
from btc_ml.trading.proofs import isolated_environment
from btc_ml.trading.timeframe_manager import (
    FORMING_BAR_CONTEXT,
    OPPOSITE_REQUIRES_OBSERVE,
    PROCESS_STRENGTH_TOO_WEAK,
    RAW_STATUS_NOT_CONFIRMED,
    SAME_CLOSED_BAR_ALREADY_ACTED,
    TimeframeManager,
    _same_closed_bar_already_actioned,
    select_state_for_flat_open,
    select_state_for_open_position,
    with_bar_close,
)
from btc_ml.trading.timeframe_state_adapter import TimeframeSources, resolve_timeframe_state


def _availability(*, tf: str, evaluation: str, bar_open: str, bar_close: str) -> dict:
    return {
        "evaluation_timestamp": evaluation,
        "timeframe": tf,
        "source_bar_open": bar_open,
        "source_bar_close": bar_close,
        "source_state_timestamp": bar_open,
        "source_event_timestamp": bar_open,
        "availability_status": "FRESH_EVENT",
        "availability_reason": "completed_bar_closed_at_or_before_evaluation",
        "is_new_event": True,
        "writer_state": "RUNNING",
    }


def _life(
    *,
    ts: str,
    tf: str,
    context: str,
    episode: int,
    started: str | None = None,
    phase: str = "ACTIVE",
    raw_status: str | None = None,
    process_strength: float | None = None,
) -> dict:
    row = {
        "timestamp": ts,
        "timeframe": tf,
        "active_market_context": context,
        "lifecycle_state": phase,
        "context_episode_id": episode,
        "active_context_started_at": started or ts,
        "context_origin_price": 77200.0,
    }
    if raw_status is not None:
        row["raw_context_status"] = raw_status
    if process_strength is not None:
        row["process_strength"] = process_strength
        row["living_process"] = "SELLER" if "SHORT" in context else "BUYER" if "LONG" in context else "NONE"
    return row


def _sources(*, evaluation: str, bar_open: str, bar_close: str, context: str, episode: int, started: str) -> TimeframeSources:
    return TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(tf="M30", evaluation=evaluation, bar_open=bar_open, bar_close=bar_close),
            ]
        ),
        lifecycle=pd.DataFrame(
            [_life(ts=bar_open, tf="M30", context=context, episode=episode, started=started)]
        ),
        lifecycle_source="parquet",
    )


def _feed() -> pd.DataFrame:
    opens = pd.date_range(start=pd.Timestamp("2026-09-13T18:00:00Z"), periods=12, freq="15min", tz="UTC")
    return with_bar_close(
        pd.DataFrame(
            {
                "timestamp": opens,
                "open": [77200.0] * len(opens),
                "high": [77280.0] * len(opens),
                "low": [77120.0] * len(opens),
                "close": [77216.9] * len(opens),
                "volume": [10.0] * len(opens),
            }
        )
    )


def _slot(direction: str | None, *, stop: float | None = None, take: float | None = None) -> dict:
    if direction is None:
        return {"open_position": None, "open_risk_usd": 0.0}
    entry = 77210.4
    if stop is None:
        stop = entry - 600.0 if direction == "LONG" else entry + 600.0
    if take is None:
        take = entry + 900.0 if direction == "LONG" else entry - 900.0
    return {
        "open_position": {
            "position_id": f"pos_{direction.lower()}",
            "direction": direction,
            "quantity": 0.1,
            "entry_price": entry,
            "stop_loss_price": stop,
            "take_profit_price": take,
            "entry_fee_usd": 1.0,
            "status": "OPEN",
        },
        "open_risk_usd": 250.0,
    }


def _views_for(positions: dict[str, dict]):
    def views(*, mark_price=None):
        return {
            "M15": positions.get("M15", _slot(None)),
            "M30": positions.get("M30", _slot(None)),
            "H1": positions.get("H1", _slot(None)),
            "H4": positions.get("H4", _slot(None)),
        }

    return views


def _m30_intents(cycle: dict) -> list[str]:
    return [cmd["intent"] for cmd in cycle["commands"] if cmd["timeframe"] == "M30"]


def _m30_reasons(cycle: dict) -> list[str]:
    out: list[str] = []
    for cmd in cycle["commands"]:
        if cmd["timeframe"] != "M30":
            continue
        out.extend(json.loads(cmd["reason_codes"]))
    return out


def test_same_closed_bar_helper_allows_same_evaluation_replay():
    state = {
        "last_actioned_source_bar_close": "2026-09-13T19:30:00Z",
        "last_actioned_evaluation_timestamp": "2026-09-13T19:30:00Z",
        "last_actioned_cognition_key": "SHORT|111|SHORT_CONTEXT|ACTIVE",
    }
    assert not _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T19:30:00Z",
        evaluation_timestamp="2026-09-13T19:30:00Z",
        cognition_key="SHORT|111|SHORT_CONTEXT|ACTIVE",
    )
    assert _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T19:30:00Z",
        evaluation_timestamp="2026-09-13T19:45:00Z",
        cognition_key="SHORT|111|SHORT_CONTEXT|ACTIVE",
    )
    assert not _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T19:30:00Z",
        evaluation_timestamp="2026-09-13T19:45:00Z",
        cognition_key="LONG|110|LONG_CONTEXT|ACTIVE",
    )
    assert not _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T20:00:00Z",
        evaluation_timestamp="2026-09-13T20:00:00Z",
        cognition_key="SHORT|111|SHORT_CONTEXT|ACTIVE",
    )


def test_m30_restated_opposite_on_same_bar_requires_observe(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    feed = _feed()

    first = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:30:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="SHORT_CONTEXT",
            episode=111,
            started="2026-09-13T19:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:31:07Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(first)
    assert "OPEN_SHORT" in _m30_intents(first)

    positions["M30"] = _slot("SHORT")
    second = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:45:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:45:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:46:11Z",
        decision_index={},
    )
    assert "OPEN_LONG" not in _m30_intents(second)
    assert "CLOSE" not in _m30_intents(second)
    assert "HOLD" in _m30_intents(second)
    assert OPPOSITE_REQUIRES_OBSERVE in _m30_reasons(second)
    assert SAME_CLOSED_BAR_ALREADY_ACTED not in _m30_reasons(second)

    positions["M30"] = _slot("SHORT")
    third = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:46:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:46:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:47:00Z",
        decision_index={},
    )
    assert "CLOSE" not in _m30_intents(third)
    assert "OPEN_SHORT" not in _m30_intents(third)
    assert "HOLD" in _m30_intents(third)


def test_same_evaluation_replay_still_emits_atomic_flip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    kwargs = dict(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:30:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="SHORT_CONTEXT",
            episode=111,
            started="2026-09-13T19:00:00Z",
        ),
        feed=_feed(),
        persist=False,
        now="2026-09-13T19:31:07Z",
        decision_index={},
    )
    first = manager.run_cycle(**kwargs)
    second = manager.run_cycle(**kwargs)
    assert _m30_intents(first) == _m30_intents(second)
    assert "CLOSE" in _m30_intents(first)
    assert "OPEN_SHORT" in _m30_intents(first)


def test_protective_stop_close_is_not_blocked_on_same_bar(tmp_path: Path, monkeypatch):
    """Manager hold-until swallows SL in preview; if a stop CLOSE is previewed, same-bar must not HOLD it."""
    from btc_ml.trading import timeframe_manager as tm

    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    monkeypatch.setattr(
        tm,
        "evaluate_exit_preview",
        lambda **_k: {
            "is_close": True,
            "is_hold": False,
            "exit_preview_action": "PREVIEW_CLOSE_LONG_STOP_LOSS",
            "exit_preview_reason": "STOP_LOSS_HIT",
            "exited_on_flip": False,
        },
    )
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    feed = _feed()
    long_sources = _sources(
        evaluation="2026-09-13T19:30:00Z",
        bar_open="2026-09-13T19:00:00Z",
        bar_close="2026-09-13T19:30:00Z",
        context="LONG_CONTEXT",
        episode=110,
        started="2026-09-13T09:00:00Z",
    )
    first = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=long_sources,
        feed=feed,
        persist=True,
        now="2026-09-13T19:31:07Z",
        decision_index={},
    )
    assert "OPEN_LONG" in _m30_intents(first)

    positions["M30"] = _slot("LONG")
    second = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:45:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:45:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:46:11Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(second)
    assert SAME_CLOSED_BAR_ALREADY_ACTED not in _m30_reasons(second)
    assert any("STOP_LOSS" in reason for reason in _m30_reasons(second))


def test_h1_forming_bar_row_is_actionable_before_close():
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-09-14T12:15:00Z",
                    bar_open="2026-09-14T11:00:00Z",
                    bar_close="2026-09-14T12:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T11:00:00Z",
                    tf="H1",
                    context="LONG_CONTEXT",
                    episode=95,
                    started="2026-09-13T07:00:00Z",
                ),
                _life(
                    ts="2026-09-14T12:00:00Z",
                    tf="H1",
                    context="SHORT_CONTEXT",
                    episode=97,
                    started="2026-09-14T12:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    state = resolve_timeframe_state(
        timeframe="H1",
        evaluation_timestamp="2026-09-14T12:15:00Z",
        sources=sources,
    )
    assert state["timeframe_direction"] == "SHORT"
    assert state["lifecycle_episode_id"] == "H1:97"
    assert state["source_bar_open"] == "2026-09-14T12:00:00Z"
    assert state["source_bar_close"] == "2026-09-14T13:00:00Z"
    assert state["context_bar_kind"] == FORMING_BAR_CONTEXT
    assert state["actionable"] is True
    assert state["lifecycle_row_timestamp"] == "2026-09-14T12:00:00Z"


def test_select_state_for_flat_open_closed_direction_wins():
    closed = {"timeframe_state": "SHORT_CONTEXT", "lifecycle_phase": "ACTIVE"}
    forming = {"timeframe_state": "LONG_CONTEXT", "lifecycle_phase": "ACTIVE"}
    chosen = select_state_for_flat_open(closed=closed, forming=forming)
    assert chosen["timeframe_state"] == "SHORT_CONTEXT"


def test_select_state_for_flat_open_observe_closed_does_not_take_forming():
    closed = {"timeframe_state": "OBSERVE", "lifecycle_phase": "INVALIDATED"}
    forming = {
        "timeframe_state": "LONG_CONTEXT",
        "lifecycle_phase": "CHALLENGED",
    }
    chosen = select_state_for_flat_open(closed=closed, forming=forming)
    assert chosen["timeframe_state"] == "OBSERVE"


def test_select_state_for_flat_open_forming_only_when_closed_missing():
    closed = {
        "timeframe_state": "UNKNOWN",
        "no_action_reason": "NO_LIFECYCLE_ROW_FOR_CLOSED_BAR",
    }
    forming = {"timeframe_state": "SHORT_CONTEXT", "lifecycle_phase": "ACTIVE"}
    chosen = select_state_for_flat_open(closed=closed, forming=forming)
    assert chosen["timeframe_state"] == "SHORT_CONTEXT"


def test_select_state_for_open_position_closed_observe_holds_through_forming_short():
    """H4 14:31: closed OBSERVE + forming SHORT must not flatten a LONG."""
    closed = {"timeframe_state": "OBSERVE", "lifecycle_phase": "INVALIDATED"}
    forming = {"timeframe_state": "SHORT_CONTEXT", "lifecycle_phase": "ACTIVE"}
    chosen = select_state_for_open_position(closed=closed, forming=forming, side="LONG")
    assert chosen["timeframe_state"] == "OBSERVE"


def test_select_state_for_open_position_forming_short_only_when_closed_missing():
    closed = {
        "timeframe_state": "UNKNOWN",
        "no_action_reason": "NO_LIFECYCLE_ROW_FOR_CLOSED_BAR",
    }
    forming = {"timeframe_state": "SHORT_CONTEXT", "lifecycle_phase": "ACTIVE"}
    chosen = select_state_for_open_position(closed=closed, forming=forming, side="LONG")
    assert chosen["timeframe_state"] == "SHORT_CONTEXT"


def test_h1_manager_opens_forming_bar_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"H1": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-09-14T12:15:00Z",
                    bar_open="2026-09-14T11:00:00Z",
                    bar_close="2026-09-14T12:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T12:00:00Z",
                    tf="H1",
                    context="SHORT_CONTEXT",
                    episode=97,
                    started="2026-09-14T12:00:00Z",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T12:15:00Z",
        sources=sources,
        feed=_feed(),
        persist=True,
        now="2026-09-14T12:16:00Z",
        decision_index={},
    )
    h1 = [cmd for cmd in cycle["commands"] if cmd["timeframe"] == "H1"]
    assert any(cmd["intent"] == "OPEN_SHORT" for cmd in h1)
    reasons = []
    for cmd in h1:
        reasons.extend(json.loads(cmd["reason_codes"]))
    assert FORMING_BAR_CONTEXT in reasons


def test_flat_open_does_not_use_forming_when_closed_bar_is_not_same_side(
    tmp_path: Path, monkeypatch
):
    """H4_3: closed OBSERVE, forming LONG CHALLENGED → no OPEN_LONG."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"H4": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H4",
                    evaluation="2026-09-15T00:15:00Z",
                    bar_open="2026-09-14T20:00:00Z",
                    bar_close="2026-09-15T00:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:00:00Z",
                    tf="H4",
                    context="OBSERVE",
                    episode=46,
                    started="2026-09-14T20:00:00Z",
                    phase="INVALIDATED",
                ),
                _life(
                    ts="2026-09-15T00:00:00Z",
                    tf="H4",
                    context="LONG_CONTEXT",
                    episode=45,
                    started="2026-09-13T08:00:00Z",
                    phase="CHALLENGED",
                    raw_status="DEVELOPING",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-15T00:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T20:00:00Z", periods=20),
        persist=True,
        now="2026-09-15T00:16:00Z",
        decision_index={},
    )
    h4 = [cmd for cmd in cycle["commands"] if cmd["timeframe"] == "H4"]
    assert not any(cmd["intent"] == "OPEN_LONG" for cmd in h4)


def test_flat_open_closed_short_does_not_open_forming_long(
    tmp_path: Path, monkeypatch
):
    """H4_3 restated paint: closed SHORT, forming LONG ACTIVE → no OPEN_LONG."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"H4": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H4",
                    evaluation="2026-09-15T00:15:00Z",
                    bar_open="2026-09-14T20:00:00Z",
                    bar_close="2026-09-15T00:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:00:00Z",
                    tf="H4",
                    context="SHORT_CONTEXT",
                    episode=47,
                    started="2026-09-15T00:00:00Z",
                    phase="ACTIVE",
                ),
                _life(
                    ts="2026-09-15T00:00:00Z",
                    tf="H4",
                    context="LONG_CONTEXT",
                    episode=45,
                    started="2026-09-13T08:00:00Z",
                    phase="ACTIVE",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-15T00:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T20:00:00Z", periods=20),
        persist=True,
        now="2026-09-15T00:16:00Z",
        decision_index={},
    )
    h4 = [cmd for cmd in cycle["commands"] if cmd["timeframe"] == "H4"]
    assert not any(cmd["intent"] == "OPEN_LONG" for cmd in h4)
    assert any(cmd["intent"] == "OPEN_SHORT" for cmd in h4)


def test_observe_on_same_bar_then_opposite_allows_atomic_flip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    feed = _feed()
    first = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:30:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="SHORT_CONTEXT",
            episode=111,
            started="2026-09-13T19:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:31:07Z",
        decision_index={},
    )
    assert "OPEN_SHORT" in _m30_intents(first)
    positions["M30"] = _slot("SHORT")
    observe = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M30",
                    evaluation="2026-09-13T19:45:00Z",
                    bar_open="2026-09-13T19:00:00Z",
                    bar_close="2026-09-13T19:30:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-13T19:00:00Z",
                    tf="M30",
                    context="OBSERVE",
                    episode=112,
                    started="2026-09-13T19:00:00Z",
                    phase="INVALIDATED",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    mid = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:45:00Z",
        sources=observe,
        feed=feed,
        persist=True,
        now="2026-09-13T19:46:00Z",
        decision_index={},
    )
    assert "HOLD" in _m30_intents(mid)
    assert "OPEN_LONG" not in _m30_intents(mid)
    third = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:46:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:46:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=113,
            started="2026-09-13T19:46:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:47:00Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(third)
    assert "OPEN_LONG" in _m30_intents(third)
    assert OPPOSITE_REQUIRES_OBSERVE not in _m30_reasons(third)


def test_take_profit_closes_even_while_same_direction_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    take = 78100.0
    positions = {
        "M30": _slot(
            "LONG",
            take=take,
            stop=76500.0,
        )
    }
    positions["M30"]["open_position"]["opened_at"] = "2026-09-13T18:00:00Z"
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    opens = pd.date_range(start=pd.Timestamp("2026-09-13T18:00:00Z"), periods=6, freq="15min", tz="UTC")
    highs = [77280.0, 78150.0, 77300.0, 77290.0, 77270.0, 77260.0]
    feed = with_bar_close(
        pd.DataFrame(
            {
                "timestamp": opens,
                "open": [77200.0] * len(opens),
                "high": highs,
                "low": [77120.0] * len(opens),
                "close": [77216.9] * len(opens),
                "volume": [10.0] * len(opens),
            }
        )
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:30:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:31:00Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(cycle)
    assert "OPEN_LONG" in _m30_intents(cycle)
    assert any("TAKE_PROFIT" in reason for reason in _m30_reasons(cycle))
    assert "TP_SL_CONTINUATION_OPEN" in _m30_reasons(cycle)
    assert "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END" not in _m30_reasons(cycle)


def test_flat_slot_retries_open_on_later_same_bar_evaluation(tmp_path: Path, monkeypatch):
    """Unfilled OPEN after TP must re-emit on the next cycle of the same bar."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    feed = _feed()
    first = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:30:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:30:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:31:00Z",
        decision_index={},
    )
    assert "OPEN_LONG" in _m30_intents(first)
    second = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:45:00Z",
        sources=_sources(
            evaluation="2026-09-13T19:45:00Z",
            bar_open="2026-09-13T19:00:00Z",
            bar_close="2026-09-13T19:30:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T19:46:00Z",
        decision_index={},
    )
    assert "OPEN_LONG" in _m30_intents(second)
    assert SAME_CLOSED_BAR_ALREADY_ACTED not in _m30_reasons(second)


def _intents(cycle: dict, tf: str) -> list[str]:
    return [cmd["intent"] for cmd in cycle["commands"] if cmd["timeframe"] == tf]


def _reasons(cycle: dict, tf: str) -> list[str]:
    out: list[str] = []
    for cmd in cycle["commands"]:
        if cmd["timeframe"] != tf:
            continue
        out.extend(json.loads(cmd["reason_codes"]))
    return out


def _feed_from(start: str, periods: int = 16) -> pd.DataFrame:
    opens = pd.date_range(start=pd.Timestamp(start), periods=periods, freq="15min", tz="UTC")
    return with_bar_close(
        pd.DataFrame(
            {
                "timestamp": opens,
                "open": [77200.0] * len(opens),
                "high": [77280.0] * len(opens),
                "low": [77120.0] * len(opens),
                "close": [77216.9] * len(opens),
                "volume": [10.0] * len(opens),
            }
        )
    )


def test_restated_duplicate_timestamp_prefers_latest():
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-09-14T22:15:00Z",
                    bar_open="2026-09-14T21:00:00Z",
                    bar_close="2026-09-14T22:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T21:00:00Z",
                    tf="H1",
                    context="LONG_CONTEXT",
                    episode=95,
                    started="2026-09-13T07:00:00Z",
                ),
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="H1",
                    context="LONG_CONTEXT",
                    episode=97,
                    started="2026-09-14T21:00:00Z",
                    phase="CHALLENGED",
                ),
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="H1",
                    context="SHORT_CONTEXT",
                    episode=99,
                    started="2026-09-14T22:00:00Z",
                    phase="ACTIVE",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    state = resolve_timeframe_state(
        timeframe="H1",
        evaluation_timestamp="2026-09-14T22:15:00Z",
        sources=sources,
        now="2026-09-14T22:16:00Z",
    )
    assert state["timeframe_direction"] == "SHORT"
    assert state["timeframe_state"] == "SHORT_CONTEXT"
    assert state["lifecycle_episode_id"] == "H1:99"
    assert state["lifecycle_phase"] == "ACTIVE"
    assert state["context_bar_kind"] == FORMING_BAR_CONTEXT
    assert state["source_bar_open"] == "2026-09-14T22:00:00Z"


def test_h1_lagged_availability_follows_now_bar():
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-09-14T21:00:00Z",
                    bar_open="2026-09-14T20:00:00Z",
                    bar_close="2026-09-14T21:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T21:00:00Z",
                    tf="H1",
                    context="LONG_CONTEXT",
                    episode=97,
                    started="2026-09-14T21:00:00Z",
                    phase="CHALLENGED",
                ),
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="H1",
                    context="SHORT_CONTEXT",
                    episode=99,
                    started="2026-09-14T22:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    state = resolve_timeframe_state(
        timeframe="H1",
        evaluation_timestamp="2026-09-14T22:15:00Z",
        sources=sources,
        now="2026-09-14T22:16:00Z",
    )
    assert state["timeframe_direction"] == "SHORT"
    assert state["lifecycle_episode_id"] == "H1:99"
    assert state["source_bar_open"] == "2026-09-14T22:00:00Z"
    assert state["context_bar_kind"] == FORMING_BAR_CONTEXT


def test_m15_forming_short_does_not_close_open_long_when_closed_bar_exists(
    tmp_path: Path, monkeypatch
):
    """Journal 1 / H4 14:31: forming opposite must not flatten over a closed row."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-14T20:45:00Z",
                    bar_open="2026-09-14T20:30:00Z",
                    bar_close="2026-09-14T20:45:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:30:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=358,
                    started="2026-09-14T19:15:00Z",
                    phase="CHALLENGED",
                ),
                _life(
                    ts="2026-09-14T20:45:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=360,
                    started="2026-09-14T20:45:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T20:45:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T19:00:00Z"),
        persist=True,
        now="2026-09-14T20:52:00Z",
        decision_index={},
    )
    assert "HOLD" in _intents(cycle, "M15")
    assert "CLOSE" not in _intents(cycle, "M15")
    assert "OPEN_SHORT" not in _intents(cycle, "M15")


def test_h1_forming_short_closes_leftover_long(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"H1": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-09-14T22:15:00Z",
                    bar_open="2026-09-14T21:00:00Z",
                    bar_close="2026-09-14T22:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="H1",
                    context="LONG_CONTEXT",
                    episode=97,
                    started="2026-09-14T21:00:00Z",
                    phase="CHALLENGED",
                ),
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="H1",
                    context="SHORT_CONTEXT",
                    episode=99,
                    started="2026-09-14T22:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T22:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T20:00:00Z", periods=12),
        persist=True,
        now="2026-09-14T22:16:00Z",
        decision_index={},
    )
    assert "CLOSE" in _intents(cycle, "H1")
    assert "OPEN_SHORT" in _intents(cycle, "H1")


def test_forming_opposite_challenged_holds_open_long(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-14T20:45:00Z",
                    bar_open="2026-09-14T20:30:00Z",
                    bar_close="2026-09-14T20:45:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:45:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=360,
                    started="2026-09-14T20:45:00Z",
                    phase="CHALLENGED",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T20:45:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T19:00:00Z"),
        persist=True,
        now="2026-09-14T20:52:00Z",
        decision_index={},
    )
    assert "HOLD" in _intents(cycle, "M15")
    assert "CLOSE" not in _intents(cycle, "M15")
    assert "OPEN_SHORT" not in _intents(cycle, "M15")


def test_adapter_passes_raw_context_status():
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-15T05:15:00Z",
                    bar_open="2026-09-15T05:00:00Z",
                    bar_close="2026-09-15T05:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-15T05:00:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=378,
                    started="2026-09-15T04:45:00Z",
                    raw_status="OBSERVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    state = resolve_timeframe_state(
        timeframe="M15",
        evaluation_timestamp="2026-09-15T05:15:00Z",
        sources=sources,
        now="2026-09-15T05:16:00Z",
    )
    assert state["timeframe_direction"] == "SHORT"
    assert state["lifecycle_phase"] == "ACTIVE"
    assert state["raw_context_status"] == "OBSERVE"
    assert state["actionable"] is True


def test_flat_open_blocked_when_raw_status_not_confirmed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-15T05:15:00Z",
                    bar_open="2026-09-15T05:00:00Z",
                    bar_close="2026-09-15T05:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-15T05:00:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=378,
                    started="2026-09-15T04:45:00Z",
                    raw_status="OBSERVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-15T05:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-15T04:00:00Z"),
        persist=True,
        now="2026-09-15T05:16:00Z",
        decision_index={},
    )
    assert "OPEN_SHORT" not in _intents(cycle, "M15")
    assert "NO_ACTION" in _intents(cycle, "M15")
    assert RAW_STATUS_NOT_CONFIRMED in _reasons(cycle, "M15")


def test_flat_open_allowed_when_raw_status_active(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-15T05:15:00Z",
                    bar_open="2026-09-15T05:00:00Z",
                    bar_close="2026-09-15T05:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-15T05:00:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=378,
                    started="2026-09-15T04:45:00Z",
                    raw_status="ACTIVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-15T05:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-15T04:00:00Z"),
        persist=True,
        now="2026-09-15T05:16:00Z",
        decision_index={},
    )
    assert "OPEN_SHORT" in _intents(cycle, "M15")
    assert RAW_STATUS_NOT_CONFIRMED not in _reasons(cycle, "M15")


def test_atomic_flip_not_gated_by_raw_status(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M30": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    observe = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M30",
                    evaluation="2026-09-13T19:45:00Z",
                    bar_open="2026-09-13T19:00:00Z",
                    bar_close="2026-09-13T19:30:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-13T19:00:00Z",
                    tf="M30",
                    context="OBSERVE",
                    episode=112,
                    started="2026-09-13T19:00:00Z",
                    phase="INVALIDATED",
                    raw_status="OBSERVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    mid = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:45:00Z",
        sources=observe,
        feed=_feed(),
        persist=True,
        now="2026-09-13T19:46:00Z",
        decision_index={},
    )
    assert "HOLD" in _m30_intents(mid)
    flip = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M30",
                    evaluation="2026-09-13T19:46:00Z",
                    bar_open="2026-09-13T19:00:00Z",
                    bar_close="2026-09-13T19:30:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-13T19:30:00Z",
                    tf="M30",
                    context="SHORT_CONTEXT",
                    episode=113,
                    started="2026-09-13T19:46:00Z",
                    raw_status="OBSERVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    third = manager.run_cycle(
        evaluation_timestamp="2026-09-13T19:46:00Z",
        sources=flip,
        feed=_feed(),
        persist=True,
        now="2026-09-13T19:47:00Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(third)
    assert "OPEN_SHORT" in _m30_intents(third)
    assert RAW_STATUS_NOT_CONFIRMED not in _m30_reasons(third)


def test_open_long_holds_when_raw_observe_same_side(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-15T05:15:00Z",
                    bar_open="2026-09-15T05:00:00Z",
                    bar_close="2026-09-15T05:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-15T05:00:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=376,
                    started="2026-09-15T03:15:00Z",
                    raw_status="OBSERVE",
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-15T05:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-15T04:00:00Z"),
        persist=True,
        now="2026-09-15T05:16:00Z",
        decision_index={},
    )
    assert "HOLD" in _intents(cycle, "M15")
    assert "CLOSE" not in _intents(cycle, "M15")


def test_open_long_closes_on_closed_bar_short_even_if_forming_still_long(
    tmp_path: Path, monkeypatch
):
    """M15_4 / M15_7: forming LONG must not hide the just-closed SHORT ACTIVE."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-14T21:00:00Z",
                    bar_open="2026-09-14T20:45:00Z",
                    bar_close="2026-09-14T21:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:45:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=362,
                    started="2026-09-14T20:45:00Z",
                ),
                _life(
                    ts="2026-09-14T21:00:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=360,
                    started="2026-09-14T19:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T21:00:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T19:00:00Z"),
        persist=True,
        now="2026-09-14T21:01:00Z",
        decision_index={},
    )
    assert "CLOSE" in _intents(cycle, "M15")
    assert "OPEN_SHORT" in _intents(cycle, "M15")


def test_open_short_closes_on_closed_bar_long_even_if_forming_still_short(
    tmp_path: Path, monkeypatch
):
    """Symmetric flip: open SHORT must OPEN_LONG when closed bar is LONG ACTIVE."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("SHORT")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-14T22:15:00Z",
                    bar_open="2026-09-14T22:00:00Z",
                    bar_close="2026-09-14T22:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T22:00:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=366,
                    started="2026-09-14T22:00:00Z",
                ),
                _life(
                    ts="2026-09-14T22:15:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=362,
                    started="2026-09-14T21:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T22:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T20:00:00Z"),
        persist=True,
        now="2026-09-14T22:16:00Z",
        decision_index={},
    )
    assert "CLOSE" in _intents(cycle, "M15")
    assert "OPEN_LONG" in _intents(cycle, "M15")


def test_open_long_holds_closed_observe_even_if_forming_still_long(
    tmp_path: Path, monkeypatch
):
    """OBSERVE_HOLD: closed OBSERVE keeps the LONG; forming LONG is not flatten authority."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-14T20:45:00Z",
                    bar_open="2026-09-14T20:30:00Z",
                    bar_close="2026-09-14T20:45:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-14T20:30:00Z",
                    tf="M15",
                    context="OBSERVE",
                    episode=361,
                    phase="NO_ACTIVE_CONTEXT",
                ),
                _life(
                    ts="2026-09-14T20:45:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=360,
                    started="2026-09-14T19:00:00Z",
                ),
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-14T20:45:00Z",
        sources=sources,
        feed=_feed_from("2026-09-14T19:00:00Z"),
        persist=True,
        now="2026-09-14T20:46:00Z",
        decision_index={},
    )
    assert "HOLD" in _intents(cycle, "M15")
    assert "CLOSE" not in _intents(cycle, "M15")
    assert "OPEN_SHORT" not in _intents(cycle, "M15")


def test_flat_open_blocks_strength_below_floor(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot(None)}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-16T07:00:00Z",
                    bar_open="2026-09-16T06:45:00Z",
                    bar_close="2026-09-16T07:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-16T06:45:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=360,
                    started="2026-09-16T03:15:00Z",
                    raw_status="ACTIVE",
                    process_strength=0.3,
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-16T07:00:00Z",
        sources=sources,
        feed=_feed_from("2026-09-16T05:00:00Z"),
        persist=True,
        now="2026-09-16T07:01:00Z",
        decision_index={},
    )
    assert "OPEN_LONG" not in _intents(cycle, "M15")
    assert PROCESS_STRENGTH_TOO_WEAK in _reasons(cycle, "M15")


def test_open_long_holds_weak_opposite_short(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    positions = {"M15": _slot("LONG")}
    monkeypatch.setattr(manager, "trader_views", _views_for(positions))
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-16T07:15:00Z",
                    bar_open="2026-09-16T07:00:00Z",
                    bar_close="2026-09-16T07:15:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-16T07:00:00Z",
                    tf="M15",
                    context="SHORT_CONTEXT",
                    episode=362,
                    started="2026-09-16T07:00:00Z",
                    raw_status="ACTIVE",
                    process_strength=0.3,
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-16T07:15:00Z",
        sources=sources,
        feed=_feed_from("2026-09-16T05:00:00Z"),
        persist=True,
        now="2026-09-16T07:16:00Z",
        decision_index={},
    )
    assert "HOLD" in _intents(cycle, "M15")
    assert "CLOSE" not in _intents(cycle, "M15")
    assert PROCESS_STRENGTH_TOO_WEAK in _reasons(cycle, "M15")
