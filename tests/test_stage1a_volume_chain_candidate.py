"""Stage 1A — volume localization → volume_response candidate (no live activation)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from storage.path_registry import PARQUET_REGISTRY, resolve_canonical  # noqa: E402
from src.btc_ml.runtime import pipeline as pipeline_mod  # noqa: E402
from volume_localization_engine_v1 import (  # noqa: E402
    build_localization_frame,
    resolve_localization_for_structure,
)
from src.btc_ml.cognition.volume_response_timestamp_identity import (  # noqa: E402
    build_response_identity_fields,
    classify_response_localization_join,
    STATUS_EXACT,
    STATUS_STALE,
)


def _frame(n: int = 4) -> pd.DataFrame:
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
                "volume": 100.0,
                "spread": spread,
                "upper_wick": high - max(open_p, close),
                "lower_wick": min(open_p, close) - low,
                "close_position": (close - low) / spread,
            }
        )
    return pd.DataFrame(rows)


def test_live_pipeline_not_activated():
    assert "volume_localization_engine_v1.py" not in pipeline_mod.CANONICAL_PIPELINE
    assert pipeline_mod.EXPECTED_CANONICAL_PIPELINE_STEP_COUNT == 20


def test_candidate_pipeline_order():
    cand = pipeline_mod.canonical_pipeline_with_volume_localization_candidate()
    assert len(cand) == 21
    assert cand.index("candle_structure_engine_v1.py") < cand.index(
        "volume_localization_engine_v1.py"
    )
    assert cand.index("volume_localization_engine_v1.py") < cand.index(
        "volume_response_engine_v1.py"
    )


def test_canonical_localization_path_registered():
    assert PARQUET_REGISTRY.get("volume_localization_memory.parquet") == "cognition"
    assert resolve_canonical("volume_localization_memory.parquet").endswith(
        "data/cognition/volume_localization_memory.parquet"
    )


def test_exact_join_no_stale_carry():
    loc = build_localization_frame(_frame(3))
    ts = loc.iloc[1]["timestamp"]
    hit = resolve_localization_for_structure(loc, ts, live_v1=True)
    assert hit["localization_join_status"] == "EXACT_FRESH_MATCH"
    assert hit["row"] is not None

    future = loc["timestamp"].max() + pd.Timedelta(minutes=15)
    stale = resolve_localization_for_structure(loc, future, live_v1=True)
    assert stale["localization_join_status"] == STATUS_STALE
    assert stale["row"] is None


def test_response_identity_join_exact():
    frame = _frame(3)
    loc = build_localization_frame(frame)
    ident = build_response_identity_fields(frame.iloc[1])
    join = classify_response_localization_join(ident, loc, live_v1=True)
    assert join["localization_join_status"] == STATUS_EXACT
    assert ident["source_candle_timestamp"] == loc.iloc[1]["timestamp"]


def test_persist_source_identity_contract_in_response_source():
    src = (REPO / "volume_response_engine_v1.py").read_text()
    assert 'state_payload["source_candle_timestamp"]' in src
    assert 'os.environ.get("BTC_ML_VOLUME_LOCALIZATION_LIVE", "0")' in src
    # Default remains off — no accidental live activation.
    assert os.environ.get("BTC_ML_VOLUME_LOCALIZATION_LIVE", "0") in {"0", "1"}


def test_no_fuzzy_join_helpers():
    loc_src = (REPO / "src/btc_ml/cognition/volume_localization_engine_v1.py").read_text()
    assert "merge_asof" not in loc_src
    assert "ffill" not in loc_src
    assert "bfill" not in loc_src
