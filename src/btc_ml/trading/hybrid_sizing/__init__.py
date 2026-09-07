"""Live CatBoost risk multiplier for canonical LIVE1B paper entries.

Fail-open: any missing artifact, feature, or prediction returns multiplier 1.0
so the trade sizes exactly as the canonical book would have.
"""

from .serve import (
    HybridSizer,
    SizingDecision,
    lifecycle_parquet_xtf_status,
    load_sizer,
    xtf_lifecycle_coverage,
)

__all__ = [
    "HybridSizer",
    "SizingDecision",
    "lifecycle_parquet_xtf_status",
    "load_sizer",
    "xtf_lifecycle_coverage",
]
