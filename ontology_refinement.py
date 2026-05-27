"""Phase 3A SELLING_CLIMAX vs STOPPING_VOLUME semantic separation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ontology_config import OntologySettings, get_ontology_settings, ontology_refinement_active

ONTOLOGY_EXPORT_COLUMNS = [
    "effort_result_zone",
    "delta_behavior_shift",
    "recovery_structure_score",
    "cluster_id",
    "cluster_behavior_resolution",
    "cluster_events_suppressed",
    "ontology_refinement_active",
]

EVENT_PRIORITY = {
    "STOPPING_VOLUME": 3,
    "SELLING_CLIMAX": 2,
    "HIGH_AVERAGE_VOLUME": 1,
}

TRACKED_SELL_SIDE_EVENTS = frozenset(
    {"STOPPING_VOLUME", "SELLING_CLIMAX", "HIGH_AVERAGE_VOLUME"}
)


def log_ontology_warning(message: str) -> None:
    print(f"[ONTOLOGY WARNING] {message}")


def compute_delta_behavior_shift(dataset: pd.DataFrame) -> pd.Series:
    """Measure improving vs aggressive delta behavior (no lookahead)."""

    delta = dataset["delta"].astype(float)
    previous = delta.shift(1)
    shift = (delta - previous) / (previous.abs() + 1e-9)
    return shift.clip(-1.0, 1.0).fillna(0.0)


def compute_recovery_structure_score(dataset: pd.DataFrame) -> pd.Series:
    """Intra-candle recovery proxy using close position and lower wick."""

    close_position = dataset["close_position_ratio"].astype(float).fillna(0.5)
    lower_wick = dataset["lower_wick_ratio"].astype(float).fillna(0.0)
    return (close_position * 0.65 + lower_wick * 0.35).clip(0.0, 1.0)


def classify_effort_result_zone(
    efficiency_decay: pd.Series,
    settings: OntologySettings,
) -> pd.Series:
    zones = pd.Series("AMBIGUOUS", index=efficiency_decay.index)
    zones.loc[efficiency_decay > settings.selling_climax_min_decay] = "CAPITULATION"
    zones.loc[efficiency_decay < settings.stopping_volume_max_decay] = "ABSORPTION"
    return zones


def _base_sell_side_mask(dataset: pd.DataFrame) -> pd.Series:
    delta_threshold = dataset["delta"].rolling(20, min_periods=5).quantile(0.35)
    return (
        (dataset["volume_percentile_50"] >= 0.80)
        & (dataset["spread_percentile_50"] >= 0.45)
        & (dataset["delta"] < delta_threshold)
        & (dataset["range_position"] < 0.45)
        & (dataset["delta"] < 0)
    )


def apply_semantic_separation(
    dataset: pd.DataFrame,
    settings: Optional[OntologySettings] = None,
) -> pd.DataFrame:
    """Apply STOPPING first, SELLING second — mutual exclusion, no overwrite."""

    settings = settings or get_ontology_settings()
    frame = dataset.copy()

    frame["delta_behavior_shift"] = compute_delta_behavior_shift(frame)
    frame["recovery_structure_score"] = compute_recovery_structure_score(frame)
    frame["effort_result_zone"] = classify_effort_result_zone(
        frame["efficiency_decay"].astype(float),
        settings,
    )

    base_mask = _base_sell_side_mask(frame)
    normal_mask = frame["auction_event_type"] == "NORMAL"

    stopping_mask = (
        base_mask
        & normal_mask
        & (frame["efficiency_decay"] < settings.stopping_volume_max_decay)
        & (frame["close_position_ratio"] > 0.35)
        & (frame["lower_wick_ratio"] > 0.25)
        & (frame["delta_behavior_shift"] > 0.0)
        & (frame["effort_result_zone"] == "ABSORPTION")
    )

    frame.loc[stopping_mask, "auction_event_type"] = "STOPPING_VOLUME"
    frame.loc[stopping_mask, "location_bias"] = "LOWER_ABSORPTION"

    selling_mask = (
        base_mask
        & (frame["auction_event_type"] == "NORMAL")
        & (frame["efficiency_decay"] > settings.selling_climax_min_decay)
        & (frame["close_position_ratio"] < 0.25)
        & (frame["lower_wick_ratio"] < 0.20)
        & (frame["delta_behavior_shift"] <= 0.0)
        & (frame["effort_result_zone"] == "CAPITULATION")
    )

    frame.loc[selling_mask, "auction_event_type"] = "SELLING_CLIMAX"
    frame.loc[selling_mask, "location_bias"] = "LOWER_CAPITULATION"

    frame["ontology_refinement_active"] = True
    return frame


def apply_legacy_sell_side_classification(dataset: pd.DataFrame) -> pd.DataFrame:
    """Legacy sell-side ontology (includes runtime lookahead — rollback only)."""

    frame = dataset.copy()

    selling_climax_condition = (
        (frame["volume_percentile_50"] >= 0.80)
        & (frame["delta"] < frame["delta"].rolling(20).quantile(0.35))
        & (frame["spread_percentile_50"] >= 0.45)
        & (
            (frame["efficiency_decay"] < 0.80)
            | (frame["efficiency_decay"] > 1.20)
        )
        & (frame["range_position"] < 0.45)
    )

    frame.loc[selling_climax_condition, "auction_event_type"] = "SELLING_CLIMAX"
    frame.loc[selling_climax_condition, "location_bias"] = "LOWER_CAPITULATION"

    if "future_return_3" not in frame.columns:
        frame["future_return_3"] = (
            frame["close"].shift(-3) / frame["close"] - 1
        )

    stopping_volume_condition = (
        (frame["volume_percentile_50"] >= 0.85)
        & (frame["spread_percentile_50"] >= 0.45)
        & (frame["delta"] < 0)
        & (frame["range_position"] < 0.40)
        & (frame["lower_wick_ratio"] > 0.10)
        & (frame["future_return_3"] > 0)
        & (frame["efficiency_decay"] < 1.20)
    )

    frame.loc[stopping_volume_condition, "auction_event_type"] = "STOPPING_VOLUME"
    frame.loc[stopping_volume_condition, "location_bias"] = "LOWER_ABSORPTION"

    frame["ontology_refinement_active"] = False
    return frame


def _event_strength(row: pd.Series) -> float:
    volume_pct = float(row.get("volume_percentile_50", 0.0) or 0.0)
    spread_pct = float(row.get("spread_percentile_50", 0.0) or 0.0)
    return (volume_pct + spread_pct) / 2.0


def deduplicate_swing_clusters(
    dataset: pd.DataFrame,
    settings: Optional[OntologySettings] = None,
) -> pd.DataFrame:
    """Within swing-low clusters retain strongest behavioral event only."""

    settings = settings or get_ontology_settings()
    frame = dataset.copy()
    frame["cluster_id"] = -1
    frame["cluster_behavior_resolution"] = frame["auction_event_type"]
    frame["cluster_events_suppressed"] = 0

    event_mask = frame["auction_event_type"].isin(TRACKED_SELL_SIDE_EVENTS)
    event_indices = frame.index[event_mask].tolist()
    if not event_indices:
        return frame

    cluster_id = 0
    index_pos = {idx: pos for pos, idx in enumerate(frame.index)}

    grouped: List[List[int]] = []
    current_group: List[int] = []

    for idx in event_indices:
        row = frame.loc[idx]
        if float(row.get("range_position", 1.0)) >= 0.45:
            continue

        if not current_group:
            current_group = [idx]
            continue

        previous_idx = current_group[-1]
        gap = index_pos[idx] - index_pos[previous_idx]
        if gap <= settings.swing_cluster_window:
            current_group.append(idx)
        else:
            grouped.append(current_group)
            current_group = [idx]

    if current_group:
        grouped.append(current_group)

    for group in grouped:
        if len(group) <= 1:
            frame.loc[group[0], "cluster_id"] = cluster_id
            cluster_id += 1
            continue

        candidates = []
        for idx in group:
            event_type = frame.at[idx, "auction_event_type"]
            candidates.append(
                (
                    EVENT_PRIORITY.get(event_type, 0),
                    _event_strength(frame.loc[idx]),
                    idx,
                    event_type,
                )
            )

        candidates.sort(reverse=True)
        winner_idx = candidates[0][2]
        winner_type = candidates[0][3]

        frame.loc[group, "auction_event_type"] = "NORMAL"
        frame.loc[group, "location_bias"] = "NEUTRAL"
        frame.loc[winner_idx, "auction_event_type"] = winner_type
        frame.loc[winner_idx, "location_bias"] = (
            "LOWER_ABSORPTION"
            if winner_type == "STOPPING_VOLUME"
            else "LOWER_CAPITULATION"
            if winner_type == "SELLING_CLIMAX"
            else "MID_AUCTION_TRANSFER"
        )

        for idx in group:
            frame.at[idx, "cluster_id"] = cluster_id
            frame.at[idx, "cluster_behavior_resolution"] = winner_type
            frame.at[idx, "cluster_events_suppressed"] = max(0, len(group) - 1)

        cluster_id += 1

    return frame


def detect_overlap_violations(dataset: pd.DataFrame) -> List[Dict[str, Any]]:
    """Detect rows that would satisfy both refined sell-side classifications."""

    base_mask = _base_sell_side_mask(dataset)
    stopping_signals = (
        base_mask
        & (dataset["efficiency_decay"] < 0.85)
        & (dataset["close_position_ratio"] > 0.35)
        & (dataset["lower_wick_ratio"] > 0.25)
    )
    selling_signals = (
        base_mask
        & (dataset["efficiency_decay"] > 1.20)
        & (dataset["close_position_ratio"] < 0.25)
        & (dataset["lower_wick_ratio"] < 0.20)
    )

    overlap = stopping_signals & selling_signals
    violations = []
    for idx in dataset.index[overlap]:
        violations.append(
            {
                "index": int(idx) if isinstance(idx, (int, np.integer)) else idx,
                "timestamp": dataset.at[idx, "timestamp"]
                if "timestamp" in dataset.columns
                else None,
            }
        )
    return violations


def neutral_ontology_exports() -> Dict[str, Any]:
    return {
        "effort_result_zone": "NEUTRAL",
        "delta_behavior_shift": 0.0,
        "recovery_structure_score": 0.0,
        "cluster_id": -1,
        "cluster_behavior_resolution": "NONE",
        "cluster_events_suppressed": 0,
        "ontology_refinement_active": False,
    }


def apply_ontology_pipeline(
    dataset: pd.DataFrame,
    settings: Optional[OntologySettings] = None,
) -> pd.DataFrame:
    settings = settings or get_ontology_settings()

    if ontology_refinement_active(settings):
        frame = apply_semantic_separation(dataset, settings=settings)
        frame = deduplicate_swing_clusters(frame, settings=settings)

        if settings.warn_on_overlap:
            violations = detect_overlap_violations(frame)
            if violations:
                log_ontology_warning(
                    f"potential overlap signals detected: {len(violations)} rows"
                )
        return frame

    return apply_legacy_sell_side_classification(dataset)
