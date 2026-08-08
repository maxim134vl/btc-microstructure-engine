"""Targeted contract tests for the observe-only STP_BE33 policy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics
from btc_ml.trading.shadow_structural_protection.be33 import (
    STATE_BE_PROTECTED,
    STATE_CLOSED,
    STATE_CLOSED_WITHOUT_PARTIAL,
    StpBe33Engine,
    partial_trigger_price,
    solve_economic_break_even,
)

SOURCE_REPO = Path(__file__).resolve().parents[1]
EPOCH = "TEST_STP_BE33_EPOCH"
EFFECTIVE_AT = "2026-08-08T00:00:00Z"


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(
        SOURCE_REPO / "config/intrabar_paper_execution.json",
        root / "config/intrabar_paper_execution.json",
    )
    epochs = root / "data/trading/paper_epochs"
    epochs.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps({"paper_epoch_id": EPOCH, "paper_only": True, "real_execution_enabled": False}) + "\n",
        encoding="utf-8",
    )
    epoch_root = root / "data/trading/intrabar_paper" / EPOCH
    books = epoch_root / "books"
    books.mkdir(parents=True)
    for table in ("signals", "commands", "orders", "fills", "positions", "trades"):
        (books / f"{table}.jsonl").write_text("", encoding="utf-8")
    wal = epoch_root / "execution_market_wal"
    wal.mkdir(parents=True)
    (wal / "events.jsonl").write_text("", encoding="utf-8")
    return root


def _position(
    repo: Path,
    *,
    position_id: str = "pos1",
    side: str = "LONG",
    entry: float = 100.0,
    stop: float | None = None,
    take: float | None = None,
    quantity: float = 3.0,
    opened_at: str = "2026-08-08T00:01:00Z",
) -> dict:
    stop = stop if stop is not None else (90.0 if side == "LONG" else 110.0)
    take = take if take is not None else (130.0 if side == "LONG" else 70.0)
    row = {
        "position_id": position_id,
        "status": "OPEN",
        "timeframe": "M15",
        "side": side,
        "quantity": quantity,
        "entry_price": entry,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "opened_at": opened_at,
        "entry_context_event_id": f"ctx_{position_id}",
        "lifecycle_episode_id": f"episode_{position_id}",
        "risk_amount_usd": 1000.0,
    }
    _append(repo / f"data/trading/intrabar_paper/{EPOCH}/books/positions.jsonl", row)
    return row


def _agg(repo: Path, *, offset: int, agg_id: int, price: float, timestamp: str) -> None:
    _append(
        repo / f"data/trading/intrabar_paper/{EPOCH}/execution_market_wal/events.jsonl",
        {
            "schema_version": "execution_market_wal_v1",
            "paper_epoch_id": EPOCH,
            "event_type": "AGG_TRADE",
            "source": "BINANCE_FUTURES",
            "symbol": "BTCUSDT",
            "wal_offset": offset,
            "aggregate_trade_id": agg_id,
            "source_event_id": f"agg_{agg_id}",
            "exchange_trade_timestamp": timestamp,
            "local_receive_timestamp": timestamp,
            "price": str(price),
            "quantity": "0.01",
        },
    )


def _engine(repo: Path) -> StpBe33Engine:
    return StpBe33Engine(repo=repo, epoch_id=EPOCH, policy_effective_at=EFFECTIVE_AT)


def _opened(repo: Path, **kwargs) -> StpBe33Engine:
    _position(repo, **kwargs)
    engine = _engine(repo)
    engine.poll_once()
    return engine


def _partial_events(engine: StpBe33Engine) -> list[dict]:
    return [
        row
        for row in engine.store.read_jsonl(engine.store.events_path)
        if row.get("event_type") == "STP_BE33_STOP_MOVED"
    ]


def test_01_long_trigger_occurs_at_one_third_exactly_once(repo: Path) -> None:
    engine = _opened(repo, side="LONG", entry=100.0, take=130.0)
    assert engine.states["pos1"]["partial_trigger_price"] == 110.0
    _agg(repo, offset=1, agg_id=101, price=109.9, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    assert engine.states["pos1"]["partial_taken"] is False
    _agg(repo, offset=2, agg_id=102, price=110.0, timestamp="2026-08-08T00:03:00Z")
    engine.poll_once()
    engine.poll_once()
    assert engine.states["pos1"]["state"] == STATE_BE_PROTECTED
    assert len(_partial_events(engine)) == 1


def test_02_short_trigger_is_symmetric(repo: Path) -> None:
    engine = _opened(repo, side="SHORT", entry=100.0, take=70.0)
    assert engine.states["pos1"]["partial_trigger_price"] == 90.0
    _agg(repo, offset=1, agg_id=201, price=90.1, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    assert engine.states["pos1"]["partial_taken"] is False
    _agg(repo, offset=2, agg_id=202, price=90.0, timestamp="2026-08-08T00:03:00Z")
    engine.poll_once()
    assert engine.states["pos1"]["state"] == STATE_BE_PROTECTED


def test_03_partial_quantity_is_one_and_remaining_is_two(repo: Path) -> None:
    engine = _opened(repo, quantity=3.0)
    _agg(repo, offset=1, agg_id=301, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["partial_quantity"] == pytest.approx(1.0)
    assert state["remaining_quantity"] == pytest.approx(2.0)
    assert state["partial_quantity"] + state["remaining_quantity"] == pytest.approx(3.0)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_04_05_economic_break_even_uses_canonical_cost_model(repo: Path, side: str) -> None:
    cfg = load_intrabar_paper_config(repo_root=repo)
    price, result = solve_economic_break_even(
        cfg=cfg,
        side=side,
        entry_price=100.0,
        quantity=2.0,
        risk_amount_usd=666.6666666667,
    )
    assert abs(result["net_pnl_usd"]) < 1e-7
    assert price > 100.0 if side == "LONG" else price < 100.0
    check = closed_trade_economics(
        cfg=cfg,
        side=side,
        entry_price=100.0,
        exit_price=price,
        quantity=2.0,
        risk_amount_usd=666.6666666667,
        exit_reason="SL",
    )
    assert abs(check["net_pnl_usd"]) < 1e-7


def test_06_trigger_provenance_is_durable_wal_lineage(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=7, agg_id=777, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["partial_trigger_agg_trade_id"] == 777
    assert state["partial_trigger_source_event_id"] == "agg_777"
    assert state["partial_trigger_wal_offset"] == 7
    assert state["partial_trigger_timestamp"] == "2026-08-08T00:02:00Z"


def test_07_duplicate_agg_trade_never_repeats_partial(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=701, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    _agg(repo, offset=2, agg_id=701, price=111.0, timestamp="2026-08-08T00:03:00Z")
    engine.poll_once()
    assert len(_partial_events(engine)) == 1
    assert engine.states["pos1"]["remaining_quantity"] == pytest.approx(2.0)


def test_08_crash_replay_restores_partial_without_second_reduction(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=801, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    events_before = engine.store.events_path.read_bytes()
    restarted = _engine(repo)
    restarted.poll_once()
    assert restarted.states["pos1"]["state"] == STATE_BE_PROTECTED
    assert restarted.states["pos1"]["remaining_quantity"] == pytest.approx(2.0)
    assert restarted.store.events_path.read_bytes() == events_before
    assert len(_partial_events(restarted)) == 1


def test_09_canonical_context_exit_before_partial_closes_without_partial(repo: Path) -> None:
    engine = _opened(repo)
    _append(
        repo / f"data/trading/intrabar_paper/{EPOCH}/books/trades.jsonl",
        {
            "trade_id": "trade1",
            "position_id": "pos1",
            "status": "CLOSED",
            "exit_reason": "CONTEXT_END",
            "exit_price": 105.0,
            "exit_ts": "2026-08-08T00:05:00Z",
            "net_pnl_usd": 10.0,
        },
    )
    engine.poll_once()
    assert engine.states["pos1"]["state"] == STATE_CLOSED_WITHOUT_PARTIAL
    assert engine.states["pos1"]["partial_taken"] is False


def test_10_original_stop_before_partial_closes_full_quantity(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=1001, price=90.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["state"] == STATE_CLOSED_WITHOUT_PARTIAL
    assert state["final_exit_reason"] == "SL"


def test_11_economic_be_stop_closes_remaining_once(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=1101, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    be_price = engine.states["pos1"]["economic_break_even_price"]
    _agg(repo, offset=2, agg_id=1102, price=be_price, timestamp="2026-08-08T00:03:00Z")
    engine.poll_once()
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["state"] == STATE_CLOSED
    assert state["final_exit_reason"] == "BE_STOP"
    assert len(engine.store.read_jsonl(engine.store.outcomes_path)) == 1


def test_12_tp_after_partial_closes_remaining_at_original_tp(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=1201, price=110.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    _agg(repo, offset=2, agg_id=1202, price=130.0, timestamp="2026-08-08T00:03:00Z")
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["state"] == STATE_CLOSED
    assert state["final_exit_reason"] == "TP"
    assert state["final_exit_price"] == 130.0


def test_13_canonical_books_and_pre_effective_h4_are_untouched(repo: Path) -> None:
    _position(
        repo,
        position_id="current_h4",
        side="LONG",
        opened_at="2026-08-07T06:27:01Z",
    )
    books = repo / f"data/trading/intrabar_paper/{EPOCH}/books"
    before = {path.name: path.read_bytes() for path in books.glob("*.jsonl")}
    engine = _engine(repo)
    engine.poll_once()
    after = {path.name: path.read_bytes() for path in books.glob("*.jsonl")}
    assert before == after
    assert "current_h4" not in engine.states
    assert engine.write_health()["canonical_write_capability"] is False
    assert engine.write_health()["live1b_command_capability"] is False
    assert engine.write_health()["real_execution_capability"] is False


def test_14_late_canonical_close_appends_comparison_without_replacing_outcome(repo: Path) -> None:
    engine = _opened(repo)
    _agg(repo, offset=1, agg_id=1401, price=90.0, timestamp="2026-08-08T00:02:00Z")
    engine.poll_once()
    assert engine.states["pos1"]["canonical_net_pnl_usd"] is None
    _append(
        repo / f"data/trading/intrabar_paper/{EPOCH}/books/trades.jsonl",
        {
            "trade_id": "canonical_late",
            "position_id": "pos1",
            "status": "CLOSED",
            "exit_reason": "CONTEXT_END",
            "exit_price": 95.0,
            "exit_ts": "2026-08-08T00:05:00Z",
            "net_pnl_usd": -20.0,
        },
    )
    engine.poll_once()
    state = engine.states["pos1"]
    assert state["canonical_net_pnl_usd"] == -20.0
    assert state["net_difference_vs_canonical_usd"] == pytest.approx(state["total_net_pnl_usd"] + 20.0)
    outcomes = engine.store.read_jsonl(engine.store.outcomes_path)
    assert len(outcomes) == 2
    assert outcomes[-1]["outcome_id"].endswith("CANONICAL_COMPARISON")
    assert engine.metrics()["total_net_pnl_stp_be33"] == pytest.approx(state["total_net_pnl_usd"])


def test_formula_examples_are_exact() -> None:
    assert partial_trigger_price(side="LONG", entry_price=100.0, take_price=130.0) == 110.0
    assert partial_trigger_price(side="SHORT", entry_price=100.0, take_price=70.0) == 90.0
