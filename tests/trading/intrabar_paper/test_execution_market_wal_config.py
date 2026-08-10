from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.execution_market_wal_config import (
    load_execution_market_wal_config,
)


def test_segmented_storage_config_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "wal.json"
    path.write_text(json.dumps({
        "schema_version": "execution_market_wal_storage_v1",
        "mode": "segmented",
        "segment_max_bytes": 1024,
        "archive_batch_rows": 16,
        "delete_verified_plaintext": False,
        "plaintext_retention_hours": 6.0,
        "warning_size_bytes": 10240,
        "critical_size_bytes": 20480,
    }))
    cfg = load_execution_market_wal_config(path)
    assert cfg.segmented_enabled is True
    assert cfg.delete_verified_plaintext is False
    assert cfg.plaintext_retention_hours == 6.0
    assert cfg.warning_size_bytes == 10240
    assert cfg.critical_size_bytes == 20480


def test_invalid_storage_mode_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "wal.json"
    path.write_text(json.dumps({
        "schema_version": "execution_market_wal_storage_v1",
        "mode": "automatic",
        "segment_max_bytes": 1024,
        "archive_batch_rows": 16,
    }))
    with pytest.raises(ValueError, match="legacy or segmented"):
        load_execution_market_wal_config(path)


def test_unknown_config_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "wal.json"
    path.write_text(json.dumps({
        "schema_version": "future",
        "mode": "segmented",
        "segment_max_bytes": 1024,
        "archive_batch_rows": 16,
    }))
    with pytest.raises(ValueError, match="unsupported"):
        load_execution_market_wal_config(path)


def test_invalid_size_threshold_order_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "wal.json"
    path.write_text(json.dumps({
        "schema_version": "execution_market_wal_storage_v1",
        "mode": "segmented",
        "segment_max_bytes": 1024,
        "archive_batch_rows": 16,
        "warning_size_bytes": 20480,
        "critical_size_bytes": 10240,
    }))
    with pytest.raises(ValueError, match="thresholds"):
        load_execution_market_wal_config(path)
