"""Live CatBoost risk multiplier for canonical LIVE1B paper entries.

Fail-open: any missing artifact, feature, or prediction returns multiplier 1.0
so the trade sizes exactly as the canonical book would have.
"""

from .serve import HybridSizer, SizingDecision, load_sizer

__all__ = ["HybridSizer", "SizingDecision", "load_sizer"]
