"""S4.1 — manager and independent timeframe traders (46 required checks).

Paper only. No exchange clients, no real execution, no production writes: every
test that executes commands runs on an isolated throwaway book.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import activation, proofs  # noqa: E402
from btc_ml.trading.command_bus import COMMAND_COLUMNS, VALID_INTENTS, CommandBus, CommandBusPaths  # noqa: E402
from btc_ml.trading.paper_core import closed_trade_economics, economics, legacy_controller  # noqa: E402
from btc_ml.trading.paper_trader_engine import PaperTraderEngine  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.timeframe_manager import TimeframeManager  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import (  # noqa: E402
    SUPPORTED_TIMEFRAMES,
    UNSUPPORTED_TIMEFRAMES,
    TimeframeSources,
    resolve_all_states,
    resolve_timeframe_state,
)
from btc_ml.trading.timeframe_trader import TimeframeTrader  # noqa: E402
from btc_ml.trading.trader_book import TraderBook  # noqa: E402

TRADING_PACKAGE = ROOT / "src" / "btc_ml" / "trading"
BASELINE_PRESERVATION = ROOT / "data" / "research" / "s4_1_preservation_baseline.json"


# --------------------------------------------------------------------------- #
# synthetic point-in-time sources
# --------------------------------------------------------------------------- #
def availability_rows(evaluation: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "evaluation_timestamp": evaluation,
                "timeframe": "M15",
                "source_bar_open": "2026-07-01T03:45:00Z",
                "source_bar_close": "2026-07-01T04:00:00Z",
                "source_state_timestamp": "2026-07-01T03:45:00Z",
                "source_event_timestamp": "2026-07-01T03:45:00Z",
                "availability_status": "FRESH_EVENT",
                "availability_reason": "completed_bar_closed_at_or_before_evaluation",
                "is_new_event": True,
                "writer_state": "RUNNING",
            },
            {
                "evaluation_timestamp": evaluation,
                "timeframe": "M30",
                "source_bar_open": "2026-07-01T03:30:00Z",
                "source_bar_close": "2026-07-01T04:00:00Z",
                "source_state_timestamp": "2026-07-01T03:30:00Z",
                "source_event_timestamp": "2026-07-01T03:30:00Z",
                "availability_status": "NO_EVENT_STATE_UNCHANGED",
                "availability_reason": "state_unchanged",
                "is_new_event": False,
                "writer_state": "EVENT_DRIVEN",
            },
            {
                "evaluation_timestamp": evaluation,
                "timeframe": "H1",
                "source_bar_open": "2026-07-01T02:00:00Z",
                "source_bar_close": "2026-07-01T03:00:00Z",
                "source_state_timestamp": "2026-07-01T02:00:00Z",
                "source_event_timestamp": "2026-07-01T02:00:00Z",
                "availability_status": "AVAILABLE_LAST_CONFIRMED",
                "availability_reason": "last_completed_bar_available",
                "is_new_event": False,
                "writer_state": "EVENT_DRIVEN",
            },
            {
                "evaluation_timestamp": evaluation,
                "timeframe": "H4",
                "source_bar_open": "2026-07-01T04:00:00Z",
                "source_bar_close": "2026-07-01T08:00:00Z",
                "source_state_timestamp": "2026-07-01T04:00:00Z",
                "source_event_timestamp": "2026-07-01T04:00:00Z",
                "availability_status": "FRESH_EVENT",
                "availability_reason": "bar_still_forming",
                "is_new_event": True,
                "writer_state": "EVENT_DRIVEN",
            },
        ]
    )


def lifecycle_rows() -> pd.DataFrame:
    """LONG at 04:00 (M15/M30 clock), SHORT at 03:00 (H1 clock)."""
    return pd.DataFrame(
        [
            {
                "timestamp": "2026-07-01T02:45:00Z",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 11,
                "invalidation_reason": None,
                "active_context_started_at": "2026-07-01T02:00:00Z",
                "context_origin_price": 60000.0,
            },
            {
                "timestamp": "2026-07-01T03:45:00Z",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 12,
                "invalidation_reason": None,
                "active_context_started_at": "2026-07-01T03:30:00Z",
                "context_origin_price": 60500.0,
            },
            {
                "timestamp": "2026-07-01T05:00:00Z",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "INVALIDATED",
                "context_episode_id": 13,
                "invalidation_reason": "FUTURE_ROW_MUST_NOT_LEAK",
                "active_context_started_at": "2026-07-01T05:00:00Z",
                "context_origin_price": 61000.0,
            },
        ]
    )


def synthetic_sources() -> TimeframeSources:
    return TimeframeSources(
        availability=availability_rows("2026-07-01T04:00:00Z"),
        lifecycle=lifecycle_rows(),
        synthesis=pd.DataFrame(
            [
                {
                    "timestamp": "2026-07-01T03:45:00Z",
                    "synthesis_state": "CONTINUATION",
                    "persistence_score": 0.5,
                    "alignment_score": 0.5,
                    "structural_rank": "MEDIUM",
                    "location_bias": "UPPER_ABSORPTION",
                }
            ]
        ),
    )


@pytest.fixture()
def states() -> dict[str, dict]:
    return resolve_all_states(evaluation_timestamp="2026-07-01T04:00:00Z", sources=synthetic_sources())


@pytest.fixture()
def isolated(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    return bus, books, traders, proofs.build_synthetic_feed()


# --------------------------------------------------------------------------- #
# 1-5: manager produces four independent outputs from own-timeframe state
# --------------------------------------------------------------------------- #
def test_01_manager_creates_four_independent_outputs(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=True,
    )
    timeframes = [command["timeframe"] for command in cycle["commands"]]
    assert timeframes == list(SUPPORTED_TIMEFRAMES)
    assert len({command["command_id"] for command in cycle["commands"]}) == 4
    assert all(command["intent"] in VALID_INTENTS for command in cycle["commands"])
    assert all(command["reason_codes"] for command in cycle["commands"])


def test_02_m15_reads_only_m15_state(states):
    assert states["M15"]["source_bar_close"] == "2026-07-01T04:00:00Z"
    assert states["M15"]["source_state_timestamp"] == "2026-07-01T03:45:00Z"
    assert states["M15"]["timeframe_direction"] == "LONG"


def test_03_m30_reads_only_m30_state(states):
    assert states["M30"]["source_state_timestamp"] == "2026-07-01T03:30:00Z"
    assert states["M30"]["availability_status"] == "NO_EVENT_STATE_UNCHANGED"
    assert states["M30"]["timeframe_direction"] == "LONG"


def test_04_h1_reads_only_h1_state(states):
    assert states["H1"]["source_bar_close"] == "2026-07-01T03:00:00Z"
    assert states["H1"]["timeframe_direction"] == "SHORT"
    assert states["H1"]["lifecycle_episode_id"] == "H1:11"


def test_05_h4_reads_only_h4_state(states):
    assert states["H4"]["availability_status"] == "FRESH_EVENT"
    assert states["H4"]["no_action_reason"] == "UNCLOSED_BAR_REJECTED"


# --------------------------------------------------------------------------- #
# 6-10: timeframe availability contract
# --------------------------------------------------------------------------- #
def test_06_d1_trader_absent():
    assert "D1" in UNSUPPORTED_TIMEFRAMES
    assert "D1" not in SUPPORTED_TIMEFRAMES
    risk = PortfolioRiskCoordinator.load()
    assert "D1" not in risk.weights
    daemon = (ROOT / "scripts" / "live" / "timeframe_trader_daemon.py").read_text(encoding="utf-8")
    assert "UNSUPPORTED_TIMEFRAMES" in daemon
    state = resolve_timeframe_state(
        timeframe="D1", evaluation_timestamp="2026-07-01T04:00:00Z", sources=synthetic_sources()
    )
    assert state["availability_status"] == "TIMEFRAME_NOT_LIVE"
    assert state["availability_reason"] == "NO_LIVE_STAGE2_WRITER"
    assert state["actionable"] is False


def test_07_no_cross_timeframe_fallback(states):
    assert states["M15"]["timeframe_direction"] != states["H1"]["timeframe_direction"]
    assert states["M15"]["lifecycle_episode_id"] != states["H1"]["lifecycle_episode_id"]
    for timeframe, state in states.items():
        assert state["lifecycle_episode_id"] in (None,) or state["lifecycle_episode_id"].startswith(f"{timeframe}:")


def test_08_event_sparse_state_remains_available(states):
    m30 = states["M30"]
    assert m30["is_new_event"] is False
    assert m30["actionable"] is True
    assert m30["no_action_reason"] is None


def test_09_incomplete_bar_rejected(states):
    assert states["H4"]["no_action_reason"] == "UNCLOSED_BAR_REJECTED"
    assert states["H4"]["timeframe_state"] == "WAITING_FOR_BAR_CLOSE"
    assert states["H4"]["actionable"] is False


def test_10_future_state_rejected(states):
    # the 05:00 lifecycle row (SHORT/INVALIDATED) must never leak backwards
    for state in states.values():
        assert state["invalidation_reason"] != "FUTURE_ROW_MUST_NOT_LEAK" if state.get("invalidation_reason") else True
        if state["lifecycle_row_timestamp"]:
            assert pd.Timestamp(state["lifecycle_row_timestamp"]) <= pd.Timestamp(state["source_bar_close"])
    empty = resolve_timeframe_state(
        timeframe="M15",
        evaluation_timestamp="2026-07-01T00:00:00Z",
        sources=synthetic_sources(),
    )
    assert empty["no_action_reason"] == "NO_AVAILABILITY_ROW_AT_OR_BEFORE_EVALUATION"


# --------------------------------------------------------------------------- #
# 11-13: command contract
# --------------------------------------------------------------------------- #
def test_11_deterministic_command_id(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    kwargs = dict(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=False,
    )
    first = manager.run_cycle(**kwargs)
    second = manager.run_cycle(**kwargs)
    assert [c["command_id"] for c in first["commands"]] == [c["command_id"] for c in second["commands"]]
    for command in first["commands"]:
        assert set(command.keys()) == set(COMMAND_COLUMNS)


def test_12_duplicate_manager_cycle_idempotent(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    kwargs = dict(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=True,
    )
    first = manager.run_cycle(**kwargs)
    second = manager.run_cycle(**kwargs)
    assert first["append_result"]["appended"] == 4
    assert second["append_result"]["appended"] == 0
    assert second["append_result"]["duplicates_rejected"] == 4
    frame = bus.frame()
    assert len(frame) == 4
    assert frame["command_id"].nunique() == 4


def test_13_trader_reads_only_own_commands(isolated):
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            ),
            proofs.synthetic_command(
                timeframe="H1", intent="OPEN_SHORT", evaluation_timestamp="2026-07-01T01:00:00Z"
            ),
        ]
    )
    pending = traders["M15"].pending_commands()
    assert [command["timeframe"] for command in pending] == ["M15"]
    cycle_feed = proofs.visible_feed(feed, "2026-07-01T01:15:00Z")
    traders["M15"].run_once(feed=cycle_feed)
    assert len(books["M15"].positions_frame()) == 1
    assert len(books["H1"].positions_frame()) == 0
    assert len(books["M30"].positions_frame()) == 0


# --------------------------------------------------------------------------- #
# 14-15: independent lifecycle
# --------------------------------------------------------------------------- #
def test_14_independent_lifecycle_episodes(states):
    episodes = {timeframe: state["lifecycle_episode_id"] for timeframe, state in states.items()}
    assert episodes["M15"] == "M15:12"
    assert episodes["H1"] == "H1:11"
    assert len({value for value in episodes.values() if value}) >= 3


def test_15_m15_invalidation_does_not_invalidate_h1():
    lifecycle = lifecycle_rows()
    lifecycle.loc[lifecycle["timestamp"] == "2026-07-01T03:45:00Z", "lifecycle_state"] = "INVALIDATED"
    lifecycle.loc[lifecycle["timestamp"] == "2026-07-01T03:45:00Z", "invalidation_reason"] = "M15_LOCAL_INVALIDATION"
    sources = synthetic_sources()
    sources.lifecycle = lifecycle
    states = resolve_all_states(evaluation_timestamp="2026-07-01T04:00:00Z", sources=sources)
    assert states["M15"]["actionable"] is False
    assert states["M15"]["lifecycle_phase"] == "INVALIDATED"
    assert states["H1"]["actionable"] is True
    assert states["H1"]["lifecycle_phase"] == "ACTIVE"
    assert states["H1"]["timeframe_direction"] == "SHORT"


# --------------------------------------------------------------------------- #
# 16-20: opposite positions and isolation
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def opposite_proof(tmp_path_factory):
    return proofs.run_opposite_positions_proof(tmp_path_factory.mktemp("opposite"))


def test_16_m15_long_and_h1_short_coexist(opposite_proof):
    checks = opposite_proof["checks"]
    assert checks["m15_position_open"] and checks["h1_position_open"]
    assert checks["m15_direction_long"] and checks["h1_direction_short"]
    assert checks["distinct_position_ids"]
    assert checks["distinct_entry_prices"]
    assert checks["distinct_stop_references"]
    assert opposite_proof["passed"]


def test_17_no_position_netting(opposite_proof):
    assert opposite_proof["checks"]["no_netting_both_present"]
    assert opposite_proof["checks"]["separate_books"]
    assert opposite_proof["gross_open_risk_usd"] == 500.0


def test_18_no_cross_trader_close(opposite_proof):
    assert opposite_proof["checks"]["m15_closed_independently"]
    assert opposite_proof["checks"]["h1_still_open_after_m15_close"]
    assert opposite_proof["checks"]["h1_book_untouched_by_m15_close"]


def test_19_one_position_per_trader(isolated):
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            )
        ]
    )
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15",
                intent="OPEN_SHORT",
                evaluation_timestamp="2026-07-01T02:00:00Z",
                episode="M15:SECOND",
            )
        ]
    )
    result = traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T02:15:00Z"))
    blocked = [o for o in result["outcomes"] if o["reason"] == "POSITION_ALREADY_OPEN"]
    assert blocked, result["outcomes"]
    positions = books["M15"].positions_frame()
    assert int((positions["status"].astype(str).str.upper() == "OPEN").sum()) == 1


def test_20_four_simultaneous_positions_supported(isolated):
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe=timeframe,
                intent="OPEN_LONG" if timeframe in {"M15", "H4"} else "OPEN_SHORT",
                evaluation_timestamp="2026-07-01T01:00:00Z",
            )
            for timeframe in SUPPORTED_TIMEFRAMES
        ]
    )
    cycle_feed = proofs.visible_feed(feed, "2026-07-01T01:15:00Z")
    for timeframe in SUPPORTED_TIMEFRAMES:
        traders[timeframe].run_once(feed=cycle_feed)
    open_positions = {timeframe: books[timeframe].open_position() for timeframe in SUPPORTED_TIMEFRAMES}
    assert all(open_positions.values())
    assert len({position["position_id"] for position in open_positions.values()}) == 4
    directions = {timeframe: position["direction"] for timeframe, position in open_positions.items()}
    assert directions == {"M15": "LONG", "M30": "SHORT", "H1": "SHORT", "H4": "LONG"}


# --------------------------------------------------------------------------- #
# 21-22: one shared execution core
# --------------------------------------------------------------------------- #
def test_21_shared_execution_core_used():
    from btc_ml.trading import paper_core

    assert paper_core.resolve_risk_sizing is economics.resolve_risk_sizing
    assert paper_core.closed_trade_economics is economics.closed_trade_economics
    assert paper_core.evaluate_exit_preview is legacy_controller.evaluate_exit_preview
    assert legacy_controller.compute_closed_trade_economics is economics.closed_trade_economics
    fingerprint = paper_core.core_fingerprint()
    assert fingerprint["economics_source"] == economics.ECONOMICS_SOURCE
    assert fingerprint["sizing_method"] == economics.SIZING_METHOD
    assert fingerprint["execution_enabled"] is False


def test_22_no_duplicated_execution_formulas():
    forbidden_definitions = (
        "ENTRY_FEE_BPS =",
        "EXIT_FEE_BPS =",
        "NORMAL_ENTRY_SLIPPAGE_BPS =",
        "STOP_LOSS_BPS =",
        "TAKE_PROFIT_BPS =",
        "def resolve_risk_sizing",
        "def closed_trade_economics",
        "def stop_take_prices",
    )
    for path in sorted(TRADING_PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for definition in forbidden_definitions:
            if path.name == "paper_core.py" and definition.endswith("="):
                continue  # paper_core only re-exports canonical constants
            assert definition not in source, f"{path.name} redefines {definition}"


# --------------------------------------------------------------------------- #
# 23-24: point-in-time fill
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def fill_proof(tmp_path_factory):
    return proofs.run_fill_contract_proof(tmp_path_factory.mktemp("fill"))


def test_23_fill_strictly_after_command_timestamp(fill_proof):
    assert fill_proof["checks"]["fill_after_command"]
    assert fill_proof["checks"]["fill_is_first_completed_bar"]
    assert fill_proof["passed"]


def test_24_no_same_bar_look_ahead(fill_proof):
    assert fill_proof["checks"]["no_same_bar_fill"]
    assert fill_proof["checks"]["single_fill_row"]


# --------------------------------------------------------------------------- #
# 25-28: P&L, fees, slippage
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def pnl_proof(tmp_path_factory):
    return proofs.run_pnl_proof(tmp_path_factory.mktemp("pnl"))


def test_25_long_pnl_correct(pnl_proof):
    row = next(r for r in pnl_proof["rows"] if r["side"] == "LONG")
    assert row["stored_gross_pnl_usd"] == pytest.approx(row["recomputed_gross_pnl_usd"])
    assert row["stored_net_pnl_usd"] == pytest.approx(row["recomputed_net_pnl_usd"])
    assert row["stored_gross_pnl_usd"] > 0


def test_26_short_pnl_correct(pnl_proof):
    row = next(r for r in pnl_proof["rows"] if r["side"] == "SHORT")
    assert row["stored_gross_pnl_usd"] == pytest.approx(row["recomputed_gross_pnl_usd"])
    assert row["stored_net_pnl_usd"] == pytest.approx(row["recomputed_net_pnl_usd"])
    assert row["stored_gross_pnl_usd"] < 0


def test_27_fees_correct(pnl_proof):
    for row in pnl_proof["rows"]:
        assert row["stored_fees_usd"] == pytest.approx(row["recomputed_fees_usd"])
        expected = closed_trade_economics(
            side=row["side"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            position_size_btc=1.0,
        )
        assert expected["entry_fee_bps"] == economics.ENTRY_FEE_BPS == 2.0
        assert expected["exit_fee_bps"] == economics.EXIT_FEE_BPS == 5.0


def test_28_slippage_correct(pnl_proof):
    for row in pnl_proof["rows"]:
        assert row["stored_slippage_usd"] == pytest.approx(row["recomputed_slippage_usd"])
    assert economics.NORMAL_ENTRY_SLIPPAGE_BPS == 3.0
    assert economics.NORMAL_EXIT_SLIPPAGE_BPS == 3.0
    assert economics.STOP_FORCED_EXIT_SLIPPAGE_BPS == 5.0


# --------------------------------------------------------------------------- #
# 29-33: risk
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def risk_proof():
    return proofs.run_portfolio_risk_proof()


def test_29_per_trader_risk_within_250(risk_proof, isolated):
    assert risk_proof["checks"]["per_trader_budget_250"]
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            )
        ]
    )
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    position = books["M15"].open_position()
    meta = json.loads(position["metadata_json"])
    assert float(meta["approved_risk_usd"]) <= 250.0
    assert float(meta["sizing"]["risk_scale_from_canonical"]) == pytest.approx(0.25)


def test_30_aggregate_risk_within_1000(risk_proof, isolated):
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe=timeframe, intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            )
            for timeframe in SUPPORTED_TIMEFRAMES
        ]
    )
    cycle_feed = proofs.visible_feed(feed, "2026-07-01T01:15:00Z")
    for timeframe in SUPPORTED_TIMEFRAMES:
        traders[timeframe].run_once(feed=cycle_feed)
    total = sum(
        PaperTraderEngine(books[timeframe]).snapshot()["open_risk_usd"] for timeframe in SUPPORTED_TIMEFRAMES
    )
    assert total == pytest.approx(1000.0)
    assert total <= PortfolioRiskCoordinator.load().portfolio_max_risk_usd


def test_31_opposing_risk_counted_gross(risk_proof):
    assert risk_proof["checks"]["opposite_risk_counted_gross"]
    risk = PortfolioRiskCoordinator.load()
    assert risk.gross_open_risk({"M15": 250.0, "H1": -250.0}) == 500.0


def test_32_invalid_stop_rejected(risk_proof, isolated):
    assert risk_proof["checks"]["invalid_stop_rejected"]
    bus, books, traders, feed = isolated
    engine = PaperTraderEngine(books["M15"])
    sizing = engine._sizing(side="LONG", entry_price=0.0, approved_risk_usd=250.0)
    assert sizing["allowed"] is False
    assert "STOP" in str(sizing["reason"])


def test_33_portfolio_limit_rejected(risk_proof):
    assert risk_proof["checks"]["aggregate_limit_rejected"]
    assert risk_proof["checks"]["trader_budget_exhausted_rejected"]
    assert risk_proof["checks"]["no_auto_reallocation"]
    assert risk_proof["passed"]


# --------------------------------------------------------------------------- #
# 34-36: restart
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def restart_proof(tmp_path_factory):
    return proofs.run_restart_proof(tmp_path_factory.mktemp("restart"))


def test_34_restart_manager_idempotent(restart_proof):
    assert restart_proof["checks"]["manager_restart_no_duplicate_commands"]
    assert restart_proof["checks"]["command_bus_unique_ids"]
    assert restart_proof["duplicate_commands"] == 0


def test_35_restart_one_trader_isolated(restart_proof):
    assert restart_proof["checks"]["single_trader_restart_isolated"]
    assert restart_proof["checks"]["single_trader_restart_no_reexecution"]


def test_36_restart_all_restores_books(restart_proof):
    assert restart_proof["checks"]["full_restart_books_stable"]
    assert restart_proof["checks"]["open_positions_preserved"]
    assert restart_proof["checks"]["four_books_restored"]
    assert restart_proof["passed"]


# --------------------------------------------------------------------------- #
# 37-39: legacy migration
# --------------------------------------------------------------------------- #
def test_37_legacy_open_position_blocks_activation(monkeypatch):
    monkeypatch.setattr(
        activation,
        "legacy_ledger_mode",
        lambda: {"mode": activation.MODE_OPEN_POSITION_PRESENT, "open_rows": 1},
    )
    gates = activation.evaluate_gates()
    assert gates["allowed"] is False
    assert activation.BLOCKED_BY_LEGACY_OPEN in gates["blocked_reasons"]
    assert gates["checks"]["legacy_open_position"] is True


def test_38_legacy_history_not_reassigned():
    legacy_positions = ROOT / "data" / "research" / "paper_simulator" / "paper_positions.parquet"
    legacy_ids: set[str] = set()
    if legacy_positions.exists():
        legacy_ids = set(pd.read_parquet(legacy_positions)["position_id"].astype(str))
    for timeframe in SUPPORTED_TIMEFRAMES:
        frame = TraderBook.production(timeframe).positions_frame()
        if not len(frame):
            continue
        assert not legacy_ids & set(frame["position_id"].astype(str))
        assert set(frame["timeframe"].astype(str).str.upper()) == {timeframe}
    migration = activation.LEGACY_MIGRATION_PATH
    if migration.exists():
        payload = json.loads(migration.read_text(encoding="utf-8"))
        assert payload["history_reassigned_to_timeframes"] is False
        assert payload["legacy_book_role"] == "READ_ONLY_HISTORICAL_BOOK"


def test_39_legacy_controller_stopped_at_cutover():
    record = activation.activation_record()
    if record is None:
        pytest.skip("production activation not performed yet")
    assert activation.legacy_controller_pids() == []
    assert activation.legacy_paper_archived() is True


# --------------------------------------------------------------------------- #
# 40-43: ownership and safety
# --------------------------------------------------------------------------- #
def _hash_datasets() -> dict[str, str | None]:
    return {rel: activation.sha256_of(ROOT / rel) for rel in activation.SEMANTIC_INVARIANT_DATASETS}


def test_40_manager_does_not_write_cognition_or_context(tmp_path):
    before = _hash_datasets()
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=True,
    )
    assert _hash_datasets() == before
    assert len(books["M15"].signals_frame()) == 0
    assert len(books["M15"].fills_frame()) == 0


def test_41_traders_do_not_write_cognition_context_or_decision(isolated):
    before = _hash_datasets()
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            )
        ]
    )
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    assert _hash_datasets() == before
    for path in books["M15"].all_paths().values():
        assert ROOT / "data" / "cognition" not in path.parents


def test_42_no_exchange_or_api_imports():
    forbidden = ("ccxt", "binance", "bybit", "requests", "websocket", "urllib.request", "http.client")
    targets = list(TRADING_PACKAGE.glob("*.py")) + [
        ROOT / "scripts" / "live" / "timeframe_manager_daemon.py",
        ROOT / "scripts" / "live" / "timeframe_trader_daemon.py",
        ROOT / "scripts" / "research" / "s4_1_candidate_replay.py",
    ]
    for path in targets:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert f"import {token}" not in source, f"{path.name} imports {token}"


def test_43_real_execution_disabled(isolated):
    bus, books, traders, feed = isolated
    bus.append(
        [
            proofs.synthetic_command(
                timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
            )
        ]
    )
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    for frame in (books["M15"].signals_frame(), books["M15"].orders_frame(), books["M15"].fills_frame()):
        assert bool(frame["execution_enabled"].iloc[-1]) is False
    positions = books["M15"].positions_frame()
    assert bool(positions["paper_only"].iloc[-1]) is True
    risk_config = json.loads((ROOT / "config" / "timeframe_trader_risk.json").read_text(encoding="utf-8"))
    assert risk_config["paper_only"] is True
    assert risk_config["execution_enabled"] is False
    assert risk_config["exchange_enabled"] is False


def _flag_mutations(source: str, flag: str) -> list[str]:
    """Statements that would turn a runtime flag on (reading it is allowed)."""
    patterns = (
        rf"os\.environ\[[\"']{flag}[\"']\]\s*=",
        rf"os\.environ\.setdefault\(\s*[\"']{flag}[\"']",
        rf"putenv\(\s*[\"']{flag}[\"']",
        rf"{flag}\s*=\s*[\"']?(1|ON|TRUE|True)",
    )
    return [pattern for pattern in patterns if re.search(pattern, source)]


def test_44_continuation_progression_remains_off():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"
    for path in sorted(TRADING_PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert _flag_mutations(source, "BTC_ML_CONTINUATION_PROGRESSION") == [], path.name


def test_45_price_gate_remains_off():
    assert os.environ.get("PRICE_GATE", "OFF").upper() == "OFF"
    for path in sorted(TRADING_PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert _flag_mutations(source, "PRICE_GATE") == [], path.name


def test_46_dashboard_visual_design_preserved():
    baseline = json.loads(BASELINE_PRESERVATION.read_text(encoding="utf-8"))
    for rel, digest in baseline["visual_invariant_files"].items():
        current = activation.sha256_of(ROOT / rel)
        assert current == digest, f"visual invariant changed: {rel}"
    assert baseline["dashboard_redesign"] is False
    assert baseline["css_theme_changed"] is False

    # §21 allows data bindings and component reuse in the binding files, so they
    # are policed by content rules rather than a frozen hash: no local styling,
    # no new stylesheet, and the S4 plane must render through existing components.
    assert baseline["binding_policy"] == "DATA_BINDINGS_AND_COMPONENT_REUSE_ONLY"
    ops_tsx = (ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx").read_text(
        encoding="utf-8"
    )
    # One inline style predates S4.1 (progress-bar width); S4.1 adds none.
    assert ops_tsx.count("style={{") == baseline["ops_dashboard_inline_styles"]
    assert ".css" not in ops_tsx
    assert "timeframe_traders" in ops_tsx
    for component in ("PanelCard", "ListRow", "SectionLabel"):
        assert component in ops_tsx
