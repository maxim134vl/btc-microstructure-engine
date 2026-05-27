"""Probabilistic cross-regime segmentation — observability layer, no ontology rewrite."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

REGIME_STATES = [
    "TREND_EXPANSION",
    "TREND_EXHAUSTION",
    "COMPRESSION",
    "VOLATILITY_EXPANSION",
    "VOLATILITY_COLLAPSE",
    "LIQUIDATION_EVENT",
    "ABSORPTION_RECOVERY",
    "BALANCED_AUCTION",
]

REGIME_EXPORT_COLUMNS = [
    "regime_state",
    "regime_confidence",
    "regime_transition_probability",
    "regime_probability_vector",
]

REGIME_PRIOR = 0.08


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _spread_volatility(candle_history: Optional[pd.DataFrame]) -> tuple[float, float]:
    if candle_history is None or len(candle_history) < 3:
        return 0.0, 0.0

    spread = pd.to_numeric(candle_history.get("spread"), errors="coerce").dropna()
    if len(spread) < 3:
        return 0.0, 0.0

    recent = spread.tail(10)
    mean_spread = float(recent.mean())
    delta = float(recent.iloc[-1] - recent.iloc[-2]) if len(recent) >= 2 else 0.0
    volatility = float(recent.std()) if len(recent) > 1 else 0.0
    normalized_delta = delta / max(mean_spread, 1e-6)
    return normalized_delta, volatility


def score_regime_likelihoods(
    snapshot: Dict[str, Any],
    runtime_cognition: Dict[str, Any],
    candle_history: Optional[pd.DataFrame] = None,
) -> Dict[str, float]:
    scores = {regime: REGIME_PRIOR for regime in REGIME_STATES}

    auction_regime = str(snapshot.get("auction_regime", "UNCERTAIN"))
    raw_conviction = float(
        snapshot.get(
            "raw_conviction",
            snapshot.get("conviction_probability", 0.0),
        )
    )
    absorption = float(snapshot.get("absorption_probability", 0.0))
    distribution = float(snapshot.get("distribution_probability", 0.0))
    entropy = float(snapshot.get("entropy_penalty", 0.0))
    conflict_density = float(snapshot.get("conflict_density", 0.0))

    synthesis_state = str(runtime_cognition.get("synthesis_state", "NONE"))
    location_bias = str(runtime_cognition.get("location_bias", "NEUTRAL"))
    trigger_event = str(runtime_cognition.get("trigger_event", "NONE"))
    persistence_score = float(runtime_cognition.get("persistence_score", 0.0))

    spread_delta, spread_volatility = _spread_volatility(candle_history)

    if auction_regime == "HIGH_CONVICTION_AUCTION" and raw_conviction > 0.55:
        scores["TREND_EXPANSION"] += 0.35 + min(0.20, raw_conviction * 0.2)

    if synthesis_state == "LOCAL_EXHAUSTION" or auction_regime == "STRUCTURAL_REGIME":
        scores["TREND_EXHAUSTION"] += 0.40

    if (
        absorption < 0.45
        and distribution < 0.45
        and raw_conviction < 0.55
        and spread_volatility < 0.15
    ):
        scores["COMPRESSION"] += 0.35

    if spread_delta > 0.08 or spread_volatility > 0.20:
        scores["VOLATILITY_EXPANSION"] += 0.30 + min(0.15, spread_delta)

    if spread_delta < -0.08 and spread_volatility < 0.12:
        scores["VOLATILITY_COLLAPSE"] += 0.30

    if (
        location_bias == "LOWER_CAPITULATION"
        or "CLIMAX" in trigger_event
        or trigger_event in {"STOPPING_VOLUME", "SELLING_CLIMAX", "BUYING_CLIMAX"}
    ):
        scores["LIQUIDATION_EVENT"] += 0.35

    if (
        auction_regime == "ABSORPTION_REGIME"
        or location_bias == "LOWER_ABSORPTION"
        or absorption > 0.50
    ):
        scores["ABSORPTION_RECOVERY"] += 0.35

    if entropy > 0.55 and conflict_density > 0.25:
        scores["BALANCED_AUCTION"] += 0.25

    if persistence_score < 0.35 and raw_conviction < 0.60:
        scores["BALANCED_AUCTION"] += 0.20

    if auction_regime == "UNCERTAIN":
        scores["BALANCED_AUCTION"] += 0.25

    return scores


def normalize_regime_scores(scores: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(value, 0.0) for value in scores.values())
    if total <= 0:
        uniform = 1.0 / len(REGIME_STATES)
        return {regime: uniform for regime in REGIME_STATES}
    return {regime: max(value, 0.0) / total for regime, value in scores.items()}


def compute_regime_transition_probability(
    current_regime: str,
    probabilistic_history: Optional[pd.DataFrame],
) -> float:
    if (
        probabilistic_history is None
        or len(probabilistic_history) < 2
        or "regime_state" not in probabilistic_history.columns
    ):
        return 0.0

    recent = probabilistic_history["regime_state"].dropna().tail(10).tolist()
    if not recent:
        return 0.0

    transitions = sum(
        1 for index in range(1, len(recent)) if recent[index] != recent[index - 1]
    )
    base_rate = transitions / max(len(recent) - 1, 1)
    if recent[-1] != current_regime:
        return _clamp(base_rate + 0.25)
    return _clamp(base_rate)


def infer_regime_segmentation(
    snapshot: Dict[str, Any],
    runtime_cognition: Dict[str, Any],
    probabilistic_history: Optional[pd.DataFrame] = None,
    candle_history: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    scores = score_regime_likelihoods(
        snapshot,
        runtime_cognition,
        candle_history=candle_history,
    )
    probabilities = normalize_regime_scores(scores)
    regime_state = max(probabilities, key=probabilities.get)
    regime_confidence = float(probabilities[regime_state])
    transition_probability = compute_regime_transition_probability(
        regime_state,
        probabilistic_history,
    )

    vector = "|".join(
        f"{regime}:{probabilities[regime]:.3f}" for regime in REGIME_STATES
    )

    return {
        "regime_state": regime_state,
        "regime_confidence": regime_confidence,
        "regime_transition_probability": transition_probability,
        "regime_probability_vector": vector,
    }
