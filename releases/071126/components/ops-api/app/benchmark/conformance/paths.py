"""Conformance benchmark output paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from storage.path_registry import repo_root

CONFORMANCE_ROOT = repo_root() / "benchmark" / "conformance"
REPORTS_DIR = CONFORMANCE_ROOT / "reports"
EXPORTS_DIR = CONFORMANCE_ROOT / "exports"
VISUALS_DIR = CONFORMANCE_ROOT / "visuals"
SPECS_DIR = repo_root() / "benchmark" / "specs"
HISTORY_DIR = CONFORMANCE_ROOT / "history"


def ensure_dirs() -> None:
    for path in (REPORTS_DIR, EXPORTS_DIR, VISUALS_DIR, HISTORY_DIR):
        path.mkdir(parents=True, exist_ok=True)


def run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def latest_pointer_path() -> Path:
    return REPORTS_DIR / "latest_conformance.json"
