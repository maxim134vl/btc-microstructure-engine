"""Ontology filter waterfall — survival rates through each filter stage."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ontology_config import get_ontology_settings
from ontology_refinement import (
    _base_sell_side_mask,
    apply_semantic_separation,
    classify_effort_result_zone,
    compute_delta_behavior_shift,
    compute_recovery_structure_score,
    deduplicate_swing_clusters,
)
from stabilization_data_utils import ensure_ontology_features, load_candle_structure

ONTOLOGY_CLASSES = (
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
    "HIGH_AVERAGE_VOLUME",
)


def _prepare_frame(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = ensure_ontology_features(dataset.copy())
    frame["volume_percentile_50"] = frame["volume"].rolling(50, min_periods=1).rank(pct=True)
    frame["spread_percentile_50"] = frame["spread"].rolling(50, min_periods=1).rank(pct=True)
    de = frame["spread"].astype(float) / frame["volume"].astype(float)
    frame["efficiency_decay"] = de / de.rolling(20, min_periods=1).mean()
    frame["auction_event_type"] = "NORMAL"
    frame["location_bias"] = "NEUTRAL"
    frame["delta_behavior_shift"] = compute_delta_behavior_shift(frame)
    frame["recovery_structure_score"] = compute_recovery_structure_score(frame)
    return frame


def _count_label(frame: pd.DataFrame, label: str) -> int:
    if "auction_event_type" not in frame.columns:
        return 0
    return int((frame["auction_event_type"] == label).sum())


def build_ontology_filter_waterfall(timeframe: str = "M15") -> Dict[str, Any]:
    settings = get_ontology_settings()
    raw = load_candle_structure()
    frame = _prepare_frame(raw)
    n = len(frame)

    stages: List[Dict[str, Any]] = []

    def _stage(name: str, mask: pd.Series | None = None, frame_state: pd.DataFrame | None = None):
        if frame_state is not None:
            counts = {cls: _count_label(frame_state, cls) for cls in ONTOLOGY_CLASSES}
            counts["TOTAL"] = sum(counts.values())
        elif mask is not None:
            counts = {"candidates": int(mask.sum())}
        else:
            counts = {}
        stages.append({
            "stage": name,
            "counts": counts,
            "survival_rate": round(counts.get("candidates", counts.get("TOTAL", 0)) / max(n, 1), 6),
        })

    _stage("raw_candles", mask=pd.Series(True, index=frame.index))

    volume_candidates = frame["volume_percentile_50"] >= 0.70
    _stage("raw_volume_candidates", mask=volume_candidates)

    buying_mask = (
        (frame["volume_percentile_50"] >= 0.90)
        & (frame["delta"] > 0)
        & (frame["spread_percentile_50"] >= 0.60)
        & ((frame["efficiency_decay"] < 0.80) | (frame["efficiency_decay"] > 1.20))
        & (frame["range_position"] > 0.80)
    )
    frame.loc[buying_mask, "auction_event_type"] = "BUYING_CLIMAX"

    hav_mask = (
        (frame["volume_percentile_50"] >= 0.70)
        & (frame["spread_percentile_50"] >= 0.30)
        & (frame["spread_percentile_50"] < 0.50)
        & (frame["efficiency_decay"] >= 0.90)
        & (frame["range_position"] > 0.35)
        & (frame["range_position"] < 0.65)
        & (frame["auction_event_type"] == "NORMAL")
    )
    frame.loc[hav_mask, "auction_event_type"] = "HIGH_AVERAGE_VOLUME"
    _stage("post_buying_hav", frame_state=frame)

    base = _base_sell_side_mask(frame)
    _stage("sell_side_base", mask=base)

    zones = classify_effort_result_zone(frame["efficiency_decay"], settings)
    grey = base & (zones == "AMBIGUOUS")
    _stage("post_grey_zone_exclusion", mask=base & ~grey)

    post_range = base & (frame["range_position"] < 0.45)
    _stage("post_range_position", mask=post_range)

    post_eff_cap = base & (zones == "CAPITULATION")
    post_eff_abs = base & (zones == "ABSORPTION")
    _stage("post_efficiency_capitulation", mask=post_eff_cap)
    _stage("post_efficiency_absorption", mask=post_eff_abs)

    post_wick_stop = post_eff_abs & (frame["lower_wick_ratio"] > settings.stopping_min_lower_wick_ratio)
    post_wick_sell = post_eff_cap & (frame["lower_wick_ratio"] < settings.selling_max_lower_wick_ratio)
    _stage("post_wick_filter_stopping", mask=post_wick_stop)
    _stage("post_wick_filter_selling", mask=post_wick_sell)

    post_delta_stop = post_wick_stop & (
        (frame["close_position_ratio"] > settings.stopping_min_close_position_ratio)
        | (frame["recovery_structure_score"] >= settings.stopping_recovery_score_alt)
    ) & (
        (frame["delta_behavior_shift"] > settings.stopping_min_delta_shift)
        | (frame["recovery_structure_score"] >= settings.stopping_recovery_score_alt)
    )
    post_delta_sell = post_wick_sell & (frame["delta_behavior_shift"] <= settings.selling_max_delta_shift)
    _stage("post_delta_filter_stopping", mask=post_delta_stop)
    _stage("post_delta_filter_selling", mask=post_delta_sell)

    separated = apply_semantic_separation(frame, settings)
    _stage("post_semantic_separation", frame_state=separated)

    deduped = deduplicate_swing_clusters(separated, settings)
    _stage("post_deduplication", frame_state=deduped)

    collapse_stage = _identify_collapse(stages, base.sum())
    filter_survival_rates = {
        s["stage"]: s["survival_rate"] for s in stages if "candidates" in s["counts"] or s["stage"].startswith("post_")
    }

    density_collapse_contribution = _collapse_contribution(stages, base.sum())

    return {
        "ontology_filter_waterfall": True,
        "timeframe": timeframe,
        "candle_rows": n,
        "stages": stages,
        "filter_survival_rates": filter_survival_rates,
        "collapse_stage": collapse_stage,
        "density_collapse_contribution": density_collapse_contribution,
        "sell_side_base_candidates": int(base.sum()),
        "grey_zone_absorbed": int(grey.sum()),
    }


def _identify_collapse(stages: List[Dict], base_sell: int) -> str:
    prev = base_sell
    collapse = "none"
    for stage in stages:
        c = stage["counts"].get("candidates")
        if c is None:
            continue
        if prev > 0 and c == 0:
            collapse = stage["stage"]
            break
        if prev > 0 and c < prev * 0.25:
            collapse = stage["stage"]
        prev = c
    return collapse


def _collapse_contribution(stages: List[Dict], base_sell: int) -> Dict[str, float]:
    if base_sell <= 0:
        return {}
    out = {}
    prev = base_sell
    for stage in stages:
        c = stage["counts"].get("candidates")
        if c is None:
            continue
        loss = max(0, prev - c)
        out[stage["stage"]] = round(loss / base_sell, 4)
        prev = c
    return out
