import os
import pandas as pd

from runtime_config import (
    MAX_STATE_ROWS
)


def _coerce_path(file_path: str, *, for_write: bool = False) -> str:
    try:
        from storage.path_registry import is_registered, resolve_read, resolve_write

        if is_registered(file_path):
            return resolve_write(file_path) if for_write else resolve_read(file_path)
    except ImportError:
        pass
    return file_path


# =====================================
# SAFE LOAD
# =====================================

def safe_read_parquet(
    file_path
):

    resolved = _coerce_path(file_path, for_write=False)

    if not os.path.exists(
        resolved
    ):

        return pd.DataFrame()

    try:

        return pd.read_parquet(
            resolved
        )

    except Exception:

        print()

        print(
            "CORRUPTED PARQUET:"
        )

        print(
            resolved
        )

        return pd.DataFrame()

# =====================================
# ATOMIC WRITE
# =====================================

def atomic_parquet_write(

    df,
    file_path

):

    resolved = _coerce_path(file_path, for_write=True)

    temp_file = (
        resolved + ".tmp"
    )

    df.to_parquet(
        temp_file,
        index=False
    )

    os.replace(
        temp_file,
        resolved
    )

# =====================================
# APPEND STATE
# =====================================

def append_state_row(

    file_path,
    new_row,
    dedup_columns=None,
    max_rows=MAX_STATE_ROWS

):

    resolved = _coerce_path(file_path, for_write=False)

    old = safe_read_parquet(
        resolved
    )

    combined = pd.concat(

        [old, new_row],

        ignore_index=True

    )

    if dedup_columns:

        combined = combined.drop_duplicates(
            subset=dedup_columns
        )

    if len(combined) > max_rows:

        combined = combined.iloc[
            -max_rows:
        ]

    atomic_parquet_write(
        combined,
        _coerce_path(file_path, for_write=True)
    )

    return combined
