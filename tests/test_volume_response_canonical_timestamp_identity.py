"""Phase 4B — volume_response canonical timestamp identity (no live activation)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))


def _load_identity():
    path = REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py"
    spec = importlib.util.spec_from_file_location("vr_ts_identity_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


identity = _load_identity()

from volume_localization_engine_v1 import (  # noqa: E402
    build_localization_frame,
    localize_bar,
)


def _structure_frame(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-07-20T00:00:00Z", periods=n, freq="15min", tz="UTC")
    rows = []
    for i, ts in enumerate(idx):
        open_p = 100.0 + i
        high, low, close = open_p + 1.0, open_p - 1.0, open_p + 0.2
        spread = high - low
        rows.append(
            {
                "timestamp": ts,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0 + i,
                "spread": spread,
                "upper_wick": high - max(open_p, close),
                "lower_wick": min(open_p, close) - low,
                "close_position": (close - low) / spread,
            }
        )
    return pd.DataFrame(rows)


def test_01_source_timestamp_from_candle_row():
    row = _structure_frame(1).iloc[0]
    ts = identity.canonical_source_candle_timestamp(row)
    assert ts == pd.Timestamp(row["timestamp"]).tz_convert("UTC")


def test_02_source_timestamp_not_from_current_time():
    row = _structure_frame(1).iloc[0]
    wall = pd.Timestamp("2099-01-01T00:00:00Z")
    ident = identity.build_response_identity_fields(row, evaluated_at=wall)
    assert ident["source_candle_timestamp"] != wall
    assert ident["source_candle_timestamp"] == pd.Timestamp(row["timestamp"]).tz_convert("UTC")


def test_03_evaluation_timestamp_stored_separately():
    row = _structure_frame(1).iloc[0]
    wall = pd.Timestamp("2099-01-01T00:00:00Z")
    ident = identity.build_response_identity_fields(row, evaluated_at=wall)
    assert ident["evaluated_at"] == wall
    assert ident["timestamp"] == wall  # legacy wall-clock meaning
    assert ident["source_candle_timestamp"] != ident["evaluated_at"]


def test_04_exact_localization_join_works():
    frame = _structure_frame(3)
    loc = build_localization_frame(frame)
    ident = identity.build_response_identity_fields(frame.iloc[1])
    join = identity.classify_response_localization_join(ident, loc, live_v1=True)
    assert join["localization_join_status"] == identity.STATUS_EXACT
    assert join["localization_fresh"] is True


def test_05_wall_clock_mismatch_does_not_block_join():
    frame = _structure_frame(2)
    loc = build_localization_frame(frame)
    ident = identity.build_response_identity_fields(
        frame.iloc[0],
        evaluated_at=pd.Timestamp("2099-06-01T12:34:56Z"),
    )
    join = identity.classify_response_localization_join(ident, loc, live_v1=True)
    assert join["localization_join_status"] == identity.STATUS_EXACT
    assert ident["evaluated_at"] != ident["source_candle_timestamp"]


def test_06_no_fuzzy_matching_in_helper_source():
    src = (REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py").read_text()
    assert "merge_asof" not in src
    assert "ffill" not in src
    assert "bfill" not in src
    assert "nearest" not in src
    assert "Timedelta(minutes" not in src


def test_07_08_missing_localization_null_not_neutral():
    frame = _structure_frame(2)
    loc = build_localization_frame(frame)
    # Future bar beyond tip → STALE, row None
    future = frame.iloc[-1].copy()
    future["timestamp"] = frame["timestamp"].max() + pd.Timedelta(minutes=15)
    ident = identity.build_response_identity_fields(future)
    join = identity.classify_response_localization_join(ident, loc, live_v1=True)
    assert join["localization_join_status"] == identity.STATUS_STALE
    assert join["row"] is None
    behavior = None if join["row"] is None else join["row"]["behavior"]
    elv = None if join["row"] is None else join["row"]["estimated_local_volume"]
    assert behavior is None
    assert elv is None
    assert behavior != "neutral"


def test_09_stale_carry_forward_absent_flag_on():
    frame = _structure_frame(2)
    loc = build_localization_frame(frame)
    future = frame.iloc[-1].copy()
    future["timestamp"] = frame["timestamp"].max() + pd.Timedelta(minutes=30)
    ident = identity.build_response_identity_fields(future)
    join = identity.classify_response_localization_join(ident, loc, live_v1=True)
    assert join["row"] is None
    assert join["localization_join_status"] == identity.STATUS_STALE


def test_10_ambiguous_match_fail_closed():
    frame = _structure_frame(2)
    loc = build_localization_frame(frame)
    dup = pd.concat([loc, loc.iloc[[0]]], ignore_index=True)
    ident = identity.build_response_identity_fields(frame.iloc[0])
    join = identity.classify_response_localization_join(ident, dup, live_v1=True)
    assert join["localization_join_status"] == identity.STATUS_AMBIGUOUS
    assert join["row"] is None


def test_11_12_legacy_rows_read_without_synthetic_timestamp():
    legacy = {"timestamp": pd.Timestamp("2026-07-26T05:15:08.501485Z"), "localized_behavior": "x"}
    join = identity.classify_response_localization_join(
        legacy, build_localization_frame(_structure_frame(2)), live_v1=True
    )
    assert join["localization_join_status"] == identity.STATUS_LEGACY_NO_SOURCE
    assert join["source_candle_timestamp"] is None
    assert identity.response_has_canonical_source_timestamp(legacy) is False


def test_13_three_consecutive_natural_candles_join_exactly():
    bars = [
        "2026-07-26T09:00:00Z",
        "2026-07-26T09:15:00Z",
        "2026-07-26T09:30:00Z",
    ]
    candle_path = REPO / "data/cognition/candle_structure_memory.parquet"
    if not candle_path.exists():
        pytest.skip("candle structure missing")
    structure = pd.read_parquet(candle_path)
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True)
    for bar in bars:
        ts = pd.Timestamp(bar)
        crow = structure[structure["timestamp"] == ts]
        assert len(crow) == 1, f"missing natural bar {bar}"
        loc = build_localization_frame(crow)
        ident = identity.build_response_identity_fields(
            crow.iloc[0],
            evaluated_at=pd.Timestamp("2099-01-01T00:00:00Z"),
        )
        join = identity.classify_response_localization_join(ident, loc, live_v1=True)
        assert join["localization_join_status"] == identity.STATUS_EXACT
        assert ident["source_candle_timestamp"] == ts


def test_14_15_16_parity_fields_preserved():
    frame = _structure_frame(3)
    loc = build_localization_frame(frame)
    for _, crow in frame.iterrows():
        ident = identity.build_response_identity_fields(crow)
        join = identity.classify_response_localization_join(ident, loc, live_v1=True)
        assert join["localization_join_status"] == identity.STATUS_EXACT
        direct = localize_bar(crow)
        assert abs(float(join["row"]["estimated_local_volume"]) - float(direct["estimated_local_volume"])) < 1e-12
        assert abs(float(join["row"]["volume_concentration"]) - float(direct["volume_concentration"])) < 1e-12
        assert join["row"]["behavior"] == direct["behavior"]


def test_17_unrelated_response_formulas_untouched():
    # effort/result / unfinished blocks must not be rewritten by identity helper module
    src = (REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py").read_text()
    assert "effort_result" not in src
    assert "unfinished_auction" not in src
    resp = (REPO / "volume_response_engine_v1.py").read_text()
    # flag gate still required
    assert "BTC_ML_VOLUME_LOCALIZATION_LIVE" in resp
    assert "source_candle_timestamp" in resp
    assert "evaluated_at" in resp


def test_18_inventory_transfer_not_wired():
    src = (REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py").read_text()
    assert "inventory_transfer" not in src
    resp = (REPO / "volume_response_engine_v1.py").read_text()
    # no new inventory wiring in this phase
    assert "inventory_transfer_state" not in resp


def test_19_location_bias_unchanged():
    src = (REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py").read_text()
    assert "location_bias" not in src


def test_20_no_live_writes_from_helpers(tmp_path):
    live = tmp_path / "volume_response_state.parquet"
    live.write_bytes(b"x")
    before = live.read_bytes()
    frame = _structure_frame(2)
    loc = build_localization_frame(frame)
    ident = identity.build_response_identity_fields(frame.iloc[0])
    _ = identity.classify_response_localization_join(ident, loc, live_v1=True)
    assert live.read_bytes() == before


def test_21_flag_default_off_and_no_pipeline_registration():
    assert os.environ.get("BTC_ML_VOLUME_LOCALIZATION_LIVE", "0") == "0"
    sys.path.insert(0, str(REPO / "src"))
    from btc_ml.runtime import pipeline as pipeline_mod  # noqa: WPS433

    assert "volume_localization_engine_v1.py" not in pipeline_mod.CANONICAL_PIPELINE


def test_22_candidate_replay_idempotent():
    frame = _structure_frame(4)
    a = [identity.build_response_identity_fields(r)["source_candle_timestamp"] for _, r in frame.iterrows()]
    b = [identity.build_response_identity_fields(r)["source_candle_timestamp"] for _, r in frame.iterrows()]
    assert a == b


def test_reinforcement_and_trading_untouched():
    for rel in (
        "auction_reinforcement_engine_v1.py",
        "probabilistic_auction_engine_v1.py",
    ):
        assert subprocess.check_output(["git", "diff", "--", rel], cwd=REPO).decode() == ""
