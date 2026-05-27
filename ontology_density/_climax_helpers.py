"""Shared climax pipeline helpers for density diagnostics."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict

import pandas as pd

from auction_climax_engine_v1 import process_auction_climax
from stabilization_data_utils import ensure_ontology_features, load_candle_structure

ONTOLOGY_CLASSES = (
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
    "HIGH_AVERAGE_VOLUME",
)


def count_events(frame: pd.DataFrame) -> Dict[str, int]:
    counts = {cls: 0 for cls in ONTOLOGY_CLASSES}
    counts["NORMAL"] = 0
    counts["TOTAL_NON_NORMAL"] = 0
    if len(frame) == 0 or "auction_event_type" not in frame.columns:
        return counts
    vc = frame["auction_event_type"].value_counts()
    for key in counts:
        if key in vc and key != "TOTAL_NON_NORMAL":
            counts[key] = int(vc[key])
    counts["TOTAL_NON_NORMAL"] = int((frame["auction_event_type"] != "NORMAL").sum())
    return counts


def run_climax_mode(
    mode: str,
    dataset: pd.DataFrame | None = None,
    timeframe: str = "M15",
) -> pd.DataFrame:
    """Run climax detection under legacy, pre_dedup refined, or current refined."""

    dataset = dataset if dataset is not None else load_candle_structure()
    if len(dataset) == 0:
        return pd.DataFrame()

    if mode == "legacy":
        env = {
            **os.environ,
            "USE_LEGACY_CLIMAX_ONTOLOGY": "true",
            "ENABLE_ONTOLOGY_REFINEMENT": "false",
        }
        return _run_climax_subprocess(dataset, env, timeframe)

    if mode == "refined_no_dedup":
        return _run_refined_without_dedup(dataset, timeframe)

    # current refined (default)
    env = {
        **os.environ,
        "USE_LEGACY_CLIMAX_ONTOLOGY": "false",
        "ENABLE_ONTOLOGY_REFINEMENT": "true",
    }
    return _run_climax_subprocess(dataset, env, timeframe)


def _run_climax_subprocess(dataset: pd.DataFrame, env: dict, timeframe: str) -> pd.DataFrame:
    """Isolated subprocess to avoid cached settings pollution."""

    import tempfile

    path = tempfile.mktemp(suffix=".parquet")
    dataset.to_parquet(path, index=False)
    code = f"""
import pandas as pd
from auction_climax_engine_v1 import process_auction_climax
df = pd.read_parquet({path!r})
result = process_auction_climax(df, {timeframe!r})
events = result.get("auction_states", pd.DataFrame())
if len(events):
    events.to_parquet({path + ".out"!r}, index=False)
"""
    # Simpler: in-process with env override via reload
    old_env = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            os.environ[k] = v
        import importlib
        import ontology_config
        import ontology_refinement
        import auction_climax_engine_v1 as ace

        importlib.reload(ontology_config)
        importlib.reload(ontology_refinement)
        importlib.reload(ace)
        result = ace.process_auction_climax(dataset.copy(), timeframe)
        return result.get("auction_states", pd.DataFrame())
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run_refined_without_dedup(dataset: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Refined separation only — simulates post-3A pre-dedup if dedup were disabled."""

    from ontology_config import get_ontology_settings
    from ontology_refinement import apply_semantic_separation

    old = {k: os.environ.get(k) for k in ("USE_LEGACY_CLIMAX_ONTOLOGY", "ENABLE_ONTOLOGY_REFINEMENT")}
    try:
        os.environ["USE_LEGACY_CLIMAX_ONTOLOGY"] = "false"
        os.environ["ENABLE_ONTOLOGY_REFINEMENT"] = "true"
        import importlib
        import ontology_config
        import ontology_refinement
        import auction_climax_engine_v1 as ace

        importlib.reload(ontology_config)
        importlib.reload(ontology_refinement)
        importlib.reload(ace)

        # Run through engine but capture pre-dedup by calling separation only on prepared frame
        prepared = ensure_ontology_features(dataset.copy())
        result = ace.process_auction_climax(prepared, timeframe)
        # Re-derive pre-dedup: apply only semantic separation on engine-prepared data
        # Use full engine output's underlying classification before dedup is not exported;
        # apply_semantic_separation on a re-run of buying/hav path:
        frame = prepared.copy()
        frame["volume_percentile_50"] = frame["volume"].rolling(50, min_periods=1).rank(pct=True)
        frame["spread_percentile_50"] = frame["spread"].rolling(50, min_periods=1).rank(pct=True)
        de = frame["spread"].astype(float) / frame["volume"].astype(float)
        frame["efficiency_decay"] = de / de.rolling(20, min_periods=1).mean()
        frame["auction_event_type"] = "NORMAL"
        frame["location_bias"] = "NEUTRAL"
        # buying + hav from engine logic (mirror auction_climax_engine_v1)
        buying = (
            (frame["volume_percentile_50"] >= 0.90)
            & (frame["delta"] > 0)
            & (frame["spread_percentile_50"] >= 0.60)
            & ((frame["efficiency_decay"] < 0.80) | (frame["efficiency_decay"] > 1.20))
            & (frame["range_position"] > 0.80)
        )
        frame.loc[buying, "auction_event_type"] = "BUYING_CLIMAX"
        hav = (
            (frame["volume_percentile_50"] >= 0.70)
            & (frame["spread_percentile_50"] >= 0.30)
            & (frame["spread_percentile_50"] < 0.50)
            & (frame["efficiency_decay"] >= 0.90)
            & (frame["range_position"] > 0.35)
            & (frame["range_position"] < 0.65)
            & (frame["auction_event_type"] == "NORMAL")
        )
        frame.loc[hav, "auction_event_type"] = "HIGH_AVERAGE_VOLUME"
        separated = apply_semantic_separation(frame, get_ontology_settings())
        return separated
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
