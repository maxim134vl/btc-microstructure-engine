"""Shared helpers for Phase 4A final validation replay."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from ontology_topology_audit import build_ontology_topology_audit  # noqa: E402
from stabilization_data_utils import (  # noqa: E402
    load_climax_events,
    load_cognition,
    load_probabilistic,
    load_reinforcement,
)

__all__ = [
    "ROOT",
    "build_ontology_topology_audit",
    "load_climax_events",
    "load_cognition",
    "load_probabilistic",
    "load_reinforcement",
]
