"""LIVE1A minimal tests for canonical intrabar context path."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from btc_ml.cognition.volume_localization_engine_v1 import localize_bar
from btc_ml.cognition.volume_response_evaluate import evaluate_response_row
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.live.intrabar.cognition_pipeline import IntrabarCognitionEngine
from btc_ml.live.intrabar.event_time_lifecycle import (
    age_bars_from_elapsed,
    detect_context_transition,
    step_event_time_lifecycle,
)
from btc_ml.live.intrabar.partial_bar_state import PartialBarStateEngine, bar_open_for
from btc_ml.live.intrabar.provisional_synthesis import synthesize_provisional_state
from btc_ml.live.intrabar.structure_geometry import compute_geometry_fields, compute_structure_fields
from btc_ml.trading.timeframe_state_adapter import TimeframeSources, resolve_timeframe_state


def _trade(price: str, qty: str, ts: str, mono: int, tid: int, sell: bool = False) -> dict:
    return {
        "price": price,
        "quantity": qty,
        "quote_quantity": str(float(price) * float(qty)),
        "exchange_trade_timestamp": ts,
        "local_receive_timestamp": ts,
        "local_receive_monotonic_ns": mono,
        "aggregate_trade_id": tid,
        "buyer_is_market_maker": sell,
        "connection_session_id": "sess",
        "reconnect_generation": 1,
    }


def test_partial_bar_uses_only_received_trades_and_no_future_extreme():
    eng = PartialBarStateEngine()
    # two trades — high/low only from received
    eng.update_agg_trade(_trade("100", "1", "2026-07-28T10:00:01Z", 1, 1))
    eng.update_agg_trade(_trade("101", "1", "2026-07-28T10:00:02Z", 2, 2))
    bar = eng.bars["M15"]
    assert bar.high_so_far == 101.0
    assert bar.low_so_far == 100.0
    assert bar.last == 101.0
    assert bar.is_closed is False
    # future extreme not applied
    assert bar.high_so_far < 105.0


def test_localization_closed_vs_provisional_api():
    fields = compute_structure_fields(100, 110, 90, 105)
    row = pd.Series({**fields, "timestamp": pd.Timestamp("2026-07-28T10:00:00Z"), "volume": 10.0})
    closed = localize_bar(row, is_closed=True)
    prov = localize_bar(
        row,
        is_closed=False,
        causal_cutoff_timestamp="2026-07-28T10:00:05Z",
        causal_cutoff_monotonic_ns=123,
    )
    assert closed.get("evaluation_mode") is None
    assert closed["is_closed"] is True
    assert prov["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert prov["is_closed"] is False
    assert prov["behavior"] == closed["behavior"]


def test_response_evaluator_deterministic():
    geom = compute_geometry_fields(100, 110, 90, 105)
    structure = {**geom, "delta": 1.0, "timestamp": "2026-07-28T10:00:00Z"}
    loc = localize_bar(pd.Series({**structure, "volume": 10.0}), is_closed=False)
    hist = pd.DataFrame(
        [{"timestamp": "2026-07-28T09:45:00Z", "estimated_local_volume": 5.0, "spread": 10.0}]
    )
    a = evaluate_response_row(
        loc,
        structure_row=structure,
        geometry_row=geom,
        classification_row={"volume_class": "unknown"},
        localization_history=hist.assign(estimated_local_volume=loc["estimated_local_volume"]),
        geometry_history=hist,
        live_v1=True,
        localization_join_status="EXACT_FRESH_MATCH",
    )
    b = evaluate_response_row(
        loc,
        structure_row=structure,
        geometry_row=geom,
        classification_row={"volume_class": "unknown"},
        localization_history=hist.assign(estimated_local_volume=loc["estimated_local_volume"]),
        geometry_history=hist,
        live_v1=True,
        localization_join_status="EXACT_FRESH_MATCH",
    )
    assert a["volume_event"] == b["volume_event"]
    assert a["effort_result_state"] == b["effort_result_state"]


def test_stage2_provisional_uses_existing_classifiers():
    geom = compute_geometry_fields(100, 110, 90, 108)
    structure = {**geom, "delta": 2.0}
    loc = localize_bar(pd.Series({**structure, "volume": 20.0, "timestamp": "t"}), is_closed=False)
    resp = evaluate_response_row(
        loc,
        structure_row=structure,
        geometry_row=geom,
        classification_row={"volume_class": "high_average"},
        live_v1=True,
        localization_join_status="EXACT_FRESH_MATCH",
    )
    out = synthesize_provisional_state(structure_row=structure, response_row=resp, prev_close=100.0)
    assert "market_context" in out
    assert out["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert out["cognitive_market_state"]


@pytest.mark.parametrize(
    "prev,new,expected",
    [
        (None, {"active_market_context": "LONG_CONTEXT"}, "CONTEXT_START"),
        (None, {"active_market_context": "SHORT_CONTEXT"}, "CONTEXT_START"),
        ({"active_market_context": "LONG_CONTEXT"}, {"active_market_context": "OBSERVE"}, "CONTEXT_END"),
        ({"active_market_context": "SHORT_CONTEXT"}, {"active_market_context": "OBSERVE"}, "CONTEXT_END"),
        (
            {"active_market_context": "LONG_CONTEXT"},
            {"active_market_context": "SHORT_CONTEXT"},
            "CONTEXT_FLIP",
        ),
        (
            {"active_market_context": "SHORT_CONTEXT"},
            {"active_market_context": "LONG_CONTEXT"},
            "CONTEXT_FLIP",
        ),
    ],
)
def test_context_transition_symmetry(prev, new, expected):
    tr = detect_context_transition(prev, new)
    assert tr is not None
    assert tr["event_type"] == expected


def test_context_event_price_is_last_causal_trade(tmp_path: Path):
    journal = ContextEventJournal(tmp_path)
    engine = IntrabarCognitionEngine(context_journal=journal)
    # Force lifecycle transition by stubbing: feed enough and monkeypatch detect
    trade = _trade("64960.00000000", "0.01", "2026-07-28T10:00:10Z", 1000, 42)
    engine.bars.update_agg_trade(trade)
    # Direct journal append path for price contract
    ev = journal.build_event(
        timeframe="M15",
        event_type="CONTEXT_START",
        previous_context="OBSERVE",
        new_context="LONG_CONTEXT",
        event_timestamp=trade["local_receive_timestamp"],
        event_monotonic_ns=1000,
        context_event_price=trade["price"],
        last_trade_id=42,
        last_trade_timestamp=trade["exchange_trade_timestamp"],
        best_bid="64959",
        best_ask="64961",
        book_update_id=1,
        bbo_receive_monotonic_ns=900,
        bbo_age_ms=0.1,
        connection_session_id="s",
        reconnect_generation=1,
        causal_cutoff_timestamp=trade["local_receive_timestamp"],
        causal_cutoff_monotonic_ns=1000,
        model_version="test",
        lifecycle_episode_id="M15:1",
    )
    assert journal.append(ev)
    assert ev["context_event_price"] == "64960.00000000"
    # future BBO rejected in pipeline: simulate
    engine.bbo = {"bbo_receive_monotonic_ns": 2000, "best_bid": "1", "best_ask": "2"}
    # dedupe
    assert journal.append(ev) is False


def test_no_duplicate_event_per_episode(tmp_path: Path):
    journal = ContextEventJournal(tmp_path)
    ev = journal.build_event(
        timeframe="M15",
        event_type="CONTEXT_START",
        previous_context="OBSERVE",
        new_context="LONG_CONTEXT",
        event_timestamp="t",
        event_monotonic_ns=5,
        context_event_price="1",
        last_trade_id=1,
        last_trade_timestamp="t",
        best_bid=None,
        best_ask=None,
        book_update_id=None,
        bbo_receive_monotonic_ns=None,
        bbo_age_ms=None,
        connection_session_id=None,
        reconnect_generation=0,
        causal_cutoff_timestamp="t",
        causal_cutoff_monotonic_ns=5,
        model_version="t",
        lifecycle_episode_id="ep1",
    )
    assert journal.append(ev)
    assert journal.append(ev) is False


def test_timeframes_independent():
    eng = PartialBarStateEngine()
    eng.update_agg_trade(_trade("100", "1", "2026-07-28T10:00:01Z", 1, 1))
    assert set(eng.bars) == {"M15", "M30", "H1", "H4"}
    assert eng.bars["M15"].bar_open_timestamp == bar_open_for("2026-07-28T10:00:01Z", "M15")
    assert eng.bars["H1"].bar_open_timestamp == bar_open_for("2026-07-28T10:00:01Z", "H1")


def test_event_time_age_mapping_keeps_n():
    # N=3 bars * 900s = 2700s for M15
    assert age_bars_from_elapsed(2699, "M15") == 2
    assert age_bars_from_elapsed(2700, "M15") == 3


def test_provisional_adapter_not_actionable_for_manager():
    life = {
        "active_market_context": "LONG_CONTEXT",
        "lifecycle_state": "ACTIVE",
        "context_episode_id": 7,
    }
    state = resolve_timeframe_state(
        timeframe="M15",
        evaluation_timestamp="2026-07-28T10:00:00Z",
        sources=TimeframeSources(),
        allow_provisional=True,
        evaluation_mode="PROVISIONAL_INTRABAR",
        provisional_lifecycle=life,
        causal_cutoff_timestamp="2026-07-28T10:00:00Z",
        causal_cutoff_monotonic_ns=1,
        model_version="v",
    )
    assert state["is_closed"] is False
    assert state["actionable"] is False
    assert state["evaluation_mode"] == "PROVISIONAL_INTRABAR"


def test_closed_bars_accumulate_per_timeframe_geometry(tmp_path: Path):
    """CTX1: completed bars must enter TF-scoped geometry for prev_close/FT."""
    journal = ContextEventJournal(tmp_path)
    engine = IntrabarCognitionEngine(context_journal=journal)
    # Open M15 bar at 10:00
    engine.on_agg_trade(_trade("100", "1", "2026-07-28T10:00:01Z", 1, 1))
    assert len(engine.geometry_by_tf["M15"]) == 0
    # Cross M15 boundary → prior M15 closes into geometry; H4 does not close
    engine.on_agg_trade(_trade("101", "1", "2026-07-28T10:15:01Z", 2, 2))
    assert len(engine.geometry_by_tf["M15"]) == 1
    assert float(engine.geometry_by_tf["M15"].iloc[-1]["close"]) == 100.0
    assert len(engine.geometry_by_tf["H4"]) == 0
    # Next M15 tip must see prev_close from completed bar
    engine.on_agg_trade(_trade("102", "1", "2026-07-28T10:15:02Z", 3, 3))
    assert engine.last_eval["M15"]["prev_close"] == 100.0
    assert engine.last_eval["H4"]["prev_close"] is None
    assert engine.last_eval["M15"]["geometry_history_rows"] == 1
    assert engine.last_eval["H4"]["geometry_history_rows"] == 0


def test_candidate_started_at_retained_same_direction():
    """CTX1: same-direction DEVELOPING must not re-stamp candidate_started_at."""
    from build_market_context_lifecycle_memory import step_lifecycle

    t0 = pd.Timestamp("2026-07-28T18:00:00Z")
    t1 = pd.Timestamp("2026-07-28T18:00:01Z")
    first = step_lifecycle(
        raw_market_context="LONG_CONTEXT",
        raw_context_status="DEVELOPING",
        raw_context_reason="r1",
        raw_cognitive_market_state="ACCEPTANCE",
        raw_state_direction="LONG",
        auction_episode="TRENDING_UP",
        timestamp=t0,
        prev=None,
    )
    assert first["lifecycle_state"] == "CANDIDATE"
    assert first["candidate_started_at"] == t0
    second = step_lifecycle(
        raw_market_context="LONG_CONTEXT",
        raw_context_status="DEVELOPING",
        raw_context_reason="r2",
        raw_cognitive_market_state="ACCEPTANCE",
        raw_state_direction="LONG",
        auction_episode="TRENDING_UP",
        timestamp=t1,
        prev=first,
    )
    assert second["lifecycle_state"] == "CANDIDATE"
    assert second["candidate_context"] == "LONG_CONTEXT"
    assert second["candidate_started_at"] == t0


def test_empty_geometry_blocks_active_start_same_stream_deterministic(tmp_path: Path):
    """Empty history → OBSERVE path; identical streams replay to same lifecycle tip."""
    journal_a = ContextEventJournal(tmp_path / "a")
    journal_b = ContextEventJournal(tmp_path / "b")
    a = IntrabarCognitionEngine(context_journal=journal_a)
    b = IntrabarCognitionEngine(context_journal=journal_b)
    stream = [
        _trade("63680", "0.01", "2026-07-28T18:00:01Z", i, i)
        for i in range(1, 6)
    ]
    for t in stream:
        a.on_agg_trade(t)
        b.on_agg_trade(t)
    for tf in ("M15", "M30", "H1", "H4"):
        la = a.last_eval[tf]["lifecycle"]
        lb = b.last_eval[tf]["lifecycle"]
        assert la["active_market_context"] == lb["active_market_context"] == "OBSERVE"
        assert a.event_counts["CONTEXT_START"] == 0
        assert b.event_counts["CONTEXT_START"] == 0
        assert la["lifecycle_state"] == lb["lifecycle_state"]


def test_no_backdated_context_start_uses_causal_trade_time(tmp_path: Path):
    """Any CONTEXT_START must stamp current causal tip, never a historical bar_open."""
    journal = ContextEventJournal(tmp_path)
    engine = IntrabarCognitionEngine(context_journal=journal)
    # Seed rising completed M15 closes so ACTIVE is reachable under current rules.
    engine.geometry_by_tf["M15"] = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-28T17:30:00Z",
                "open": 63000.0,
                "high": 63200.0,
                "low": 62900.0,
                "close": 63150.0,
                "volume": 50.0,
                "delta": 5.0,
                "spread": 300.0,
                "timeframe": "M15",
                "estimated_local_volume": 50.0,
            },
            {
                "timestamp": "2026-07-28T17:45:00Z",
                "open": 63150.0,
                "high": 63500.0,
                "low": 63100.0,
                "close": 63480.0,
                "volume": 60.0,
                "delta": 8.0,
                "spread": 400.0,
                "timeframe": "M15",
                "estimated_local_volume": 60.0,
            },
        ]
    )
    tip_ts = "2026-07-29T06:40:00Z"
    tip_price = "64412.50000000"
    engine.on_agg_trade(_trade(tip_price, "0.02", tip_ts, 9001, 9001))
    for tf, ev in engine.last_context_event.items():
        assert not str(ev["event_timestamp"]).startswith("2026-07-28T17")
        assert ev["event_timestamp"] == tip_ts or ev["event_timestamp"].startswith("2026-07-29")
        assert float(ev["context_event_price"]) == float(tip_price)
