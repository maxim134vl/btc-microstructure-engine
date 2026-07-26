"""Stage 3B1.1 — UTC-safe alignment merge for decision cognition bridge."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from runtime_integrity import enrich_alignment_status, normalize_utc_merge_timestamp

REPO = Path(__file__).resolve().parents[1]


def _load_unpatched_enrich():
    src = subprocess.check_output(["git", "show", "739d57a:runtime_integrity.py"])
    path = REPO / "data/candidate/architecture_recovery/stage3b11_utc_alignment_candidate/runtime_integrity_unpatched.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("runtime_integrity_unpatched", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.enrich_alignment_status


def _frame(ts_values, *, aware: bool, score: float = 0.5) -> pd.DataFrame:
    if aware:
        ts = pd.to_datetime(ts_values, utc=True)
    else:
        ts = pd.to_datetime(ts_values)  # naive proven-UTC wall clock
    return pd.DataFrame({"timestamp": ts, "alignment_score": score})


def test_normalize_utc_no_epoch_shift_naive_or_aware():
    naive = pd.Series(pd.to_datetime(["2026-07-25 08:45:00", "2026-07-26 19:15:00"]))
    aware = pd.to_datetime(naive, utc=True)
    out_naive = normalize_utc_merge_timestamp(naive)
    out_aware = normalize_utc_merge_timestamp(aware)
    assert (out_naive.astype("int64").to_numpy() == aware.astype("int64").to_numpy()).all()
    assert (out_aware.astype("int64").to_numpy() == aware.astype("int64").to_numpy()).all()


@pytest.mark.parametrize(
    "left_aware,right_aware",
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_merge_matrix_identical_instant_matching(left_aware, right_aware):
    left = _frame(["2026-07-25 08:45:00", "2026-07-26 19:15:00"], aware=left_aware, score=0.4)
    right = _frame(["2026-07-25 08:45:00"], aware=right_aware, score=0.5)
    out = enrich_alignment_status(left, synthesis=right)
    assert len(out) == 2
    matched = out.loc[
        pd.to_datetime(out["timestamp"], utc=True)
        == pd.Timestamp("2026-07-25 08:45:00", tz="UTC")
    ].iloc[0]
    assert float(matched["alignment_score_reference"]) == 0.5


def test_old_function_fails_mixed_tz_new_succeeds_with_reference_parity():
    old_enrich = _load_unpatched_enrich()
    left = _frame(["2026-07-25 08:45:00", "2026-07-26 19:15:00"], aware=True, score=0.4)
    right = _frame(["2026-07-25 08:45:00"], aware=False, score=0.5)

    with pytest.raises(ValueError, match="datetime64"):
        old_enrich(left, synthesis=right)

    left_ref = left.copy()
    right_ref = right.copy()
    left_ref["timestamp"] = pd.to_datetime(left_ref["timestamp"], utc=True)
    right_ref["timestamp"] = pd.to_datetime(right_ref["timestamp"], utc=True)
    reference = old_enrich(left_ref, synthesis=right_ref)
    patched = enrich_alignment_status(left, synthesis=right)

    assert len(reference) == len(patched)
    assert list(reference.columns) == list(patched.columns)
    assert (
        pd.to_datetime(reference["timestamp"], utc=True)
        .astype("int64")
        .to_numpy()
        == pd.to_datetime(patched["timestamp"], utc=True).astype("int64").to_numpy()
    ).all()
    assert (
        reference["alignment_status"].astype(str).to_numpy()
        == patched["alignment_status"].astype(str).to_numpy()
    ).all()


def test_both_aware_parity_with_old_function():
    old_enrich = _load_unpatched_enrich()
    left = _frame(["2026-07-25 08:45:00", "2026-07-26 19:15:00"], aware=True)
    right = _frame(["2026-07-25 08:45:00"], aware=True)
    old = old_enrich(left, synthesis=right)
    new = enrich_alignment_status(left, synthesis=right)
    assert len(old) == len(new)
    assert (
        old["alignment_status"].astype(str).to_numpy()
        == new["alignment_status"].astype(str).to_numpy()
    ).all()


def test_inputs_not_mutated():
    left = _frame(["2026-07-25 08:45:00"], aware=True)
    right = _frame(["2026-07-25 08:45:00"], aware=False)
    left_before = left.copy(deep=True)
    right_before = right.copy(deep=True)
    _ = enrich_alignment_status(left, synthesis=right)
    assert left.equals(left_before)
    assert right.equals(right_before)


def test_missing_timestamp_column_fails_closed():
    left = pd.DataFrame({"alignment_score": [0.5]})
    right = _frame(["2026-07-25 08:45:00"], aware=False)
    with pytest.raises(ValueError, match="timestamp column missing"):
        enrich_alignment_status(left, synthesis=right)


def test_unparseable_timestamp_fails_closed():
    series = pd.Series(["2026-07-25 08:45:00", "not-a-timestamp"])
    with pytest.raises(ValueError, match="UTC timestamp normalization failed|NaT from non-null"):
        normalize_utc_merge_timestamp(series)


def test_unparseable_type_fails_closed():
    series = pd.Series([object()])
    with pytest.raises(ValueError, match="UTC timestamp normalization failed|NaT from non-null"):
        normalize_utc_merge_timestamp(series)


def test_non_null_nat_sentinel_fails_closed(monkeypatch):
    """If parsing yields NaT from a non-null input, fail closed (no silent drop)."""
    original = pd.to_datetime

    def _fake_to_datetime(values, *args, **kwargs):
        series = pd.Series(values)
        out = original(series, *args, **kwargs)
        # Force a non-null → NaT regression path for the guard.
        out = out.copy()
        out.iloc[0] = pd.NaT
        return out

    monkeypatch.setattr(pd, "to_datetime", _fake_to_datetime)
    with pytest.raises(ValueError, match="NaT from non-null"):
        normalize_utc_merge_timestamp(pd.Series(["2026-07-25 08:45:00"]))
