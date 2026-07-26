"""Single source of parquet truth — canonical data/ layout with legacy shims (Phase 4B)."""

from __future__ import annotations

import os
import shutil
import warnings
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

DATA_CATEGORIES = (
    "live",
    "cognition",
    "reinforcement",
    "probabilistic",
    "diagnostics",
    "replay",
    "artifacts",
)

_REPO_ROOT: Path | None = None


def repo_root() -> Path:
    global _REPO_ROOT
    if _REPO_ROOT is None:
        _REPO_ROOT = Path(__file__).resolve().parents[1]
    return _REPO_ROOT


def data_root() -> Path:
    raw = os.environ.get("BTC_ML_DATA_ROOT") or os.environ.get("DATA_ROOT") or "data"
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root() / path
    return path


# filename -> category (canonical subdirectory under data/)
PARQUET_REGISTRY: dict[str, str] = {
    # live
    "live_market_feed.parquet": "live",
    "multi_exchange_flow.parquet": "live",
    # cognition
    "candle_structure_memory.parquet": "cognition",
    "volume_classification_memory.parquet": "cognition",
    "behavioral_sequence_memory.parquet": "cognition",
    "microstructure_candle_memory.parquet": "cognition",
    "volume_response_state.parquet": "cognition",
    "climactic_behavior_memory.parquet": "cognition",
    "runtime_cognition_memory.parquet": "cognition",
    "intermediate_cognition_memory.parquet": "cognition",
    "multi_timeframe_synthesis.parquet": "cognition",
    "multi_timeframe_availability_memory.parquet": "cognition",
    "runtime_cognition_alignment_audit.parquet": "cognition",
    "adaptive_meta_cognition_state.parquet": "cognition",
    "volume_reactions.parquet": "cognition",
    "candle_geometry_v2_memory.parquet": "cognition",
    # Canonical v1 localization memory (Stage 1A candidate; required for safe_read under cognition/)
    "volume_localization_memory.parquet": "cognition",
    "volume_localization_v2_memory.parquet": "cognition",
    "behavioral_scoring_memory.parquet": "cognition",
    "live_volume_flow_memory.parquet": "cognition",
    "flow_liquidity_interaction_memory.parquet": "cognition",
    "auction_context_arbitration_memory.parquet": "cognition",
    # reinforcement
    "auction_reinforcement_memory.parquet": "reinforcement",
    "auction_synthesis_memory.parquet": "reinforcement",
    "auction_convergence_memory.parquet": "reinforcement",
    "auction_decay_memory.parquet": "reinforcement",
    # probabilistic
    "probabilistic_auction_memory.parquet": "probabilistic",
    "state_transition_memory.parquet": "probabilistic",
    "state_transition_engine_state.parquet": "probabilistic",
    # diagnostics
    "htf_structure_memory.parquet": "diagnostics",
    "htf_ltf_context_memory.parquet": "diagnostics",
    "runtime_dependency_state.parquet": "diagnostics",
    # replay / artifacts (non-runtime research outputs)
    "research_master_dataset.parquet": "artifacts",
    "btc_15m.parquet": "artifacts",
}

# Additional legacy read locations (never written by canonical writers).
EXTRA_LEGACY_READ_PATHS: dict[str, tuple[str, ...]] = {
    "live_market_feed.parquet": ("datasets/live/latest.parquet",),
}

# Backward-compatible string constants (resolve at read/write time via helpers).
CANONICAL_LIVE_FEED_PATH = "live_market_feed.parquet"
LEGACY_LIVE_FEED_PATH = "datasets/live/latest.parquet"


def normalize_filename(name: str) -> str:
    base = os.path.basename(name.strip())
    if not base.endswith(".parquet"):
        base = f"{base}.parquet"
    return base


def is_registered(name: str) -> bool:
    return normalize_filename(name) in PARQUET_REGISTRY


def resolve_canonical(name: str) -> str:
    """Return canonical data/<category>/<file> path (may not exist yet)."""
    filename = normalize_filename(name)
    if filename not in PARQUET_REGISTRY:
        return str(repo_root() / filename)
    category = PARQUET_REGISTRY[filename]
    return str(data_root() / category / filename)


def _legacy_candidates(name: str) -> Iterable[str]:
    filename = normalize_filename(name)
    root = repo_root()
    yield str(root / filename)
    for extra in EXTRA_LEGACY_READ_PATHS.get(filename, ()):
        yield str(root / extra)


def resolve_read(name: str, *, migrate: bool = True) -> str:
    """Return best existing path: canonical, then legacy root/mirror."""
    filename = normalize_filename(name)
    if filename not in PARQUET_REGISTRY:
        return str(repo_root() / filename)

    canonical = resolve_canonical(filename)
    if os.path.exists(canonical):
        return canonical

    for legacy in _legacy_candidates(filename):
        if os.path.exists(legacy):
            if migrate:
                migrate_legacy(filename, source=legacy)
                if os.path.exists(canonical):
                    return canonical
            return legacy

    return canonical


def resolve_write(name: str) -> str:
    """Return canonical write path; ensure parent directory exists."""
    filename = normalize_filename(name)
    target = resolve_canonical(filename) if filename in PARQUET_REGISTRY else str(repo_root() / filename)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    return target


def migrate_legacy(name: str, *, source: str | None = None) -> bool:
    """Copy legacy parquet to canonical location if canonical is absent."""
    filename = normalize_filename(name)
    if filename not in PARQUET_REGISTRY:
        return False

    canonical = resolve_canonical(filename)
    if os.path.exists(canonical):
        return False

    if source is None:
        for candidate in _legacy_candidates(filename):
            if os.path.exists(candidate):
                source = candidate
                break

    if source is None or not os.path.exists(source):
        return False

    Path(canonical).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, canonical)
    warnings.warn(
        f"Migrated legacy parquet {source} -> {canonical}",
        RuntimeWarning,
        stacklevel=2,
    )
    return True


def migrate_all_legacy() -> list[str]:
    """Migrate all registered legacy root parquets into data/."""
    migrated: list[str] = []
    for filename in PARQUET_REGISTRY:
        if migrate_legacy(filename):
            migrated.append(filename)
    return migrated


def ensure_data_layout() -> None:
    """Create data/ category directories."""
    root = data_root()
    for category in DATA_CATEGORIES:
        (root / category).mkdir(parents=True, exist_ok=True)


def all_registered_filenames() -> list[str]:
    return sorted(PARQUET_REGISTRY.keys())


def registry_summary() -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {cat: [] for cat in DATA_CATEGORIES}
    for filename, category in PARQUET_REGISTRY.items():
        summary[category].append(filename)
    return summary
