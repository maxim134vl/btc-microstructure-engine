"""Typing contract for the ``context_entered_at`` column of the decision log.

The column is the only Arrow ``timestamp[us, tz=UTC]`` field in a 114-column
schema where every other temporal value is stored as an ISO string. Writing a
string into it degrades the concatenated frame to object dtype, which Arrow
refuses to convert -- the failure that froze live context refresh cycles on
2026-07-25.

These tests are fully isolated: they build their own parquet files under tmp_path
and assert that the production log is never touched.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_LOG = ROOT / "data/live/context_decision_log.parquet"
CANONICAL_ARROW_TYPE = "timestamp[us, tz=UTC]"
CANONICAL_PANDAS_DTYPE = "datetime64[us, UTC]"


def _load_logger():
    path = ROOT / "scripts/live/append_context_decision_log.py"
    spec = importlib.util.spec_from_file_location("append_context_decision_log", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("append_context_decision_log", module)
    spec.loader.exec_module(module)
    return module


logger = _load_logger()
coerce = logger.coerce_utc_timestamp_series
normalize = logger.normalize_canonical_timestamp_columns
COLUMN = "context_entered_at"


def _frame(values: list) -> pd.DataFrame:
    return pd.DataFrame({"candle_timestamp": [f"c{i}" for i in range(len(values))], COLUMN: values})


def _write(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    normalize(frame).to_parquet(path, index=False)
    return pd.read_parquet(path)


# --------------------------------------------------------------- 1..3 batches
def test_01_null_only_batch_writes_and_preserves_nulls(tmp_path):
    out = _write(_frame([None, None]), tmp_path / "a.parquet")
    assert out[COLUMN].isna().all()
    assert str(out[COLUMN].dtype) == CANONICAL_PANDAS_DTYPE


def test_02_non_null_only_batch_writes(tmp_path):
    out = _write(
        _frame(["2026-07-25T08:10:00Z", "2026-07-25T09:15:00.500000Z"]), tmp_path / "b.parquet"
    )
    assert out[COLUMN].notna().all()


def test_03_mixed_null_and_non_null_batch_writes(tmp_path):
    out = _write(_frame([None, "2026-07-25T08:10:00Z", None]), tmp_path / "c.parquet")
    assert list(out[COLUMN].isna()) == [True, False, True]


# ----------------------------------------------------------- 4..6 value forms
def test_04_microsecond_precision_is_preserved(tmp_path):
    out = _write(_frame(["2026-07-25T08:10:00.123456Z"]), tmp_path / "d.parquet")
    assert out[COLUMN].iloc[0] == pd.Timestamp("2026-07-25T08:10:00.123456Z")


def test_05_second_precision_does_not_become_nat(tmp_path):
    """The exact shape that broke production: no microseconds after a row with them."""
    out = _write(
        _frame(["2026-07-25T08:10:00.123456Z", "2026-07-25T09:15:00Z"]), tmp_path / "e.parquet"
    )
    assert out[COLUMN].notna().all()
    assert out[COLUMN].iloc[1] == pd.Timestamp("2026-07-25T09:15:00Z")


def test_06_timezone_aware_values_are_not_double_converted(tmp_path):
    aware = pd.Timestamp("2026-07-25T11:10:00+03:00")
    out = _write(_frame([aware, "2026-07-25T08:10:00+00:00"]), tmp_path / "f.parquet")
    assert out[COLUMN].iloc[0] == pd.Timestamp("2026-07-25T08:10:00Z")
    assert out[COLUMN].iloc[1] == pd.Timestamp("2026-07-25T08:10:00Z")


# ------------------------------------------------- 7..10 append / persistence
def test_07_append_to_existing_parquet_succeeds(tmp_path):
    path = tmp_path / "g.parquet"
    _write(_frame([None, "2026-07-25T07:30:00.123456Z"]), path)
    existing = pd.read_parquet(path)

    new_row = pd.DataFrame([{"candle_timestamp": "c9", COLUMN: "2026-07-25T09:15:00Z"}])
    combined = pd.concat([existing, new_row], ignore_index=True)
    assert combined[COLUMN].dtype == object, "precondition: concat degrades to object"

    out = _write(combined, path)
    assert len(out) == 3
    assert out[COLUMN].iloc[2] == pd.Timestamp("2026-07-25T09:15:00Z")


def test_08_arrow_schema_type_is_preserved(tmp_path):
    path = tmp_path / "h.parquet"
    _write(_frame([None, "2026-07-25T08:10:00Z"]), path)
    assert str(pq.read_schema(path).field(COLUMN).type) == CANONICAL_ARROW_TYPE


def test_09_existing_prefix_is_immutable_across_append(tmp_path):
    path = tmp_path / "i.parquet"
    first = _write(_frame(["2026-07-25T07:00:00.111111Z", None]), path)
    prefix_before = first[COLUMN].tolist()

    combined = pd.concat(
        [first, pd.DataFrame([{"candle_timestamp": "cx", COLUMN: "2026-07-25T09:15:00Z"}])],
        ignore_index=True,
    )
    after = _write(combined, path)

    assert after[COLUMN].tolist()[:2] == prefix_before
    assert after["candle_timestamp"].tolist()[:2] == first["candle_timestamp"].tolist()


def test_10_normalization_does_not_create_or_drop_rows(tmp_path):
    frame = _frame([None, "2026-07-25T08:10:00Z", "2026-07-25T09:15:00.5Z", None])
    out = _write(frame, tmp_path / "j.parquet")
    assert len(out) == 4
    assert out["candle_timestamp"].tolist() == ["c0", "c1", "c2", "c3"]
    assert not out["candle_timestamp"].duplicated().any()


# -------------------------------------------------------- 11 invalid handling
@pytest.mark.parametrize("bad", ["not-a-timestamp", "2026-13-45T99:99:99Z", "12345abc"])
def test_11_invalid_value_fails_closed(bad):
    with pytest.raises(logger.DecisionLoggerError) as excinfo:
        coerce([bad], COLUMN)
    message = str(excinfo.value)
    assert "INVALID_TIMESTAMP" in message
    assert COLUMN in message


def test_11b_empty_string_is_treated_as_null():
    assert coerce(["", "   "], COLUMN).isna().all()


# ----------------------------------------------- 12 production file untouched
def test_12_production_decision_log_untouched_by_this_module(tmp_path):
    if not PRODUCTION_LOG.exists():
        pytest.skip("production decision log not present")
    digest = hashlib.sha256(PRODUCTION_LOG.read_bytes()).hexdigest()
    mtime = PRODUCTION_LOG.stat().st_mtime

    _write(_frame([None, "2026-07-25T09:15:00Z"]), tmp_path / "k.parquet")

    assert hashlib.sha256(PRODUCTION_LOG.read_bytes()).hexdigest() == digest
    assert PRODUCTION_LOG.stat().st_mtime == mtime
