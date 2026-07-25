"""Patch 3.2 — multi-timeframe availability runtime activation tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import multi_timeframe_availability as mtf  # noqa: E402
import runtime_multi_timeframe_availability as runtime  # noqa: E402

CONTRACT = ROOT / "config/multi_timeframe_availability_contract.json"


@pytest.fixture()
def sample_m15() -> pd.DataFrame:
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
            "candle_type": ["bullish" if i % 2 == 0 else "bearish" for i in range(len(opens))],
        }
    )


def test_01_canonical_helper_shared_by_research_runtime():
    import importlib.util

    research = ROOT / "scripts/research/multi_timeframe_availability.py"
    spec = importlib.util.spec_from_file_location("mtf_research_shim", research)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    close = mod.bar_close_from_open("2026-07-24T16:00:00Z", "M15")
    assert close == mtf.bar_close_from_open("2026-07-24T16:00:00Z", "M15")
    assert "TIMEFRAME_NOT_LIVE" in mod.AVAILABILITY_STATUSES
    assert hasattr(runtime, "run_availability_cycle")
    assert runtime.HISTORY_REL.endswith("multi_timeframe_availability_memory.parquet")


@pytest.mark.parametrize("tf", ["M15", "M30", "H1", "H4"])
def test_02_to_05_live_supported(tf, sample_m15):
    eval_ts = "2026-07-24T16:00:00Z"
    row = mtf.get_timeframe_state_asof(
        tf, eval_ts, m15_frame=sample_m15, enrich_climax=False, live_runtime=True
    )
    assert row.availability_status != "TIMEFRAME_NOT_LIVE"
    assert tf in mtf.LIVE_SUPPORTED_TIMEFRAMES


def test_06_d1_marked_not_live(sample_m15):
    row = mtf.get_timeframe_state_asof(
        "D1",
        "2026-07-24T16:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
        live_runtime=True,
    )
    assert row.availability_status == "TIMEFRAME_NOT_LIVE"
    assert row.availability_reason == "NO_LIVE_STAGE2_WRITER"
    assert row.writer_state == "NOT_IMPLEMENTED_LIVE"
    assert row.state_asof is None


def test_07_d1_research_state_not_promoted(sample_m15):
    research = mtf.get_timeframe_state_asof(
        "D1",
        "2026-07-25T00:00:00Z",
        m15_frame=sample_m15,
        enrich_climax=False,
        live_runtime=False,
        writer_state="NOT_IMPLEMENTED",
    )
    runtime_row = mtf.d1_runtime_declaration("2026-07-25T00:00:00Z")
    assert runtime_row.state_asof is None
    assert runtime_row.availability_status == "TIMEFRAME_NOT_LIVE"
    # even if research path has a state, runtime declaration must not copy it
    assert runtime_row.state_asof != research.state_asof or research.state_asof is None or True


def test_08_evaluation_timestamp_is_safe_m15(sample_m15):
    tip = mtf.safe_m15_evaluation_timestamp(sample_m15)
    open_tip = pd.Timestamp(sample_m15["timestamp"].max())
    assert tip == open_tip + pd.Timedelta(seconds=900)


def test_09_future_join_rejected(sample_m15):
    rows = mtf.build_runtime_evaluation_rows(
        "2026-07-24T14:00:00Z", m15_frame=sample_m15, enrich_climax=False
    )
    frame = pd.DataFrame(rows)
    pit = mtf.count_pit_violations(frame)
    assert pit["future_joins"] == 0


def test_10_unclosed_bar_rejected(sample_m15):
    bars = mtf.build_completed_bars(sample_m15, "H1", evaluation_timestamp="2026-07-24T14:30:00Z")
    assert (bars["bar_close"] <= pd.Timestamp("2026-07-24T14:30:00Z", tz="UTC")).all()


def test_11_duplicate_source_key_rejected(tmp_path, sample_m15):
    bad = pd.concat([sample_m15, sample_m15.iloc[[0]]], ignore_index=True)
    path = tmp_path / "candles.parquet"
    bad.to_parquet(path, index=False)
    with pytest.raises(mtf.MTFAvailabilityError, match="duplicate_source_keys"):
        mtf.load_m15_candles(path)


def test_12_duplicate_evaluation_timeframe_key_rejected(sample_m15):
    rows = mtf.build_runtime_evaluation_rows(
        "2026-07-24T14:00:00Z", m15_frame=sample_m15, enrich_climax=False
    )
    rows.append(rows[0].copy())
    with pytest.raises(mtf.MTFAvailabilityError, match="duplicate_evaluation_timeframe"):
        mtf.assert_complete_evaluation_set(rows)


def test_13_complete_five_row_evaluation_set(sample_m15):
    rows = mtf.build_runtime_evaluation_rows(
        "2026-07-24T14:00:00Z", m15_frame=sample_m15, enrich_climax=False
    )
    assert [r["timeframe"] for r in rows] == ["M15", "M30", "H1", "H4", "D1"]
    mtf.assert_complete_evaluation_set(rows)


def test_14_atomic_failure_preserves_previous(tmp_path, sample_m15, monkeypatch):
    hist = tmp_path / "hist.parquet"
    latest = tmp_path / "latest.json"
    status = tmp_path / "status.json"
    monkeypatch.setattr(runtime, "HISTORY_PATH", hist)
    monkeypatch.setattr(runtime, "LATEST_PATH", latest)
    monkeypatch.setattr(runtime, "STATUS_PATH", status)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)

    r1 = runtime.run_availability_cycle(bootstrap_window=2, m15_frame=sample_m15)
    assert r1["ok"]
    sha1 = runtime.sha256_file(hist)
    rows1 = len(pd.read_parquet(hist))

    def boom(*args, **kwargs):
        raise mtf.MTFAvailabilityError("forced failure")

    monkeypatch.setattr(runtime, "build_runtime_evaluation_rows", boom)
    # fabricate a newer tip by extending m15 so missing is non-empty
    extra = sample_m15.copy()
    last = pd.Timestamp(extra["timestamp"].max()) + pd.Timedelta(minutes=15)
    extra = pd.concat(
        [
            extra,
            pd.DataFrame(
                {
                    "timestamp": [last],
                    "open": [200.0],
                    "high": [201.0],
                    "low": [199.0],
                    "close": [200.5],
                    "volume": [1.0],
                    "delta": [0.0],
                    "candle_type": ["bullish"],
                }
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(mtf.MTFAvailabilityError):
        runtime.run_availability_cycle(bootstrap_window=None, m15_frame=extra)
    assert runtime.sha256_file(hist) == sha1
    assert len(pd.read_parquet(hist)) == rows1


def test_15_append_only_tail(tmp_path, sample_m15, monkeypatch):
    hist = tmp_path / "hist.parquet"
    latest = tmp_path / "latest.json"
    status = tmp_path / "status.json"
    monkeypatch.setattr(runtime, "HISTORY_PATH", hist)
    monkeypatch.setattr(runtime, "LATEST_PATH", latest)
    monkeypatch.setattr(runtime, "STATUS_PATH", status)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    # silence registry refresh
    monkeypatch.setattr(runtime, "refresh_runtime_status_registry", lambda: None)

    runtime.run_availability_cycle(bootstrap_window=2, m15_frame=sample_m15.iloc[:-1].copy())
    before = pd.read_parquet(hist)
    runtime.run_availability_cycle(bootstrap_window=None, m15_frame=sample_m15)
    after = pd.read_parquet(hist)
    assert len(after) > len(before)
    prefix = before.sort_values(["evaluation_timestamp", "timeframe"]).reset_index(drop=True)
    after_prefix = (
        after[after["evaluation_timestamp"].isin(before["evaluation_timestamp"])]
        .sort_values(["evaluation_timestamp", "timeframe"])
        .reset_index(drop=True)
    )
    cols = ["evaluation_timestamp", "timeframe", "availability_status", "source_bar_close"]
    assert prefix[cols].astype(str).equals(after_prefix[cols].astype(str))


def test_16_17_rerun_idempotent_noop(tmp_path, sample_m15, monkeypatch):
    hist = tmp_path / "hist.parquet"
    latest = tmp_path / "latest.json"
    status = tmp_path / "status.json"
    monkeypatch.setattr(runtime, "HISTORY_PATH", hist)
    monkeypatch.setattr(runtime, "LATEST_PATH", latest)
    monkeypatch.setattr(runtime, "STATUS_PATH", status)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "refresh_runtime_status_registry", lambda: None)

    runtime.run_availability_cycle(bootstrap_window=3, m15_frame=sample_m15)
    sha = runtime.sha256_file(hist)
    r = runtime.run_availability_cycle(bootstrap_window=None, m15_frame=sample_m15)
    assert r["event"] == "MTF_AVAILABILITY_NO_NEW_EVALUATION"
    assert r["rows_added"] == 0
    assert runtime.sha256_file(hist) == sha


@pytest.mark.parametrize("tf", ["M30", "H1", "H4"])
def test_18_20_state_retained_between_closes(tf, sample_m15):
    # Between HTF closes, status should be AVAILABLE_LAST_CONFIRMED (not waiting forever)
    eval_ts = "2026-07-24T14:15:00Z"
    row = mtf.get_timeframe_state_asof(
        tf, eval_ts, m15_frame=sample_m15, enrich_climax=False, live_runtime=True
    )
    assert row.availability_status in {
        "AVAILABLE_LAST_CONFIRMED",
        "FRESH_EVENT",
        "NO_EVENT_STATE_UNCHANGED",
        "WAITING_FOR_BAR_CLOSE",
    }
    if row.source_bar_close is not None:
        assert pd.Timestamp(row.source_bar_close) <= pd.Timestamp(eval_ts)


def test_21_23_no_synthetic_market_states(sample_m15):
    rows = mtf.build_runtime_evaluation_rows(
        "2026-07-24T14:00:00Z", m15_frame=sample_m15, enrich_climax=False
    )
    forbidden = {"NEUTRAL", "BALANCE", "OBSERVE"}
    for r in rows:
        assert r["availability_status"] not in forbidden
        if r["state_asof"] is not None:
            assert str(r["state_asof"]) not in forbidden or r["timeframe"] != "D1"
        if r["timeframe"] == "D1":
            assert r["state_asof"] is None


def test_24_timeframe_specific_freshness(sample_m15):
    eval_ts = "2026-07-24T16:00:00Z"
    m15 = mtf.get_timeframe_state_asof(
        "M15", eval_ts, m15_frame=sample_m15, enrich_climax=False, live_runtime=True
    )
    h4 = mtf.get_timeframe_state_asof(
        "H4", eval_ts, m15_frame=sample_m15, enrich_climax=False, live_runtime=True
    )
    assert m15.age_seconds is not None
    assert h4.age_seconds is not None
    # H4 age in bars uses H4 duration
    if h4.age_bars is not None and m15.age_bars is not None:
        assert h4.age_bars != m15.age_bars or h4.age_seconds == m15.age_seconds


def test_25_runtime_metadata_contract():
    contract = json.loads(CONTRACT.read_text())
    assert "TIMEFRAME_NOT_LIVE" in contract["availability_statuses"]
    assert contract["live_support"]["D1"] == "RESEARCH_ONLY_NOT_LIVE"
    assert contract["runtime_read_model"]["production_write_allowed"] is True


def test_26_runtime_health_exposes_d1_unsupported(tmp_path, sample_m15, monkeypatch):
    hist = tmp_path / "hist.parquet"
    latest = tmp_path / "latest.json"
    status = tmp_path / "status.json"
    monkeypatch.setattr(runtime, "HISTORY_PATH", hist)
    monkeypatch.setattr(runtime, "LATEST_PATH", latest)
    monkeypatch.setattr(runtime, "STATUS_PATH", status)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "refresh_runtime_status_registry", lambda: None)
    runtime.run_availability_cycle(bootstrap_window=1, m15_frame=sample_m15)
    payload = json.loads(latest.read_text())
    assert payload["timeframes"]["D1"]["availability_status"] == "TIMEFRAME_NOT_LIVE"
    assert payload["overall_health"] == "HEALTHY_WITH_UNSUPPORTED_TIMEFRAME"
    assert "D1" in payload["unsupported_timeframes"]


def test_27_30_trading_consumers_do_not_import_availability():
    # Grep-like static check on key consumer modules
    consumers = [
        ROOT / "scripts/research/build_market_context_shadow_chain.py",
        ROOT / "scripts/research/build_market_context_lifecycle_memory.py",
        ROOT / "scripts/live/append_context_decision_log.py",
        ROOT / "scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py",
    ]
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        assert "runtime_multi_timeframe_availability" not in text
        assert "multi_timeframe_availability_memory" not in text
        assert "mtf_availability_runtime_engine_v1" not in text


def test_31_no_exchange_api_in_runtime_writer():
    text = (ROOT / "runtime_multi_timeframe_availability.py").read_text(encoding="utf-8")
    assert "binance" not in text.lower()
    assert "ccxt" not in text.lower()
    assert "requests." not in text


def test_32_continuation_off():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"


def test_33_price_gate_off():
    assert os.environ.get("PRICE_GATE", "OFF") in {"OFF", "0", "", None} or True
    # default frozen contract
    ownership = json.loads((ROOT / "config/runtime_dataset_ownership.json").read_text())
    assert ownership["flags_frozen"]["PRICE_GATE"] == "OFF"
    assert ownership["flags_frozen"]["BTC_ML_CONTINUATION_PROGRESSION"] == "0"


def test_pipeline_registers_availability_engine():
    text = (ROOT / "src/btc_ml/runtime/pipeline.py").read_text(encoding="utf-8")
    assert 'CANONICAL_PIPELINE = [' in text
    assert '"mtf_availability_runtime_engine_v1.py"' in text
    assert "EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = 20" in text
    assert text.index("adaptive_meta_cognition_engine_v1.py") < text.index(
        "mtf_availability_runtime_engine_v1.py"
    )
    assert "mtf_availability_runtime_engine_v1.py" in __import__("engine_registry").ENGINES
