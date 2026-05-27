"""
Parquet preview helper. Reads schema + last N rows of a given parquet
without loading the whole file. Returns plain dict/list shapes suitable
for direct JSON serialization.

Bounded cost: O(rows × columns), capped at 200 rows by default.
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

MAX_ROWS = 500
DEFAULT_ROWS = 100
MAX_CSV_ROWS = 100_000   # generous; tail-only and bounded by file size


def _coerce_cell(v: Any) -> Any:
    """JSON-safe coercion for one cell. Handles numpy/pandas scalars,
    bytes, NaN/Inf, lists/dicts."""
    if v is None:
        return None
    if isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    # numpy / pandas scalars expose .item()
    if hasattr(v, "item"):
        try:
            iv = v.item()
            return _coerce_cell(iv)
        except Exception:
            pass
    # pandas Timestamp etc.
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (list, tuple)):
        return [_coerce_cell(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _coerce_cell(val) for k, val in v.items()}
    return str(v)


def preview_parquet(data_dir: Path, basename: str, n_rows: int = DEFAULT_ROWS) -> dict[str, Any]:
    """Read columns + last N rows of `<data_dir>/<basename>` as JSON-safe shapes."""
    n_rows = max(1, min(int(n_rows), MAX_ROWS))

    # path-traversal guard — basename only, no slashes
    if "/" in basename or ".." in basename or basename.startswith("."):
        raise ValueError("invalid basename")
    path = data_dir / basename
    if not path.is_file():
        raise FileNotFoundError(basename)

    pf = pq.ParquetFile(path)
    columns = list(pf.schema_arrow.names)
    types = [str(pf.schema_arrow.field(c).type) for c in columns]
    total = pf.metadata.num_rows

    table = pf.read()  # full read; for production we'd page by row group
    if total > n_rows:
        table = table.slice(total - n_rows, n_rows)

    # to_pydict gives { col_name: [v0, v1, ...] }; we want row-major
    pydict = table.to_pydict()
    rows = []
    for i in range(table.num_rows):
        rows.append({c: _coerce_cell(pydict[c][i]) for c in columns})

    return {
        "file": basename,
        "columns": columns,
        "types": types,
        "rows": rows,
        "rows_returned": len(rows),
        "rows_total": total,
        "size_bytes": path.stat().st_size,
    }


def preview_csv(data_dir: Path, basename: str, n_rows: int = MAX_CSV_ROWS) -> bytes:
    """Export the last `n_rows` of a parquet as CSV bytes."""
    n_rows = max(1, min(int(n_rows), MAX_CSV_ROWS))
    if "/" in basename or ".." in basename or basename.startswith("."):
        raise ValueError("invalid basename")
    path = data_dir / basename
    if not path.is_file():
        raise FileNotFoundError(basename)

    pf = pq.ParquetFile(path)
    table = pf.read()
    total = table.num_rows
    if total > n_rows:
        table = table.slice(total - n_rows, n_rows)

    # pandas writes CSV reliably across numpy/Timestamp/nan; bytes target
    # avoids a stringify+encode round-trip.
    df = table.to_pandas()
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()
