"""Lock the M15 14–15 Sep closed-bar flatten tape (bug book B-M15-03)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_m15_sep14_closed_bar_would_flatten_held_longs():
    from scripts.audit.replay_m15_sep14_closed_bar_exit import simulate, _seed_lifecycle

    tape, _sim = simulate(_seed_lifecycle())
    flatten = {
        (row["bar_open"], row["actual"])
        for row in tape
        if row["closed_bar_would_flatten"]
    }
    assert ("2026-09-14T20:45:00Z", "M15_2") in flatten
    assert ("2026-09-14T23:00:00Z", "M15_4") in flatten
    assert ("2026-09-15T06:15:00Z", "M15_7") in flatten
    assert ("2026-09-14T18:00:00Z", "M15_1") not in flatten


def test_m15_bug_book_exists():
    path = ROOT / "docs" / "audit" / "M15_BUG_BOOK_20260914.md"
    text = path.read_text(encoding="utf-8")
    assert "B-M15-03" in text
    assert "test_open_long_closes_on_closed_bar_short_even_if_forming_still_long" in text
