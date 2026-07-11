"""Dashboard service configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = BACKEND_ROOT.parent
REPO_ROOT = DASHBOARD_ROOT.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.pipeline_metadata import (  # noqa: E402
    CANONICAL_PIPELINE as _CANONICAL_PIPELINE,
    EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
)

POLL_INTERVAL_S = float(os.environ.get("DASHBOARD_POLL_INTERVAL", "2.0"))
API_PREFIX = "/api/v1"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DASHBOARD_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))

TIMEFRAMES = ("M15", "M30", "H1", "H4", "D1")

REGIME_LABELS = (
    "TREND_EXPANSION",
    "TREND_EXHAUSTION",
    "COMPRESSION",
    "VOLATILITY_EXPANSION",
    "VOLATILITY_COLLAPSE",
    "LIQUIDATION_EVENT",
    "ABSORPTION_RECOVERY",
    "BALANCED_AUCTION",
)

ONTOLOGY_EVENT_TYPES = (
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
    "HIGH_AVERAGE_VOLUME",
)

# Synced with app.pipeline_metadata (dashboard-local mirror of runtime pipeline)
CANONICAL_PIPELINE = list(_CANONICAL_PIPELINE)
