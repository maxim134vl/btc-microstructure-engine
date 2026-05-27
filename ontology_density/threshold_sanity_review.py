"""Threshold sanity review — current vs legacy vs architecture docs."""

from __future__ import annotations

from typing import Any, Dict

from ontology_config import get_ontology_settings


def build_threshold_sanity_review(timeframe: str = "M15") -> Dict[str, Any]:
    settings = get_ontology_settings()

    architecture_doc_thresholds = {
        "efficiency_decay_grey_zone": (settings.grey_zone_low, settings.grey_zone_high),
        "selling_climax_min_decay": settings.selling_climax_min_decay,
        "stopping_volume_max_decay": settings.stopping_volume_max_decay,
        "stopping_lower_wick_min": "0.25 (EFFORT_RESULT_SEMANTICS) / 0.10 (legacy runtime)",
        "stopping_delta_shift": "> 0 (refined) — legacy used future_return_3 lookahead (removed 3A)",
    }

    current = {
        "selling_climax_min_decay": settings.selling_climax_min_decay,
        "stopping_volume_max_decay": settings.stopping_volume_max_decay,
        "grey_zone_low": settings.grey_zone_low,
        "grey_zone_high": settings.grey_zone_high,
        "stopping_min_lower_wick_ratio": settings.stopping_min_lower_wick_ratio,
        "stopping_min_delta_shift": settings.stopping_min_delta_shift,
        "stopping_recovery_score_alt": settings.stopping_recovery_score_alt,
        "selling_max_lower_wick_ratio": settings.selling_max_lower_wick_ratio,
        "selling_max_delta_shift": settings.selling_max_delta_shift,
        "swing_cluster_window": settings.swing_cluster_window,
    }

    legacy_reference = {
        "selling_climax_efficiency": "< 0.80 OR > 1.20 (combined path — semantic collapse fixed in 3A)",
        "stopping_lower_wick": "> 0.10",
        "stopping_future_return_3": "> 0 (removed from refined runtime — no lookahead)",
    }

    assessment = []
    if settings.stopping_min_lower_wick_ratio > 0.15:
        assessment.append("stopping_wick_threshold_stricter_than_legacy")
    if settings.stopping_min_delta_shift > 0 and settings.stopping_recovery_score_alt >= 0.5:
        assessment.append("stopping_delta_path_strict_without_lookahead_substitute")

    return {
        "threshold_sanity_review": True,
        "timeframe": timeframe,
        "current_thresholds": current,
        "legacy_reference_thresholds": legacy_reference,
        "architecture_doc_thresholds": architecture_doc_thresholds,
        "assessment_flags": assessment,
        "restoration_guidance": (
            "Relax secondary STOPPING discriminators (wick, delta/recovery) while "
            "preserving effort/result grey-zone separation per Phase 3A architecture."
        ),
    }
