"""Stage 2.5 calibration output paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from storage.path_registry import repo_root

CALIBRATION_ROOT = repo_root() / "benchmark" / "calibration"
REPORTS_DIR = CALIBRATION_ROOT / "reports"
HISTORY_DIR = CALIBRATION_ROOT / "history"
EXPORTS_DIR = CALIBRATION_ROOT / "exports"


def ensure_dirs() -> None:
    for path in (REPORTS_DIR, HISTORY_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def latest_pointer_path() -> Path:
    return REPORTS_DIR / "latest_stage2_5_calibration.json"


def weekly_history_path() -> Path:
    return HISTORY_DIR / "weekly_calibration.jsonl"
