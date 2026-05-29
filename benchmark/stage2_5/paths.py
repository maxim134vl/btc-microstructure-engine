"""Stage 2.5 benchmark output paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from storage.path_registry import repo_root

BENCHMARK_ROOT = repo_root() / "benchmark"
REPORTS_DIR = BENCHMARK_ROOT / "reports"
EXPORTS_DIR = BENCHMARK_ROOT / "exports"
VISUALS_DIR = BENCHMARK_ROOT / "visuals"
REPLAY_DIR = BENCHMARK_ROOT / "replay"


def ensure_dirs() -> None:
    for path in (REPORTS_DIR, EXPORTS_DIR, VISUALS_DIR, REPLAY_DIR):
        path.mkdir(parents=True, exist_ok=True)


def run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def latest_pointer_path() -> Path:
    return REPORTS_DIR / "latest_stage2_5.json"
