"""
Unit tests for ParquetScannerCollector. Uses a tmp_path with synthesized
parquet files so we don't depend on the engine running.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from btc_metrics_exporter.config import Config
from btc_metrics_exporter.collectors.parquet_scanner import ParquetScannerCollector
from btc_metrics_exporter.logging import configure_logging
from btc_metrics_exporter.registry import build_metrics


def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    table = pa.Table.from_pandas(df)
    pq.write_table(table, path)


def _cfg(tmp_path: Path) -> Config:
    # bypass env-driven defaults via direct construction
    return Config(
        listen_host="127.0.0.1",
        listen_port=9101,
        data_dir=tmp_path,
        scan_interval_seconds=10,
        feature_sample_rows=2000,
        regime_sample_rows=5000,
        log_level="WARNING",
    )


@pytest.mark.asyncio
async def test_emits_size_age_for_each_file(tmp_path: Path) -> None:
    _write_parquet(tmp_path / "intraday_flow.parquet",
                   pd.DataFrame({"timestamp": [1, 2], "avg_price": [1.0, 2.0], "delta": [0.1, 0.2]}))
    _write_parquet(tmp_path / "oi_history.parquet",
                   pd.DataFrame({"timestamp": [1], "open_interest": [10.0]}))

    cfg = _cfg(tmp_path)
    log = configure_logging(cfg)
    metrics = build_metrics()
    c = ParquetScannerCollector(cfg, metrics, log)

    await c.collect()

    samples = {s.name: {tuple(sorted(s.labels.items())): s.value for s in metric.samples}
               for metric in metrics.registry.collect()
               for s in [metric]}

    # confirm size_bytes was emitted for both files
    size_samples = {
        s.labels["file"]: s.value
        for m in metrics.registry.collect()
        if m.name == "btc_parquet_size_bytes"
        for s in m.samples
    }
    assert "intraday_flow.parquet" in size_samples
    assert "oi_history.parquet" in size_samples
    assert size_samples["intraday_flow.parquet"] > 0


@pytest.mark.asyncio
async def test_schema_valid_flag(tmp_path: Path) -> None:
    # missing the `delta` column → schema invalid
    _write_parquet(tmp_path / "intraday_flow.parquet",
                   pd.DataFrame({"timestamp": [1, 2], "avg_price": [1.0, 2.0]}))

    cfg = _cfg(tmp_path)
    log = configure_logging(cfg)
    metrics = build_metrics()
    c = ParquetScannerCollector(cfg, metrics, log)

    await c.collect()

    valid = {
        s.labels["file"]: s.value
        for m in metrics.registry.collect()
        if m.name == "btc_parquet_schema_valid"
        for s in m.samples
    }
    assert valid["intraday_flow.parquet"] == 0.0


@pytest.mark.asyncio
async def test_no_files_does_not_crash(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = configure_logging(cfg)
    metrics = build_metrics()
    c = ParquetScannerCollector(cfg, metrics, log)
    # should run cleanly
    await c.collect()


@pytest.mark.asyncio
async def test_row_delta_per_minute(tmp_path: Path) -> None:
    path = tmp_path / "intraday_flow.parquet"
    _write_parquet(path, pd.DataFrame({"timestamp": [1], "avg_price": [1.0], "delta": [0.0]}))

    cfg = _cfg(tmp_path)
    log = configure_logging(cfg)
    metrics = build_metrics()
    c = ParquetScannerCollector(cfg, metrics, log)

    await c.collect()
    # simulate growth
    time.sleep(0.05)
    _write_parquet(path, pd.DataFrame({
        "timestamp": list(range(120)),
        "avg_price": [1.0] * 120,
        "delta": [0.0] * 120,
    }))
    await c.collect()

    rate = {
        s.labels["file"]: s.value
        for m in metrics.registry.collect()
        if m.name == "btc_parquet_rows_delta_per_minute"
        for s in m.samples
    }
    # 119 rows added in < 1s → rate is large; just assert positive
    assert rate.get("intraday_flow.parquet", 0) > 0
