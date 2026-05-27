"""Storage / parquet shims — canonical package surface (Phase 4B)."""

from parquet_utils import safe_read_parquet, append_state_row, atomic_parquet_write
from state_manager_v1 import refresh_state, STATE
from storage.path_registry import (
    PARQUET_REGISTRY,
    ensure_data_layout,
    is_registered,
    migrate_all_legacy,
    resolve_canonical,
    resolve_read,
    resolve_write,
)

__all__ = [
    "PARQUET_REGISTRY",
    "safe_read_parquet",
    "append_state_row",
    "atomic_parquet_write",
    "refresh_state",
    "STATE",
    "ensure_data_layout",
    "is_registered",
    "migrate_all_legacy",
    "resolve_canonical",
    "resolve_read",
    "resolve_write",
]
