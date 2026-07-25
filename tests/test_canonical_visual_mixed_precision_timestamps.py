"""Mixed-precision ISO-8601 parsing contract for the canonical visual trade view.

The archived legacy ledger writes exit timestamps with microseconds; the
timeframe traders write whole seconds. Under pandas 3.x, letting `to_datetime`
infer a format from the first element makes every second-precision value coerce
to NaT, which silently reclassified two genuinely closed S4 trades as unclosed.

Parsing must therefore be per-value ISO-8601, never inferred from the column.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.visual.canonical_trade_view import (  # noqa: E402
    LEGACY_TIMEFRAME,
    build_canonical_visual_trades,
    reconcile,
    utc_series,
    utc_stamp,
)

LEGACY_EXIT = "2026-07-24T20:20:14.123456Z"
S4_EXIT = "2026-07-25T09:15:00Z"


@pytest.fixture(scope="module")
def view() -> pd.DataFrame:
    return build_canonical_visual_trades()


@pytest.fixture(scope="module")
def invariants(view: pd.DataFrame) -> dict:
    return reconcile(view)


# ------------------------------------------------------------ 1..7 precision
def test_01_seconds_only_parses():
    assert utc_stamp("2026-07-25T09:15:00Z") == pd.Timestamp("2026-07-25T09:15:00Z")


def test_02_milliseconds_parse():
    assert utc_stamp("2026-07-25T09:15:00.250Z") == pd.Timestamp("2026-07-25T09:15:00.250Z")


def test_03_microseconds_parse():
    assert utc_stamp(LEGACY_EXIT) == pd.Timestamp(LEGACY_EXIT)


def test_04_mixed_precision_column_has_no_nat():
    """The exact regression: microseconds first, then whole seconds."""
    parsed = utc_series([LEGACY_EXIT, S4_EXIT])
    assert parsed.notna().all()
    assert parsed.iloc[1] == pd.Timestamp(S4_EXIT)


def test_04b_naive_inference_would_have_failed():
    """Guards the reason this helper exists rather than a bare to_datetime."""
    naive = pd.to_datetime([LEGACY_EXIT, S4_EXIT], utc=True, errors="coerce")
    assert naive.isna().any(), "pandas no longer mis-infers; helper may be simplifiable"
    assert utc_series([LEGACY_EXIT, S4_EXIT]).notna().all()


def test_05_zulu_suffix_supported():
    assert utc_stamp("2026-07-25T09:15:00Z").tzname() == "UTC"


def test_06_explicit_offset_supported():
    assert utc_stamp("2026-07-25T09:15:00+00:00") == pd.Timestamp(S4_EXIT)
    assert utc_stamp("2026-07-25T12:15:00+03:00") == pd.Timestamp(S4_EXIT)


def test_07_nullable_values_stay_null():
    parsed = utc_series([None, "", "   ", S4_EXIT])
    assert list(parsed.isna()) == [True, True, True, False]


# ------------------------------------------------------- 8 invalid handling
@pytest.mark.parametrize("bad", ["not-a-timestamp", "2026-13-45T99:99:99Z", "abc123"])
def test_08_invalid_timestamp_fails_closed(bad):
    """An unparseable value must never masquerade as a valid instant."""
    parsed = utc_stamp(bad)
    assert pd.isna(parsed)
    frame = pd.DataFrame({"exit_timestamp": [bad], "entry_timestamp": [S4_EXIT]})
    assert int(utc_series(frame["exit_timestamp"]).isna().sum()) == 1


# ------------------------------------------------- 9..11 real trade lineage
def _rows_for(view: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    return view[view["timeframe"] == timeframe]


@pytest.mark.parametrize("timeframe", ["M15", "M30"])
def test_09_10_s4_closed_trade_renders_closed(view, timeframe):
    rows = _rows_for(view, timeframe)
    if rows.empty:
        pytest.skip(f"no {timeframe} trade in the canonical view yet")
    parsed = utc_series(rows["exit_timestamp"])
    assert parsed.notna().all(), f"{timeframe} closed trade parsed as unclosed"
    assert (utc_series(rows["entry_timestamp"]) < parsed).all()


def test_11_legacy_trades_remain_valid(view):
    legacy = _rows_for(view, LEGACY_TIMEFRAME)
    assert len(legacy) >= 1
    assert utc_series(legacy["exit_timestamp"]).notna().all()
    assert (legacy["source_book"] == "LEGACY_GLOBAL_PAPER_LEDGER_ARCHIVE").all()


# --------------------------------------------------------- 12..15 invariants
def test_12_no_unclosed_positions_rendered_as_trades(invariants):
    assert invariants["missing_exit_timestamp"] == 0


def test_13_no_future_joins(invariants, view):
    assert invariants["inverted_timestamps"] == 0
    assert invariants["legacy_rows_after_boundary"] == 0
    assert invariants["s4_rows_before_boundary"] == 0


def test_14_every_row_is_a_distinct_closed_trade(view):
    assert not view["visual_trade_id"].duplicated().any()
    entry = utc_series(view["entry_timestamp"])
    exit_ = utc_series(view["exit_timestamp"])
    assert entry.notna().all()
    assert exit_.notna().all()
    assert len(view) == int((exit_ > entry).sum())


def test_15_canonical_economics_unchanged(view, invariants):
    assert invariants["pnl_reconciliation_errors"] == 0
    for _, row in view.iterrows():
        expected = row["gross_pnl"] - row["fees_paid"] - row["slippage_paid"]
        assert row["net_pnl"] == pytest.approx(expected, abs=1e-6)
        assert row["economics_version"] == "CANONICAL_PAPER_TRADE_ECONOMICS_V1"
