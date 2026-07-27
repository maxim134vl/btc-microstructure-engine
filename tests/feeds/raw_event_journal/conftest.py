"""Ensure src layout is importable for raw_event_journal tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SRC = _ROOT / "src"
for path in (str(_SRC), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
