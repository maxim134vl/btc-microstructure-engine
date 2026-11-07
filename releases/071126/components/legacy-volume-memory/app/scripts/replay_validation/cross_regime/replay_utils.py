"""Shared helpers for cross-regime replay validation."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from scripts.replay_validation.replay_utils import (  # noqa: E402
    load_probabilistic,
    load_reinforcement,
    rows_with_decomposition,
)

__all__ = [
    "ROOT",
    "load_probabilistic",
    "load_reinforcement",
    "rows_with_decomposition",
]
