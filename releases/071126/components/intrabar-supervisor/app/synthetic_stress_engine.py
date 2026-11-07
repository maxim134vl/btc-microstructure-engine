"""Seedable synthetic stress scenarios for adversarial replay — no ontology rewrite."""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Tuple

STRESS_SCENARIOS = [
    "VOLATILITY_SPIKE",
    "FAKE_BREAKOUT",
    "LIQUIDITY_VACUUM",
    "DELAYED_CONTINUATION",
    "FRAGMENTED_AUCTION",
    "CONTRADICTION_FLOOD",
    "ENTROPY_SHOCK",
    "ABRUPT_REGIME_FLIP",
    "UNSTABLE_ABSORPTION",
    "RECURSIVE_REINFORCEMENT_TRAP",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def apply_stress_scenario(
    scenario: str,
    base_snapshot: Dict[str, Any],
    seed: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return stressed snapshot copy and scenario metadata (observability-only perturbation)."""

    rng = random.Random(seed)
    stressed = copy.deepcopy(base_snapshot)
    metadata = {
        "stress_scenario": scenario,
        "stress_seed": seed,
        "stress_applied": True,
    }

    if scenario == "VOLATILITY_SPIKE":
        stressed["entropy_penalty"] = _clamp(
            float(stressed.get("entropy_penalty", 0.0)) + 0.25 + rng.random() * 0.15
        )
        stressed["regime_transition_probability"] = _clamp(
            float(stressed.get("regime_transition_probability", 0.0)) + 0.30
        )

    elif scenario == "FAKE_BREAKOUT":
        jitter = rng.random() * 0.08
        stressed["raw_conviction"] = _clamp(
            float(stressed.get("raw_conviction", 0.5)) + 0.20 + jitter
        )
        stressed["reinforcement_component"] = _clamp(
            float(stressed.get("reinforcement_component", 0.0)) + 0.15 + jitter * 0.5
        )
        stressed["entropy_penalty"] = _clamp(
            float(stressed.get("entropy_penalty", 0.0)) + 0.12 + jitter * 0.25
        )

    elif scenario == "LIQUIDITY_VACUUM":
        stressed["absorption_probability"] = _clamp(
            float(stressed.get("absorption_probability", 0.0)) * 0.35
        )
        stressed["distribution_probability"] = _clamp(
            float(stressed.get("distribution_probability", 0.0)) * 0.35
        )
        stressed["conflict_density"] = _clamp(
            float(stressed.get("conflict_density", 0.0)) + 0.20
        )

    elif scenario == "DELAYED_CONTINUATION":
        stressed["persistence_component"] = _clamp(
            float(stressed.get("persistence_component", 0.0)) * 0.50
        )
        stressed["raw_conviction"] = _clamp(
            float(stressed.get("raw_conviction", 0.5)) + 0.08
        )

    elif scenario == "FRAGMENTED_AUCTION":
        stressed["conflict_density"] = _clamp(
            float(stressed.get("conflict_density", 0.0)) + 0.35
        )
        stressed["contradiction_flags"] = (
            str(stressed.get("contradiction_flags", ""))
            + "|absorption_distribution_coexistence|continuation_plus_distribution"
        ).strip("|")

    elif scenario == "CONTRADICTION_FLOOD":
        jitter = rng.random() * 0.10
        stressed["conflict_density"] = _clamp(
            float(stressed.get("conflict_density", 0.0)) + 0.45 + jitter
        )
        stressed["contradiction_escalation_score"] = _clamp(
            float(stressed.get("contradiction_escalation_score", 0.0)) + 0.25 + jitter * 0.5
        )

    elif scenario == "ENTROPY_SHOCK":
        stressed["entropy_penalty"] = _clamp(
            float(stressed.get("entropy_penalty", 0.0)) + 0.40 + rng.random() * 0.10
        )
        stressed["entropy_transition_type"] = "LOW_TO_HIGH_ENTROPY"

    elif scenario == "ABRUPT_REGIME_FLIP":
        stressed["regime_state"] = "VOLATILITY_EXPANSION"
        stressed["regime_confidence"] = 0.35 + rng.random() * 0.15
        stressed["regime_transition_probability"] = 0.85

    elif scenario == "UNSTABLE_ABSORPTION":
        stressed["absorption_probability"] = _clamp(
            float(stressed.get("absorption_probability", 0.0)) + 0.30
        )
        stressed["persistence_component"] = _clamp(
            float(stressed.get("persistence_component", 0.0)) * 0.40
        )
        stressed["regime_state"] = "ABSORPTION_RECOVERY"

    elif scenario == "RECURSIVE_REINFORCEMENT_TRAP":
        jitter = rng.random() * 0.08
        stressed["reinforcement_component"] = _clamp(
            float(stressed.get("reinforcement_component", 0.0)) + 0.25 + jitter
        )
        stressed["reinforcement_acceleration"] = _clamp(
            float(stressed.get("reinforcement_acceleration", 0.0)) + 0.12 + jitter * 0.5
        )
        stressed["runaway_reinforcement"] = True

    else:
        metadata["stress_applied"] = False

    return stressed, metadata


def generate_all_stress_scenarios(
    base_snapshot: Dict[str, Any],
    seed: int = 42,
) -> List[Dict[str, Any]]:
    outputs = []
    for index, scenario in enumerate(STRESS_SCENARIOS):
        stressed, metadata = apply_stress_scenario(
            scenario,
            base_snapshot,
            seed=seed + index,
        )
        outputs.append(
            {
                "scenario": scenario,
                "stressed_snapshot": stressed,
                "metadata": metadata,
            }
        )
    return outputs


def stress_degradation_score(
    baseline_snapshot: Dict[str, Any],
    stressed_snapshot: Dict[str, Any],
) -> float:
    """Measure probabilistic degradation under stress (observability metric)."""

    base_conviction = float(
        baseline_snapshot.get(
            "disciplined_conviction",
            baseline_snapshot.get("raw_conviction", 0.0),
        )
    )
    stressed_conviction = float(
        stressed_snapshot.get(
            "disciplined_conviction",
            stressed_snapshot.get("raw_conviction", base_conviction),
        )
    )
    base_entropy = float(baseline_snapshot.get("entropy_penalty", 0.0))
    stressed_entropy = float(stressed_snapshot.get("entropy_penalty", base_entropy))
    base_conflict = float(baseline_snapshot.get("conflict_density", 0.0))
    stressed_conflict = float(stressed_snapshot.get("conflict_density", base_conflict))

    conviction_shift = abs(stressed_conviction - base_conviction)
    entropy_shift = abs(stressed_entropy - base_entropy)
    conflict_shift = abs(stressed_conflict - base_conflict)

    return _clamp(
        conviction_shift * 0.45
        + entropy_shift * 0.30
        + conflict_shift * 0.25
    )
