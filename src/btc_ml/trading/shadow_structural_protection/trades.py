"""Read-only exact aggTrade / bookTicker loaders for causal candle profiles."""

from __future__ import annotations

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


def load_agg_trades(
    *,
    repo: Path,
    start: datetime,
    end: datetime,
    symbol: str = "BTCUSDT",
) -> pd.DataFrame:
    """Load exact aggTrade events with exchange timestamps in [start, end]."""
    root = repo / "data" / "raw_market_events_v2" / "agg_trade"
    frames: list[pd.DataFrame] = []
    for hour_dir in _hour_dirs(root, start, end):
        for path in sorted(hour_dir.glob("*.parquet")):
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            if df.empty:
                continue
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "symbol" in df.columns:
        df = df[df["symbol"].astype(str).str.upper() == symbol.upper()]
    ts_col = "exchange_trade_timestamp" if "exchange_trade_timestamp" in df.columns else "exchange_event_timestamp"
    df["_ts"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df[df["_ts"].notna()]
    df = df[(df["_ts"] >= pd.Timestamp(start)) & (df["_ts"] <= pd.Timestamp(end))]
    if "aggregate_trade_id" in df.columns:
        df = df.drop_duplicates(subset=["aggregate_trade_id"], keep="first")
    df["price"] = df["price"].astype(float)
    df["quantity"] = df["quantity"].astype(float)
    if "quote_quantity" in df.columns:
        df["quote_quantity"] = df["quote_quantity"].astype(float)
    else:
        df["quote_quantity"] = df["price"] * df["quantity"]
    return df.sort_values(["_ts", "aggregate_trade_id"]).reset_index(drop=True)


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
    if "exchange_event_timestamp" in df.columns:
        df["_ts"] = pd.to_datetime(df["exchange_event_timestamp"], utc=True, errors="coerce")
    else:
        df["_ts"] = pd.NaT
    missing = df["_ts"].isna()
    if missing.any() and "local_receive_timestamp" in df.columns:
        df.loc[missing, "_ts"] = pd.to_datetime(df.loc[missing, "local_receive_timestamp"], utc=True, errors="coerce")
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
