"""Auction-only native file reads; shared readers and writers stay unchanged.

An explicit Arrow filesystem keeps local reads out of Pandas' Python-file
handle branch (Arrow #54536). Pandas still performs its existing conversion,
including Pandas index metadata, extension dtypes, timezones and attrs.
"""
import os

import pandas as pd
from pyarrow.fs import LocalFileSystem

from parquet_utils import _coerce_path, atomic_parquet_write
from runtime_config import MAX_STATE_ROWS


def safe_read_parquet(file_path):
    resolved = _coerce_path(file_path, for_write=False)
    if not os.path.exists(resolved):
        return pd.DataFrame()
    try:
        return pd.read_parquet(resolved, filesystem=LocalFileSystem())
    except Exception:
        print()
        print("CORRUPTED PARQUET:")
        print(resolved)
        return pd.DataFrame()


def should_persist_state(file_path, state_dict):
    # Same state_guard decision; only its reader is local to this child.
    old = safe_read_parquet(file_path)
    if len(old) == 0:
        return True
    latest = old.iloc[-1]
    for key, value in state_dict.items():
        if key not in latest:
            return True
        if str(latest[key]) != str(value):
            return True
    return False


def append_state_row(file_path, new_row, dedup_columns=None,
                     max_rows=MAX_STATE_ROWS):
    # Same append/retention rules and original durable/validated atomic writer.
    resolved = _coerce_path(file_path, for_write=False)
    old = safe_read_parquet(resolved)
    combined = pd.concat([old, new_row], ignore_index=True)
    if dedup_columns:
        combined = combined.drop_duplicates(subset=dedup_columns)
    if len(combined) > max_rows:
        combined = combined.iloc[-max_rows:]
    atomic_parquet_write(combined, _coerce_path(file_path, for_write=True))
    return combined
