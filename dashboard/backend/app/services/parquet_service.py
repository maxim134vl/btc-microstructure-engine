"""Async-safe parquet readers with TTL cache for dashboard observability."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd

from storage.path_registry import PARQUET_REGISTRY, resolve_read

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_TTL_S = 1.5
_LOCK = asyncio.Lock()


def _serialize(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if pd.isna(value):
        return None
    if isinstance(value, (float, int, str, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    text = str(value)
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def _read_parquet_sync(name: str, tail: int | None = None) -> pd.DataFrame:
    path = resolve_read(name)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if tail is not None and len(df) > tail:
        df = df.tail(tail)
    return df


async def read_parquet(name: str, tail: int | None = None) -> pd.DataFrame:
    cache_key = f"{name}:{tail}"
    now = time.time()
    async with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now - cached["ts"] < _CACHE_TTL_S:
            return cached["df"].copy()

    df = await asyncio.to_thread(_read_parquet_sync, name, tail)
    async with _LOCK:
        _CACHE[cache_key] = {"ts": now, "df": df.copy()}
    return df


def df_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or len(df) == 0:
        return []
    frame = df.tail(limit) if limit else df
    records = frame.to_dict(orient="records")
    return [{k: _serialize(v) for k, v in row.items()} for row in records]


def latest_row(df: pd.DataFrame) -> dict[str, Any] | None:
    records = df_records(df, limit=1)
    return records[-1] if records else None


def file_snapshot(name: str) -> dict[str, Any]:
    path = resolve_read(name)
    snap: dict[str, Any] = {
        "file": name,
        "path": path,
        "category": PARQUET_REGISTRY.get(name),
        "exists": os.path.exists(path),
        "mtime": None,
        "age_seconds": None,
        "row_count": 0,
        "latest_timestamp": None,
        "stale": False,
    }
    if not snap["exists"]:
        snap["stale"] = True
        return snap

    mtime = os.path.getmtime(path)
    snap["mtime"] = datetime.fromtimestamp(mtime).isoformat()
    snap["age_seconds"] = round(time.time() - mtime, 1)
    snap["stale"] = snap["age_seconds"] > 300

    try:
        df = _read_parquet_sync(name, tail=1)
        snap["row_count"] = int(len(pd.read_parquet(path)))
        if len(df) > 0 and "timestamp" in df.columns:
            snap["latest_timestamp"] = _serialize(df["timestamp"].iloc[-1])
    except Exception as error:
        snap["read_error"] = str(error)
        snap["stale"] = True

    return snap


def parse_regime_vector(raw: Any) -> dict[str, float]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    text = str(raw)
    result: dict[str, float] = {}
    for part in text.split("|"):
        if ":" not in part:
            continue
        label, value = part.split(":", 1)
        try:
            result[label.strip()] = float(value)
        except ValueError:
            continue
    return result
