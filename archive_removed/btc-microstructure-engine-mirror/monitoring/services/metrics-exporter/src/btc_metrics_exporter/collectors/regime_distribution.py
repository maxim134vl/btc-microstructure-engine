"""
Sample the regime column from the configured source parquet and emit
distribution + Shannon entropy. A sudden collapse in entropy signals
the regime detector has degenerated.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pyarrow.parquet as pq

from ..config import REGIME_SOURCE_COLUMN, REGIME_SOURCE_FILE
from .base import Collector


class RegimeDistributionCollector(Collector):
    name = "regime_distribution"

    async def collect(self) -> None:
        path = self.cfg.data_dir / REGIME_SOURCE_FILE
        if not path.is_file():
            return

        loop = asyncio.get_running_loop()
        try:
            counts = await loop.run_in_executor(
                None, _read_regime_counts, path, REGIME_SOURCE_COLUMN, self.cfg.regime_sample_rows
            )
        except KeyError:
            # column absent — nothing to do (e.g. before runtime has produced regime)
            return
        except Exception:
            self.metrics.parquet_read_errors_total.labels(REGIME_SOURCE_FILE, "regime_read").inc()
            self.log.exception("regime.read_failed")
            return

        if not counts:
            return

        total = sum(counts.values())
        m = self.metrics
        entropy = 0.0
        for regime, n in counts.items():
            p = n / total
            m.regime_distribution.labels(REGIME_SOURCE_FILE, str(regime)).set(p)
            if p > 0:
                entropy -= p * math.log2(p)
        m.regime_entropy.labels(REGIME_SOURCE_FILE).set(entropy)


def _read_regime_counts(path: Path, column: str, n_rows: int) -> dict[object, int]:
    pf = pq.ParquetFile(path)
    if column not in pf.schema_arrow.names:
        raise KeyError(column)
    table = pf.read(columns=[column])
    total = table.num_rows
    if total > n_rows:
        table = table.slice(total - n_rows, n_rows)
    arr = table.column(column)
    counts: dict[object, int] = {}
    for v in arr.to_pylist():
        if v is None:
            continue
        counts[v] = counts.get(v, 0) + 1
    return counts
