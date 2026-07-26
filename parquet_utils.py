import os
import threading
import time
import uuid

import pandas as pd

from runtime_config import MAX_STATE_ROWS

_REPLACE_ATTEMPTS = 3
_REPLACE_BASE_DELAY_S = 0.05

# Bounded transient read retry (reader opened destination during atomic rewrite).
_TRANSIENT_READ_ATTEMPTS = 3
_TRANSIENT_READ_DELAYS_S = (0.10, 0.25, 0.50)


class ParquetTransientReadError(OSError):
    """Raised after bounded retries on transient parquet metadata/footer failures."""


class WriteCandidateValidationError(OSError):
    """Raised when a temp parquet candidate fails validation before atomic replace."""


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


def is_transient_parquet_read_error(exc: BaseException) -> bool:
    """Narrow classifier for incomplete footer/metadata races during atomic rewrite."""
    try:
        import pyarrow as pa
    except ImportError:  # pragma: no cover
        pa = None

    if isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError):
        msg = str(exc).lower()
        markers = (
            "invalid column metadata",
            "corrupt file",
            "parquet magic bytes",
            "parquet file size is 0 bytes",
            "was smaller than indicated in the footer",
            "footer",
            "ended prematurely",
        )
        if any(m in msg for m in markers):
            return True

    if pa is not None:
        arrow_io = getattr(pa, "ArrowIOError", None)
        arrow_invalid = getattr(pa, "ArrowInvalid", None)
        if arrow_io is not None and isinstance(exc, arrow_io):
            return True
        if arrow_invalid is not None and isinstance(exc, arrow_invalid):
            msg = str(exc).lower()
            if any(
                m in msg
                for m in (
                    "parquet",
                    "footer",
                    "metadata",
                    "magic",
                    "corrupt",
                    "truncated",
                    "premature",
                )
            ):
                return True

    # pyarrow may wrap IO failures as generic Exception subclasses with these messages.
    name = type(exc).__name__
    if name in {"ArrowInvalid", "ArrowIOError", "OSError"}:
        msg = str(exc).lower()
        if any(
            m in msg
            for m in (
                "invalid column metadata",
                "corrupt file",
                "parquet",
                "footer",
                "magic",
            )
        ):
            return True
    return False


def validate_parquet_candidate(
    temp_file: str,
    *,
    expected_rows: int,
    expected_columns: list[str] | None = None,
    timestamp_col: str | None = None,
    enforce_timestamp_integrity: bool = False,
) -> None:
    """Validate a temp parquet before os.replace. Raises WriteCandidateValidationError."""
    import pyarrow.parquet as pq

    try:
        if not os.path.exists(temp_file) or os.path.getsize(temp_file) <= 0:
            raise WriteCandidateValidationError(
                f"WRITE_CANDIDATE_VALIDATION_FAILED empty_or_missing tmp={temp_file}"
            )

        pf = pq.ParquetFile(temp_file)
        _ = pf.metadata
        schema = pf.schema_arrow
        table = pf.read()
        row_count = int(table.num_rows)
        if row_count != int(expected_rows):
            raise WriteCandidateValidationError(
                f"WRITE_CANDIDATE_VALIDATION_FAILED row_count "
                f"expected={expected_rows} actual={row_count} tmp={temp_file}"
            )

        names = list(schema.names)
        if expected_columns is not None and names != list(expected_columns):
            raise WriteCandidateValidationError(
                f"WRITE_CANDIDATE_VALIDATION_FAILED schema_mismatch tmp={temp_file}"
            )

        if enforce_timestamp_integrity:
            ts_name = timestamp_col if timestamp_col and timestamp_col in names else None
            if ts_name is None and "timestamp" in names:
                ts_name = "timestamp"
            if ts_name is None:
                raise WriteCandidateValidationError(
                    f"WRITE_CANDIDATE_VALIDATION_FAILED missing_timestamp_col tmp={temp_file}"
                )
            series = pd.to_datetime(table.column(ts_name).to_pandas(), utc=True, errors="coerce")
            if series.isna().any():
                raise WriteCandidateValidationError(
                    f"WRITE_CANDIDATE_VALIDATION_FAILED null_timestamps tmp={temp_file}"
                )
            if not bool(series.is_monotonic_increasing):
                raise WriteCandidateValidationError(
                    f"WRITE_CANDIDATE_VALIDATION_FAILED non_monotonic_timestamps "
                    f"tmp={temp_file}"
                )
            if int(series.duplicated().sum()) != 0:
                raise WriteCandidateValidationError(
                    f"WRITE_CANDIDATE_VALIDATION_FAILED duplicate_timestamps "
                    f"tmp={temp_file}"
                )
    except WriteCandidateValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as validation failure
        raise WriteCandidateValidationError(
            f"WRITE_CANDIDATE_VALIDATION_FAILED {type(exc).__name__}: {exc} tmp={temp_file}"
        ) from exc


def read_parquet_with_transient_retry(
    file_path: str,
    *,
    columns: list[str] | None = None,
    attempts: int = _TRANSIENT_READ_ATTEMPTS,
    delays_s: tuple[float, ...] = _TRANSIENT_READ_DELAYS_S,
) -> pd.DataFrame:
    """Read parquet with bounded retry on transient metadata/footer races."""
    resolved = _coerce_path(file_path, for_write=False)
    if not os.path.exists(resolved):
        raise FileNotFoundError(resolved)

    last_error: BaseException | None = None
    max_attempts = max(1, int(attempts))
    for attempt in range(max_attempts):
        try:
            frame = pd.read_parquet(resolved, columns=columns)
            if attempt > 0:
                print(
                    "PARQUET_TRANSIENT_READ_RECOVERED "
                    f"path={resolved} attempt={attempt + 1}"
                )
            return frame
        except Exception as exc:  # noqa: BLE001 — classify narrowly below
            last_error = exc
            if not is_transient_parquet_read_error(exc):
                raise
            if attempt + 1 >= max_attempts:
                break
            delay = delays_s[min(attempt, len(delays_s) - 1)] if delays_s else 0.1
            time.sleep(float(delay))

    raise ParquetTransientReadError(
        f"UPSTREAM_PARQUET_TEMPORARILY_UNREADABLE path={resolved} "
        f"attempts={max_attempts} last={type(last_error).__name__}: {last_error}"
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
    file_path,
    *,
    validate: bool = True,
    timestamp_col: str | None = "timestamp",
    enforce_timestamp_integrity: bool = False,

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
        # Ensure buffers are durable before validation/replace.
        try:
            with open(temp_file, "rb") as handle:
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass

        if validate:
            try:
                validate_parquet_candidate(
                    temp_file,
                    expected_rows=int(len(df)),
                    expected_columns=list(df.columns),
                    timestamp_col=timestamp_col if timestamp_col in df.columns else None,
                    enforce_timestamp_integrity=enforce_timestamp_integrity,
                )
            except WriteCandidateValidationError:
                print(
                    "WRITE_CANDIDATE_VALIDATION_FAILED "
                    f"tmp={temp_file} target={resolved}"
                )
                raise

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
