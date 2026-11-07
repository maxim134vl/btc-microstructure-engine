"""NEAR_TP_MISS: per-TF closed-bar close when the bar approached TP and did not fill."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests" / "trading") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "trading"))

from btc_ml.trading.near_tp_miss import (  # noqa: E402
    DEFAULT_MISS_BPS,
    NEAR_TP_MISS,
    TIMEFRAMES,
    closed_bar_ohlc,
    miss_bps_from_contract,
    near_tp_miss_settings,
    near_tp_misses,
)
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.proofs import isolated_environment  # noqa: E402
from btc_ml.trading.timeframe_manager import TimeframeManager, with_bar_close  # noqa: E402

from test_s41_live1b_chain_contract import _sources_for  # noqa: E402

TF_BARS = {
    "M15": ("2026-07-01T03:45:00Z", "2026-07-01T04:00:00Z"),
    "M30": ("2026-07-01T03:30:00Z", "2026-07-01T04:00:00Z"),
    "H1": ("2026-07-01T03:00:00Z", "2026-07-01T04:00:00Z"),
    "H4": ("2026-07-01T00:00:00Z", "2026-07-01T04:00:00Z"),
}

LONG_ENTRY = 80_000.0
LONG_TP = 81_200.0
LONG_SL = 79_200.0
SHORT_ENTRY = 80_000.0
SHORT_TP = 78_800.0
SHORT_SL = 80_800.0


def _feed(*, near_tf: str | None, side: str = "LONG") -> pd.DataFrame:
    opens = pd.date_range("2026-07-01T00:00:00Z", periods=16, freq="15min", tz="UTC")
    rows = []
    near_open, near_close = TF_BARS[near_tf] if near_tf else (None, None)
    near_start = pd.Timestamp(near_open) if near_open else None
    near_end = pd.Timestamp(near_close) if near_close else None
    for ts in opens:
        bar_end = ts + pd.Timedelta(minutes=15)
        in_window = (
            near_tf is not None
            and near_start is not None
            and near_end is not None
            and bar_end > near_start
            and bar_end <= near_end
        )
        if in_window and side == "LONG":
            high, low, close = 81_160.0, 80_400.0, 81_050.0
        elif in_window and side == "SHORT":
            high, low, close = 79_600.0, 78_840.0, 78_950.0
        else:
            high, low, close = 80_050.0, 79_950.0, 80_000.0
        rows.append(
            {
                "timestamp": ts,
                "open": 80_000.0,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10.0,
            }
        )
    return with_bar_close(pd.DataFrame(rows))


def _feed_single_wick(m15_open: str, *, side: str = "LONG") -> pd.DataFrame:
    """Near-TP wick on one 15m print only. Other TFs see it only if it sits in their bar."""
    opens = pd.date_range("2026-07-01T00:00:00Z", periods=16, freq="15min", tz="UTC")
    wick_open = pd.Timestamp(m15_open)
    rows = []
    for ts in opens:
        if ts == wick_open and side == "LONG":
            high, low, close = 81_160.0, 80_400.0, 81_050.0
        elif ts == wick_open and side == "SHORT":
            high, low, close = 79_600.0, 78_840.0, 78_950.0
        else:
            high, low, close = 80_050.0, 79_950.0, 80_000.0
        rows.append(
            {
                "timestamp": ts,
                "open": 80_000.0,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10.0,
            }
        )
    return with_bar_close(pd.DataFrame(rows))


def _empty_view() -> dict:
    return {"open_position": None, "open_risk_usd": 0.0}


def _open_view(*, side: str, entry: float, tp: float, sl: float) -> dict:
    return {
        "open_position": {
            "position_id": f"pos_{side.lower()}",
            "direction": side,
            "quantity": 0.1,
            "entry_price": entry,
            "stop_loss_price": sl,
            "take_profit_price": tp,
            "entry_fee_usd": 1.0,
            "status": "OPEN",
            "opened_at": "2026-06-30T12:00:00Z",
        },
        "open_risk_usd": 250.0,
    }


def _views_one(tf: str, *, side: str = "LONG") -> dict[str, dict]:
    views = {name: _empty_view() for name in TIMEFRAMES}
    if side == "LONG":
        views[tf] = _open_view(side="LONG", entry=LONG_ENTRY, tp=LONG_TP, sl=LONG_SL)
    else:
        views[tf] = _open_view(side="SHORT", entry=SHORT_ENTRY, tp=SHORT_TP, sl=SHORT_SL)
    return views


def _ctx(side: str = "LONG") -> dict[str, str]:
    label = "LONG_CONTEXT" if side == "LONG" else "SHORT_CONTEXT"
    return {name: label for name in TIMEFRAMES}


@pytest.mark.s41_chain_contract
def test_contract_miss_bps_is_ten_and_applies_to_every_tf():
    assert miss_bps_from_contract() == DEFAULT_MISS_BPS == 10.0
    settings = near_tp_miss_settings()
    assert settings["enabled"] is True
    assert settings["applies_to"] == TIMEFRAMES


@pytest.mark.s41_chain_contract
@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_filter_long_near_miss_on_each_tf(tf: str):
    assert near_tp_misses(
        side="LONG",
        take_profit_price=LONG_TP,
        bar_high=81_160.0,
        bar_low=80_400.0,
        bar_close=81_050.0,
    )
    ohlc = closed_bar_ohlc(
        _feed(near_tf=tf, side="LONG"),
        bar_open=TF_BARS[tf][0],
        bar_close=TF_BARS[tf][1],
    )
    assert ohlc is not None
    assert ohlc["high"] == pytest.approx(81_160.0)
    assert near_tp_misses(
        side="LONG",
        take_profit_price=LONG_TP,
        bar_high=ohlc["high"],
        bar_low=ohlc["low"],
        bar_close=ohlc["close"],
    )


@pytest.mark.s41_chain_contract
@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_filter_short_near_miss_on_each_tf(tf: str):
    assert near_tp_misses(
        side="SHORT",
        take_profit_price=SHORT_TP,
        bar_high=79_600.0,
        bar_low=78_840.0,
        bar_close=78_950.0,
    )
    ohlc = closed_bar_ohlc(
        _feed(near_tf=tf, side="SHORT"),
        bar_open=TF_BARS[tf][0],
        bar_close=TF_BARS[tf][1],
    )
    assert ohlc is not None
    assert ohlc["low"] == pytest.approx(78_840.0)
    assert near_tp_misses(
        side="SHORT",
        take_profit_price=SHORT_TP,
        bar_high=ohlc["high"],
        bar_low=ohlc["low"],
        bar_close=ohlc["close"],
    )


@pytest.mark.s41_chain_contract
def test_filter_silent_when_far_from_tp_or_tp_printed():
    assert not near_tp_misses(
        side="LONG",
        take_profit_price=LONG_TP,
        bar_high=80_050.0,
        bar_low=79_950.0,
        bar_close=80_000.0,
    )
    assert not near_tp_misses(
        side="LONG",
        take_profit_price=LONG_TP,
        bar_high=LONG_TP,
        bar_low=80_400.0,
        bar_close=81_050.0,
    )
    assert not near_tp_misses(
        side="SHORT",
        take_profit_price=SHORT_TP,
        bar_high=80_050.0,
        bar_low=79_950.0,
        bar_close=80_000.0,
    )
    assert not near_tp_misses(
        side="SHORT",
        take_profit_price=SHORT_TP,
        bar_high=79_600.0,
        bar_low=SHORT_TP,
        bar_close=78_950.0,
    )


@pytest.mark.s41_chain_contract
def test_h4_window_does_not_inherit_a_later_m15_wick():
    """M15 03:45 wick is inside H4 00:00–04:00; that is H4's own bar, not M15 inheritance.

    A *previous* H4 (20:00–00:00) must not see the 03:45 wick.
    """
    feed = _feed(near_tf="M15", side="LONG")
    prior_h4 = closed_bar_ohlc(
        feed,
        bar_open="2026-06-30T20:00:00Z",
        bar_close="2026-07-01T00:00:00Z",
    )
    assert prior_h4 is None or prior_h4["high"] < 81_000.0
    this_h4 = closed_bar_ohlc(
        feed,
        bar_open="2026-07-01T00:00:00Z",
        bar_close="2026-07-01T04:00:00Z",
    )
    assert this_h4 is not None
    assert this_h4["high"] == pytest.approx(81_160.0)


def _run_cycle(tmp_path, monkeypatch, *, tf: str, side: str, near_tf: str | None, views=None):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / f"books_{tf}_{side}")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    monkeypatch.setattr(
        manager,
        "trader_views",
        lambda **_k: views if views is not None else _views_one(tf, side=side),
    )
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=_sources_for(_ctx(side)),
        feed=_feed(near_tf=near_tf, side=side),
        persist=True,
    )
    return cycle, manager, bus


@pytest.mark.s41_chain_contract
@pytest.mark.parametrize("tf", TIMEFRAMES)
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_manager_closes_near_tp_miss_per_tf(tmp_path, monkeypatch, tf: str, side: str):
    cycle, _manager, _bus = _run_cycle(tmp_path, monkeypatch, tf=tf, side=side, near_tf=tf)
    cmd = next(c for c in cycle["commands"] if c["timeframe"] == tf)
    assert cmd["intent"] == "CLOSE"
    assert cmd.get("exit_reason") == NEAR_TP_MISS or NEAR_TP_MISS in json.loads(cmd["reason_codes"])
    same_cycle_open = [
        c
        for c in cycle["commands"]
        if c["timeframe"] == tf and c["intent"] in {"OPEN_LONG", "OPEN_SHORT", "FLIP"}
    ]
    assert same_cycle_open == []


@pytest.mark.s41_chain_contract
@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_manager_holds_when_this_tf_bar_is_not_near_tp(tmp_path, monkeypatch, tf: str):
    cycle, _manager, _bus = _run_cycle(tmp_path, monkeypatch, tf=tf, side="LONG", near_tf=None)
    cmd = next(c for c in cycle["commands"] if c["timeframe"] == tf)
    assert cmd["intent"] == "HOLD"
    assert "NEAR_TP_MISS" not in json.loads(cmd["reason_codes"])


@pytest.mark.s41_chain_contract
def test_m15_near_miss_does_not_close_h4_with_far_tp(tmp_path, monkeypatch):
    views = {name: _empty_view() for name in TIMEFRAMES}
    views["M15"] = _open_view(side="LONG", entry=LONG_ENTRY, tp=LONG_TP, sl=LONG_SL)
    views["H4"] = _open_view(side="LONG", entry=LONG_ENTRY, tp=90_000.0, sl=LONG_SL)
    cycle, _manager, _bus = _run_cycle(
        tmp_path,
        monkeypatch,
        tf="M15",
        side="LONG",
        near_tf="M15",
        views=views,
    )
    m15 = next(c for c in cycle["commands"] if c["timeframe"] == "M15")
    h4 = next(c for c in cycle["commands"] if c["timeframe"] == "H4")
    assert m15["intent"] == "CLOSE"
    assert NEAR_TP_MISS in json.loads(m15["reason_codes"]) or m15.get("exit_reason") == NEAR_TP_MISS
    assert h4["intent"] == "HOLD"


@pytest.mark.s41_chain_contract
def test_h4_does_not_close_on_a_bar_that_ended_before_entry(tmp_path, monkeypatch):
    """Live H4 opened mid-next-bar must not inherit the previous H4 wick."""
    views = {name: _empty_view() for name in TIMEFRAMES}
    views["H4"] = _open_view(side="LONG", entry=LONG_ENTRY, tp=LONG_TP, sl=LONG_SL)
    views["H4"]["open_position"]["opened_at"] = "2026-07-01T04:00:01Z"
    cycle, _manager, _bus = _run_cycle(
        tmp_path,
        monkeypatch,
        tf="H4",
        side="LONG",
        near_tf="H4",
        views=views,
    )
    h4 = next(c for c in cycle["commands"] if c["timeframe"] == "H4")
    assert h4["intent"] == "HOLD"
    assert "NEAR_TP_MISS" not in json.loads(h4["reason_codes"])


def _intents(cycle: dict) -> dict[str, str]:
    return {c["timeframe"]: c["intent"] for c in cycle["commands"]}


def _reasons(cycle: dict, tf: str) -> list[str]:
    cmd = next(c for c in cycle["commands"] if c["timeframe"] == tf)
    return json.loads(cmd["reason_codes"])


@pytest.mark.s41_chain_contract
def test_early_h4_wick_closes_only_h4(tmp_path, monkeypatch):
    """00:00–00:15 wick is inside H4 00:00–04:00 and outside M15/M30/H1 of this cycle."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "h4_own_bar")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    views = {name: _open_view(side="LONG", entry=LONG_ENTRY, tp=LONG_TP, sl=LONG_SL) for name in TIMEFRAMES}
    monkeypatch.setattr(manager, "trader_views", lambda **_k: views)
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=_sources_for(_ctx("LONG")),
        feed=_feed_single_wick("2026-07-01T00:00:00Z", side="LONG"),
        persist=True,
    )
    intents = _intents(cycle)
    assert intents["H4"] == "CLOSE"
    assert NEAR_TP_MISS in _reasons(cycle, "H4")
    assert intents["M15"] == "HOLD"
    assert intents["M30"] == "HOLD"
    assert intents["H1"] == "HOLD"
    assert "NEAR_TP_MISS" not in _reasons(cycle, "M15")
    assert "NEAR_TP_MISS" not in _reasons(cycle, "M30")
    assert "NEAR_TP_MISS" not in _reasons(cycle, "H1")


