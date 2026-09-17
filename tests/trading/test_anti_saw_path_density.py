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
    assert score.path_atr >= 2.0
    assert score.failed_breakouts >= 1


def test_h4_chop_with_thin_path_atr_is_saw() -> None:
    """H4 4-bar window: same saw, path/ATR often < 2. Rejected probes still count."""
    rows = [
        {"timestamp": "2026-09-11T00:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.4},
        {"timestamp": "2026-09-11T04:00:00Z", "open": 100.4, "high": 103.5, "low": 100.0, "close": 100.2},
        {"timestamp": "2026-09-11T08:00:00Z", "open": 100.2, "high": 101.0, "low": 96.5, "close": 100.5},
        {"timestamp": "2026-09-11T12:00:00Z", "open": 100.5, "high": 101.2, "low": 99.4, "close": 100.1},
    ]
    score = score_bars(rows, min_bars=3)
    assert score.path_atr < 2.0
    assert score.failed_breakouts >= 1
    assert score.balance_support >= 0.55
    assert score.is_saw is True


def test_two_sided_volume_confirms_price_chop() -> None:
    rows = _saw()
    for row in rows:
        row["high"] = 104.0
        row["low"] = 96.0
        row["volume"] = 100.0
        row["delta"] = 5.0 if float(row["close"]) > float(row["open"]) else -5.0
    score = score_bars(rows)
    assert score.volume_present is True
    assert score.volume_two_sided >= 0.55
    assert score.is_saw is True


def test_balance_auction_confirms_price_chop() -> None:
    rows = _saw()
    for row in rows:
        row["high"] = 104.0
        row["low"] = 96.0
        row["auction_episode"] = "BALANCE"
    score = score_bars(rows)
    assert score.auction_present is True
    assert score.auction_balance_share >= 0.5
    assert score.is_saw is True


def test_missing_volume_and_auction_fail_open_on_features() -> None:
    score = score_bars(_saw())
    assert score.volume_present is False
    assert score.auction_present is False
    assert score.is_saw is True  # price path still confirms


def test_trend_with_volume_is_not_saw() -> None:
    rows = _trend()
    for row in rows:
        row["volume"] = 80.0
        row["delta"] = 40.0
        row["auction_episode"] = "CONTINUATION"
    score = score_bars(rows)
    assert score.is_saw is False
    assert score.net_over_path > 0.8


def test_tiny_chop_without_atr_churn_is_not_saw() -> None:
    rows = []
    for i in range(8):
        up = i % 2 == 0
        open_ = 100.0
        close = 100.05 if up else 99.95
        rows.append(
            {
                "timestamp": f"2026-09-11T00:{i:02d}:00Z",
                "open": open_,
                "low": 98.0,
                "high": 102.0,
                "close": close,
            }
        )
    score = score_bars(rows)
    assert score.is_saw is False
    assert score.path_atr < 2.0


def test_failed_breakouts_count_rejected_range_probes() -> None:
    from btc_ml.trading.anti_saw_path_density import count_failed_breakouts

    highs = [100.0, 102.0, 101.0, 99.0, 100.5]
    lows = [99.0, 100.0, 99.5, 97.0, 99.0]
    closes = [99.5, 101.5, 100.2, 97.5, 100.0]
    up, down = count_failed_breakouts(highs, lows, closes)
    assert up >= 1
    assert down >= 1


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


def test_manager_open_blocked_on_saw_close_still_fires(tmp_path, monkeypatch):
    import pandas as pd

    from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
    from btc_ml.trading.proofs import build_synthetic_feed, isolated_environment
    from btc_ml.trading.timeframe_manager import TimeframeManager
    from btc_ml.trading.timeframe_state_adapter import TimeframeSources

    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    saw_bars = []
    for i in range(8):
        up = i % 2 == 0
        open_ = 100.0
        close = 101.5 if up else 98.5
        minute = i * 15
        hour = 2 + minute // 60
        minute = minute % 60
        saw_bars.append(
            {
                "timestamp": f"2026-07-01T{hour:02d}:{minute:02d}:00Z",
                "open": open_,
                "low": min(open_, close) - 0.1,
                "high": max(open_, close) + 0.1,
                "close": close,
            }
        )
    saw = PathDensitySawFilter(
        {"anti_saw_path_density": {"enabled": True, "mode": "enforce"}},
        bars_by_tf={"M15": saw_bars, "M30": saw_bars, "H1": saw_bars, "H4": saw_bars},
    )
    manager = TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
        saw_filter=saw,
    )

    def _availability(tf: str) -> dict:
        return {
            "evaluation_timestamp": "2026-07-01T04:00:00Z",
            "timeframe": tf,
            "source_bar_open": "2026-07-01T03:45:00Z",
            "source_bar_close": "2026-07-01T04:00:00Z",
            "source_state_timestamp": "2026-07-01T03:45:00Z",
            "source_event_timestamp": "2026-07-01T03:45:00Z",
            "availability_status": "FRESH_EVENT",
            "availability_reason": "completed_bar_closed_at_or_before_evaluation",
            "is_new_event": True,
            "writer_state": "RUNNING",
        }

    def _life(tf: str, context: str) -> dict:
        return {
            "timestamp": "2026-07-01T03:45:00Z",
            "timeframe": tf,
            "active_market_context": context,
            "lifecycle_state": "ACTIVE",
            "context_episode_id": f"{tf}-ep",
            "active_context_started_at": "2026-07-01T03:45:00Z",
            "context_origin_price": 60500.0,
        }

    sources = TimeframeSources(
        availability=pd.DataFrame([_availability(tf) for tf in ("M15", "M30", "H1", "H4")]),
        lifecycle=pd.DataFrame([_life(tf, "LONG_CONTEXT") for tf in ("M15", "M30", "H1", "H4")]),
        lifecycle_source="parquet",
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=sources,
        feed=build_synthetic_feed(),
        persist=True,
        decision_index={},
    )
    m15 = next(cmd for cmd in cycle["commands"] if cmd["timeframe"] == "M15")
    assert m15["intent"] != "OPEN_LONG"
    assert BLOCK_REASON in str(m15["reason_codes"])
