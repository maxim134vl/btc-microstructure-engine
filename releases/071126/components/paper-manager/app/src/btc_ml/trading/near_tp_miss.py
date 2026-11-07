"""NEAR_TP_MISS: close on this TF's closed bar if it approached TP and did not fill.

Per-timeframe. Long and short. Does not wait for the next bar.
Saw and strength do not gate this CLOSE. Not a TP fill. Not ATOMIC_FLIP.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
_S41_CONTRACT_PATH = ROOT / "config" / "trading" / "s41_live1b_chain_contract.json"

NEAR_TP_MISS = "NEAR_TP_MISS"
DEFAULT_MISS_BPS = 10.0
TIMEFRAMES = ("M15", "M30", "H1", "H4")


def _contract_payload(payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    if payload is not None:
        return payload
    try:
        return json.loads(_S41_CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def near_tp_miss_settings(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    block = _contract_payload(payload).get("near_tp_miss") or {}
    applies = tuple(
        str(tf).upper()
        for tf in (block.get("applies_to") or TIMEFRAMES)
        if str(tf).strip()
    )
    try:
        bps = float(block.get("miss_bps", DEFAULT_MISS_BPS))
    except (TypeError, ValueError):
        bps = DEFAULT_MISS_BPS
    return {
        "enabled": bool(block.get("enabled", True)),
        "miss_bps": bps if bps > 0 else DEFAULT_MISS_BPS,
        "applies_to": applies or TIMEFRAMES,
    }


def miss_bps_from_contract(payload: Mapping[str, Any] | None = None) -> float:
    return float(near_tp_miss_settings(payload)["miss_bps"])


def near_tp_misses(
    *,
    side: str,
    take_profit_price: float,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    miss_bps: float = DEFAULT_MISS_BPS,
) -> bool:
    """True when this closed bar was next to TP and closed without paying it."""
    side_u = str(side or "").upper()
    tp = float(take_profit_price)
    high = float(bar_high)
    low = float(bar_low)
    close = float(bar_close)
    if tp <= 0 or miss_bps <= 0:
        return False
    band = tp * (miss_bps / 10_000.0)
    if side_u == "LONG":
        if close >= tp or high >= tp:
            return False
        return high >= tp - band
    if side_u == "SHORT":
        if close <= tp or low <= tp:
            return False
        return low <= tp + band
    return False


def closed_bar_ohlc(
    feed: pd.DataFrame | None,
    *,
    bar_open: Any,
    bar_close: Any,
) -> dict[str, float] | None:
    """OHLC of one closed bar window. Feed rows are typically 15m.

    Includes rows whose close stamp is in (bar_open, bar_close].
    M15 → one row. H4 → the 15m prints inside that H4.
    """
    if feed is None or not len(feed) or bar_open is None or bar_close is None:
        return None
    start = pd.to_datetime(bar_open, utc=True, errors="coerce")
    end = pd.to_datetime(bar_close, utc=True, errors="coerce")
    if pd.isna(start) or pd.isna(end) or end <= start:
        return None
    column = "bar_close_timestamp" if "bar_close_timestamp" in feed.columns else "timestamp"
    stamps = pd.to_datetime(feed[column], utc=True, errors="coerce")
    window = feed.loc[(stamps > start) & (stamps <= end)].copy()
    if not len(window):
        return None
    window["_stamp"] = stamps.loc[window.index]
    window = window.sort_values("_stamp")
    high = pd.to_numeric(window["high"], errors="coerce").max() if "high" in window.columns else None
    low = pd.to_numeric(window["low"], errors="coerce").min() if "low" in window.columns else None
    close = pd.to_numeric(window["close"], errors="coerce").iloc[-1] if "close" in window.columns else None
    if high is None or low is None or close is None:
        return None
    if pd.isna(high) or pd.isna(low) or pd.isna(close):
        return None
    return {"high": float(high), "low": float(low), "close": float(close)}
