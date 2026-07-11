"""JSON-safe conversion helpers for dashboard API payloads."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_json_safe(value: Any) -> Any:
    """Recursively convert pandas/numpy/scalar values into strict JSON values."""

    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass
        return value.isoformat()
    if isinstance(value, dict):
        return {str(to_json_safe(key)): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return [to_json_safe(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return to_json_safe(value.to_dict())
    if isinstance(value, np.ndarray):
        return to_json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return to_json_safe(value.item())
        except Exception:
            pass
    return value
