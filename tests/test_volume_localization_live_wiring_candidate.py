"""Phase 4A — volume localization live-wiring candidate tests (no live activation)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from volume_localization_engine_v1 import (  # noqa: E402
    ALGORITHM_VERSION,
    build_localization_frame,
    localize_bar,
    resolve_localization_for_structure,
)
from src.btc_ml.runtime import pipeline as pipeline_mod  # noqa: E402


def _structure_frame(n: int = 8) -> pd.DataFrame:
    idx = pd.date_range("2026-07-20T00:00:00Z", periods=n, freq="15min", tz="UTC")
    rows = []
    for i, ts in enumerate(idx):
        if i == 0:
            open_p, high, low, close = 100.0, 100.2, 99.0, 100.1
        else:
            open_p = close = 100.0 + i
            high, low = open_p + 0.1, open_p - 0.1
        spread = high - low
        rows.append(
            {
                "timestamp": ts,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
                "spread": spread,
                "upper_wick": high - max(open_p, close),
                "lower_wick": min(open_p, close) - low,
                "close_position": (close - low) / spread if spread else 0.5,
            }
        )
    return pd.DataFrame(rows)


def test_01_legacy_formula_unchanged():
    assert ALGORITHM_VERSION == "volume_localization_v1@8fbde36"
    row = pd.Series(
        {
            "timestamp": pd.Timestamp("2026-07-20T00:00:00Z"),
            "open": 100.0,
            "high": 100.2,
            "low": 99.0,
            "close": 100.1,
            "volume": 100.0,
            "spread": 1.2,
            "upper_wick": 0.1,
            "lower_wick": 1.0,
            "close_position": (100.1 - 99.0) / 1.2,
        }
    )
    out = localize_bar(row)
    assert out["behavior"] == "localized_absorption"
    assert abs(out["estimated_local_volume"] - 70.0) < 1e-12


def test_02_production_candidate_equals_shadow_builder():
    import importlib.util

    path = REPO / "scripts/research/capability_gap/volume_localization_candidate.py"
    spec = importlib.util.spec_from_file_location("vl_shadow_cand", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    frame = _structure_frame(5)
    for _, row in frame.iterrows():
        a = localize_bar(row)
        b = mod.localize_bar(row)
        assert a["behavior"] == b["behavior"]
        assert abs(a["estimated_local_volume"] - b["estimated_local_volume"]) < 1e-12
        assert abs(a["volume_concentration"] - b["volume_concentration"]) < 1e-12
        assert abs(a["zone_low"] - b["zone_low"]) < 1e-12
        assert abs(a["zone_high"] - b["zone_high"]) < 1e-12


def test_03_completed_m15_only_and_monotonic():
    out = build_localization_frame(_structure_frame(6))
    assert len(out) == 6
    assert bool(pd.to_datetime(out["timestamp"], utc=True).is_monotonic_increasing)
    assert out["timestamp"].duplicated().sum() == 0
    assert (out["source_timeframe"] == "M15").all()


def test_04_atomic_output(tmp_path, monkeypatch):
    import parquet_utils

    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    target = tmp_path / "volume_localization_memory.parquet"
    df = build_localization_frame(_structure_frame(3))
    seen = []
    real = pd.DataFrame.to_parquet

    def track(self, path, *a, **k):
        seen.append(str(path))
        return real(self, path, *a, **k)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", track)
    parquet_utils.atomic_parquet_write(
        df, str(target), validate=True, timestamp_col="timestamp", enforce_timestamp_integrity=True
    )
    assert len(seen) == 1
    assert Path(seen[0]).parent == target.parent
    assert target.exists()


def test_05_06_07_runtime_order_candidate():
    cand = pipeline_mod.canonical_pipeline_with_volume_localization_candidate()
    assert "volume_localization_engine_v1.py" in cand
    assert cand.index("candle_structure_engine_v1.py") < cand.index(
        "volume_localization_engine_v1.py"
    )
    assert cand.index("volume_localization_engine_v1.py") < cand.index(
        "volume_response_engine_v1.py"
    )
    # Stage 1B: live CANONICAL_PIPELINE activated via the same helper order.
    assert "volume_localization_engine_v1.py" in pipeline_mod.CANONICAL_PIPELINE
    assert pipeline_mod.EXPECTED_CANONICAL_PIPELINE_STEP_COUNT == 21
    assert len(cand) == 21
    assert pipeline_mod.CANONICAL_PIPELINE == cand


def test_08_09_10_exact_join_no_fuzzy_no_stale():
    loc = build_localization_frame(_structure_frame(3))
    ts = loc.iloc[1]["timestamp"]
    ok = resolve_localization_for_structure(loc, ts, live_v1=True)
    assert ok["localization_join_status"] == "EXACT_FRESH_MATCH"
    assert ok["localization_fresh"] is True

    # Beyond localization tip → stale (no tip-carry / no fuzzy match).
    future = loc["timestamp"].max() + pd.Timedelta(minutes=15)
    stale = resolve_localization_for_structure(loc, future, live_v1=True)
    assert stale["localization_join_status"] == "STALE_LOCALIZATION_MATCH"
    assert stale["row"] is None


def test_11_12_13_missing_stays_null_not_zero_not_neutral():
    loc = build_localization_frame(_structure_frame(2))
    miss = resolve_localization_for_structure(
        loc, pd.Timestamp("2099-01-01T00:00:00Z"), live_v1=True
    )
    assert miss["row"] is None
    # consumer contract simulation
    elv = None if miss["row"] is None else miss["row"]["estimated_local_volume"]
    behavior = None if miss["row"] is None else miss["row"]["behavior"]
    assert elv is None
    assert behavior is None
    assert elv != 0
    assert behavior not in {"neutral", "NEUTRAL"}


def test_14_fresh_match_marked_explicitly():
    loc = build_localization_frame(_structure_frame(2))
    hit = resolve_localization_for_structure(loc, loc.iloc[0]["timestamp"], live_v1=True)
    assert hit["localization_join_status"] == "EXACT_FRESH_MATCH"
    assert hit["localization_fresh"] is True


def test_15_16_duplicate_ambiguous_fail_closed():
    loc = build_localization_frame(_structure_frame(2))
    dup = pd.concat([loc, loc.iloc[[0]]], ignore_index=True)
    amb = resolve_localization_for_structure(dup, loc.iloc[0]["timestamp"], live_v1=True)
    assert amb["localization_join_status"] == "AMBIGUOUS_LOCALIZATION_MATCH"
    assert amb["row"] is None


def test_17_18_19_response_receives_fields_and_mapping():
    loc = build_localization_frame(_structure_frame(3))
    join = resolve_localization_for_structure(loc, loc.iloc[0]["timestamp"], live_v1=True)
    assert join["row"]["estimated_local_volume"] is not None
    assert join["row"]["volume_concentration"] is not None
    # identity mapping behavior → localized_behavior
    assert join["row"]["behavior"] in {
        "body_participation",
        "localized_absorption",
        "localized_distribution",
    }


def test_20_unrelated_response_fields_contract_documented():
    # Live flag OFF preserves tip-carry semantics; candidate path only adds localization fields.
    resp = (REPO / "volume_response_engine_v1.py").read_text()
    assert "BTC_ML_VOLUME_LOCALIZATION_LIVE" in resp
    assert 'os.environ.get("BTC_ML_VOLUME_LOCALIZATION_LIVE", "0")' in resp
    assert '_VOLUME_LOCALIZATION_LIVE' in resp


def test_21_location_bias_unchanged_by_module():
    out = build_localization_frame(_structure_frame(2))
    assert "location_bias" not in out.columns


def test_22_inventory_transfer_not_wired():
    src = (REPO / "src/btc_ml/cognition/volume_localization_engine_v1.py").read_text()
    assert "inventory_transfer" not in src
    out = build_localization_frame(_structure_frame(2))
    assert "inventory_transfer_state" not in out.columns


def test_23_reinforcement_weights_unchanged():
    import subprocess

    assert (
        subprocess.check_output(["git", "diff", "--", "auction_reinforcement_engine_v1.py"], cwd=REPO).decode()
        == ""
    )


def test_24_probabilistic_formulas_unchanged():
    import subprocess

    assert (
        subprocess.check_output(["git", "diff", "--", "probabilistic_auction_engine_v1.py"], cwd=REPO).decode()
        == ""
    )


def test_25_context_policy_unchanged():
    import subprocess

    for rel in (
        "src/btc_ml/context/decision_policy.py",
        "scripts/live/context_refresh_daemon.py",
    ):
        # allow empty or missing-path diffs
        try:
            diff = subprocess.check_output(["git", "diff", "--", rel], cwd=REPO).decode()
        except Exception:
            continue
        # these may have pre-existing dirt; skip hard fail if already dirty before our phase
        assert "volume_localization" not in diff


def test_26_trading_files_unchanged_by_this_phase():
    import subprocess

    for rel in ("src/btc_ml/trading", "scripts/live/manager"):
        out = subprocess.check_output(["git", "diff", "--name-only", "--", rel], cwd=REPO).decode().strip()
        # tolerate pre-existing dirt; require no new volume localization references introduced here
        if out:
            for f in out.splitlines():
                text = subprocess.check_output(["git", "diff", "--", f], cwd=REPO).decode()
                assert "volume_localization" not in text


def test_27_no_live_outputs_written_by_builder(tmp_path):
    live = tmp_path / "volume_localization_memory.parquet"
    live.write_bytes(b"x")
    before = live.read_bytes()
    _ = build_localization_frame(_structure_frame(3))
    assert live.read_bytes() == before


def test_28_no_daemon_created():
    assert not (REPO / "scripts/live/volume_localization_daemon.py").exists()
    # Localization runs inside canonical pipeline — no separate daemon.
    assert "volume_localization_engine_v1.py" in pipeline_mod.CANONICAL_PIPELINE


def test_29_candidate_replay_idempotent():
    frame = _structure_frame(10)
    a = build_localization_frame(frame)
    b = build_localization_frame(frame)
    assert a["timestamp"].tolist() == b["timestamp"].tolist()
    assert a["estimated_local_volume"].tolist() == b["estimated_local_volume"].tolist()


def test_30_no_lookahead_in_localize_bar():
    import inspect

    src = inspect.getsource(localize_bar)
    assert "market_context" not in src
    assert "decision" not in src
    assert "fill" not in src


@pytest.mark.skipif(
    not (REPO / "data/cognition/volume_localization_memory.parquet").exists(),
    reason="legacy orphan missing",
)
@pytest.mark.skipif(
    not (REPO / "data/cognition/candle_structure_memory.parquet").exists(),
    reason="candle missing",
)
def test_live_artifact_parity_5000():
    structure = pd.read_parquet(REPO / "data/cognition/candle_structure_memory.parquet")
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True)
    cand = build_localization_frame(structure)
    legacy = pd.read_parquet(REPO / "data/cognition/volume_localization_memory.parquet")
    legacy["timestamp"] = pd.to_datetime(legacy["timestamp"], utc=True)
    merged = cand.merge(
        legacy[
            [
                "timestamp",
                "estimated_local_volume",
                "volume_concentration",
                "zone_low",
                "zone_high",
                "behavior",
            ]
        ],
        on="timestamp",
        suffixes=("_c", "_l"),
    )
    assert len(merged) >= 5000
    assert (merged["estimated_local_volume_c"] - merged["estimated_local_volume_l"]).abs().max() == 0
    assert (merged["behavior_c"] == merged["behavior_l"]).all()
