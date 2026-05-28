"""Build synchronized MTF auction map data (M15 → D1)."""

from __future__ import annotations

from typing import Any

import pandas as pd

TIMEFRAMES = ("D1", "H4", "H1", "M15")

TIMEFRAME_RESAMPLE = {
    "M15": None,
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}


def _aggregate_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp")
    aggregated = indexed.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "delta": "sum",
        }
    )
    return aggregated.dropna(subset=["open"]).reset_index()


def build_mtf_frames(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return OHLC frames for each supported timeframe."""

    base = base.sort_values("timestamp").dropna(subset=["timestamp"]).copy()
    frames: dict[str, pd.DataFrame] = {"M15": base}
    for tf, rule in TIMEFRAME_RESAMPLE.items():
        if rule:
            frames[tf] = _aggregate_ohlc(base, rule)
    return frames


def attach_cognition_to_bars(bars: pd.DataFrame, cognition: pd.DataFrame) -> pd.DataFrame:
    """Merge cognition memory onto bar timestamps (backward asof)."""

    if len(bars) == 0:
        return bars
    left = bars.sort_values("timestamp").dropna(subset=["timestamp"])
    if len(cognition) == 0 or "timestamp" not in cognition.columns:
        return left
    right = cognition.sort_values("timestamp").dropna(subset=["timestamp"])
    overlap = set(left.columns) & set(right.columns) - {"timestamp"}
    if overlap:
        right = right.rename(columns={column: f"{column}_cog" for column in overlap})
    return pd.merge_asof(left, right, on="timestamp", direction="backward")


def bars_to_chart_payload(frame: pd.DataFrame, *, max_bars: int = 80) -> list[dict[str, Any]]:
    """Serialize bar rows for frontend chart rendering."""

    if len(frame) == 0:
        return []
    tail = frame.tail(max_bars).copy()
    rows: list[dict[str, Any]] = []
    for _, row in tail.iterrows():
        rows.append(
            {
                "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
                "delta": float(row["delta"]) if pd.notna(row.get("delta")) else None,
            }
        )
    return rows


def build_mtf_auction_map(
    base_candles: pd.DataFrame,
    cognition_enriched: pd.DataFrame,
    *,
    max_bars: int = 80,
) -> dict[str, Any]:
    """Build synchronized MTF chart payloads with cognition attached."""

    mtf_frames = build_mtf_frames(base_candles)
    payload: dict[str, Any] = {}

    for tf in TIMEFRAMES:
        bars = mtf_frames.get(tf, pd.DataFrame())
        if len(bars) == 0:
            payload[tf] = {"bars": [], "bar_count": 0}
            continue
        merged = attach_cognition_to_bars(bars, cognition_enriched)
        payload[tf] = {
            "timeframe": tf,
            "bars": bars_to_chart_payload(merged, max_bars=max_bars),
            "bar_count": len(merged),
            "start": merged["timestamp"].iloc[max(0, len(merged) - max_bars)].isoformat(),
            "end": merged["timestamp"].iloc[-1].isoformat(),
        }
    return payload
