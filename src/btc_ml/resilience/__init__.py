"""Resilience module shims."""

from adversarial_ontology_stability import evaluate_ontology_under_stress
from calibration_resilience import compute_resilience_metrics
from ontology_drift_detection import detect_ontology_drift

__all__ = [
    "evaluate_ontology_under_stress",
    "compute_resilience_metrics",
    "detect_ontology_drift",
]
