"""
Centralized configuration. All knobs come from env vars with explicit
defaults — no implicit settings sources, no hidden state.

The schema/feature allowlists are domain knowledge: which parquet files
the runtime is expected to produce, what columns they must contain, and
which feature columns we are willing to compute health for. Keeping them
in source (rather than env) makes them code-reviewable and version-able.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"env var {name} must be int, got {raw!r}") from e


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default)


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name) or default


# -----------------------------------------------------------------------------
# Schema allowlist — parquet files we know about and their required columns.
# Files not listed here are still tracked for freshness/size, but their
# `btc_parquet_schema_valid` defaults to 1 (no opinion).
# -----------------------------------------------------------------------------
EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "intraday_flow.parquet": frozenset({"timestamp", "avg_price", "delta"}),
    "oi_history.parquet":    frozenset({"timestamp", "open_interest"}),
    "orderbook.parquet":     frozenset({"timestamp", "imbalance"}),
    "live_market_feed.parquet": frozenset({"timestamp"}),
}

# -----------------------------------------------------------------------------
# Feature allowlist — columns we're willing to compute health for. Keeps the
# cardinality of {feature=…} labels bounded.
# Format: { parquet_basename: [column_name, ...] }
# -----------------------------------------------------------------------------
FEATURE_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "intraday_flow.parquet": ("avg_price", "delta", "volume"),
    "oi_history.parquet":    ("open_interest",),
    "orderbook.parquet":     ("imbalance", "spread"),
}

# -----------------------------------------------------------------------------
# Producer + kind map. Identifies which container is responsible for a given
# parquet, and how strictly we judge its freshness:
#
#   kind = "live"    — must be written every few seconds; freshness alerts ON
#          "rest"    — REST-collector cadence (~30-60s tolerable)
#          "memory"  — pipeline-engine memory/cache; sparse writes OK
#          "unknown" — anything not in this map (default; alerts OFF)
# -----------------------------------------------------------------------------
PARQUET_PRODUCERS: dict[str, dict[str, str]] = {
    "live_market_feed.parquet":     {"producer": "binance-feed",   "kind": "live"},
    "intraday_flow.parquet":        {"producer": "intraday-flow",  "kind": "rest"},
    "multi_exchange_flow.parquet":  {"producer": "multi-exchange", "kind": "live"},
    "orderbook.parquet":            {"producer": "orderbook",      "kind": "live"},
    "oi_history.parquet":           {"producer": "oi",             "kind": "rest"},
    "liquidations.parquet":         {"producer": "liquidations",   "kind": "live"},
}

# Anything matching this suffix is classified as a pipeline memory file by
# default (no live-freshness expectation).
PIPELINE_MEMORY_SUFFIX = "_memory.parquet"


def classify_parquet(basename: str) -> tuple[str, str]:
    """Returns (producer, kind) for a given parquet basename."""
    if basename in PARQUET_PRODUCERS:
        info = PARQUET_PRODUCERS[basename]
        return info["producer"], info["kind"]
    if basename.endswith(PIPELINE_MEMORY_SUFFIX):
        return "pipeline", "memory"
    return "unknown", "unknown"


# -----------------------------------------------------------------------------
# Regime source — which parquet+column holds categorical regime values.
# If the column doesn't exist at runtime, the regime collector emits nothing.
# -----------------------------------------------------------------------------
REGIME_SOURCE_FILE = "intraday_flow.parquet"
REGIME_SOURCE_COLUMN = "regime"


@dataclass(frozen=True)
class Config:
    # ---- server ----
    listen_host: str = field(default_factory=lambda: _env_str("LISTEN_HOST", "0.0.0.0"))
    listen_port: int = field(default_factory=lambda: _env_int("METRICS_EXPORTER_PORT", 9101))

    # ---- data plane ----
    data_dir: Path = field(default_factory=lambda: _env_path("DATA_DIR", "/data"))

    # ---- scan loop ----
    scan_interval_seconds: int = field(
        default_factory=lambda: _env_int("METRICS_EXPORTER_SCAN_INTERVAL_SECONDS", 10)
    )
    feature_sample_rows: int = field(
        default_factory=lambda: _env_int("METRICS_EXPORTER_FEATURE_SAMPLE_ROWS", 2000)
    )
    regime_sample_rows: int = field(
        default_factory=lambda: _env_int("METRICS_EXPORTER_REGIME_SAMPLE_ROWS", 5000)
    )

    # ---- logging ----
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())

    # ---- service identity (for structured logs) ----
    service_name: str = "metrics-exporter"
    service_version: str = "0.1.0"

    def validate(self) -> None:
        if self.scan_interval_seconds < 1:
            raise ValueError("METRICS_EXPORTER_SCAN_INTERVAL_SECONDS must be >= 1")
        if self.feature_sample_rows < 100:
            raise ValueError("METRICS_EXPORTER_FEATURE_SAMPLE_ROWS must be >= 100")
        if not (0 < self.listen_port < 65536):
            raise ValueError("METRICS_EXPORTER_PORT out of range")
