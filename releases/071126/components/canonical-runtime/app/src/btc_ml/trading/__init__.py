"""S4.1 — manager + independent timeframe paper traders.

Paper-only. No exchange clients, no real execution. All execution math is
delegated to the canonical paper economics core; this package only adds
per-timeframe isolation (state, lifecycle, books, risk).
"""

from __future__ import annotations

SUPPORTED_TIMEFRAMES = ("M15", "M30", "H1", "H4")
UNSUPPORTED_TIMEFRAMES = ("D1",)

__all__ = ["SUPPORTED_TIMEFRAMES", "UNSUPPORTED_TIMEFRAMES"]
