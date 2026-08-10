#!/usr/bin/env python3
"""Liveness only: PID 1 is alive and has not declared terminal failure."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    status = json.loads((ROOT / "run/docker_model_runtime_status.json").read_text())
    os.kill(int(status["pid"]), 0)
    alive = status.get("state") in {"STARTING", "READY"}
except (OSError, ValueError, KeyError, TypeError):
    alive = False
sys.exit(0 if alive else 1)
