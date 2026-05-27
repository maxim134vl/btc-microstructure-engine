"""Post-event behavioral evolution metrics — no lookahead dependency."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ontology_config import OntologySettings, get_ontology_settings

POST_EVENT_EXPORT_COLUMNS = [
    "climax_resolution_behavior",
    "absorption_persistence_score",
    "continuation_failure_rate",
    "stabilization_duration",
    "post_climax_entropy_shift",
    "inventory_transfer_quality",
    "capitulation_decay_rate",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _resolve_behavior_label(
    event_type: str,
    continuation_failure: float,
    absorption_persistence: float,
) -> str:
    if event_type == "STOPPING_VOLUME":
        if absorption_persistence >= 0.55 and continuation_failure <= 0.45:
            return "ABSORPTION_HELD"
        if continuation_failure >= 0.65:
            return "ABSORPTION_FAILED"
        return "ABSORPTION_UNRESOLVED"

    if event_type == "SELLING_CLIMAX":
        if continuation_failure >= 0.60:
            return "CAPITULATION_CONTINUED"
        if absorption_persistence >= 0.50:
            return "CAPITULATION_ABSORBED"
        return "CAPITULATION_DECAYING"

    return "UNCLASSIFIED"


def compute_post_event_evolution(
    dataset: pd.DataFrame,
    settings: Optional[OntologySettings] = None,
) -> pd.DataFrame:
    """Compute evolution metrics using only bars after each event (batch-safe)."""

    settings = settings or get_ontology_settings()
    horizon = settings.post_event_horizon
    frame = dataset.copy()

    for column in POST_EVENT_EXPORT_COLUMNS:
        frame[column] = np.nan

    event_types = {"STOPPING_VOLUME", "SELLING_CLIMAX"}
    event_indices = frame.index[
        frame["auction_event_type"].isin(event_types)
    ].tolist()

    for idx in event_indices:
        position = frame.index.get_loc(idx)
        if isinstance(position, slice):
            continue

        future = frame.iloc[position + 1 : position + 1 + horizon]
        if len(future) == 0:
            continue

        event_type = frame.at[idx, "auction_event_type"]
        event_delta = float(frame.at[idx, "delta"])
        event_decay = float(frame.at[idx, "efficiency_decay"])

        close_positions = future.get(
            "close_position_ratio",
            pd.Series(dtype=float),
        ).astype(float)
        deltas = future["delta"].astype(float)
        decays = future["efficiency_decay"].astype(float)

        absorption_persistence = _clamp(close_positions.mean())
        negative_continuation = (deltas < 0).mean()
        continuation_failure = _clamp(negative_continuation)

        stabilization = 0
        for decay_value in decays:
            if float(decay_value) < settings.stopping_volume_max_decay:
                stabilization += 1
            else:
                break

        entropy_shift = _clamp(
            (decays.mean() - event_decay) / (abs(event_decay) + 1e-9),
            -1.0,
            1.0,
        )

        delta_decay = deltas.mean() - event_delta
        capitulation_decay = _clamp(
            (-delta_decay) / (abs(event_delta) + 1e-9),
            0.0,
            1.0,
        )

        recovery_gain = _clamp(
            float(close_positions.iloc[-1]) - float(
                frame.at[idx, "close_position_ratio"]
            ),
            0.0,
            1.0,
        )
        inventory_transfer = _clamp(
            absorption_persistence * 0.55
            + recovery_gain * 0.25
            + (1.0 - continuation_failure) * 0.20,
        )

        resolution = _resolve_behavior_label(
            event_type,
            continuation_failure,
            absorption_persistence,
        )

        frame.at[idx, "climax_resolution_behavior"] = resolution
        frame.at[idx, "absorption_persistence_score"] = absorption_persistence
        frame.at[idx, "continuation_failure_rate"] = continuation_failure
        frame.at[idx, "stabilization_duration"] = float(stabilization)
        frame.at[idx, "post_climax_entropy_shift"] = entropy_shift
        frame.at[idx, "inventory_transfer_quality"] = inventory_transfer
        frame.at[idx, "capitulation_decay_rate"] = capitulation_decay

    return frame


def neutral_post_event_exports() -> Dict[str, Any]:
    return {
        "climax_resolution_behavior": "UNCLASSIFIED",
        "absorption_persistence_score": 0.0,
        "continuation_failure_rate": 0.0,
        "stabilization_duration": 0.0,
        "post_climax_entropy_shift": 0.0,
        "inventory_transfer_quality": 0.0,
        "capitulation_decay_rate": 0.0,
    }