@pytest.mark.s41_chain_contract
def test_m30_first_half_wick_closes_m30_h1_h4_not_m15(tmp_path, monkeypatch):
    """03:30–03:45 wick sits in M30/H1/H4 closed bars; M15's own bar is 03:45–04:00."""
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "m30_own_bar")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    views = {name: _open_view(side="LONG", entry=LONG_ENTRY, tp=LONG_TP, sl=LONG_SL) for name in TIMEFRAMES}
    monkeypatch.setattr(manager, "trader_views", lambda **_k: views)
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=_sources_for(_ctx("LONG")),
        feed=_feed_single_wick("2026-07-01T03:30:00Z", side="LONG"),
        persist=True,
    )
    intents = _intents(cycle)
    assert intents["M15"] == "HOLD"
    assert "NEAR_TP_MISS" not in _reasons(cycle, "M15")
    for tf in ("M30", "H1", "H4"):
        assert intents[tf] == "CLOSE"
        assert NEAR_TP_MISS in _reasons(cycle, tf)


@pytest.mark.s41_chain_contract
def test_printed_tp_is_take_profit_not_near_tp_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "tp_hit")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    monkeypatch.setattr(manager, "trader_views", lambda **_k: _views_one("M15", side="LONG"))
    feed = _feed(near_tf="M15", side="LONG")
    feed.loc[feed["high"] >= 81_000.0, "high"] = LONG_TP
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=_sources_for(_ctx("LONG")),
        feed=feed,
        persist=True,
    )
    m15 = next(c for c in cycle["commands"] if c["timeframe"] == "M15")
    assert m15["intent"] == "CLOSE"
    reasons = json.loads(m15["reason_codes"])
    assert NEAR_TP_MISS not in reasons
    assert any("TAKE_PROFIT" in r for r in reasons) or "TAKE_PROFIT" in str(m15.get("exit_reason") or "")


