"""Longitudinal cognition memory paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from storage.path_registry import repo_root

MEMORY_ROOT = repo_root() / "benchmark" / "memory"
HISTORY_DIR = MEMORY_ROOT / "history"
CYCLES_DIR = HISTORY_DIR / "cycles"
REPORTS_DIR = MEMORY_ROOT / "reports"
EXPORTS_DIR = MEMORY_ROOT / "exports"
VISUALS_DIR = MEMORY_ROOT / "visuals"
DATASETS_DIR = MEMORY_ROOT / "datasets"

DATASET_BUCKETS = (
    "validated_cognition",
    "failed_cognition",
    "contradiction_events",
    "drift_epochs",
    "toxic_periods",
    "calibration_history",
    "regression_history",
    "ontology_health_history",
)


def ensure_dirs() -> None:
    for path in (HISTORY_DIR, CYCLES_DIR, REPORTS_DIR, EXPORTS_DIR, VISUALS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for bucket in DATASET_BUCKETS:
        (DATASETS_DIR / bucket).mkdir(parents=True, exist_ok=True)


def run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def index_path() -> Path:
    return MEMORY_ROOT / "index.json"


def latest_evolution_path() -> Path:
    return REPORTS_DIR / "latest_evolution.json"
