"""Canonical storage layer — parquet path registry (Phase 4B)."""

from storage.path_registry import (
    DATA_CATEGORIES,
    PARQUET_REGISTRY,
    ensure_data_layout,
    is_registered,
    migrate_all_legacy,
    migrate_legacy,
    resolve_canonical,
    resolve_read,
    resolve_write,
)

__all__ = [
    "DATA_CATEGORIES",
    "PARQUET_REGISTRY",
    "ensure_data_layout",
    "is_registered",
    "migrate_all_legacy",
    "migrate_legacy",
    "resolve_canonical",
    "resolve_read",
    "resolve_write",
]
