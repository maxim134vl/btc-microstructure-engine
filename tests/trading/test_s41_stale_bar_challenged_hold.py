"""S4.1 late-OPEN / CHALLENGED-hold / OBSERVE-close / bookkeeping contract.

Locks the M30 2026-09-13 one-bar short: do not OPEN after the next TF bar
has already closed; do not inherit the next bar's open-stamped lifecycle
row; do not CLOSE on opposite CHALLENGED; CLOSE on OBSERVE via S4.1.
Do not restore candle-close exit, hold=3, or journal flatten.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts" / "live") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "live"))

from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
from btc_ml.trading.proofs import isolated_environment, synthetic_command
from btc_ml.trading.timeframe_manager import TimeframeManager, _preview_context_for_open_position
from btc_ml.trading.timeframe_state_adapter import (
    NO_LIFECYCLE_ROW_FOR_CLOSED_BAR,
    STALE_CLOSED_BAR_SUPERSEDED,
    TimeframeSources,
    closed_bar_superseded,
    resolve_timeframe_state,
)
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
import bounded_paper_trading_controller_auto_ledger_no_real_execution as ctrl


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


def _life(*, ts: str, tf: str, context: str, episode: int, phase: str = "ACTIVE", started: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "timeframe": tf,
        "active_market_context": context,
        "lifecycle_state": phase,
        "context_episode_id": episode,
        "active_context_started_at": started or ts,
        "context_origin_price": 77000.0,
    }


def _sources(availability: list[dict], lifecycle: list[dict]) -> TimeframeSources:
    return TimeframeSources(
        availability=pd.DataFrame(availability),
        lifecycle=pd.DataFrame(lifecycle),
        lifecycle_source="parquet",
    )


def test_next_bar_open_stamp_is_not_this_bar():
    """08:30 SHORT row is the 08:30-09:00 bar, not the bar that closed 08:30."""
    sources = _sources(
        [
            _availability(
                tf="M30",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T08:00:00Z",
                bar_close="2026-09-13T08:30:00Z",
            )
        ],
        [
            _life(ts="2026-09-13T08:00:00Z", tf="M30", context="OBSERVE", episode=163, phase="NO_ACTIVE_CONTEXT"),
            _life(ts="2026-09-13T08:30:00Z", tf="M30", context="SHORT_CONTEXT", episode=164, started="2026-09-13T08:00:00Z"),
        ],
    )
    state = resolve_timeframe_state(
        timeframe="M30",
        evaluation_timestamp="2026-09-13T08:45:00Z",
        sources=sources,
    )
    assert state["timeframe_state"] == "OBSERVE"
    assert state["actionable"] is False
    assert state["lifecycle_episode_id"] == "M30:163"


def test_missing_this_bar_row_does_not_inherit_previous():
    sources = _sources(
        [
            _availability(
                tf="M30",
                evaluation="2026-09-13T09:15:00Z",
                bar_open="2026-09-13T08:30:00Z",
                bar_close="2026-09-13T09:00:00Z",
            )
        ],
        [
            _life(ts="2026-09-13T08:00:00Z", tf="M30", context="OBSERVE", episode=163, phase="NO_ACTIVE_CONTEXT"),
        ],
    )
    state = resolve_timeframe_state(
        timeframe="M30",
        evaluation_timestamp="2026-09-13T09:15:00Z",
        sources=sources,
    )
    assert state["actionable"] is False
    assert state["timeframe_state"] == "UNKNOWN"
    assert state["no_action_reason"] == NO_LIFECYCLE_ROW_FOR_CLOSED_BAR


def test_this_bar_open_stamp_is_used():
    sources = _sources(
        [
            _availability(
                tf="M30",
                evaluation="2026-09-13T09:00:00Z",
                bar_open="2026-09-13T08:30:00Z",
                bar_close="2026-09-13T09:00:00Z",
            )
        ],
        [
            _life(ts="2026-09-13T08:30:00Z", tf="M30", context="SHORT_CONTEXT", episode=164, started="2026-09-13T08:00:00Z"),
        ],
    )
    state = resolve_timeframe_state(
        timeframe="M30",
        evaluation_timestamp="2026-09-13T09:00:00Z",
        sources=sources,
    )
    assert state["actionable"] is True
    assert state["timeframe_state"] == "SHORT_CONTEXT"
    assert state["lifecycle_episode_id"] == "M30:164"


def test_stale_closed_bar_blocks_open_not_lifecycle_fields():
    sources = _sources(
        [
            _availability(
                tf="M30",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T08:00:00Z",
                bar_close="2026-09-13T08:30:00Z",
            )
        ],
        [
            _life(ts="2026-09-13T08:00:00Z", tf="M30", context="SHORT_CONTEXT", episode=164, started="2026-09-13T08:00:00Z"),
        ],
    )
    fresh = resolve_timeframe_state(
        timeframe="M30",
        evaluation_timestamp="2026-09-13T08:45:00Z",
        sources=sources,
        now="2026-09-13T08:46:00Z",
    )
    assert fresh["actionable"] is True
    late = resolve_timeframe_state(
        timeframe="M30",
        evaluation_timestamp="2026-09-13T08:45:00Z",
        sources=sources,
        now="2026-09-13T09:00:14Z",
    )
    assert late["actionable"] is False
    assert late["no_action_reason"] == STALE_CLOSED_BAR_SUPERSEDED
    assert late["timeframe_state"] == "SHORT_CONTEXT"
    assert closed_bar_superseded(
        timeframe="M30",
        source_bar_close="2026-09-13T08:30:00Z",
        now="2026-09-13T09:00:00Z",
    )
    assert not closed_bar_superseded(
        timeframe="M30",
        source_bar_close="2026-09-13T08:30:00Z",
        now="2026-09-13T08:59:59Z",
    )


def test_manager_does_not_open_stale_m30_short(tmp_path: Path):
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    sources = _sources(
        [
            _availability(
                tf="M15",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T08:30:00Z",
                bar_close="2026-09-13T08:45:00Z",
            ),
            _availability(
                tf="M30",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T08:00:00Z",
                bar_close="2026-09-13T08:30:00Z",
            ),
            _availability(
                tf="H1",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T07:00:00Z",
                bar_close="2026-09-13T08:00:00Z",
            ),
            _availability(
                tf="H4",
                evaluation="2026-09-13T08:45:00Z",
                bar_open="2026-09-13T04:00:00Z",
                bar_close="2026-09-13T08:00:00Z",
            ),
        ],
        [
            _life(ts="2026-09-13T08:00:00Z", tf="M30", context="SHORT_CONTEXT", episode=164, started="2026-09-13T08:00:00Z"),
            _life(ts="2026-09-13T08:30:00Z", tf="M15", context="OBSERVE", episode=1, phase="NO_ACTIVE_CONTEXT"),
            _life(ts="2026-09-13T07:00:00Z", tf="H1", context="OBSERVE", episode=1, phase="NO_ACTIVE_CONTEXT"),
            _life(ts="2026-09-13T04:00:00Z", tf="H4", context="OBSERVE", episode=1, phase="NO_ACTIVE_CONTEXT"),
        ],
    )
    feed = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-09-13T08:30:00Z"], utc=True),
            "open": [77000.0],
            "high": [77100.0],
            "low": [76900.0],
            "close": [77050.0],
            "volume": [10.0],
            "bar_close": pd.to_datetime(["2026-09-13T08:45:00Z"], utc=True),
        }
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-09-13T08:45:00Z",
        sources=sources,
        feed=feed,
        persist=True,
        now="2026-09-13T09:00:14Z",
        decision_index={},
    )
    by_tf = {cmd["timeframe"]: cmd for cmd in cycle["commands"]}
    assert by_tf["M30"]["intent"] != "OPEN_SHORT"
    assert STALE_CLOSED_BAR_SUPERSEDED in str(by_tf["M30"]["reason_codes"])


def test_challenged_opposite_holds_active_opposite_closes():
    challenged = ctrl.evaluate_exit_preview(
        side="SHORT",
        entry_price=76778.8,
        quantity=1.0,
        stop_loss_price=77000.0,
        take_profit_price=76000.0,
        entry_fee_usd=0.1,
        current_price=76645.0,
        latest_high=76700.0,
        latest_low=76600.0,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="CHALLENGED",
    )
    assert challenged["is_close"] is False
    assert "HOLD" in challenged["exit_preview_action"]
    active = ctrl.evaluate_exit_preview(
        side="SHORT",
        entry_price=76778.8,
        quantity=1.0,
        stop_loss_price=77000.0,
        take_profit_price=76000.0,
        entry_fee_usd=0.1,
        current_price=76645.0,
        latest_high=76700.0,
        latest_low=76600.0,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert active["is_close"] is True
    assert "CONTEXT_FLIP_SHORT_TO_LONG" in active["exit_preview_reason"]


def test_observe_closes_open_short_via_s41_not_journal():
    assert _preview_context_for_open_position("SHORT", "OBSERVE") == "OBSERVE"
    end = ctrl.evaluate_exit_preview(
        side="SHORT",
        entry_price=76778.8,
        quantity=1.0,
        stop_loss_price=77000.0,
        take_profit_price=76000.0,
        entry_fee_usd=0.1,
        current_price=76645.0,
        latest_high=76700.0,
        latest_low=76600.0,
        latest_context="OBSERVE",
        latest_lifecycle_state="NO_ACTIVE_CONTEXT",
    )
    assert end["is_close"] is True
    assert "CONTEXT_END_EVENT_SHORT" in end["exit_preview_reason"]
    assert "CONTEXT_FLIP" not in end["exit_preview_reason"]


def test_consumer_marks_stale_open_processed(tmp_path: Path):
    bus, _books, _ = isolated_environment(tmp_path / "bus")
    command = synthetic_command(
        timeframe="M30",
        intent="OPEN_SHORT",
        evaluation_timestamp="2026-09-13T08:45:00Z",
        episode="M30:164",
    )
    command["source_bar_close"] = "2026-09-13T08:30:00Z"
    command["action_allowed"] = True
    bus.append([command])

    class _Cfg:
        timeframes = ("M30",)
        max_bbo_age_ms = 2000.0

    class _Engine:
        cfg = _Cfg()
        bbo = type(
            "BBO",
            (),
            {"resolve_live_local_entry_bbo": staticmethod(lambda **_k: (object(), None, 0.0, "local"))},
        )()

        def execution_market_ready_for_entry(self) -> bool:
            return True

        def apply_s41_manager_command(self, _command: dict) -> dict:
            raise AssertionError("stale OPEN must not be applied")

    consumer = S41CommandConsumer(
        _Engine(),
        checkpoint_path=tmp_path / "s41_command_cursor.json",
        consume_after=None,
        bus=bus,
    )
    actions = consumer.poll(now="2026-09-13T09:00:14Z")
    assert actions
    assert actions[0]["status"] == f"ENTRY_BLOCKED_{STALE_CLOSED_BAR_SUPERSEDED}"
    stored = json.loads((tmp_path / "s41_command_cursor.json").read_text(encoding="utf-8"))
    assert command["command_id"] in stored.get("processed_command_ids", [])
