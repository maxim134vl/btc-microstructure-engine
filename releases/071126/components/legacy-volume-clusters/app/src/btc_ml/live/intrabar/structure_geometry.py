"""OHLC structure/geometry helpers (canonical formulas only)."""

from __future__ import annotations

from typing import Any


def compute_structure_fields(
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, Any]:
    """Copy of candle_structure_engine_v1 formulas."""
    spread = float(high) - float(low)
    body = abs(float(close) - float(open_))
    upper_wick = float(high) - max(float(open_), float(close))
    lower_wick = min(float(open_), float(close)) - float(low)
    close_position = (float(close) - float(low)) / (spread + 0.000001)
    return {
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "spread": spread,
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "close_position": close_position,
    }


def compute_geometry_fields(
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    recent_spreads: list[float] | None = None,
) -> dict[str, Any]:
    """Structure + rejection flags from candle_geometry_engine_v2 rules."""
    base = compute_structure_fields(open_, high, low, close)
    spread = base["spread"]
    upper_wick_ratio = base["upper_wick"] / (spread + 0.000001)
    lower_wick_ratio = base["lower_wick"] / (spread + 0.000001)
    close_position = base["close_position"]
    upper_rejection = bool(upper_wick_ratio > 0.4 and close_position < 0.6)
    lower_rejection = bool(lower_wick_ratio > 0.4 and close_position > 0.4)
    spreads = list(recent_spreads or []) + [spread]
    if len(spreads) >= 2:
        # Match rolling(20) spirit with available causal history.
        window = spreads[-20:]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / max(len(window) - 1, 1)
        std = var**0.5
        spread_zscore = (spread - mean) / (std + 0.000001)
    else:
        spread_zscore = 0.0
    base.update(
        {
            "upper_wick_ratio": upper_wick_ratio,
            "lower_wick_ratio": lower_wick_ratio,
            "upper_rejection": upper_rejection,
            "lower_rejection": lower_rejection,
            "spread_zscore": float(spread_zscore),
        }
    )
    return base
