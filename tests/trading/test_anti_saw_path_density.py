"""Path-density saw score: trend vs chop, no bar-count delay."""

from __future__ import annotations

from btc_ml.trading.anti_saw_path_density import (
    BLOCK_REASON,
    PathDensitySawFilter,
    score_bars,
)


def _trend(n: int = 8, start: float = 100.0) -> list[dict]:
    rows = []
    price = start
    for i in range(n):
        nxt = price + 2.0
        rows.append(
            {
                "timestamp": f"2026-09-11T00:{i:02d}:00Z",
                "open": price,
                "low": price - 0.1,
                "high": nxt + 0.1,
                "close": nxt,
            }
        )
        price = nxt
    return rows


def _saw(n: int = 8, start: float = 100.0) -> list[dict]:
    rows = []
    for i in range(n):
        up = i % 2 == 0
        open_ = start
        close = start + 1.5 if up else start - 1.5
        rows.append(
            {
                "timestamp": f"2026-09-11T00:{i:02d}:00Z",
                "open": open_,
                "low": min(open_, close) - 0.1,
                "high": max(open_, close) + 0.1,
                "close": close,
            }
        )
    return rows


def test_trend_is_not_saw() -> None:
    score = score_bars(_trend())
    assert score.is_saw is False
    assert score.reason is None
    assert score.net_over_path > 0.8
    assert score.rotation < 0.3


def test_chop_is_saw() -> None:
    score = score_bars(_saw())
    assert score.is_saw is True
    assert score.reason == BLOCK_REASON
    assert score.balance_support >= 0.55
    assert score.net_over_path <= 0.40
    assert score.path_atr > 0


def test_short_history_fails_open() -> None:
    score = score_bars(_saw(n=2))
    assert score.is_saw is False
    assert score.reason == "INSUFFICIENT_HISTORY"


def test_filter_enforce_blocks_saw() -> None:
    filt = PathDensitySawFilter(
        {"anti_saw_path_density": {"enabled": True, "mode": "enforce"}},
        bars_by_tf={"M15": _saw()},
    )
    decision = filt.evaluate(timeframe="M15")
    assert decision.block is True
    assert decision.reason == BLOCK_REASON


def test_filter_candidate_observes_but_does_not_block() -> None:
    filt = PathDensitySawFilter(
        {"anti_saw_path_density": {"enabled": True, "mode": "candidate"}},
        bars_by_tf={"M15": _saw()},
    )
    decision = filt.evaluate(timeframe="M15")
    assert decision.block is False
    assert decision.score is not None
    assert decision.score.is_saw is True
    assert decision.detail == "candidate_observe"


def test_filter_disabled_or_missing_bars_allows() -> None:
    off = PathDensitySawFilter({"anti_saw_path_density": {"enabled": False}})
    assert off.evaluate(timeframe="M15").block is False
    empty = PathDensitySawFilter(
        {"anti_saw_path_density": {"enabled": True, "mode": "enforce"}},
        bars_by_tf={"M15": []},
    )
    assert empty.evaluate(timeframe="M15").block is False
