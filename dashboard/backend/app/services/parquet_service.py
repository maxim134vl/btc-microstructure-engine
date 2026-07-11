"""Async-safe parquet readers — PyArrow metadata, tail reads, column projection."""

from __future__ import annotations

import asyncio
import json
import os
import time
import warnings
from datetime import datetime
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.services.parquet_columns import resolve_columns
from app.parquet_read_safety import is_temp_parquet_path
from app.services.dashboard_paths import resolve_dashboard_read
from storage.path_registry import PARQUET_REGISTRY

_DATA_CACHE: dict[str, dict[str, Any]] = {}
_METADATA_CACHE: dict[str, dict[str, Any]] = {}
_DATA_CACHE_TTL_S = 30.0
_METADATA_CACHE_TTL_S = 15.0
_DATA_CACHE_MAX_ROWS = 10_000
_DATA_CACHE_MAX_ENTRIES = 32
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


def _filter_columns(schema: pa.Schema, columns: list[str] | None) -> list[str] | None:
    if columns is None:
        return None
    names = set(schema.names)
    picked = [c for c in columns if c in names]
    return picked or None


def parquet_metadata(name: str) -> dict[str, Any]:
    """Row count and schema via PyArrow metadata — zero row decode."""
    path = resolve_dashboard_read(name)
    meta: dict[str, Any] = {
        "file": name,
        "path": path,
        "exists": os.path.exists(path),
        "row_count": 0,
        "num_columns": 0,
        "columns": [],
    }
    if not meta["exists"]:
        return meta
    try:
        pf = pq.ParquetFile(path)
        meta["row_count"] = int(pf.metadata.num_rows)
        meta["num_columns"] = int(pf.metadata.num_columns)
        meta["columns"] = list(pf.schema_arrow.names)
    except Exception as error:
        meta["read_error"] = str(error)
    return meta


def _read_parquet_tail_sync(
    path: str,
    *,
    tail: int | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    if is_temp_parquet_path(path):
        return pd.DataFrame()
    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        pf = pq.ParquetFile(path)
    except Exception as exc:
        # Optional dashboard read: degrade gracefully, do not crash ops snapshot.
        warnings.warn(
            f"dashboard parquet read degraded for {path}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return pd.DataFrame()
    num_rows = pf.metadata.num_rows
    if num_rows == 0:
        return pd.DataFrame()

    use_columns = _filter_columns(pf.schema_arrow, columns)
    rows_needed = num_rows if tail is None else min(max(int(tail), 0), num_rows)

    if rows_needed >= num_rows:
        table = pf.read(columns=use_columns)
    else:
        chunks: list[pa.Table] = []
        collected = 0
        for rg_idx in range(pf.num_row_groups - 1, -1, -1):
            chunks.append(pf.read_row_group(rg_idx, columns=use_columns))
            collected += pf.metadata.row_group(rg_idx).num_rows
            if collected >= rows_needed:
                break
        table = pa.concat_tables(list(reversed(chunks)))
        if table.num_rows > rows_needed:
            table = table.slice(table.num_rows - rows_needed)

    return table.to_pandas()


def _read_parquet_sync(
    name: str,
    tail: int | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    path = resolve_dashboard_read(name)
    use_columns = resolve_columns(name, columns)
    return _read_parquet_tail_sync(path, tail=tail, columns=use_columns)


async def read_parquet_metadata(name: str) -> dict[str, Any]:
    cache_key = f"meta:{name}"
    now = time.time()
    async with _LOCK:
        cached = _METADATA_CACHE.get(cache_key)
        if cached and now - cached["ts"] < _METADATA_CACHE_TTL_S:
            return dict(cached["data"])

    data = await asyncio.to_thread(parquet_metadata, name)
    async with _LOCK:
        _METADATA_CACHE[cache_key] = {"ts": now, "data": data}
    return data


async def read_parquet(
    name: str,
    tail: int | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    use_columns = resolve_columns(name, columns)
    col_key = ",".join(use_columns) if use_columns else "*"
    cache_key = f"{name}:{tail}:{col_key}"
    now = time.time()
    cacheable = tail is not None and 0 < int(tail) <= _DATA_CACHE_MAX_ROWS
    async with _LOCK:
        for key, value in list(_DATA_CACHE.items()):
            if now - value["ts"] >= _DATA_CACHE_TTL_S:
                _DATA_CACHE.pop(key, None)
        cached = _DATA_CACHE.get(cache_key)
        if cacheable and cached and now - cached["ts"] < _DATA_CACHE_TTL_S:
            return cached["df"].copy()

    df = await asyncio.to_thread(_read_parquet_sync, name, tail, use_columns)
    if not cacheable:
        return df
    async with _LOCK:
        while len(_DATA_CACHE) >= _DATA_CACHE_MAX_ENTRIES:
            oldest = min(_DATA_CACHE, key=lambda key: _DATA_CACHE[key]["ts"])
            _DATA_CACHE.pop(oldest, None)
        _DATA_CACHE[cache_key] = {"ts": now, "df": df.copy()}
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
    """Metadata-only row count; latest timestamp via 1-row projected tail read."""
    path = resolve_dashboard_read(name)
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
        meta = parquet_metadata(name)
        snap["row_count"] = int(meta.get("row_count") or 0)
        ts_col = "timestamp"
        schema_cols = meta.get("columns") or []
        if ts_col in schema_cols:
            df = _read_parquet_tail_sync(path, tail=1, columns=[ts_col])
            if len(df) > 0 and ts_col in df.columns:
                snap["latest_timestamp"] = _serialize(df[ts_col].iloc[-1])
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


def clear_parquet_caches() -> None:
    """Test helper — drop in-memory parquet caches."""
    _DATA_CACHE.clear()
    _METADATA_CACHE.clear()
