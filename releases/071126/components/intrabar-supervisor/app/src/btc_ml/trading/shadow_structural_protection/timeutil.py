"""Timestamp helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def iso(dt: datetime | pd.Timestamp | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, pd.Timestamp):
        if pd.isna(dt):
            return None
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat().replace("+00:00", "Z")


def candle_open(ts: datetime, tf_seconds: int) -> datetime:
    epoch = int(ts.timestamp())
    open_epoch = epoch - (epoch % tf_seconds)
    return datetime.fromtimestamp(open_epoch, tz=timezone.utc)
