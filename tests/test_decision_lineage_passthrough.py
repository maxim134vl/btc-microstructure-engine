"""Phase 2A — additive decision_id lineage contract (identity only).

Proves passthrough of immutable context_decision_log.decision_id through
manager command → signal → order → fill → position → trade without changing
trading policy, risk, sizing, or P&L. No live ledger writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import proofs  # noqa: E402
from btc_ml.trading.command_bus import COMMAND_COLUMNS, classify_command_lineage  # noqa: E402
from btc_ml.trading.paper_trader_engine import command_decision_id  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.timeframe_manager import (  # noqa: E402
    LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH,
    LINEAGE_EXACT_UNIQUE_MATCH,
    LINEAGE_NO_EXACT_DECISION_MATCH,
    TimeframeManager,
    load_decision_identity_index,
    resolve_decision_identity,
)

# Reuse S4.1 synthetic fixtures
from test_s4_1_manager_independent_timeframe_traders import (  # noqa: E402
    lifecycle_rows,
    synthetic_sources,
)

CANONICAL_DECISION_ID = "ctx_dec_lineage_test_0001"
BAR_OPEN = "2026-07-01T03:45:00Z"
BAR_CLOSE = "2026-07-01T04:00:00Z"
EVAL_TS = "2026-07-01T04:00:00Z"


def _decision_log_frame(*, decision_id: str = CANONICAL_DECISION_ID) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": decision_id,
                "source_timeframe": "15m",
                "candle_timestamp": BAR_OPEN,
                "candle_close_time_utc": BAR_CLOSE,
                "context_episode_id": 12,
                "lifecycle_episode_id": 12,
                "action_allowed": True,
                "context_state": "LONG_CONTEXT",
            }
        ]
    )


def _write_decision_log(path: Path, frame: pd.DataFrame | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    (frame if frame is not None else _decision_log_frame()).to_parquet(path, index=False)
    return path


def _trading_fingerprint(commands: list[dict]) -> list[dict]:
    keys = (
        "timeframe",
        "intent",
        "action_allowed",
        "reason_codes",
        "approved_risk_usd",
        "requested_risk_usd",
        "timeframe_direction",
        "lifecycle_episode_id",
        "stop_reference",
    )
    return [{k: c.get(k) for k in keys} for c in commands]


# --------------------------------------------------------------------------- #
# Identity helpers
# --------------------------------------------------------------------------- #
def test_01_exact_join_resolves_canonical_decision_id(tmp_path):
    log = _write_decision_log(tmp_path / "context_decision_log.parquet")
    index = load_decision_identity_index(log)
    hit = resolve_decision_identity(
        timeframe="M15",
        source_bar_open=BAR_OPEN,
        source_bar_close=BAR_CLOSE,
        evaluation_timestamp=EVAL_TS,
        index=index,
    )
    assert hit["decision_id"] == CANONICAL_DECISION_ID
    assert hit["context_id"] == "12"
    assert hit["lineage_lookup_status"] == LINEAGE_EXACT_UNIQUE_MATCH


def test_01b_adjacent_bars_do_not_create_false_ambiguity(tmp_path):
    """Prev close == next open must not collide when indexes are separated."""
    frame = pd.DataFrame(
        [
            {
                "decision_id": "dec_a",
                "source_timeframe": "15m",
                "candle_timestamp": "2026-07-01T03:45:00Z",
                "candle_close_time_utc": "2026-07-01T04:00:00Z",
                "context_episode_id": 1,
                "lifecycle_episode_id": 1,
            },
            {
                "decision_id": "dec_b",
                "source_timeframe": "15m",
                "candle_timestamp": "2026-07-01T04:00:00Z",
                "candle_close_time_utc": "2026-07-01T04:15:00Z",
                "context_episode_id": 2,
                "lifecycle_episode_id": 2,
            },
        ]
    )
    log = _write_decision_log(tmp_path / "decisions.parquet", frame)
    index = load_decision_identity_index(log)
    assert all(
        h.get("lineage_lookup_status") != LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH
        for table in index.values()
        for h in table.values()
    )
    first = resolve_decision_identity(
        timeframe="M15",
        source_bar_open="2026-07-01T03:45:00Z",
        source_bar_close="2026-07-01T04:00:00Z",
        evaluation_timestamp="2026-07-01T04:00:00Z",
        index=index,
    )
    second = resolve_decision_identity(
        timeframe="M15",
        source_bar_open="2026-07-01T04:00:00Z",
        source_bar_close="2026-07-01T04:15:00Z",
        evaluation_timestamp="2026-07-01T04:15:00Z",
        index=index,
    )
    assert first["decision_id"] == "dec_a"
    assert first["lineage_lookup_status"] == LINEAGE_EXACT_UNIQUE_MATCH
    assert second["decision_id"] == "dec_b"
    assert second["lineage_lookup_status"] == LINEAGE_EXACT_UNIQUE_MATCH


def test_01c_ambiguous_exact_match_fails_closed(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "decision_id": "dec_dup_1",
                "source_timeframe": "15m",
                "candle_timestamp": BAR_OPEN,
                "candle_close_time_utc": BAR_CLOSE,
                "context_episode_id": 1,
            },
            {
                "decision_id": "dec_dup_2",
                "source_timeframe": "15m",
                "candle_timestamp": BAR_OPEN,
                "candle_close_time_utc": BAR_CLOSE,
                "context_episode_id": 2,
            },
        ]
    )
    log = _write_decision_log(tmp_path / "decisions.parquet", frame)
    index = load_decision_identity_index(log)
    hit = resolve_decision_identity(
        timeframe="M15",
        source_bar_open=BAR_OPEN,
        source_bar_close=BAR_CLOSE,
        evaluation_timestamp=EVAL_TS,
        index=index,
    )
    assert hit["decision_id"] is None
    assert hit["lineage_lookup_status"] == LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH


def test_01d_zero_match_fails_closed():
    hit = resolve_decision_identity(
        timeframe="M15",
        source_bar_open=BAR_OPEN,
        source_bar_close=BAR_CLOSE,
        evaluation_timestamp=EVAL_TS,
        index={"open": {}, "close": {}},
    )
    assert hit["decision_id"] is None
    assert hit["lineage_lookup_status"] == LINEAGE_NO_EXACT_DECISION_MATCH


def test_02_manager_passthrough_unchanged(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    log = _write_decision_log(tmp_path / "decisions.parquet")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    cycle = manager.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=False,
        decision_log_path=log,
    )
    m15 = next(c for c in cycle["commands"] if c["timeframe"] == "M15")
    assert m15["decision_id"] == CANONICAL_DECISION_ID
    assert m15["decision_id"] != m15["command_id"]
    assert m15["lineage_lookup_status"] == LINEAGE_EXACT_UNIQUE_MATCH
    assert str(m15["command_id"]).startswith("TF_CMD_")
    assert not str(m15["decision_id"]).startswith("TF_CMD_")


def test_03_manager_does_not_invent_decision_id(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    cycle = manager.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=False,
        decision_index={},  # empty → no synthetic IDs
    )
    for command in cycle["commands"]:
        assert command.get("decision_id") is None
        assert command["command_id"] is not None


def test_04_trader_does_not_alias_decision_id_to_command_id(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    feed = proofs.build_synthetic_feed()
    command = proofs.synthetic_command(
        timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
    )
    command["decision_id"] = CANONICAL_DECISION_ID
    bus.append([command])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    order = books["M15"].orders_frame().iloc[0]
    assert order["decision_id"] == CANONICAL_DECISION_ID
    assert order["decision_id"] != order["command_id"]
    assert order["command_id"] == command["command_id"]


def test_05_to_09_new_rows_receive_original_decision_id(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    feed = proofs.build_synthetic_feed()
    open_cmd = proofs.synthetic_command(
        timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
    )
    open_cmd["decision_id"] = CANONICAL_DECISION_ID
    bus.append([open_cmd])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))

    signal = books["M15"].signals_frame().iloc[0]
    order = books["M15"].orders_frame().iloc[0]
    fill = books["M15"].fills_frame().iloc[0]
    position = books["M15"].positions_frame().iloc[0]
    assert signal["decision_id"] == CANONICAL_DECISION_ID
    assert order["decision_id"] == CANONICAL_DECISION_ID
    assert fill["decision_id"] == CANONICAL_DECISION_ID
    assert position["decision_id"] == CANONICAL_DECISION_ID

    close_cmd = proofs.synthetic_command(
        timeframe="M15",
        intent="CLOSE",
        evaluation_timestamp="2026-07-01T02:00:00Z",
        episode="M15:12",
    )
    close_decision = "ctx_dec_lineage_close_0002"
    close_cmd["decision_id"] = close_decision
    bus.append([close_cmd])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T02:15:00Z"))
    trade = books["M15"].trades_frame().iloc[0]
    assert trade["decision_id"] == close_decision
    assert trade["decision_id"] != trade["command_id"]


def test_10_legacy_command_without_decision_id_reads(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    # Write a parquet row missing identity columns entirely
    legacy = {
        col: None
        for col in COMMAND_COLUMNS
        if col
        not in {
            "command_id",
            "timeframe",
            "intent",
            "action_allowed",
            "evaluation_timestamp",
            "schema_version",
            "asset",
            "paper_only",
            "execution_enabled",
            "reason_codes",
            "created_at",
        }
    }
    legacy.update(
        {
            "command_id": "TF_CMD_LEGACY_ONLY",
            "timeframe": "M15",
            "intent": "HOLD",
            "action_allowed": False,
            "evaluation_timestamp": "2026-06-01T00:00:00Z",
            "schema_version": "timeframe_manager_command_v1",
            "asset": "BTCUSDT",
            "paper_only": True,
            "execution_enabled": False,
            "reason_codes": '["LEGACY"]',
            "created_at": "2026-06-01T00:00:00Z",
        }
    )
    # Drop new identity cols to simulate pre-patch file
    legacy_cols = [c for c in COMMAND_COLUMNS if c not in {
        "decision_id",
        "context_id",
        "canonical_episode_id",
        "timeframe_episode_id",
        "source_decision_timestamp",
    }]
    frame = pd.DataFrame([{c: legacy.get(c) for c in legacy_cols}], columns=legacy_cols)
    bus.paths.memory.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(bus.paths.memory, index=False)

    loaded = bus.frame()
    assert len(loaded) == 1
    assert "decision_id" in loaded.columns
    assert pd.isna(loaded.iloc[0]["decision_id"]) or loaded.iloc[0]["decision_id"] is None
    record = loaded.iloc[0].to_dict()
    assert classify_command_lineage(record) == "LEGACY_NO_DECISION_ID"
    assert command_decision_id(record) is None


def test_11_legacy_records_get_no_synthetic_id(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    feed = proofs.build_synthetic_feed()
    command = proofs.synthetic_command(
        timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
    )
    # Explicit legacy: no decision_id key
    command.pop("decision_id", None)
    bus.append([command])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    order = books["M15"].orders_frame().iloc[0]
    assert order["decision_id"] is None or pd.isna(order["decision_id"])
    assert order["command_id"] == command["command_id"]
    # Must not have written command_id into decision_id
    assert str(order["decision_id"]) != str(order["command_id"])


def test_12_observe_not_actionable_stays_no_action(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    sources = synthetic_sources()
    # Force M15 non-actionable (OBSERVE / invalidated)
    lifecycle = lifecycle_rows()
    lifecycle.loc[lifecycle["timestamp"] == "2026-07-01T03:45:00Z", "lifecycle_state"] = "INVALIDATED"
    lifecycle.loc[lifecycle["timestamp"] == "2026-07-01T03:45:00Z", "invalidation_reason"] = "OBSERVE_LIKE"
    sources.lifecycle = lifecycle
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    cycle = manager.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=sources,
        feed=proofs.build_synthetic_feed(),
        persist=False,
        decision_index={},
    )
    m15 = next(c for c in cycle["commands"] if c["timeframe"] == "M15")
    assert m15["intent"] == "NO_ACTION"
    assert m15["action_allowed"] is False


def test_13_action_allowed_false_does_not_open(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    feed = proofs.build_synthetic_feed()
    command = proofs.synthetic_command(
        timeframe="M15", intent="NO_ACTION", evaluation_timestamp="2026-07-01T01:00:00Z"
    )
    command["action_allowed"] = False
    command["decision_id"] = CANONICAL_DECISION_ID
    bus.append([command])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    assert len(books["M15"].positions_frame()) == 0
    assert len(books["M15"].orders_frame()) == 0


def test_14_risk_blocked_remains_blocked(tmp_path):
    bus, books, traders = proofs.isolated_environment(tmp_path / "books")
    feed = proofs.build_synthetic_feed()
    command = proofs.synthetic_command(
        timeframe="M15",
        intent="OPEN_LONG",
        evaluation_timestamp="2026-07-01T01:00:00Z",
        approved_risk_usd=0.0,
    )
    command["decision_id"] = CANONICAL_DECISION_ID
    bus.append([command])
    traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
    # Zero approved risk must not open a position
    assert len(books["M15"].positions_frame()) == 0


def test_15_duplicate_suppression_unchanged(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    log = _write_decision_log(tmp_path / "decisions.parquet")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    kwargs = dict(
        evaluation_timestamp=EVAL_TS,
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=True,
        decision_log_path=log,
    )
    first = manager.run_cycle(**kwargs)
    second = manager.run_cycle(**kwargs)
    assert first["append_result"]["appended"] == 4
    assert second["append_result"]["appended"] == 0
    assert second["append_result"]["duplicates_rejected"] == 4
    assert len(bus.frame()) == 4


def test_16_18_direction_size_price_pnl_unchanged_by_identity(tmp_path):
    """Behavioral equality: identity attachment must not alter trade economics."""
    feed = proofs.build_synthetic_feed()

    def _run(*, with_decision: bool):
        root = tmp_path / ("with" if with_decision else "without")
        bus, books, traders = proofs.isolated_environment(root)
        command = proofs.synthetic_command(
            timeframe="M15", intent="OPEN_LONG", evaluation_timestamp="2026-07-01T01:00:00Z"
        )
        if with_decision:
            command["decision_id"] = CANONICAL_DECISION_ID
        bus.append([command])
        traders["M15"].run_once(feed=proofs.visible_feed(feed, "2026-07-01T01:15:00Z"))
        pos = books["M15"].positions_frame().iloc[0]
        return {
            "direction": str(pos["direction"]),
            "quantity": float(pos["quantity"]),
            "entry_price": float(pos["entry_price"]),
            "realized_pnl": float(pos["realized_pnl"]),
            "unrealized_pnl": float(pos["unrealized_pnl"]),
            "decision_id": pos.get("decision_id"),
            "command_id": pos.get("command_id"),
        }

    baseline = _run(with_decision=False)
    linked = _run(with_decision=True)
    for key in ("direction", "quantity", "entry_price", "realized_pnl", "unrealized_pnl"):
        assert baseline[key] == linked[key], f"regression on {key}"
    assert baseline["decision_id"] is None or pd.isna(baseline["decision_id"])
    assert linked["decision_id"] == CANONICAL_DECISION_ID
    assert linked["decision_id"] != linked["command_id"]


def test_19_manager_command_fingerprint_stable_with_identity(tmp_path):
    bus_a, books_a, _ = proofs.isolated_environment(tmp_path / "a")
    bus_b, books_b, _ = proofs.isolated_environment(tmp_path / "b")
    manager_a = TimeframeManager(bus=bus_a, books=books_a, risk=PortfolioRiskCoordinator.load())
    manager_b = TimeframeManager(bus=bus_b, books=books_b, risk=PortfolioRiskCoordinator.load())
    feed = proofs.build_synthetic_feed()
    sources = synthetic_sources()
    without = manager_a.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=sources,
        feed=feed,
        persist=False,
        decision_index={},
    )
    log = _write_decision_log(tmp_path / "decisions.parquet")
    with_id = manager_b.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=sources,
        feed=feed,
        persist=False,
        decision_log_path=log,
    )
    assert _trading_fingerprint(without["commands"]) == _trading_fingerprint(with_id["commands"])
    assert [c["command_id"] for c in without["commands"]] == [c["command_id"] for c in with_id["commands"]]
    m15 = next(c for c in with_id["commands"] if c["timeframe"] == "M15")
    assert m15["decision_id"] == CANONICAL_DECISION_ID


def test_20_fixture_counts_stable(tmp_path):
    bus, books, _ = proofs.isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    cycle = manager.run_cycle(
        evaluation_timestamp=EVAL_TS,
        sources=synthetic_sources(),
        feed=proofs.build_synthetic_feed(),
        persist=True,
        decision_index={},
    )
    assert len(cycle["commands"]) == 4
    assert len(bus.frame()) == 4
    assert cycle["append_result"]["appended"] == 4


def test_command_columns_include_additive_identity_fields():
    for col in (
        "decision_id",
        "context_id",
        "canonical_episode_id",
        "timeframe_episode_id",
        "source_decision_timestamp",
    ):
        assert col in COMMAND_COLUMNS
