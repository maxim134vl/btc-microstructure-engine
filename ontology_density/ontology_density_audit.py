"""Ontology density audit across legacy, refined, and current modes."""

from __future__ import annotations

from typing import Any, Dict

from ontology_density._climax_helpers import count_events, run_climax_mode
from ontology_density.expectation_model import build_timeframe_density_expectation
from stabilization_data_utils import load_candle_structure


def _density(counts: Dict[str, int], candles: int) -> Dict[str, float]:
    if candles <= 0:
        return {k: 0.0 for k in counts}
    return {k: round(v / candles, 6) for k, v in counts.items()}


def build_ontology_density_audit(timeframe: str = "M15") -> Dict[str, Any]:
    candles = load_candle_structure()
    n = len(candles)

    legacy_events = run_climax_mode("legacy", candles, timeframe)
    pre_dedup = run_climax_mode("refined_no_dedup", candles, timeframe)
    current_events = run_climax_mode("current", candles, timeframe)

    legacy_counts = count_events(legacy_events)
    pre_dedup_counts = count_events(pre_dedup)
    current_counts = count_events(current_events)

    expectation = build_timeframe_density_expectation(timeframe)

    density_by_mode = {
        "pre_phase_3a_legacy": _density(legacy_counts, n),
        "post_phase_3a_pre_dedup": _density(pre_dedup_counts, n),
        "post_phase_3b_current": _density(current_counts, n),
    }

    def _delta(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
        keys = set(a) | set(b)
        return {k: round(a.get(k, 0) - b.get(k, 0), 6) for k in keys}

    density_delta = {
        "legacy_to_current": _delta(density_by_mode["pre_phase_3a_legacy"], density_by_mode["post_phase_3b_current"]),
        "legacy_to_pre_dedup": _delta(density_by_mode["pre_phase_3a_legacy"], density_by_mode["post_phase_3a_pre_dedup"]),
        "pre_dedup_to_current": _delta(density_by_mode["post_phase_3a_pre_dedup"], density_by_mode["post_phase_3b_current"]),
    }

    def _ratio(current: float, baseline: float) -> float:
        if baseline <= 0:
            return 0.0 if current <= 0 else float("inf")
        return round(current / baseline, 4)

    ontology_density_ratio = {
        cls: _ratio(
            density_by_mode["post_phase_3b_current"].get(cls, 0),
            density_by_mode["pre_phase_3a_legacy"].get(cls, 0),
        )
        for cls in ("BUYING_CLIMAX", "SELLING_CLIMAX", "STOPPING_VOLUME", "HIGH_AVERAGE_VOLUME", "TOTAL_NON_NORMAL")
    }

    return {
        "ontology_density_audit": True,
        "timeframe": timeframe,
        "candle_rows": n,
        "counts_by_mode": {
            "pre_phase_3a_legacy": legacy_counts,
            "post_phase_3a_pre_dedup": pre_dedup_counts,
            "post_phase_3b_current": current_counts,
        },
        "ontology_density_by_timeframe": density_by_mode,
        "ontology_density_delta": density_delta,
        "ontology_density_ratio": ontology_density_ratio,
        "timeframe_density_expectation": expectation,
        "diagnosis_hint": _diagnosis_hint(density_by_mode, n, expectation),
    }


def _diagnosis_hint(densities: dict, n: int, expectation: dict) -> str:
    current = densities["post_phase_3b_current"]
    legacy = densities["pre_phase_3a_legacy"]
    if n < 500:
        return (
            "REPLAY_ENVIRONMENT: candle sample is small (<500 bars). "
            "Sparse counts may reflect short replay window as much as filtering."
        )
    if current.get("TOTAL_NON_NORMAL", 0) < legacy.get("TOTAL_NON_NORMAL", 0) * 0.25:
        return "ONTOLOGY_OVER_FILTERING: current density <25% of legacy on same dataset."
    expected = expectation["by_class_per_candle"]["SELLING_CLIMAX"]["typical_min"]
    if current.get("SELLING_CLIMAX", 0) < expected and legacy.get("SELLING_CLIMAX", 0) >= expected:
        return "SELL_SIDE_COLLAPSE: refined sell-side filters likely over-constrained vs architecture intent."
    return "DENSITY_WITHIN_EXPECTED_VARIANCE"
