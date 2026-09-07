"""Pruned + hour-cached aggTrade reader for tick replays.

`load_agg_trades` decodes all 21 columns of every hourly file it touches and
re-parses the string exchange timestamps on each call. The Hybrid replay calls it
~7 times per market hour (four protective windows plus the entry-price lookback,
which spans three hours), so the same bytes are decompressed and the same strings
re-parsed roughly seven times over. This reader decodes only the three columns the
replay actually consumes, converts timestamps to int64 nanoseconds once per hour,
and keeps a small LRU of decoded hours.

Rows are returned as parallel numpy arrays rather than a DataFrame: the replay
scans them with vectorised comparisons, and building a per-window DataFrame was
itself a measurable share of the cost.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

_COLUMNS = ["exchange_trade_timestamp", "price", "aggregate_trade_id", "symbol"]

# Empty typed arrays, returned for hours with no data so callers never branch on None.
_EMPTY = (
    np.empty(0, dtype="int64"),
    np.empty(0, dtype="float64"),
    np.empty(0, dtype="int64"),
)

TickWindow = tuple[np.ndarray, np.ndarray, np.ndarray]


class TickHourCache:
    """Read aggTrade hours as (ts_ns, price, aggregate_trade_id), caching decoded hours.

    max_hours only has to cover the reuse pattern of a single replay cycle: the
    protective window and the entry-price lookback both sit within a few hours of
    the evaluation boundary, so a handful of hours removes essentially all re-reads
    while keeping the resident set small.
    """

    def __init__(self, *, repo: Path, symbol: str = "BTCUSDT", max_hours: int = 6) -> None:
        self.root = Path(repo) / "data" / "raw_market_events_v2" / "agg_trade"
        self.symbol = str(symbol).upper()
        self.max_hours = max(1, int(max_hours))
        self._hours: OrderedDict[pd.Timestamp, TickWindow] = OrderedDict()
        self.hour_loads = 0
        self.hour_hits = 0

    # ---------- hour decoding ----------

    def _decode_hour(self, hour: pd.Timestamp) -> TickWindow:
        directory = self.root / f"date={hour.strftime('%Y-%m-%d')}" / f"hour={hour.strftime('%H')}"
        if not directory.exists():
            return _EMPTY

        tables: list[pa.Table] = []
        for path in sorted(directory.glob("*.parquet")):
            # ParquetFile.read reads this one file. pq.read_table would treat the path
            # as a dataset and unify schemas across the pack, which fails outright:
            # the `date` column is large_string in some append batches and
            # dictionary-encoded in others.
            try:
                table = pq.ParquetFile(path).read(columns=_COLUMNS)
            except Exception:
                continue
            if table.num_rows:
                tables.append(table)
        if not tables:
            return _EMPTY

        # promote_options keeps the mixed large_string/dictionary encodings across
        # append batches from fusing into a schema error.
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="permissive")

        symbols = pc.utf8_upper(table.column("symbol").cast(pa.string()))
        keep = pc.equal(symbols, pa.scalar(self.symbol))
        if not pc.all(keep).as_py():
            table = table.filter(keep)
            if not table.num_rows:
                return _EMPTY

        stamps = pd.to_datetime(
            table.column("exchange_trade_timestamp").cast(pa.string()).to_pandas(),
            utc=True,
            errors="coerce",
        )
        price = table.column("price").cast(pa.float64()).to_pandas().to_numpy(dtype="float64", copy=False)
        ids = table.column("aggregate_trade_id").cast(pa.int64()).to_pandas().to_numpy(dtype="int64", copy=False)

        ts_ns = stamps.to_numpy(dtype="datetime64[ns]").astype("int64")
        valid = stamps.notna().to_numpy()
        # NaT casts to int64 min; drop those rows rather than let them sort first.
        if not valid.all():
            ts_ns, price, ids = ts_ns[valid], price[valid], ids[valid]
        if not len(ts_ns):
            return _EMPTY

        # Overlapping appends after a stream restart can repeat aggregate ids; sort by
        # (ts, id) then keep the first of each id, matching load_agg_trades' dedup key.
        order = np.lexsort((ids, ts_ns))
        ts_ns, price, ids = ts_ns[order], price[order], ids[order]
        _, first = np.unique(ids, return_index=True)
        if len(first) != len(ids):
            first.sort()
            ts_ns, price, ids = ts_ns[first], price[first], ids[first]

        return ts_ns, price, ids

    def _hour(self, hour: pd.Timestamp) -> TickWindow:
        cached = self._hours.get(hour)
        if cached is not None:
            self._hours.move_to_end(hour)
            self.hour_hits += 1
            return cached
        decoded = self._decode_hour(hour)
        self.hour_loads += 1
        self._hours[hour] = decoded
        while len(self._hours) > self.max_hours:
            self._hours.popitem(last=False)
        return decoded

    # ---------- queries ----------

    def window(self, *, start: pd.Timestamp, end: pd.Timestamp) -> TickWindow:
        """Ticks with start < ts <= end, in exchange-timestamp order."""
        if end <= start:
            return _EMPTY
        start_ns = int(pd.Timestamp(start).value)
        end_ns = int(pd.Timestamp(end).value)

        chunks: list[TickWindow] = []
        hour = pd.Timestamp(start).floor("h")
        last_hour = pd.Timestamp(end).floor("h")
        while hour <= last_hour:
            ts_ns, price, ids = self._hour(hour)
            if len(ts_ns):
                lo = int(np.searchsorted(ts_ns, start_ns, side="right"))
                hi = int(np.searchsorted(ts_ns, end_ns, side="right"))
                if hi > lo:
                    chunks.append((ts_ns[lo:hi], price[lo:hi], ids[lo:hi]))
            hour += pd.Timedelta(hours=1)

        if not chunks:
            return _EMPTY
        if len(chunks) == 1:
            return chunks[0]
        return (
            np.concatenate([c[0] for c in chunks]),
            np.concatenate([c[1] for c in chunks]),
            np.concatenate([c[2] for c in chunks]),
        )

    def last_price_at_or_before(
        self,
        ts: pd.Timestamp,
        *,
        max_lookback_hours: int = 6,
    ) -> float | None:
        """Freshest trade price with exchange timestamp <= ts, or None if the pack has none."""
        boundary_ns = int(pd.Timestamp(ts).value)
        hour = pd.Timestamp(ts).floor("h")
        for _ in range(max(1, int(max_lookback_hours))):
            ts_ns, price, _ids = self._hour(hour)
            if len(ts_ns):
                cut = int(np.searchsorted(ts_ns, boundary_ns, side="right"))
                if cut > 0:
                    return float(price[cut - 1])
            hour -= pd.Timedelta(hours=1)
        return None

    def stats(self) -> dict[str, int]:
        return {
            "hour_loads": self.hour_loads,
            "hour_cache_hits": self.hour_hits,
            "hours_resident": len(self._hours),
        }
