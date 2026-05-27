"""Adversarial ontology stability — ensure semantic separation under stress."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ontology_refinement import (
    EVENT_PRIORITY,
    apply_semantic_separation,
    detect_overlap_violations,
    deduplicate_swing_clusters,
)
from synthetic_stress_engine import STRESS_SCENARIOS, apply_stress_scenario

STABILITY_EXPORT_COLUMNS = [
    "ontology_separation_score",
    "ontology_overlap_count",
    "ontology_stress_scenarios_tested",
    "ontology_stress_failures",
    "ontology_adversarial_stable",
]


def _build_baseline_snapshot() -> Dict[str, Any]:
    return {
        "volume_percentile_50": 0.90,
        "spread_percentile_50": 0.55,
        "delta": -1200.0,
        "range_position": 0.30,
        "efficiency_decay": 0.70,
        "close_position_ratio": 0.42,
        "lower_wick_ratio": 0.30,
        "auction_event_type": "NORMAL",
        "location_bias": "NEUTRAL",
    }


def _snapshot_to_frame(snapshot: Dict[str, Any], context_rows: int = 25) -> pd.DataFrame:
    """Build multi-row frame so rolling quantiles work under stress replay."""

    rows: List[Dict[str, Any]] = []
    for offset in range(context_rows):
        row = dict(snapshot)
        volume_pct = float(row.get("volume_percentile_50", 0.5))
        spread_pct = float(row.get("spread_percentile_50", 0.5))
        row["volume_percentile_50"] = max(0.2, volume_pct - (context_rows - offset) * 0.01)
        row["spread_percentile_50"] = max(0.2, spread_pct - (context_rows - offset) * 0.005)
        row["delta"] = float(row.get("delta", -500.0)) * (0.85 + offset * 0.01)
        row["auction_event_type"] = "NORMAL"
        row["location_bias"] = "NEUTRAL"
        rows.append(row)

    rows[-1] = dict(snapshot)
    rows[-1]["auction_event_type"] = "NORMAL"
    rows[-1]["location_bias"] = "NEUTRAL"
    return pd.DataFrame(rows)


def evaluate_ontology_under_stress(
    base_snapshot: Dict[str, Any] | None = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run refined ontology through adversarial stress perturbations."""

    base_snapshot = base_snapshot or _build_baseline_snapshot()
    failures: List[str] = []
    tested = 0

    for index, scenario in enumerate(STRESS_SCENARIOS):
        tested += 1
        stressed_snapshot, _ = apply_stress_scenario(
            scenario,
            base_snapshot,
            seed=seed + index,
        )
        frame = _snapshot_to_frame(stressed_snapshot)
        frame = apply_semantic_separation(frame)
        frame = deduplicate_swing_clusters(frame)
        classified = frame.iloc[-1]

        overlap = detect_overlap_violations(frame)
        if overlap:
            failures.append(f"{scenario}:overlap")

        event_type = classified["auction_event_type"]
        if event_type in {"STOPPING_VOLUME", "SELLING_CLIMAX"}:
            zone = classified.get("effort_result_zone")
            if event_type == "STOPPING_VOLUME" and zone == "CAPITULATION":
                failures.append(f"{scenario}:stopping_in_capitulation_zone")
            if event_type == "SELLING_CLIMAX" and zone == "ABSORPTION":
                failures.append(f"{scenario}:selling_in_absorption_zone")

    overlap_count = len(detect_overlap_violations(_snapshot_to_frame(base_snapshot)))
    separation_score = max(0.0, 1.0 - (len(failures) / max(tested, 1)))

    return {
        "ontology_separation_score": round(separation_score, 4),
        "ontology_overlap_count": overlap_count,
        "ontology_stress_scenarios_tested": tested,
        "ontology_stress_failures": "|".join(failures) if failures else "NONE",
        "ontology_adversarial_stable": len(failures) == 0,
        "event_priority_order": list(EVENT_PRIORITY.keys()),
    }


def neutral_stability_exports() -> Dict[str, Any]:
    return {
        "ontology_separation_score": 1.0,
        "ontology_overlap_count": 0,
        "ontology_stress_scenarios_tested": 0,
        "ontology_stress_failures": "NONE",
        "ontology_adversarial_stable": True,
    }
