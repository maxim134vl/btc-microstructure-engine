"""Unit tests for S4.1 LIVE1B-aligned BBO fill."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from btc_ml.trading.s41_live1b_fill import CausalBBO, fill_price_for, resolve_live1b_style_fill


def _write_ticker(tmp_path: Path, *, bid: float, ask: float, recv: str) -> Path:
    root = tmp_path / "book_ticker" / "date=2026-08-15" / "hour=07"
    root.mkdir(parents=True)
    path = root / "book_ticker__start=x__end=y__session=s__batch=00000001.parquet"
    pd.DataFrame(
        [
            {
                "best_bid_price": bid,
                "best_ask_price": ask,
                "local_receive_timestamp": recv,
                "local_receive_monotonic_ns": 1,
                "update_id": 42,
            }
        ]
    ).to_parquet(path)
    return path


def test_live1b_long_entry_is_ask_not_origin(tmp_path: Path):
    now = datetime(2026, 8, 15, 7, 53, 25, tzinfo=timezone.utc)
    _write_ticker(tmp_path, bid=100.0, ask=100.2, recv="2026-08-15T07:53:24.500000Z")
    fill = resolve_live1b_style_fill(
        side="LONG",
        action="ENTRY",
        book_ticker_root=tmp_path / "book_ticker",
        now=now,
        max_age_ms=5_000.0,
    )
    assert fill.available
    assert fill.price == 100.2
    assert fill.source == "execution_market_bbo"
    assert fill.timestamp is not None
    # Not next-candle close semantics: timestamp is execution now, not bar close.
    assert "07:53" in fill.timestamp or fill.timestamp.endswith("Z")


def test_live1b_long_exit_is_bid(tmp_path: Path):
    now = datetime(2026, 8, 15, 7, 53, 25, tzinfo=timezone.utc)
    _write_ticker(tmp_path, bid=99.5, ask=99.6, recv="2026-08-15T07:53:24.500000Z")
    fill = resolve_live1b_style_fill(
        side="LONG",
        action="EXIT",
        book_ticker_root=tmp_path / "book_ticker",
        now=now,
        max_age_ms=5_000.0,
    )
    assert fill.available
    assert fill.price == 99.5


def test_stale_bbo_blocks(tmp_path: Path):
    now = datetime(2026, 8, 15, 7, 53, 25, tzinfo=timezone.utc)
    _write_ticker(tmp_path, bid=100.0, ask=100.2, recv="2026-08-15T07:50:00Z")
    fill = resolve_live1b_style_fill(
        side="LONG",
        action="ENTRY",
        book_ticker_root=tmp_path / "book_ticker",
        now=now,
        max_age_ms=2_000.0,
    )
    assert not fill.available
    assert fill.reason == "ENTRY_BLOCKED_STALE_BBO"


def test_fill_price_for_policy_matches_live1b():
    bbo = CausalBBO("id", 10.0, 10.5, "t", 1)
    assert fill_price_for(side="LONG", action="ENTRY", bbo=bbo) == 10.5
    assert fill_price_for(side="LONG", action="EXIT", bbo=bbo) == 10.0
    assert fill_price_for(side="SHORT", action="ENTRY", bbo=bbo) == 10.0
    assert fill_price_for(side="SHORT", action="EXIT", bbo=bbo) == 10.5
