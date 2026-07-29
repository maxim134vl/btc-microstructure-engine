"""Fact-based source audit for SHADOW-STP1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import DEFAULT_TICK_SIZE
from .timeutil import iso, utc_now
from .trades import exact_trade_source_available


def run_source_audit(*, repo: Path) -> dict[str, Any]:
    trade = exact_trade_source_available(repo)
    book_root = repo / "data" / "raw_market_events_v2" / "book_ticker"
    book_files = list(book_root.rglob("*.parquet"))
    vc_path = repo / "data" / "cognition" / "volume_classification_memory.parquet"
    vr_path = repo / "data" / "cognition" / "volume_response_state.parquet"

    sources: list[dict[str, Any]] = []
    sources.append(
        {
            "path": trade.get("path"),
            "producer": trade.get("producer"),
            "write_mode": trade.get("write_mode"),
            "retention": "partitioned by date/hour; observed dates in tree",
            "timestamp_semantics": "exchange_trade_timestamp (exchange event clock)",
            "price_semantics": "last trade price Decimal→float",
            "quantity_semantics": "base asset quantity; quote_quantity present",
            "dedup_key": trade.get("dedup_key"),
            "latest_timestamp": _latest_from_partitions(repo / "data/raw_market_events_v2/agg_trade"),
            "earliest_timestamp": _earliest_from_partitions(repo / "data/raw_market_events_v2/agg_trade"),
            "causal_historical_replay_possible": trade.get("causal_historical_replay_possible"),
            "exact_volume_by_price_possible": bool(trade.get("available")),
            "file_count": trade.get("file_count"),
            "columns": trade.get("columns"),
        }
    )
    sources.append(
        {
            "path": "data/raw_market_events_v2/book_ticker",
            "producer": "scripts/live/run_intrabar_cognition_service.py → raw_event_journal archival_writer",
            "write_mode": "append parquet batches",
            "retention": "partitioned by date/hour",
            "timestamp_semantics": "exchange_event_timestamp when present else local_receive_timestamp",
            "price_semantics": "best_bid_price / best_ask_price",
            "quantity_semantics": "best bid/ask sizes",
            "dedup_key": "update_id",
            "file_count": len(book_files),
            "causal_historical_replay_possible": bool(book_files),
            "latest_timestamp": _latest_from_partitions(book_root),
            "earliest_timestamp": _earliest_from_partitions(book_root),
        }
    )
    if vc_path.exists():
        vc = pd.read_parquet(vc_path)
        sources.append(
            {
                "path": "data/cognition/volume_classification_memory.parquet",
                "producer": "volume_classification_engine_v1.py",
                "write_mode": "parquet rewrite/append via resolve_write",
                "columns": list(vc.columns),
                "volume_class_values": sorted(vc["volume_class"].dropna().astype(str).unique().tolist())
                if "volume_class" in vc.columns
                else [],
                "timeframe": "M15_ONLY_IMPLIED_900s_NO_TF_COLUMN",
                "row_timestamp_field": "timestamp",
                "causal_asof_possible": True,
                "latest_timestamp": iso(pd.to_datetime(vc["timestamp"], utc=True).max()),
                "earliest_timestamp": iso(pd.to_datetime(vc["timestamp"], utc=True).min()),
            }
        )
    if vr_path.exists():
        vr = pd.read_parquet(vr_path)
        sources.append(
            {
                "path": "data/cognition/volume_response_state.parquet",
                "producer": "volume_response_engine_v1.py",
                "reaction_fields": [
                    c
                    for c in ("effort_result_state", "localized_behavior", "volume_event", "unfinished_auction")
                    if c in vr.columns
                ],
                "timeframe_field": "source_timeframe",
                "source_candle_identity": "source_candle_timestamp",
                "classification_timestamp": "timestamp",
                "latest_timestamp": iso(pd.to_datetime(vr["timestamp"], utc=True).max())
                if "timestamp" in vr.columns
                else None,
            }
        )

    exact_ok = bool(trade.get("available"))
    return {
        "generated_at": utc_now(),
        "tick_size_source": {
            "value": DEFAULT_TICK_SIZE,
            "basis": "observed BTCUSDT aggTrade price quantum in raw journal (0.01)",
            "not_atr": True,
            "not_percent": True,
        },
        "exact_intrabar_trade_source_verified": exact_ok,
        "causal_replay_available": exact_ok and bool(book_files),
        "blocked_reason": None if exact_ok else "SHADOW_STP1_BLOCKED_NO_EXACT_INTRABAR_VOLUME",
        "sources": sources,
        "forbidden_approximations": [
            "OHLCV approximation",
            "uniform volume distribution",
            "wick/body allocation",
            "execution_distribution approximation",
        ],
    }


def _latest_from_partitions(root: Path) -> str | None:
    dates = sorted(root.glob("date=*"))
    if not dates:
        return None
    hours = sorted(dates[-1].glob("hour=*"))
    if not hours:
        return None
    files = sorted(hours[-1].glob("*.parquet"))
    if not files:
        return None
    # parse end= from filename if present
    name = files[-1].name
    if "end=" in name:
        part = name.split("end=")[1].split("__")[0]
        # 20260729T194306918039Z
        try:
            return f"{part[0:4]}-{part[4:6]}-{part[6:8]}T{part[9:11]}:{part[11:13]}:{part[13:15]}.{part[15:21]}Z"
        except Exception:
            return part
    return name


def _earliest_from_partitions(root: Path) -> str | None:
    dates = sorted(root.glob("date=*"))
    if not dates:
        return None
    hours = sorted(dates[0].glob("hour=*"))
    if not hours:
        return None
    files = sorted(hours[0].glob("*.parquet"))
    if not files:
        return None
    name = files[0].name
    if "start=" in name:
        part = name.split("start=")[1].split("__")[0]
        try:
            return f"{part[0:4]}-{part[4:6]}-{part[6:8]}T{part[9:11]}:{part[11:13]}:{part[13:15]}.{part[15:21]}Z"
        except Exception:
            return part
    return name
