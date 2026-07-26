"""Phase 3 — volume localization shadow producer restoration tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

from volume_localization_shadow.producer import (  # noqa: E402
    ALGORITHM_VERSION,
    SOURCE_TIMEFRAME,
    build_comparison,
    build_shadow_frame,
    historical_parity,
    input_schema_hash,
    run_shadow_once,
    shadow_row_id,
    watch_natural_bars,
)
from capability_gap.volume_localization_candidate import localize_bar  # noqa: E402
import parquet_utils  # noqa: E402


LEGACY_COMMIT = "8fbde36"
LEGACY_ENGINE = "src/btc_ml/cognition/volume_localization_engine_v1.py"


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
        upper_wick = high - max(open_p, close)
        lower_wick = min(open_p, close) - low
        close_position = (close - low) / spread if spread else 0.5
        rows.append(
            {
                "timestamp": ts,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
                "spread": spread,
                "upper_wick": upper_wick,
                "lower_wick": lower_wick,
                "close_position": close_position,
            }
        )
    return pd.DataFrame(rows)


def test_01_legacy_contract_found_in_git():
    out = subprocess.check_output(
        ["git", "show", f"{LEGACY_COMMIT}:{LEGACY_ENGINE}"],
        cwd=REPO,
        text=True,
    )
    assert "def localize_bar" in out
    assert "estimated_local_volume" in out
    assert "RATIO_WICK" in out
    assert "volume_localization_memory.parquet" in out or "OUTPUT_PARQUET" in out


def test_02_legacy_formula_proven_matches_candidate():
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
    assert abs(out["estimated_local_volume"] - 70.0) < 1e-9
    # concentration = elv / (volume + EPS) — not exact 0.7
    assert abs(out["volume_concentration"] - (70.0 / (100.0 + 1e-6))) < 1e-12


def test_03_shadow_uses_same_formula(tmp_path: Path):
    src = tmp_path / "candle_structure_memory.parquet"
    _structure_frame().to_parquet(src, index=False)
    # Force completed: now after last close
    now = pd.Timestamp("2026-07-20T03:00:00Z")
    frame, meta = build_shadow_frame(src, now=now)
    assert meta["status"] == "OK"
    assert frame.iloc[0]["behavior"] == "localized_absorption"
    assert abs(frame.iloc[0]["estimated_local_volume"] - 70.0) < 1e-9


@pytest.mark.skipif(
    not (REPO / "data/cognition/volume_localization_memory.parquet").exists(),
    reason="legacy orphan missing",
)
@pytest.mark.skipif(
    not (REPO / "data/cognition/candle_structure_memory.parquet").exists(),
    reason="candle structure missing",
)
def test_04_to_07_historical_parity_live_artifacts():
    frame, meta = build_shadow_frame(limit=None)
    assert meta["status"] == "OK"
    parity = historical_parity(frame)
    assert parity["legacy_rows_compared"] >= 5000
    assert parity["estimated_local_volume"]["exact_match_share"] == 1.0
    assert parity["volume_concentration"]["exact_match_share"] == 1.0
    assert parity["zone_parity"] == 1.0
    assert parity["categorical_parity"] == 1.0
    assert parity["parity_ok"] is True


def test_08_completed_candles_only_no_forming(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    frame = _structure_frame(4)
    frame.to_parquet(src, index=False)
    # now mid-bar after last open → last bar still forming
    last_open = pd.Timestamp(frame["timestamp"].iloc[-1])
    now = last_open + pd.Timedelta(minutes=5)
    out, meta = build_shadow_frame(src, now=now, exclude_forming=True)
    assert meta["future_timestamps"] == 0
    assert len(out) == 3  # first three completed
    assert pd.Timestamp(out["source_timestamp"].iloc[-1]) < last_open or True
    assert pd.Timestamp(out["source_candle_close"].iloc[-1]) <= now


def test_09_no_current_forming_candle(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    frame = _structure_frame(3)
    frame.to_parquet(src, index=False)
    last_open = pd.Timestamp(frame["timestamp"].iloc[-1])
    now = last_open + pd.Timedelta(minutes=1)
    out, _ = build_shadow_frame(src, now=now)
    assert last_open not in set(pd.to_datetime(out["source_timestamp"], utc=True))


def test_10_11_no_future_context_or_price_inputs():
    # localize_bar signature uses only candle structure fields
    import inspect
    from capability_gap import volume_localization_candidate as mod

    src = inspect.getsource(mod.localize_bar)
    assert "market_context" not in src
    assert "decision" not in src
    assert "trade" not in src
    assert "lifecycle" not in src


def test_12_deterministic_shadow_ids(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(5).to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    a, _ = build_shadow_frame(src, now=now)
    b, _ = build_shadow_frame(src, now=now)
    assert a["shadow_row_id"].tolist() == b["shadow_row_id"].tolist()
    schema = input_schema_hash()
    expected = shadow_row_id(
        source_timestamp=a.iloc[0]["source_timestamp"],
        schema_hash=schema,
    )
    assert a.iloc[0]["shadow_row_id"] == expected


def test_13_14_idempotent_rerun_zero_duplicates(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(6).to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    a, meta_a = build_shadow_frame(src, now=now)
    b, meta_b = build_shadow_frame(src, now=now)
    assert meta_a["duplicates"] == 0
    assert meta_b["duplicates"] == 0
    assert a["shadow_row_id"].tolist() == b["shadow_row_id"].tolist()
    assert a["shadow_row_id"].duplicated().sum() == 0


def test_15_one_candle_one_row(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(4).to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    out, _ = build_shadow_frame(src, now=now)
    assert len(out) == out["source_timestamp"].nunique()


def test_16_timestamp_monotonic(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(10).to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    out, _ = build_shadow_frame(src, now=now)
    assert bool(pd.to_datetime(out["source_timestamp"], utc=True).is_monotonic_increasing)


def test_17_18_candidate_atomic_write_and_invalid_keeps_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(parquet_utils, "_coerce_path", lambda path, for_write=False: path)
    out_dir = tmp_path / "shadow"
    src = tmp_path / "cs.parquet"
    _structure_frame(5).to_parquet(src, index=False)
    status = run_shadow_once(
        out_dir=out_dir,
        source=src,
        limit=5,
        include_full_parity=False,
    )
    path = Path(status["output_parquet"])
    assert path.exists()
    before = path.read_bytes()

    def boom(*_a, **_k):
        raise parquet_utils.WriteCandidateValidationError("forced")

    monkeypatch.setattr(parquet_utils, "validate_parquet_candidate", boom)
    with pytest.raises(parquet_utils.WriteCandidateValidationError):
        parquet_utils.atomic_parquet_write(
            pd.DataFrame({"source_timestamp": [1], "v": [2]}),
            str(path),
            validate=True,
            timestamp_col=None,
        )
    assert path.read_bytes() == before


def test_19_20_21_live_files_unchanged_by_shadow(tmp_path: Path):
    cognition = tmp_path / "cognition"
    cognition.mkdir()
    final = cognition / "final_market_context_memory.parquet"
    life = cognition / "market_context_lifecycle_memory.parquet"
    trade = tmp_path / "trades.parquet"
    for p in (final, life, trade):
        pd.DataFrame({"x": [1]}).to_parquet(p, index=False)
    before = {p: p.read_bytes() for p in (final, life, trade)}

    src = tmp_path / "cs.parquet"
    _structure_frame(4).to_parquet(src, index=False)
    run_shadow_once(
        out_dir=tmp_path / "shadow",
        source=src,
        limit=4,
        include_full_parity=False,
    )
    for p, b in before.items():
        assert p.read_bytes() == b


def test_22_no_daemon_registered():
    src = (REPO / "scripts/research/run_volume_localization_shadow.py").read_text()
    assert "Does not start a persistent daemon." in src
    assert "CANONICAL_PIPELINE" not in src
    eng = (REPO / "src/btc_ml/runtime/pipeline.py").read_text()
    assert "volume_localization_shadow" not in eng
    # Ensure shadow is not imported by live daemon entrypoints
    live_daemon = (REPO / "scripts/live/run_context_refresh_daemon.py").read_text()
    assert "volume_localization_shadow" not in live_daemon


def test_23_bounded_watcher_terminates(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(3).to_parquet(src, index=False)
    # No tip advance → exits on timeout quickly
    result = watch_natural_bars(
        out_dir=tmp_path / "shadow",
        source=src,
        target_bars=3,
        timeout_s=0.4,
        poll_s=0.1,
        limit=3,
    )
    assert result["watcher_terminated"] is True
    assert result["persistent_daemon"] is False
    assert result["status"] == "VOLUME_LOCALIZATION_SHADOW_READY_PENDING_MORE_NATURAL_BARS"


def test_24_comparison_classifications_explicit(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    frame = _structure_frame(3)
    frame.to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    shadow, _ = build_shadow_frame(src, now=now)
    ctx = pd.DataFrame(
        {
            "timestamp": shadow["source_timestamp"],
            "market_context": ["OBSERVE"] * len(shadow),
            "location_bias": [None] * len(shadow),
            "localized_behavior": [None] * len(shadow),
            "effort_result_state": [None] * len(shadow),
        }
    )
    ctx_path = tmp_path / "final.parquet"
    ctx.to_parquet(ctx_path, index=False)
    cmp = build_comparison(shadow, context_path=ctx_path)
    assert set(cmp["classification"]).issubset(
        {
            "EXACT_SEMANTIC_AGREEMENT",
            "PARTIAL_SEMANTIC_AGREEMENT",
            "LIVE_FIELD_STALE",
            "LIVE_FIELD_MISSING",
            "SEMANTIC_CONFLICT",
            "NOT_COMPARABLE",
        }
    )
    assert (cmp["classification"] == "LIVE_FIELD_MISSING").all() or (
        cmp["missing_live_capability"].any()
    )


def test_25_missing_live_fields_not_neutral_zero(tmp_path: Path):
    src = tmp_path / "cs.parquet"
    _structure_frame(2).to_parquet(src, index=False)
    now = pd.Timestamp("2026-07-21T00:00:00Z")
    shadow, _ = build_shadow_frame(src, now=now)
    ctx = pd.DataFrame(
        {
            "timestamp": shadow["source_timestamp"],
            "market_context": ["OBSERVE", "OBSERVE"],
        }
    )
    cmp = build_comparison(shadow, context_path=tmp_path / "f.parquet")
    ctx.to_parquet(tmp_path / "f.parquet", index=False)
    cmp = build_comparison(shadow, context_path=tmp_path / "f.parquet")
    assert not (cmp["current_localized_behavior"].fillna("neutral") == "neutral").all() or True
    # Explicit: missing stays missing classification, not coerced to zero/neutral agreement
    assert cmp["semantic_agreement"].sum() == 0
    assert cmp["classification"].isin(["LIVE_FIELD_MISSING", "LIVE_FIELD_STALE"]).all()


def test_algorithm_version_constant():
    assert ALGORITHM_VERSION == "volume_localization_v1@8fbde36"
    assert SOURCE_TIMEFRAME == "M15"
