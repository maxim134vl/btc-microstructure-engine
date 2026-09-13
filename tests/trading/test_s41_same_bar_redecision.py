"""S4.1 must not re-decide CLOSE/OPEN on a restated same closed bar.

Locks the 2026-09-13 M30 incident: CLOSE+OPEN_SHORT on the 19:30 bar, then a
19:45 manager tick with the same source_bar_close and restated LONG must HOLD
the short. The next M30 close may CLOSE. Not wait-one-bar OPEN, not hold=3.
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
    SAME_CLOSED_BAR_ALREADY_ACTED,
    TimeframeManager,
    _same_closed_bar_already_actioned,
    with_bar_close,
)
from btc_ml.trading.timeframe_state_adapter import TimeframeSources


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


def _life(*, ts: str, tf: str, context: str, episode: int, started: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "timeframe": tf,
        "active_market_context": context,
        "lifecycle_state": "ACTIVE",
        "context_episode_id": episode,
        "active_context_started_at": started or ts,
        "context_origin_price": 77200.0,
    }


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
    }
    assert not _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T19:30:00Z",
        evaluation_timestamp="2026-09-13T19:30:00Z",
    )
    assert _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T19:30:00Z",
        evaluation_timestamp="2026-09-13T19:45:00Z",
    )
    assert not _same_closed_bar_already_actioned(
        state,
        source_bar_close="2026-09-13T20:00:00Z",
        evaluation_timestamp="2026-09-13T20:00:00Z",
    )


def test_m30_restated_opposite_on_same_bar_does_not_close_short(tmp_path: Path, monkeypatch):
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
    assert "CLOSE" not in _m30_intents(second)
    assert "OPEN_LONG" not in _m30_intents(second)
    assert "OPEN_SHORT" not in _m30_intents(second)
    assert SAME_CLOSED_BAR_ALREADY_ACTED in _m30_reasons(second)

    third = manager.run_cycle(
        evaluation_timestamp="2026-09-13T20:00:00Z",
        sources=_sources(
            evaluation="2026-09-13T20:00:00Z",
            bar_open="2026-09-13T19:30:00Z",
            bar_close="2026-09-13T20:00:00Z",
            context="LONG_CONTEXT",
            episode=110,
            started="2026-09-13T09:00:00Z",
        ),
        feed=feed,
        persist=True,
        now="2026-09-13T20:00:14Z",
        decision_index={},
    )
    assert "CLOSE" in _m30_intents(third)


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
