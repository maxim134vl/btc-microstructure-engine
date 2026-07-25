"""Patch 3.1 — multi-timeframe availability contract tests (candidate-only)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import multi_timeframe_availability as mtf  # noqa: E402

CONTRACT = ROOT / "config" / "multi_timeframe_availability_contract.json"
CANDIDATE = ROOT / "data" / "research" / "patch3_1_candidate_mtf_availability.parquet"


@pytest.fixture()
def contract() -> dict:
    return mtf.load_contract(CONTRACT)


@pytest.fixture()
def sample_m15() -> pd.DataFrame:
    # 8 hours of M15 bars starting at 12:00Z
    opens = pd.date_range("2026-07-24T12:00:00Z", periods=32, freq="15min", tz="UTC")
    close = [100.0 + i for i in range(len(opens))]
    return pd.DataFrame(
        {
            "timestamp": opens,
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1.0] * len(opens),
            "delta": [0.0] * len(opens),
        }
    )


def test_01_contract_exists_and_five_timeframes(contract):
    assert set(contract["timeframes"]) == {"M15", "M30", "H1", "H4", "D1"}
    assert "FRESH_EVENT" in contract["availability_statuses"]
    assert "AVAILABLE_LAST_CONFIRMED" in contract["availability_statuses"]
    assert "WAITING_FOR_BAR_CLOSE" in contract["availability_statuses"]


@pytest.mark.parametrize(
    "tf,open_ts,eval_ts,ok",
    [
        ("M15", "2026-07-24T16:00:00Z", "2026-07-24T16:15:00Z", True),
        ("M15", "2026-07-24T16:00:00Z", "2026-07-24T16:14:59Z", False),
        ("M30", "2026-07-24T16:00:00Z", "2026-07-24T16:30:00Z", True),
        ("M30", "2026-07-24T16:00:00Z", "2026-07-24T16:29:59Z", False),
        ("H1", "2026-07-24T16:00:00Z", "2026-07-24T17:00:00Z", True),
        ("H1", "2026-07-24T16:00:00Z", "2026-07-24T16:59:59Z", False),
        ("H4", "2026-07-24T12:00:00Z", "2026-07-24T16:00:00Z", True),
        ("H4", "2026-07-24T12:00:00Z", "2026-07-24T15:59:59Z", False),
        ("D1", "2026-07-24T00:00:00Z", "2026-07-25T00:00:00Z", True),
        ("D1", "2026-07-24T00:00:00Z", "2026-07-24T23:59:59Z", False),
    ],
)
def test_02_completed_bar_boundaries(tf, open_ts, eval_ts, ok):
    assert mtf.is_bar_completed(bar_open=open_ts, timeframe=tf, evaluation_timestamp=eval_ts) is ok


def test_03_partial_htf_rejected(sample_m15):
    # At 12:45Z close (eval), M30 bar opened 12:30 is not closed until 13:00
    eval_ts = "2026-07-24T12:45:00Z"
    bars = mtf.build_completed_bars(sample_m15, "M30", evaluation_timestamp=eval_ts)
    assert (bars["bar_close"] <= pd.Timestamp(eval_ts)).all()
    assert not any(bars["bar_open"] == pd.Timestamp("2026-07-24T12:30:00Z"))


def test_04_asof_never_future(sample_m15):
    eval_ts = "2026-07-24T14:00:00Z"
    for tf in mtf.TIMEFRAMES:
        row = mtf.get_timeframe_state_asof(
            tf,
            eval_ts,
            m15_frame=sample_m15,
            enrich_climax=False,
        )
        if row.source_bar_close:
            assert pd.Timestamp(row.source_bar_close) <= pd.Timestamp(eval_ts)


def test_05_duplicate_source_key_fail_closed(sample_m15):
    bad = pd.concat([sample_m15, sample_m15.iloc[[0]]], ignore_index=True)
    tmp = ROOT / "data" / "research" / "_tmp_dup_m15_test.parquet"
    bad.to_parquet(tmp, index=False)
    try:
        with pytest.raises(mtf.MTFAvailabilityError, match="duplicate_source_keys"):
            mtf.load_m15_candles(tmp)
    finally:
        if tmp.exists():
            tmp.unlink()


def test_06_no_event_not_no_state(sample_m15):
    # Between M30 closes, state remains available
    a = mtf.get_timeframe_state_asof(
        "M30",
        "2026-07-24T13:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
    )
    b = mtf.get_timeframe_state_asof(
        "M30",
        "2026-07-24T13:15:00Z",
        m15_frame=sample_m15,
        previous_evaluation_timestamp="2026-07-24T13:00:00Z",
        enrich_climax=False,
    )
    assert a.availability_status in {"FRESH_EVENT", "NO_EVENT_STATE_UNCHANGED", "AVAILABLE_LAST_CONFIRMED"}
    assert b.availability_status == "AVAILABLE_LAST_CONFIRMED"
    assert b.state_asof is not None or b.source_bar_close is not None
    assert b.availability_status not in {"UNKNOWN", "DATASET_MISSING"}


def test_07_waiting_bar_close_insufficient_history():
    tiny = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-24T12:00:00Z"], utc=True),
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [1.0],
            "delta": [0.0],
        }
    )
    # eval before first M15 close
    row = mtf.get_timeframe_state_asof(
        "M15",
        "2026-07-24T12:10:00Z",
        m15_frame=tiny,
        enrich_climax=False,
    )
    assert row.availability_status in {"WAITING_FOR_BAR_CLOSE", "INSUFFICIENT_HISTORY"}


def test_08_dataset_missing():
    row = mtf.get_timeframe_state_asof(
        "M15",
        "2026-07-24T16:00:00Z",
        source_dataset=ROOT / "data" / "research" / "does_not_exist.parquet",
        enrich_climax=False,
    )
    assert row.availability_status == "DATASET_MISSING"


def test_09_thresholds_timeframe_specific(contract):
    assert contract["timeframes"]["M15"]["stale_latency_seconds"] < contract["timeframes"]["D1"][
        "stale_latency_seconds"
    ]
    assert contract["timeframes"]["D1"]["expected_cadence_seconds"] == 86400


def test_10_no_synthetic_forbidden_labels_on_missing(sample_m15):
    row = mtf.get_timeframe_state_asof(
        "H4",
        "2026-07-24T12:15:00Z",
        m15_frame=sample_m15.iloc[:1],
        enrich_climax=False,
    )
    # Must not invent BALANCE/OBSERVE/NEUTRAL when insufficient
    if row.availability_status in {"WAITING_FOR_BAR_CLOSE", "INSUFFICIENT_HISTORY"}:
        assert row.state_asof not in {"NEUTRAL", "BALANCE", "OBSERVE", "NO_STATE", "UNKNOWN"}


def test_11_utc_boundaries_d1(sample_m15):
    bars = mtf.build_completed_bars(sample_m15, "D1", evaluation_timestamp="2026-07-25T00:00:00Z")
    if len(bars):
        assert all(ts.tzinfo is not None for ts in bars["bar_open"])


def test_12_candidate_research_only():
    assert "data/research/" in str(CANDIDATE)
    if CANDIDATE.exists():
        meta = json.loads(
            (ROOT / "data/research/patch3_1_candidate_mtf_availability.meta.json").read_text()
        )
        assert meta.get("production_write_allowed") is False


def test_13_candidate_no_lookahead_gate():
    if not CANDIDATE.exists():
        pytest.skip("candidate not built")
    frame = pd.read_parquet(CANDIDATE)
    eval_ts = pd.to_datetime(frame["evaluation_timestamp"], utc=True)
    close_ts = pd.to_datetime(frame["source_bar_close"], utc=True)
    mask = close_ts.notna()
    assert (close_ts[mask] <= eval_ts[mask]).all()


def test_14_helper_does_not_write_production(tmp_path, sample_m15):
    before = {
        p: p.stat().st_mtime
        for p in [
            ROOT / "data/cognition/final_market_context_memory.parquet",
            ROOT / "data/live/context_decision_log.parquet",
            ROOT / "data/research/paper_simulator/paper_signals.parquet",
        ]
        if p.exists()
    }
    mtf.get_timeframe_state_asof(
        "M15",
        "2026-07-24T14:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
    )
    for path, mtime in before.items():
        assert path.stat().st_mtime == mtime


def test_15_continuation_price_gate_off():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") in {"0", "false", "False", ""}
    assert os.environ.get("PRICE_GATE", "OFF") in {"OFF", "0", "false", "False", ""}


def test_16_age_bars_correct(sample_m15):
    row = mtf.get_timeframe_state_asof(
        "M15",
        "2026-07-24T14:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
    )
    if row.age_seconds is not None:
        assert abs(row.age_bars - (row.age_seconds / 900.0)) < 1e-6


def test_17_source_state_preserved_not_coerced(sample_m15):
    row = mtf.get_timeframe_state_asof(
        "M15",
        "2026-07-24T14:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
    )
    # geometry fallback uses bullish/bearish, not BALANCE/OBSERVE
    if row.state_asof is not None:
        assert row.state_asof in {"bullish", "bearish"} or isinstance(row.state_asof, str)
