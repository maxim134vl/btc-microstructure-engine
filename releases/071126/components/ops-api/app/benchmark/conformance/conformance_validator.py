"""Compare expected benchmark behavior against observed runtime profile."""

from __future__ import annotations

from typing import Any


def _observed_value(profile: dict[str, Any], spec: dict[str, Any]) -> float | None:
    key = spec.get("observed_key")
    if not key:
        return None
    value = profile.get(key)
    if value is None:
        return None
    return float(value)


def _score_metric(observed: float | None, spec: dict[str, Any]) -> tuple[str, str, float]:
    if observed is None:
        return "PARTIAL", "No observed runtime data for this metric.", 0.0

    min_val = spec.get("min")
    max_val = spec.get("max")
    inverse_max = spec.get("inverse_max")
    inverse_key = spec.get("inverse_key")

    divergence = 0.0
    if min_val is not None and observed < float(min_val):
        gap = float(min_val) - observed
        divergence = min(1.0, gap / max(float(min_val), 0.01))
        if divergence >= 0.5:
            return "SEVERE_DRIFT", f"Observed {observed:.1%} below minimum {float(min_val):.1%}.", divergence
        if divergence >= 0.25:
            return "DRIFTING", f"Observed {observed:.1%} drifting below expected {float(min_val):.1%}.", divergence
        return "PARTIAL", f"Observed {observed:.1%} slightly below expected {float(min_val):.1%}.", divergence

    if max_val is not None and observed > float(max_val):
        gap = observed - float(max_val)
        divergence = min(1.0, gap / max(float(max_val), 0.01))
        if divergence >= 0.5:
            return "SEVERE_DRIFT", f"Observed {observed:.1%} exceeds maximum {float(max_val):.1%}.", divergence
        if divergence >= 0.25:
            return "DRIFTING", f"Observed {observed:.1%} drifting above expected {float(max_val):.1%}.", divergence
        return "FAILED", f"Observed {observed:.1%} exceeds maximum {float(max_val):.1%}.", divergence

    if inverse_key and inverse_max is not None:
        # handled separately when inverse profile value passed in validate_layer
        pass

    return "CONFIRMED", f"Observed {observed:.1%} within architectural expectations.", 0.0


def validate_layer(
    layer: str,
    spec: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    metrics = spec.get("metrics") or {}

    for metric_name, metric_spec in metrics.items():
        observed = _observed_value(profile, metric_spec)
        verdict, note, divergence = _score_metric(observed, metric_spec)

        inverse_key = metric_spec.get("inverse_key")
        inverse_max = metric_spec.get("inverse_max")
        if inverse_key and inverse_max is not None:
            inverse_observed = profile.get(inverse_key)
            if inverse_observed is not None and float(inverse_observed) > float(inverse_max):
                verdict = "CALIBRATION_COLLAPSE" if float(inverse_observed) >= float(inverse_max) * 1.5 else "FAILED"
                note = (
                    f"Inverse metric {inverse_key}={float(inverse_observed):.1%} "
                    f"exceeds max {float(inverse_max):.1%}."
                )
                divergence = max(divergence, min(1.0, float(inverse_observed) - float(inverse_max)))

        if metric_name in ("ontology_coherence", "market_structure_coherence") and verdict in ("FAILED", "SEVERE_DRIFT"):
            verdict = "ONTOLOGY_DEGRADATION"

        results.append(
            {
                "layer": layer,
                "metric": metric_name,
                "expected_level": metric_spec.get("expected_level"),
                "expected_description": metric_spec.get("description"),
                "observed_key": metric_spec.get("observed_key"),
                "observed_value": observed,
                "min": metric_spec.get("min"),
                "max": metric_spec.get("max"),
                "verdict": verdict,
                "note": note,
                "divergence": round(divergence, 4),
                "calibration_hint": metric_spec.get("calibration_hint"),
            }
        )

    return results
