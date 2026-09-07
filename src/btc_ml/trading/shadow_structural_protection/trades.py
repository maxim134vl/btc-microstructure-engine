"""Read-only exact aggTrade / bookTicker loaders for causal candle profiles."""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .timeutil import iso, parse_ts


def _hour_dirs(root: Path, start: datetime, end: datetime) -> list[Path]:
    out: list[Path] = []
    cur = start.replace(minute=0, second=0, microsecond=0)
    end_h = end.replace(minute=0, second=0, microsecond=0)
    while cur <= end_h:
        p = root / f"date={cur.strftime('%Y-%m-%d')}" / f"hour={cur.strftime('%H')}"
        if p.exists():
            out.append(p)
        cur += timedelta(hours=1)
    return out


_HOUR_CACHE: "OrderedDict[tuple[str, str], pd.DataFrame]" = OrderedDict()
_HOUR_CACHE_MAX = int(os.environ.get("STP_AGG_HOUR_CACHE", "192"))

# The aggTrade partitions carry 21 columns, most of them strings (payload hashes,
# session ids, timestamps as text) that nothing here reads: ~7.6 MB per hour file
# against ~1 MB for the six columns actually used. Reading only these turns the
# per-hour cost from parse-heavy into near-free.
_READ_COLUMNS = (
    "exchange_trade_timestamp",
    "exchange_event_timestamp",
    "symbol",
    "aggregate_trade_id",
    "price",
    "quantity",
    "quote_quantity",
    "buyer_is_market_maker",
)


def clear_agg_trade_cache() -> None:
    _HOUR_CACHE.clear()


def agg_trade_cache_stats() -> dict[str, int]:
    return {
        "hours_resident": len(_HOUR_CACHE),
        "hour_loads": _CACHE_STATS["loads"],
        "hour_hits": _CACHE_STATS["hits"],
    }


_CACHE_STATS = {"loads": 0, "hits": 0}


def _read_hour(hour_dir: Path, symbol: str) -> pd.DataFrame:
    """Parse one hour partition into the canonical cleaned frame.

    Kept identical in semantics to the previous whole-window implementation:
    symbol filter, timestamp parse, dedup on aggregate_trade_id, float casts,
    chronological sort. Doing it per hour is what makes it cacheable, since a
    trade's causal lookback overlaps the previous trade's by all but an hour.
    """
    frames: list[pd.DataFrame] = []
    for path in sorted(hour_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(path, columns=list(_READ_COLUMNS))
        except (ValueError, KeyError):
            # Older partitions may not carry every column; fall back to a full read.
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
        except Exception:
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    if "symbol" in df.columns:
        df = df.loc[df["symbol"].astype(str).str.upper() == symbol.upper()]
    ts_col = (
        "exchange_trade_timestamp"
        if "exchange_trade_timestamp" in df.columns
        else "exchange_event_timestamp"
    )
    df = df.copy()
    df["_ts"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce", format="ISO8601")
    df = df.loc[df["_ts"].notna()]
    if "aggregate_trade_id" in df.columns:
        df = df.drop_duplicates(subset=["aggregate_trade_id"], keep="first")
    df["price"] = df["price"].astype(float)
    df["quantity"] = df["quantity"].astype(float)
    if "quote_quantity" in df.columns:
        df["quote_quantity"] = df["quote_quantity"].astype(float)
    else:
        df["quote_quantity"] = df["price"] * df["quantity"]
    df = df.drop(columns=[c for c in ("symbol",) if c in df.columns])
    return df.sort_values(["_ts", "aggregate_trade_id"]).reset_index(drop=True)


def _hour_frame(hour_dir: Path, symbol: str) -> pd.DataFrame:
    key = (str(hour_dir), symbol.upper())
    cached = _HOUR_CACHE.get(key)
    if cached is not None:
        _HOUR_CACHE.move_to_end(key)
        _CACHE_STATS["hits"] += 1
        return cached
    frame = _read_hour(hour_dir, symbol)
    _HOUR_CACHE[key] = frame
    _CACHE_STATS["loads"] += 1
    while len(_HOUR_CACHE) > _HOUR_CACHE_MAX:
        _HOUR_CACHE.popitem(last=False)
    return frame


def load_agg_trades(
    *,
    repo: Path,
    start: datetime,
    end: datetime,
    symbol: str = "BTCUSDT",
) -> pd.DataFrame:
    """Load exact aggTrade events with exchange timestamps in [start, end]."""
    root = repo / "data" / "raw_market_events_v2" / "agg_trade"
    frames = [
        frame
        for hour_dir in _hour_dirs(root, start, end)
        if not (frame := _hour_frame(hour_dir, symbol)).empty
    ]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    df = df.loc[(df["_ts"] >= lo) & (df["_ts"] <= hi)]
    # Hours are read in chronological order and each is internally sorted, so the
    # concatenation is already ordered; re-sort only if a partition bled across
    # its hour boundary.
    if not df["_ts"].is_monotonic_increasing:
        df = df.sort_values(["_ts", "aggregate_trade_id"])
    return df.reset_index(drop=True)


def load_book_ticker(
    *,
    repo: Path,
    start: datetime,
    end: datetime,
    symbol: str = "BTCUSDT",
) -> pd.DataFrame:
    root = repo / "data" / "raw_market_events_v2" / "book_ticker"
    frames: list[pd.DataFrame] = []
    for hour_dir in _hour_dirs(root, start, end):
        for path in sorted(hour_dir.glob("*.parquet")):
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            if not df.empty:
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "symbol" in df.columns:
        df = df[df["symbol"].astype(str).str.upper() == symbol.upper()]
    # Prefer exchange ts; fall back to local receive (documented in audit).
    # Normalize to a single datetime64[ns, UTC] series to avoid unit upcast errors
    # when mixing exchange (s) and local receive (us) columns.
    exch = (
        pd.to_datetime(df["exchange_event_timestamp"], utc=True, errors="coerce")
        if "exchange_event_timestamp" in df.columns
        else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    )
    local = (
        pd.to_datetime(df["local_receive_timestamp"], utc=True, errors="coerce")
        if "local_receive_timestamp" in df.columns
        else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    )
    df["_ts"] = exch.fillna(local)
    df = df[df["_ts"].notna()]
    df = df[(df["_ts"] >= pd.Timestamp(start)) & (df["_ts"] <= pd.Timestamp(end))]
    if "update_id" in df.columns:
        df = df.drop_duplicates(subset=["update_id"], keep="first")
    for c in ("best_bid_price", "best_ask_price", "spread"):
        if c in df.columns:
            df[c] = df[c].astype(float)
    return df.sort_values(["_ts", "update_id"] if "update_id" in df.columns else ["_ts"]).reset_index(drop=True)


def exact_trade_source_available(repo: Path) -> dict[str, Any]:
    root = repo / "data" / "raw_market_events_v2" / "agg_trade"
    files = list(root.rglob("*.parquet"))
    if not files:
        return {"available": False, "path": str(root), "file_count": 0}
    # Sample earliest/latest from partition names + one file
    dates = sorted({p.parts[-3] for p in files if "date=" in p.parts[-3]})
    sample = pd.read_parquet(files[0])
    return {
        "available": True,
        "path": "data/raw_market_events_v2/agg_trade",
        "file_count": len(files),
        "date_partitions": dates,
        "columns": list(sample.columns),
        "dedup_key": "aggregate_trade_id",
        "timestamp_field": "exchange_trade_timestamp",
        "producer": "scripts/live/run_intrabar_cognition_service.py → raw_event_journal archival_writer",
        "write_mode": "append parquet batches",
        "causal_historical_replay_possible": True,
    }
