"""Shared helpers for adversarial replay validation."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from scripts.replay_validation.replay_utils import load_probabilistic  # noqa: E402

__all__ = ["ROOT", "load_probabilistic"]
