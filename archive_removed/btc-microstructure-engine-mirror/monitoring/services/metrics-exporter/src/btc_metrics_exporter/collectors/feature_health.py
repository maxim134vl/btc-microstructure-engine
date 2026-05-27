"""
Compute health stats on the *tail* of each parquet — bounded I/O.

For each (file, feature) pair in FEATURE_ALLOWLIST we emit:
  * NaN ratio
  * inf count
  * z-score mean (drift indicator)
  * z-score std  (normalization-collapse indicator)

These are *not* trading features — they are sanity statistics over the data
the engine has just emitted. Treat them as smoke detectors, not signals.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..config import FEATURE_ALLOWLIST
from .base import Collector


class FeatureHealthCollector(Collector):
    name = "feature_health"

    async def collect(self) -> None:
        data_dir: Path = self.cfg.data_dir
        if not data_dir.is_dir():
            return

        for basename, features in FEATURE_ALLOWLIST.items():
            path = data_dir / basename
            if not path.is_file():
                continue
            try:
                await self._scan_one(path, basename, features)
            except Exception:
                self.metrics.parquet_read_errors_total.labels(basename, "feature_read").inc()
                self.log.exception("feature.scan_failed", file=basename)

    async def _scan_one(self, path: Path, basename: str, features: tuple[str, ...]) -> None:
        loop = asyncio.get_running_loop()
        n_rows = self.cfg.feature_sample_rows
        df: pd.DataFrame = await loop.run_in_executor(None, _read_tail, path, features, n_rows)
        if df.empty:
            return

        m = self.metrics
        for feat in features:
            if feat not in df.columns:
                # column missing — schema scanner will flag; we just skip
                continue
            col = df[feat].astype("float64", copy=False).to_numpy()
            n = col.size
            if n == 0:
                continue

            nan_mask = np.isnan(col)
            inf_mask = np.isinf(col)
            nan_ratio = float(nan_mask.sum()) / n
            inf_count = int(inf_mask.sum())

            m.feature_nan_ratio.labels(basename, feat).set(nan_ratio)
            m.feature_inf_count.labels(basename, feat).set(inf_count)

            # drift / collapse detector: stats on the finite values
            finite = col[~(nan_mask | inf_mask)]
            if finite.size >= 2:
                mu = float(finite.mean())
                sd = float(finite.std(ddof=1))
                m.feature_zscore_mean.labels(basename, feat).set(mu)
                m.feature_zscore_std.labels(basename, feat).set(sd)
            else:
                m.feature_zscore_mean.labels(basename, feat).set(0.0)
                m.feature_zscore_std.labels(basename, feat).set(0.0)


def _read_tail(path: Path, columns: tuple[str, ...], n_rows: int) -> pd.DataFrame:
    """Read at most the last n_rows of the requested columns.

    Strategy: read the file via pyarrow with a column projection, slice
    the tail, convert to pandas. This still scans the full parquet for
    column data — pyarrow does not support reverse iteration — but the
    column projection bounds memory.

    Bounded cost: O(rows × len(columns) × dtype_size). For 2000 rows and
    5 numeric columns this is < 100 KB regardless of total file size.
    """
    pf = pq.ParquetFile(path)
    have = set(pf.schema_arrow.names)
    cols = [c for c in columns if c in have]
    if not cols:
        return pd.DataFrame()
    table = pf.read(columns=cols)
    total = table.num_rows
    if total > n_rows:
        table = table.slice(total - n_rows, n_rows)
    return table.to_pandas(types_mapper=None)


def _dtype_is_numeric(arr: Any) -> bool:
    try:
        return np.issubdtype(arr.dtype, np.number)
    except Exception:
        return False