@pytest.mark.s41_chain_contract
def test_after_near_tp_miss_later_bar_reopens_canonically(tmp_path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "reopen")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    monkeypatch.setattr(manager, "trader_views", lambda **_k: _views_one("M15", side="LONG"))
    first = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=_sources_for(_ctx("LONG")),
        feed=_feed(near_tf="M15", side="LONG"),
        persist=True,
    )
    m15_close = next(c for c in first["commands"] if c["timeframe"] == "M15")
    assert m15_close["intent"] == "CLOSE"

    monkeypatch.setattr(
        manager,
        "trader_views",
        lambda **_k: {name: _empty_view() for name in TIMEFRAMES},
    )
    later = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:15:00Z",
        sources=_sources_for(
            _ctx("LONG"),
            evaluation="2026-07-01T04:15:00Z",
            m15_bar_open="2026-07-01T04:00:00Z",
            m15_bar_close="2026-07-01T04:15:00Z",
            m15_life_ts="2026-07-01T04:00:00Z",
        ),
        feed=_feed(near_tf=None, side="LONG"),
        persist=True,
    )
    m15_open = next(c for c in later["commands"] if c["timeframe"] == "M15")
    assert m15_open["intent"] == "OPEN_LONG"
    assert "EPISODE_ALREADY_TRADED" not in json.loads(m15_open["reason_codes"])
    assert "HOLD_AFTER_NEAR_TP_MISS" not in json.loads(m15_open["reason_codes"])
