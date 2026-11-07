"""Phase 3B ontology stabilization feature flags — warning-only, no auto-correction."""

from __future__ import annotations

import os
from dataclasses import dataclass

from calibration_config import _env_bool, _env_float


@dataclass(frozen=True)
class StabilizationSettings:
    enable_ontology_stabilization: bool = True
    warn_on_drift: bool = True
    drift_warning_threshold: float = 0.45
    fragility_warning_threshold: float = 0.45
    overlap_warning_threshold: float = 0.35


def get_stabilization_settings() -> StabilizationSettings:
    return StabilizationSettings(
        enable_ontology_stabilization=_env_bool(
            "ENABLE_ONTOLOGY_STABILIZATION",
            True,
        ),
        warn_on_drift=_env_bool("STABILIZATION_WARN_ON_DRIFT", True),
        drift_warning_threshold=_env_float("ONTOLOGY_DRIFT_WARNING_THRESHOLD", 0.45),
        fragility_warning_threshold=_env_float(
            "SEMANTIC_FRAGILITY_WARNING_THRESHOLD",
            0.45,
        ),
        overlap_warning_threshold=_env_float(
            "ONTOLOGY_OVERLAP_WARNING_THRESHOLD",
            0.35,
        ),
    )


def stabilization_active(settings: StabilizationSettings | None = None) -> bool:
    settings = settings or get_stabilization_settings()
    return settings.enable_ontology_stabilization
