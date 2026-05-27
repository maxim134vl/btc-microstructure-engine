"""Phase 3A ontology refinement feature flags — semantic separation only."""

from __future__ import annotations

import os
from dataclasses import dataclass

from calibration_config import _env_bool, _env_float


@dataclass(frozen=True)
class OntologySettings:
    enable_ontology_refinement: bool = True
    use_legacy_climax_ontology: bool = False
    selling_climax_min_decay: float = 1.20
    stopping_volume_max_decay: float = 0.85
    grey_zone_low: float = 0.85
    grey_zone_high: float = 1.20
    swing_cluster_window: int = 5
    post_event_horizon: int = 5
    warn_on_overlap: bool = True


def get_ontology_settings() -> OntologySettings:
    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    return OntologySettings(
        enable_ontology_refinement=_env_bool(
            "ENABLE_ONTOLOGY_REFINEMENT",
            True,
        ),
        use_legacy_climax_ontology=_env_bool(
            "USE_LEGACY_CLIMAX_ONTOLOGY",
            False,
        ),
        selling_climax_min_decay=_env_float(
            "SELLING_CLIMAX_MIN_DECAY",
            1.20,
        ),
        stopping_volume_max_decay=_env_float(
            "STOPPING_VOLUME_MAX_DECAY",
            0.85,
        ),
        grey_zone_low=_env_float("ONTOLOGY_GREY_ZONE_LOW", 0.85),
        grey_zone_high=_env_float("ONTOLOGY_GREY_ZONE_HIGH", 1.20),
        swing_cluster_window=_env_int("SWING_CLUSTER_WINDOW", 5),
        post_event_horizon=_env_int("POST_EVENT_HORIZON", 5),
        warn_on_overlap=_env_bool("ONTOLOGY_WARN_ON_OVERLAP", True),
    )


def ontology_refinement_active(settings: OntologySettings | None = None) -> bool:
    settings = settings or get_ontology_settings()
    return settings.enable_ontology_refinement and not settings.use_legacy_climax_ontology
