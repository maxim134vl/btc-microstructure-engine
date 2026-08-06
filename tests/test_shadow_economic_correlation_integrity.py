"""Crash-idempotency and manifest-lineage assurance for EQCORR."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from btc_ml.trading.shadow_economic_correlation import (
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    POLICY_IDS,
)
from btc_ml.trading.shadow_economic_correlation.engine import (
    ShadowEconomicCorrelationEngine,
)
from btc_ml.trading.shadow_economic_correlation.sleeves import (
    initial_policy_sleeves,
)


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def integrity_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"

    (repo / "config").mkdir(parents=True)

    shutil.copy(
        REPO / "config/intrabar_paper_execution.json",
        repo / "config/intrabar_paper_execution.json",
    )

    books = (
        repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )
    books.mkdir(parents=True)

    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "positions",
        "trades",
    ):
        (books / f"{name}.jsonl").write_text(
            "",
            encoding="utf-8",
        )

    epochs = repo / "data/trading/paper_epochs"
    epochs.mkdir(parents=True)

    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EXPECTED_EPOCH,
                "trading_contract_fingerprint":
                EXPECTED_ACTIVE_FP,
                "parent_trading_contract_fingerprint":
                EXPECTED_PARENT_FP,
                "epoch_status": "ACTIVE",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    context_root = (
        repo
        / "data/cognition/intrabar_context_events"
    )
    context_root.mkdir(parents=True)

    (context_root / "events.jsonl").write_text(
        "",
        encoding="utf-8",
    )

    (repo / "data/runtime").mkdir(parents=True)

    return repo


def books_root(repo: Path) -> Path:
    return (
        repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )


def shadow_root(repo: Path) -> Path:
    return (
        repo
        / "data/trading/shadow_economic_correlation"
        / "epochs"
        / EXPECTED_EPOCH
    )


def seed_entry(repo: Path) -> None:
    books = books_root(repo)

    fill = {
        "fill_id": "fill1",
        "order_id": "order1",
        "command_id": "command1",
        "action": "ENTRY",
        "timeframe": "M15",
        "side": "LONG",
        "quantity": 1.0,
        "paper_fill_price": 100_000.0,
        "ts": "2026-07-29T19:00:00Z",
        "context_event_id": "context1",
    }

    position = {
        "position_id": "position1",
        "status": "OPEN",
        "timeframe": "M15",
        "side": "LONG",
        "quantity": 1.0,
        "entry_price": 100_000.0,
        "stop_loss_price": 99_000.0,
        "take_profit_price": 102_000.0,
        "entry_fill_id": "fill1",
        "entry_command_id": "command1",
        "entry_context_event_id": "context1",
        "lifecycle_episode_id": "episode1",
        "opened_at": "2026-07-29T19:00:00Z",
        "risk_budget_usd": 1000.0,
        "risk_amount_usd": 1000.0,
        "notional_usd": 100_000.0,
        "equity_at_entry_usd": 100_000.0,
        "risk_pct_at_entry": 1.0,
    }

    command = {
        "command_id": "command1",
        "signal_id": "signal1",
    }

    signal = {
        "signal_id": "signal1",
        "context_event_id": "context1",
        "lifecycle_episode_id": "episode1",
        "timeframe": "M15",
        "risk_budget_usd": 1000.0,
    }

    for name, rows in (
        ("fills", [fill]),
        ("positions", [position]),
        ("commands", [command]),
        ("signals", [signal]),
    ):
        (books / f"{name}.jsonl").write_text(
            "".join(
                json.dumps(row) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )


def write_trade(
    repo: Path,
    *,
    trade_id: str = "trade1",
    position_id: str = "position1",
) -> dict:
    trade = {
        "trade_id": trade_id,
        "position_id": position_id,
        "entry_ts": "2026-07-29T19:00:00Z",
        "exit_ts": "2026-07-29T19:30:00Z",
        "exit_price": 99_000.0,
        "exit_reason": "STOP_LOSS",
        "gross_pnl_usd": -1000.0,
        "fees_usd": 10.0,
        "slippage_usd": 5.0,
        "net_pnl_usd": -1015.0,
        "risk_amount_usd": 1000.0,
    }

    (
        books_root(repo)
        / "trades.jsonl"
    ).write_text(
        json.dumps(trade) + "\n",
        encoding="utf-8",
    )

    return trade


def active_rows(
    engine: ShadowEconomicCorrelationEngine,
    table: str,
) -> list[dict]:
    return [
        row
        for row in engine.store.read_all(table)
        if row.get(
            "shadow_policy_manifest_fingerprint"
        )
        == engine.manifest_fp
    ]


def test_all_new_journal_rows_have_active_lineage(
    integrity_repo: Path,
) -> None:
    seed_entry(integrity_repo)

    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    engine.process_new_entries()
    write_trade(integrity_repo)
    engine.process_new_closes()

    for table in (
        "candidate_snapshots",
        "cluster_snapshots",
        "policy_decisions",
        "virtual_positions",
        "virtual_trades",
        "quality_outcomes",
        "candidate_feature_enrichments",
    ):
        rows = engine.store.read_all(table)

        assert rows, table

        assert all(
            row.get(
                "shadow_policy_manifest_fingerprint"
            )
            == engine.manifest_fp
            for row in rows
        )

        assert all(
            row.get("source_epoch_id")
            == engine.epoch_id
            for row in rows
        )

        assert all(
            row.get(
                "source_contract_fingerprint"
            )
            == engine.source_fp
            for row in rows
        )


def test_partial_candidate_is_rolled_back_and_retried_once(
    integrity_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_entry(integrity_repo)

    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    original_append = engine.store.append
    raised = False

    def flaky_append(
        table: str,
        row: dict,
    ) -> dict:
        nonlocal raised

        result = original_append(table, row)

        if (
            table == "policy_decisions"
            and not raised
        ):
            raised = True
            raise RuntimeError(
                "SIMULATED_CANDIDATE_CRASH"
            )

        return result

    monkeypatch.setattr(
        engine.store,
        "append",
        flaky_append,
    )

    failed = engine.process_new_entries()

    assert failed[0]["status"] == "CANDIDATE_ERROR"
    assert not engine.processed_candidates
    assert not engine.store.read_inflight()

    for table in (
        "candidate_snapshots",
        "cluster_snapshots",
        "policy_decisions",
        "virtual_positions",
        "candidate_feature_enrichments",
    ):
        assert not active_rows(engine, table)

    monkeypatch.setattr(
        engine.store,
        "append",
        original_append,
    )

    completed = engine.process_new_entries()

    assert completed
    assert len(engine.processed_candidates) == 1

    primary_decisions = [
        row
        for row in active_rows(
            engine,
            "policy_decisions",
        )
        if not row.get("record_type")
    ]

    assert len(primary_decisions) == len(POLICY_IDS)

    assert len(
        {
            (
                row["candidate_id"],
                row["policy_id"],
            )
            for row in primary_decisions
        }
    ) == len(POLICY_IDS)


def test_partial_close_is_rolled_back_and_accrued_once(
    integrity_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_entry(integrity_repo)

    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    engine.process_new_entries()
    trade = write_trade(integrity_repo)

    baseline_before = dict(
        engine.sleeves[
            "BASELINE_ALL_ELIGIBLE"
        ]["sleeves"]["M15"]
    )

    original_append = engine.store.append
    raised = False

    def flaky_append(
        table: str,
        row: dict,
    ) -> dict:
        nonlocal raised

        result = original_append(table, row)

        if (
            table == "virtual_trades"
            and not raised
        ):
            raised = True
            raise RuntimeError(
                "SIMULATED_CLOSE_CRASH"
            )

        return result

    monkeypatch.setattr(
        engine.store,
        "append",
        flaky_append,
    )

    failed = engine.process_new_closes()

    assert failed[0]["status"] == "CLOSE_ERROR"

    assert (
        trade["trade_id"]
        not in engine.processed_closes
    )

    assert not engine.store.read_inflight()
    assert not active_rows(engine, "virtual_trades")
    assert not active_rows(engine, "quality_outcomes")

    baseline_after_failure = (
        engine.sleeves[
            "BASELINE_ALL_ELIGIBLE"
        ]["sleeves"]["M15"]
    )

    assert (
        baseline_after_failure[
            "cumulative_realized_net_pnl_usd"
        ]
        == baseline_before[
            "cumulative_realized_net_pnl_usd"
        ]
    )

    assert (
        baseline_after_failure[
            "closed_trades_count"
        ]
        == baseline_before[
            "closed_trades_count"
        ]
    )

    monkeypatch.setattr(
        engine.store,
        "append",
        original_append,
    )

    completed = engine.process_new_closes()

    assert completed[0]["status"] == "CLOSED"

    baseline_trades = [
        row
        for row in active_rows(
            engine,
            "virtual_trades",
        )
        if (
            row.get("trade_id")
            == trade["trade_id"]
            and row.get("policy_id")
            == "BASELINE_ALL_ELIGIBLE"
        )
    ]

    assert len(baseline_trades) == 1

    restarted = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    restarted.process_new_closes()

    baseline_after_restart = [
        row
        for row in active_rows(
            restarted,
            "virtual_trades",
        )
        if (
            row.get("trade_id")
            == trade["trade_id"]
            and row.get("policy_id")
            == "BASELINE_ALL_ELIGIBLE"
        )
    ]

    assert len(baseline_after_restart) == 1


def test_checkpoint_sleeves_are_authoritative(
    integrity_repo: Path,
) -> None:
    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    engine.sleeves[
        "MAX_2_SAME_DIRECTION"
    ]["sleeves"]["M30"][
        "current_equity_usd"
    ] = 123_456.0

    engine._save_checkpoint()

    mirror = engine.store.read_json(
        "policy_sleeves.json"
    )

    mirror[
        "MAX_2_SAME_DIRECTION"
    ]["sleeves"]["M30"][
        "current_equity_usd"
    ] = 999.0

    engine.store.write_json(
        "policy_sleeves.json",
        mirror,
    )

    restarted = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    assert (
        restarted.sleeves[
            "MAX_2_SAME_DIRECTION"
        ]["sleeves"]["M30"][
            "current_equity_usd"
        ]
        == 123_456.0
    )


def test_close_without_candidate_is_not_marked_processed(
    integrity_repo: Path,
) -> None:
    trade = write_trade(
        integrity_repo,
        trade_id="trade_without_candidate",
        position_id="missing_position",
    )

    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    first = engine.process_new_closes()
    second = engine.process_new_closes()

    assert first[0]["status"] == "NO_CANDIDATE"
    assert second[0]["status"] == "NO_CANDIDATE"

    assert (
        trade["trade_id"]
        not in engine.processed_closes
    )

    assert not active_rows(
        engine,
        "quality_outcomes",
    )


def test_stale_partial_transaction_rolls_back_on_restart(
    integrity_repo: Path,
) -> None:
    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    engine.store.begin_transaction(
        kind="candidate",
        key="stale_candidate",
        base_generation=engine.state_generation,
    )

    engine.store.append(
        "candidate_snapshots",
        {
            "candidate_id": "stale_candidate",
        },
    )

    marker = engine.store.read_inflight()
    marker["owner_pid"] = 2_147_483_647

    engine.store.write_json(
        engine.store.INFLIGHT_NAME,
        marker,
    )

    restarted = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    assert (
        restarted.transaction_recovery["status"]
        == "ROLLED_BACK"
    )

    assert not restarted.store.read_inflight()

    assert not [
        row
        for row in active_rows(
            restarted,
            "candidate_snapshots",
        )
        if row.get("candidate_id")
        == "stale_candidate"
    ]


def test_committed_marker_is_cleared_without_rollback(
    integrity_repo: Path,
) -> None:
    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    base_generation = engine.state_generation

    engine.store.begin_transaction(
        kind="candidate",
        key="committed_candidate",
        base_generation=base_generation,
    )

    engine.store.append(
        "candidate_snapshots",
        {
            "candidate_id": "committed_candidate",
        },
    )

    engine.processed_candidates.add(
        "committed_candidate"
    )
    engine._save_checkpoint()

    assert engine.store.read_inflight()

    restarted = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    assert (
        restarted.transaction_recovery["status"]
        == "COMMITTED_MARKER_CLEARED"
    )

    assert not restarted.store.read_inflight()

    assert any(
        row.get("candidate_id")
        == "committed_candidate"
        for row in active_rows(
            restarted,
            "candidate_snapshots",
        )
    )


def test_manifest_change_preserves_history_but_resets_generation(
    integrity_repo: Path,
) -> None:
    root = shadow_root(integrity_repo)
    root.mkdir(parents=True)

    (root / "policy_manifest.json").write_text(
        json.dumps(
            {
                "shadow_policy_manifest_fingerprint":
                "legacy_manifest",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (root / "checkpoint.json").write_text(
        json.dumps(
            {
                "state_generation": 7,
                "active_policy_manifest_fingerprint":
                "legacy_manifest",
                "processed_candidates": [
                    "legacy_candidate"
                ],
                "processed_closes": [],
                "policy_sleeves":
                initial_policy_sleeves(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (root / "candidate_snapshots.jsonl").write_text(
        json.dumps(
            {
                "candidate_id":
                "legacy_candidate",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    assert not engine.processed_candidates

    assert (
        "legacy_manifest"
        in engine.invalidated_manifest_fps
    )

    assert not active_rows(
        engine,
        "candidate_snapshots",
    )

    assert len(
        engine.store.read_all(
            "candidate_snapshots"
        )
    ) == 1

    checkpoint = engine.store.read_json(
        "checkpoint.json"
    )

    assert (
        checkpoint[
            "active_shadow_policy_manifest_fingerprint"
        ]
        == engine.manifest_fp
    )


def test_manifest_and_health_declare_integrity_contracts(
    integrity_repo: Path,
) -> None:
    engine = ShadowEconomicCorrelationEngine(
        repo=integrity_repo,
        strict_epoch=True,
    )

    assert (
        engine.manifest["shadow_model_version"]
        == "SHADOW_EQCORR1_2_V2"
    )

    assert (
        engine.manifest["lineage_contract"]
        == "EQCORR_POLICY_MANIFEST_LINEAGE_V1"
    )

    assert (
        engine.manifest["transaction_contract"]
        == "EQCORR_CRASH_SAFE_JSONL_V1"
    )

    health = engine.write_health()

    assert (
        health[
            "shadow_policy_manifest_fingerprint"
        ]
        == engine.manifest_fp
    )

    assert (
        health["transaction_contract"]
        == "EQCORR_CRASH_SAFE_JSONL_V1"
    )
