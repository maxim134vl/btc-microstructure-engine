"""Atomic JSON writers for LIVE1A runtime health files."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    indent: int = 2,
) -> None:
    """Write JSON atomically via a unique same-directory temp file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=indent, default=str) + "\n"
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
