"""Trade-render fix — adapter ordinals, TF isolation, historical context segments."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))
sys.path.insert(0, str(ROOT / "src"))

from timeframe_chart_truth import (  # noqa: E402
    CANDIDATE_DIR,
    TIMEFRAMES,
    assert_entities_tf_isolated,
    assign_tf_ordinals,
    build_tf_context_segments,
    build_timeframe_chart_truth,
)


@pytest.fixture(scope="module")
def truth():
    return build_timeframe_chart_truth(window_days=7)


def test_candidate_dir_and_schema(truth):
    assert "vis_trade_render_context_fix" in str(CANDIDATE_DIR)
    assert truth["schema_version"] == "timeframe_chart_truth_v4"
    assert truth["visual_contract"]["trade_public_numbers"] is True
    assert truth["visual_contract"]["per_tf_context_bands"] is True
    assert truth["visual_contract"]["global_lifecycle_strip"] is False


def test_stable_ordinals_tf_n(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        entities = (block.get("closed_trades") or []) + (block.get("open_positions") or [])
        if not entities:
            continue
        ordered = sorted(
            entities,
            key=lambda e: (
                e.get("entry_timestamp") or "",
                e.get("created_at") or e.get("entry_timestamp") or "",
                e.get("trade_id") or e.get("position_id") or "",
            ),
        )
        assert ordered[0]["public_number"] == f"{tf}_1"
        assert ordered[0]["display_label"] == f"{tf}_1"
        for e in entities:
            assert e["public_number"] == e["display_label"]
            assert e["public_number"].startswith(f"{tf}_")
            assert " · " not in e["public_number"]
            assert "e3ee" not in e["public_number"].lower()
        # Deterministic rebuild
        closed = [dict(e) for e in (block.get("closed_trades") or [])]
        opens = [dict(e) for e in (block.get("open_positions") or [])]
        for e in closed + opens:
            e["public_number"] = None
            e["display_label"] = None
            e["ordinal"] = None
        assign_tf_ordinals(tf, closed_trades=closed, open_positions=opens)
        rebuilt = {(e.get("trade_id") or e.get("position_id")): e["public_number"] for e in closed + opens}
        original = {(e.get("trade_id") or e.get("position_id")): e["public_number"] for e in entities}
        assert rebuilt == original


def test_context_history_per_tf_isolated(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        segs = block.get("context_segments") or []
        assert segs == (block.get("context_history") or [])
        assert block.get("context_source") == "timeframe_command_memory"
        assert len(segs) >= 1
        for seg in segs:
            assert seg["timeframe"] == tf
            assert seg.get("start_timestamp")
            assert seg.get("end_timestamp")
            assert seg.get("directional_state")
            assert seg.get("source") == "timeframe_command_memory"
        if tf in ("M15", "M30", "H1"):
            assert len(segs) > 1


def test_trade_isolation_zero_foreign(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        assert block.get("contamination") == []
        for entity in (block.get("closed_trades") or []) + (block.get("open_positions") or []):
            assert entity["timeframe"] == tf


def test_context_builder_and_contamination_assert():
    m15 = build_tf_context_segments("M15")
    assert m15 and all(s["timeframe"] == "M15" for s in m15)
    bad = assert_entities_tf_isolated([{"timeframe": "H1", "trade_id": "x"}], timeframe="M15")
    assert len(bad) == 1
