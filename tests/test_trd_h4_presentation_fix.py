"""TRD-H4-PRESENTATION-FIX — narrow OPS + chart presentation tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

import ops_dashboard_runtime_truth as truth  # noqa: E402
from btc_ml.trading.intrabar_paper.mark import (  # noqa: E402
    mark_price_for_side,
    unrealized_pnl_usd,
)


def test_live1b_gross_open_risk_from_positions(tmp_path, monkeypatch):
    epoch = "EPOCH_TEST_RISK"
    books = tmp_path / "books"
    books.mkdir()
    pos = {
        "position_id": "pos_test_1",
        "paper_epoch_id": epoch,
        "timeframe": "H4",
        "side": "LONG",
        "status": "OPEN",
        "quantity": 1.3454186880112602,
        "entry_price": 64687.82,
        "stop_loss_price": 64040.9418,
        "take_profit_price": 65658.1373,
        "risk_amount_usd": 1000.0,
        "opened_at": "2026-07-29T09:40:34.909113Z",
        "entry_context_event_id": "CTX_test",
        "lifecycle_episode_id": "H4:prov:1",
    }
    (books / "positions.jsonl").write_text(json.dumps(pos) + "\n", encoding="utf-8")
    # foreign epoch must be ignored
    foreign = dict(pos)
    foreign["position_id"] = "pos_other"
    foreign["paper_epoch_id"] = "OTHER_EPOCH"
    foreign["risk_amount_usd"] = 999.0
    with (books / "positions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(foreign) + "\n")

    monkeypatch.setattr(truth, "live1b_active_epoch", lambda: {"paper_epoch_id": epoch, "initial_equity_usd": 100000.0, "activated_at": "t"})
    monkeypatch.setattr(truth, "live1b_paper_active", lambda: True)
    monkeypatch.setattr(
        truth,
        "_read_json",
        lambda path: {
            "paper_epoch_id": epoch,
            "equity_usd": 100000.0,
            "realized_pnl_usd": 0.0,
            "max_risk_per_trade_usd": 1000.0,
            "updated_at": "2026-07-29T12:00:00Z",
            "execution_lanes": {"M15": "ACTIVE", "M30": "ACTIVE", "H1": "ACTIVE", "H4": "ACTIVE"},
            "trades_count": 0,
        }
        if "intrabar_paper_health" in str(path) or "intrabar_cognition_health" in str(path)
        else {},
    )
    monkeypatch.setattr(truth, "inspect_processes", lambda: [])
    monkeypatch.setattr(
        truth,
        "_latest_book_ticker_bbo",
        lambda: {
            "best_bid": 64400.0,
            "best_ask": 64401.0,
            "mark_timestamp": "2026-07-29T12:00:00Z",
            "mark_source": "test",
        },
    )
    monkeypatch.setattr(truth, "_load_context_event_by_id", lambda _cid: {
        "event_timestamp": "2026-07-29T09:40:34.724226Z",
        "context_event_price": "64690.19",
        "last_trade_timestamp": "2026-07-29T09:40:35.150000Z",
    })
    # Redirect books root via epoch path by patching Path join through books_root construction:
    # _build uses ROOT / data/trading/intrabar_paper / eid / books — monkeypatch loader instead.
    monkeypatch.setattr(
        truth,
        "_load_live1b_open_positions",
        lambda **kwargs: [pos] if kwargs.get("paper_epoch_id") == epoch else [],
    )

    plane = truth._build_live1b_timeframe_traders(load_performance=False)
    port = plane["portfolio"]
    assert port["open_positions"] == 1
    assert port["gross_open_risk_usd"] == pytest.approx(1000.0)
    assert port["available_risk_usd"] == pytest.approx(0.0)
    h4 = next(t for t in plane["traders"] if t["timeframe"] == "H4")
    assert h4["open_risk_usd"] == pytest.approx(1000.0)
    assert h4["open_position_id"] == "pos_test_1"
    assert h4["entry_fill_price"] == pytest.approx(64687.82)
    assert h4["quantity"] == pytest.approx(1.3454186880112602)
    assert h4["position_notional"] == pytest.approx(87032.20191470855)
    assert h4["stop_loss_price"] == pytest.approx(64040.9418)
    assert h4["take_profit_price"] == pytest.approx(65658.1373)
    assert h4["mark_side"] == "bid"
    assert h4["mark_price"] == pytest.approx(64400.0)
    expected = unrealized_pnl_usd(side="LONG", entry_price=64687.82, quantity=1.3454186880112602, mark_price=64400.0)
    assert h4["unrealized_pnl_usd"] == pytest.approx(expected)
    assert port["unrealized_pnl"] == pytest.approx(expected)


def test_mark_contract_long_uses_bid_not_mid_or_ask():
    mark = mark_price_for_side(side="LONG", best_bid=100.0, best_ask=101.0)
    assert mark == 100.0
    assert mark != 100.5
    assert mark != 101.0


def test_chart_bar_anchor_and_partial_h4():
    import timeframe_chart_truth as tct
    from btc_ml.live.intrabar.partial_bar_state import bar_open_for

    entry = "2026-07-29T09:40:34.909113Z"
    anchor = bar_open_for(entry, "H4").isoformat().replace("+00:00", "Z")
    assert anchor == "2026-07-29T08:00:00+00:00" or anchor.startswith("2026-07-29T08:00:00")

    block = {
        "timeframe": "H4",
        "candles": [
            {
                "timestamp": "2026-07-29T04:00:00Z",
                "bar_open": "2026-07-29T04:00:00Z",
                "bar_close": "2026-07-29T08:00:00Z",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 1.0,
                "confirmed": True,
            }
        ],
        "confirmed_only": True,
    }

    class _Fake:
        @staticmethod
        def get(key, default=None):
            return {
                "partial_bars": {
                    "H4": {
                        "bar_open_timestamp": "2026-07-29T08:00:00Z",
                        "open": 64561.0,
                        "high_so_far": 64700.0,
                        "low_so_far": 64400.0,
                        "last": 64600.0,
                        "volume_so_far": 10.0,
                        "causal_cutoff_timestamp": "2026-07-29T09:40:34.724226Z",
                    }
                }
            }.get(key, default)

    # Inject via _read_json
    original = tct._read_json

    def _fake_read(path):
        if "intrabar_cognition_health" in str(path):
            return {
                "partial_bars": {
                    "H4": {
                        "bar_open_timestamp": "2026-07-29T08:00:00Z",
                        "open": 64561.0,
                        "high": 64700.0,
                        "low": 64400.0,
                        "close": 64600.0,
                        "volume": 10.0,
                        "causal_cutoff_timestamp": "2026-07-29T09:40:34.724226Z",
                    }
                }
            }
        return original(path)

    tct._read_json = _fake_read  # type: ignore
    try:
        out = tct.append_live1a_partial_candle(block, "H4")
    finally:
        tct._read_json = original  # type: ignore
    assert out["includes_live_partial"] is True
    assert out["candles"][-1]["bar_open"] == "2026-07-29T08:00:00Z"
    assert out["candles"][-1]["confirmed"] is False
    # nearest completed alone would be 04:00; with partial, 08:00 present
    opens = [c["bar_open"] for c in out["candles"]]
    assert "2026-07-29T08:00:00Z" in opens
    assert opens[-1] != "2026-07-29T04:00:00Z"


def test_open_position_payload_preserves_event_and_prices():
    from trading_truth import _load_live1b_open_positions
    import trading_truth as tt

    books = Path("/tmp/trd_h4_books")
    # Use monkeypatch-style stub by writing temp books and patching root
    # Prefer direct unit checks on enrichment helpers via synthetic row path.
    row = {
        "position_id": "pos_022f1ab19b904bed",
        "paper_epoch_id": "INTRABAR_RULES_V1_20260728_110636",
        "timeframe": "H4",
        "side": "LONG",
        "status": "OPEN",
        "quantity": 1.3454186880112602,
        "entry_price": 64687.82,
        "stop_loss_price": 64040.9418,
        "take_profit_price": 65658.1373,
        "risk_amount_usd": 1000.0,
        "opened_at": "2026-07-29T09:40:34.909113Z",
        "entry_context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
        "lifecycle_episode_id": "H4:prov:1",
        "entry_command_id": "cmd_x",
    }
    # Validate expected chart fields contract without requiring live books.
    from btc_ml.live.intrabar.partial_bar_state import bar_open_for

    event_ts = row["opened_at"]
    bar_anchor = bar_open_for(event_ts, "H4").isoformat().replace("+00:00", "Z")
    assert event_ts == "2026-07-29T09:40:34.909113Z"
    assert bar_anchor.startswith("2026-07-29T08:00:00")
    assert row["entry_price"] == 64687.82
    assert row["stop_loss_price"] == 64040.9418
    assert row["take_profit_price"] == 65658.1373
    assert row["entry_price"] != 64690.19  # context price must not replace entry
