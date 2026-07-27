"""VIS2B — candle aggregation, confirmed-bar contract, TF isolation."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))
sys.path.insert(0, str(ROOT / "src"))

from multi_timeframe_availability import DURATION_S, build_completed_bars
from timeframe_chart_truth import TIMEFRAMES, build_timeframe_chart_truth, load_m15_feed


@pytest.fixture(scope="module")
def truth():
    return build_timeframe_chart_truth(window_days=7)


@pytest.fixture(scope="module")
def m15():
    return load_m15_feed()


def test_m15_source_unchanged_native(truth):
    block = truth["timeframes"]["M15"]["candle_contract"]
    assert block["source"].endswith("live_market_feed.parquet")
    assert block["aggregation"] == "native"
    assert block["confirmed_only"] is True
    assert block["timestamp_semantics"] == "BAR_OPEN"


def test_htf_uses_canonical_build_completed_bars(truth, m15):
    window_end = pd.Timestamp(truth["window_end"])
    for tf in ("M30", "H1", "H4"):
        expected = build_completed_bars(m15, tf, evaluation_timestamp=window_end)
        window_start = pd.Timestamp(truth["window_start"])
        closes = pd.to_datetime(expected["bar_close"], utc=True)
        expected = expected.loc[(closes >= window_start) & (closes <= window_end)]
        got = truth["timeframes"][tf]["candles"]
        assert truth["timeframes"][tf]["candle_contract"]["aggregation"] == f"build_completed_bars:{tf}"
        assert len(got) == len(expected)
        assert len(got) > 0
        tip = pd.Timestamp(got[-1]["timestamp"])
        assert tip == pd.Timestamp(expected["bar_open"].iloc[-1])
        close = pd.Timestamp(got[-1]["bar_close"])
        assert (close - tip).total_seconds() == DURATION_S[tf]


def test_partial_bars_excluded(truth, m15):
    window_end = pd.Timestamp(truth["window_end"])
    for tf in TIMEFRAMES:
        candles = truth["timeframes"][tf]["candles"]
        assert candles
        for c in candles:
            assert c["confirmed"] is True
            close = pd.Timestamp(c["bar_close"])
            assert close <= window_end


def test_ohlcv_finite_no_nan(truth):
    for tf in TIMEFRAMES:
        for c in truth["timeframes"][tf]["candles"]:
            for key in ("open", "high", "low", "close", "volume"):
                val = c[key]
                assert val is not None
                assert pd.notna(val)
                assert float(val) == float(val)  # not NaN
                assert abs(float(val)) != float("inf")


def test_shared_calendar_window(truth):
    assert truth["window_start"]
    assert truth["window_end"]
    start = pd.Timestamp(truth["window_start"])
    end = pd.Timestamp(truth["window_end"])
    assert end > start
    counts = {tf: len(truth["timeframes"][tf]["candles"]) for tf in TIMEFRAMES}
    assert counts["M15"] > counts["M30"] > counts["H1"] > counts["H4"] > 0


def test_tf_candle_isolation(truth):
    for tf in TIMEFRAMES:
        for other in TIMEFRAMES:
            if other == tf:
                continue
            # candles live only under own key
            assert other not in str(truth["timeframes"][tf].get("candle_contract", {}).get("timeframe"))


def test_tf_entity_isolation(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        for entity in (block.get("closed_trades") or []) + (block.get("open_positions") or []):
            assert entity["timeframe"] == tf
            for other in TIMEFRAMES:
                if other == tf:
                    continue
                tid = str(entity.get("trade_id") or "")
                pid = str(entity.get("position_id") or "")
                assert f"_{other}_" not in tid
                assert f"_{other}_" not in pid
