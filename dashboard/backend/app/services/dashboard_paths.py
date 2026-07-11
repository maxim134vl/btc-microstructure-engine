"""Dashboard-local parquet path resolution overlays.

Does not modify storage/path_registry.py. Used only by the ops monitor API
to locate research/cognition artifacts that live under data/* but are not
always present in the root registry.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import REPO_ROOT
from storage.path_registry import data_root, normalize_filename, resolve_read

# Known on-disk locations for research / decision artifacts (read-only).
DASHBOARD_PARQUET_CANDIDATES: dict[str, tuple[str, ...]] = {
    "market_state_memory.parquet": (
        "data/cognition/market_state_memory.parquet",
        "data/probabilistic/market_state_memory.parquet",
    ),
    "trading_state_memory.parquet": (
        "data/cognition/trading_state_memory.parquet",
        "data/probabilistic/trading_state_memory.parquet",
    ),
    "trading_state_feature_snapshots.parquet": (
        "data/replay/trading_state_feature_snapshots.parquet",
        "data/cognition/trading_state_feature_snapshots.parquet",
    ),
    "trading_state_validation_memory.parquet": (
        "data/diagnostics/trading_state_validation_memory.parquet",
    ),
    "economic_validation_memory.parquet": (
        "data/diagnostics/economic_validation_memory.parquet",
        "data/ml/economic_validation_memory.parquet",
    ),
    "shadow_inference_memory.parquet": (
        "data/ml/shadow_inference_memory.parquet",
        "data/diagnostics/shadow_inference_memory.parquet",
    ),
    "model_monitoring_memory.parquet": (
        "data/ml/model_monitoring_memory.parquet",
        "data/diagnostics/model_monitoring_memory.parquet",
    ),
    "toxic_box_memory.parquet": (
        "data/diagnostics/toxic_box_memory.parquet",
        "data/ml/toxic_box_memory.parquet",
    ),
    "runtime_engine_state.parquet": (
        "runtime_engine_state.parquet",
        "data/diagnostics/runtime_engine_state.parquet",
        "data/runtime/runtime_engine_state.parquet",
    ),
}


def resolve_dashboard_read(name: str) -> str:
    """Resolve parquet for dashboard reads: registry first, then known data/* paths."""
    filename = normalize_filename(name)
    primary = resolve_read(filename)
    if os.path.exists(primary):
        return primary

    root = Path(REPO_ROOT)
    for relative in DASHBOARD_PARQUET_CANDIDATES.get(filename, ()):
        candidate = root / relative
        if candidate.exists():
            return str(candidate)

    # Last resort: scan data categories for the filename.
    try:
        data = Path(data_root())
        if data.exists():
            for path in data.rglob(filename):
                if path.is_file() and ".tmp" not in path.name:
                    return str(path)
    except Exception:
        pass

    return primary
