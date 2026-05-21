import os
import pandas as pd

from runtime_config import (
    MAX_STATE_ROWS
)

# =====================================
# SAFE LOAD
# =====================================

def safe_read_parquet(
    file_path
):

    if not os.path.exists(
        file_path
    ):

        return pd.DataFrame()

    try:

        return pd.read_parquet(
            file_path
        )

    except Exception:

        print()

        print(
            "CORRUPTED PARQUET:"
        )

        print(
            file_path
        )

        return pd.DataFrame()

# =====================================
# ATOMIC WRITE
# =====================================

def atomic_parquet_write(

    df,
    file_path

):

    temp_file = (
        file_path + ".tmp"
    )

    df.to_parquet(
        temp_file,
        index=False
    )

    os.replace(
        temp_file,
        file_path
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

    old = safe_read_parquet(
        file_path
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
        file_path
    )

    return combined
