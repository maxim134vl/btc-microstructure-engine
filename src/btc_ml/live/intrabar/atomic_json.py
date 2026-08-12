"""Atomic JSON writers for LIVE1A runtime health files."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


def _json_strict_safe(value: Any) -> Any:
    """Return a strict-JSON-safe object: no NaN / Infinity."""

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    # numpy scalar support without hard dependency.
    if value.__class__.__module__.startswith("numpy"):
        try:
            return _json_strict_safe(value.item())
        except Exception:
            return str(value)

    if isinstance(value, dict):
        return {str(k): _json_strict_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_strict_safe(v) for v in value]

    return value


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    indent: int = 2,
) -> None:
    """Write JSON atomically via a unique same-directory temp file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    raw = (
        json.dumps(
            _json_strict_safe(payload),
            indent=indent,
            default=str,
            allow_nan=False,
        )
        + "\n"
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.{threading.get_ident()}.tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise
