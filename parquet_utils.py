import os
import threading
import time
import uuid

import pandas as pd

from runtime_config import MAX_STATE_ROWS

_REPLACE_ATTEMPTS = 3
_REPLACE_BASE_DELAY_S = 0.05


def _coerce_path(file_path: str, *, for_write: bool = False) -> str:
    try:
        from storage.path_registry import is_registered, resolve_read, resolve_write

        if is_registered(file_path):
            return resolve_write(file_path) if for_write else resolve_read(file_path)
    except ImportError:
        pass
    return file_path


def _unique_temp_path(resolved: str) -> str:
    """Unique temp beside the target — never a shared deterministic `.tmp` path."""
    directory = os.path.dirname(resolved) or "."
    basename = os.path.basename(resolved)
    token = (
        f".{basename}.tmp.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.parquet"
    )
    return os.path.join(directory, token)


def _cleanup_own_temp(temp_file: str) -> None:
    try:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
    except OSError:
        pass


def _replace_with_retry(temp_file: str, resolved: str) -> None:
    last_error: Exception | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            if not os.path.exists(temp_file):
                raise FileNotFoundError(
                    f"atomic parquet temp missing before replace: "
                    f"tmp={temp_file} target={resolved}"
                )
            if os.path.getsize(temp_file) <= 0:
                raise OSError(
                    f"atomic parquet temp empty before replace: "
                    f"tmp={temp_file} target={resolved}"
                )
            os.replace(temp_file, resolved)
            return
        except (FileNotFoundError, PermissionError) as exc:
            last_error = exc
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                break
            time.sleep(_REPLACE_BASE_DELAY_S * (attempt + 1))

    raise RuntimeError(
        f"atomic parquet replace failed after {_REPLACE_ATTEMPTS} attempts: "
        f"tmp={temp_file} target={resolved}: {last_error}"
    ) from last_error


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
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)

    temp_file = _unique_temp_path(resolved)

    try:
        df.to_parquet(
            temp_file,
            index=False
        )
        _replace_with_retry(temp_file, resolved)
    except Exception:
        _cleanup_own_temp(temp_file)
        raise

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
