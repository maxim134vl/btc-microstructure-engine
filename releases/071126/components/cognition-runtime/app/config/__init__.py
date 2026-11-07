"""Unified configuration layer — single source of truth (Phase 4A)."""

from config.adversarial import get_adversarial_settings
from config.calibration import get_calibration_settings
from config.ontology import get_ontology_settings, ontology_refinement_active
from config.replay import get_replay_settings
from config.runtime import (
    DATASET_DIRECTORY,
    ENABLE_EVENT_DRIVEN,
    ENABLE_RUNTIME_CACHE,
    LEGACY_LIVE_FEED_PARQUET,
    LIVE_MARKET_FEED_PARQUET,
    MAX_STATE_ROWS,
    RUNTIME_LOOP_DELAY,
    STATE_DIRECTORY,
)
from config.stabilization import get_stabilization_settings, stabilization_active

__all__ = [
    "DATASET_DIRECTORY",
    "ENABLE_EVENT_DRIVEN",
    "ENABLE_RUNTIME_CACHE",
    "LEGACY_LIVE_FEED_PARQUET",
    "LIVE_MARKET_FEED_PARQUET",
    "MAX_STATE_ROWS",
    "RUNTIME_LOOP_DELAY",
    "STATE_DIRECTORY",
    "get_adversarial_settings",
    "get_calibration_settings",
    "get_ontology_settings",
    "get_replay_settings",
    "get_stabilization_settings",
    "ontology_refinement_active",
    "stabilization_active",
]
