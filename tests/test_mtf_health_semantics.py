"""MTF/runtime cognition health semantics for sparse event outputs."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.mtf_observability import (  # noqa: E402
    MTF_HEALTH_INPUT_STALE,
    MTF_HEALTH_OUTPUT_NOT_REFRESHING,
    MTF_HEALTH_PRODUCER_FAILED,
    MTF_HEALTH_PRODUCER_STALE,
    MTF_HEALTH_SPARSE_OK,
    classify_mtf_health,
)

NOW = pd.Timestamp("2026-07-23T13:00:00Z").timestamp()


def _classify(**overrides):
    payload = {
        "latest_event_timestamp": "2026-07-23T08:00:00Z",
        "latest_input_candle_timestamp": "2026-07-23T12:45:00Z",
        "producer_heartbeat_timestamp": "2026-07-23T12:59:00Z",
        "producer_last_status": "SUCCESS",
        "output_mtime": "2026-07-23T12:59:30Z",
        "source_reference_timestamp": "2026-07-23T12:45:00Z",
        "lineage_propagation_timestamp": "2026-07-23T12:59:20Z",
        "now": NOW,
        "stale_after_seconds": 30 * 60,
    }
    payload.update(overrides)
    return classify_mtf_health(**payload)


def test_sparse_mtf_event_with_fresh_heartbeat_is_sparse_ok() -> None:
    health = _classify()

    assert health["health_classification"] == MTF_HEALTH_SPARSE_OK
    assert health["event_lag_seconds"] == 17_100.0
    assert health["heartbeat_lag_seconds"] == 60.0
    assert health["input_lag_seconds"] == 0.0
    assert "NO_NEW_MTF_EVENT" in health["freshness_warning"]


def test_stale_heartbeat_is_producer_stale() -> None:
    health = _classify(producer_heartbeat_timestamp="2026-07-23T10:00:00Z")

    assert health["health_classification"] == MTF_HEALTH_PRODUCER_STALE
    assert "heartbeat" in health["freshness_warning"].lower()


def test_failed_heartbeat_is_producer_failed() -> None:
    health = _classify(producer_last_status="FAILED")

    assert health["health_classification"] == MTF_HEALTH_PRODUCER_FAILED
    assert health["producer_last_status"] == "FAILED"


def test_stale_input_candle_is_input_stale() -> None:
    health = _classify(latest_input_candle_timestamp="2026-07-23T10:00:00Z")

    assert health["health_classification"] == MTF_HEALTH_INPUT_STALE
    assert health["input_lag_seconds"] == 9_900.0


def test_stale_output_mtime_with_fresh_input_and_heartbeat_is_output_not_refreshing() -> None:
    health = _classify(
        latest_event_timestamp="2026-07-23T12:45:00Z",
        output_mtime="2026-07-23T10:00:00Z",
    )

    assert health["health_classification"] == MTF_HEALTH_OUTPUT_NOT_REFRESHING
    assert "mtime" in health["freshness_warning"]
