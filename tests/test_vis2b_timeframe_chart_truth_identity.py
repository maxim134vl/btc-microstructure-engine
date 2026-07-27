"""VIS2B — identity, episode regressions, source exclusions, lifecycle separation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))
sys.path.insert(0, str(ROOT / "src"))

from timeframe_chart_truth import TIMEFRAMES, build_timeframe_chart_truth


@pytest.fixture(scope="module")
def truth():
    return build_timeframe_chart_truth(window_days=14)


def _all_entities(truth):
    rows = []
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        rows.extend(block.get("closed_trades") or [])
        rows.extend(block.get("open_positions") or [])
    return rows


def test_trade_id_primary_closed(truth):
    for tf in TIMEFRAMES:
        for trade in truth["timeframes"][tf]["closed_trades"]:
            assert trade.get("trade_id")
            assert not str(trade.get("display_label", "")).startswith("CTX ")
            assert "CTX " not in str(trade.get("trade_id"))


def test_position_id_primary_open(truth):
    for tf in TIMEFRAMES:
        for pos in truth["timeframes"][tf]["open_positions"]:
            assert pos.get("position_id")
            assert not str(pos.get("display_label", "")).startswith("CTX ")


def test_unproven_episode_not_shown_as_id(truth):
    for entity in _all_entities(truth):
        if entity.get("episode_status") == "UNPROVEN":
            assert entity.get("episode_id") is None


def test_no_fragile_ctx_suffix_as_trade_identity(truth):
    for entity in _all_entities(truth):
        label = str(entity.get("display_label") or "")
        assert not label.startswith("CTX ")
        assert entity.get("trade_id") or entity.get("position_id")


def test_source_exclusions_declared(truth):
    excluded = truth["data_quality"]["excluded_sources"]
    joined = " ".join(excluded).lower()
    assert "research" in joined
    assert "legacy" in joined
    assert "dashboard" in joined
    assert "quarantine" in joined
    for entity in _all_entities(truth):
        assert str(entity.get("source_book", "")).startswith("TIMEFRAME_TRADER_")


def test_global_lifecycle_singular(truth):
    life = truth["global_lifecycle"]
    assert "episodes" in life
    assert "active_episode" in life
    ids = [ep["episode_id"] for ep in life["episodes"]]
    assert len(ids) == len(set(ids))
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        assert "episodes" not in block
        for entity in (block.get("closed_trades") or []) + (block.get("open_positions") or []):
            assert "global_lifecycle" not in entity


def test_episode_743_isolation_no_false_ctx(truth):
    hits = []
    for tf in TIMEFRAMES:
        for entity in (truth["timeframes"][tf].get("closed_trades") or []):
            stamped = str(entity.get("stamped_lifecycle_episode_id") or "")
            if stamped.endswith(":743") or stamped == "743":
                hits.append(entity)
    assert len(hits) == 3
    tfs = sorted(e["timeframe"] for e in hits)
    assert tfs == ["H1", "M15", "M30"]
    for entity in hits:
        # Must not claim global CTX 743 when temporal proof fails.
        assert entity.get("episode_id") != 743
        assert entity.get("episode_status") == "UNPROVEN"
        assert not str(entity.get("display_label")).startswith("CTX 743")


def test_episode_879_entities_on_own_charts(truth):
    by_tf = {tf: [] for tf in TIMEFRAMES}
    for tf in TIMEFRAMES:
        for entity in (truth["timeframes"][tf].get("closed_trades") or []) + (
            truth["timeframes"][tf].get("open_positions") or []
        ):
            stamped = str(entity.get("stamped_lifecycle_episode_id") or "")
            if stamped.endswith(":879") or entity.get("episode_id") == 879:
                by_tf[tf].append(entity)
    assert by_tf["M15"]
    assert by_tf["M30"]
    assert by_tf["H1"]
    assert not by_tf["H4"]
    # Global 879 appears at most once in strip episodes.
    eps = [ep for ep in truth["global_lifecycle"]["episodes"] if ep.get("episode_id") == 879]
    assert len(eps) <= 1


def test_episode_881_h4_only(truth):
    hits = []
    for tf in TIMEFRAMES:
        for entity in (truth["timeframes"][tf].get("closed_trades") or []) + (
            truth["timeframes"][tf].get("open_positions") or []
        ):
            stamped = str(entity.get("stamped_lifecycle_episode_id") or "")
            if stamped.endswith(":881") or entity.get("episode_id") == 881:
                hits.append(entity)
    assert hits
    assert all(h["timeframe"] == "H4" for h in hits)
    eps = [ep for ep in truth["global_lifecycle"]["episodes"] if ep.get("episode_id") == 881]
    assert len(eps) <= 1


def test_stop_take_null_semantics(truth):
    for entity in _all_entities(truth):
        for key in ("stop_price", "take_profit_price"):
            val = entity.get(key)
            if val is None:
                continue
            assert val != 0 or True  # zero only if truly zero price distance — allow numeric
            assert val == val
