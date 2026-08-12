"""TRD-SLEEVE2: per-timeframe equity sleeves + dynamic 1% risk."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import resolve_risk_sizing
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
from btc_ml.trading.intrabar_paper.trading_contract import (
    CANONICAL_SOURCE_EPOCH,
    EXPECTED_SOURCE_FINGERPRINT,
    ZERO_DIFF_MATCH,
    assert_source_fingerprint,
    build_trading_contract_manifest,
    clone_trading_epoch_contract,
    compare_replay_books,
    compute_risk_budget_usd,
    size_with_contract,
    sleeve2_capital_overrides,
    validate_sleeve2_contract_diff,
)
from epoch_isolation_helpers import (
    WORKSPACE,
    assert_no_runtime_touch,
    make_isolated_contract_repo,
    runtime_file_hashes,
)

REPO = WORKSPACE


def _install_source_epoch(repo: Path) -> None:
    src = REPO / "data" / "trading" / "paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json"
    dst = repo / "data" / "trading" / "paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def _seed_engine(tmp_path: Path, *, stamp: str, with_sleeves: bool = True):
    repo = tmp_path / f"repo_{stamp}"
    (repo / "config").mkdir(parents=True)
    raw = json.loads((REPO / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n")
    for p in (
        repo / "data/cognition/intrabar_context_events",
        repo / "data/trading/intrabar_paper",
        repo / "data/trading/paper_epochs",
    ):
        p.mkdir(parents=True)
    _install_source_epoch(repo)
    cfg = load_intrabar_paper_config(repo_root=repo)
    ep = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=400_000.0, utc_stamp=stamp),
        epochs_root=cfg.epochs_root,
    )
    epoch_root = cfg.books_root / ep.paper_epoch_id
    if with_sleeves:
        source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=repo)
        clone = clone_trading_epoch_contract(
            CANONICAL_SOURCE_EPOCH,
            ep.paper_epoch_id,
            sleeve2_capital_overrides(),
            repo_root=repo,
            output_root=epoch_root,
            source_manifest=source,
        )
        (epoch_root / "trading_contract.json").write_text(
            json.dumps(
                {
                    "trading_contract_manifest": clone.manifest,
                    "trading_contract_fingerprint": clone.fingerprint,
                    "parent_epoch_id": CANONICAL_SOURCE_EPOCH,
                },
                indent=2,
            )
            + "\n"
        )
        SleeveLedger.initialize(epoch_id=ep.paper_epoch_id, epoch_root=epoch_root)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=64685.0,
        best_ask=64687.82,
        receive_monotonic_ns=1_000_000,
        book_update_id="seed",
        domain="context",
    )
    return cfg, repo, eng, ep


def _h4_start(mono: int = 2_000_000) -> dict:
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
        "event_type": "CONTEXT_START",
        "timeframe": "H4",
        "previous_context": "OBSERVE",
        "new_context": "LONG_CONTEXT",
        "event_monotonic_ns": mono,
        "event_timestamp": fresh,
        "decision_available_at": fresh,
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "materialization_source": "closed_bar_context_decision",
        "delivery_mode": "LIVE",
        "context_event_price": 64687.82,
        "best_bid": 64685.0,
        "best_ask": 64687.82,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": "H4:prov:1",
    }


@pytest.fixture
def isolated_source_repo(tmp_path: Path) -> Path:
    return make_isolated_contract_repo(tmp_path, stamp="SLEEVE_SRC", activate_source=True)


def test_source_fingerprint_matches(isolated_source_repo: Path):
    m = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=isolated_source_repo)
    assert assert_source_fingerprint(m) == EXPECTED_SOURCE_FINGERPRINT


def test_sleeve2_allowlisted_diff_only(tmp_path: Path, isolated_source_repo: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=isolated_source_repo)
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "PER_TF_EQUITY_1PCT_V1_TEST",
        sleeve2_capital_overrides(),
        repo_root=isolated_source_repo,
        output_root=tmp_path,
        source_manifest=source,
    )
    validate_sleeve2_contract_diff(clone.diff)
    assert clone.diff["capital.capital_model"]["to"] == "PER_TIMEFRAME_REALIZED_EQUITY"
    assert clone.diff["capital.master_initial_equity_usd"]["to"] == 400000.0
    assert clone.manifest["position_sizing"]["risk_cap_semantics"] == "PER_TIMEFRAME_CURRENT_EQUITY_PERCENT"
    for key in (
        "context_consumption",
        "entry_rules",
        "protection_geometry",
        "exit_rules",
        "market_execution",
        "costs",
        "state_and_persistence",
        "safety",
        "execution_config_snapshot",
    ):
        assert clone.manifest[key] == source[key]


def test_no_fixed_1000_cap_after_equity_change(tmp_path: Path, isolated_source_repo: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=isolated_source_repo)
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "PER_TF_EQUITY_1PCT_V1_RISK",
        sleeve2_capital_overrides(),
        repo_root=isolated_source_repo,
        output_root=tmp_path,
        source_manifest=source,
    )
    cfg = load_intrabar_paper_config(repo_root=isolated_source_repo)
    shared = resolve_risk_sizing(cfg=cfg, side="LONG", entry_price=64687.82, equity_usd=200_000.0)
    assert shared.risk_amount_usd == pytest.approx(1000.0)
    b102 = compute_risk_budget_usd(clone.manifest, timeframe="M15", current_equity_usd=102_000.0)
    b97 = compute_risk_budget_usd(clone.manifest, timeframe="H1", current_equity_usd=97_000.0)
    assert b102 == pytest.approx(1020.0)
    assert b97 == pytest.approx(970.0)
    s102 = size_with_contract(
        cfg=cfg,
        manifest=clone.manifest,
        side="LONG",
        entry_price=64687.82,
        timeframe="M15",
        current_equity_usd=102_000.0,
    )
    assert s102.risk_amount_usd == pytest.approx(1020.0)
    assert s102.quantity > shared.quantity


def test_h4_isolated_fixture_quantity_and_geometry(tmp_path: Path):
    _, _, eng, _ = _seed_engine(tmp_path, stamp="H4FIX")
    acts = eng.process_context_event(_h4_start())
    assert acts and acts[0]["status"] == "ENTERED"
    pos = eng.positions["H4"]
    assert pos.entry_price == pytest.approx(64687.82)
    assert pos.stop_loss_price == pytest.approx(64040.9418)
    assert pos.take_profit_price == pytest.approx(65658.1373)
    assert pos.quantity == pytest.approx(1.3454186880112602)
    assert pos.risk_amount_usd == pytest.approx(1000.0)
    sig = eng.books.read_all("signals")[0]
    assert sig["equity_at_entry_usd"] == pytest.approx(100000.0)
    assert sig["risk_budget_usd"] == pytest.approx(1000.0)
    assert sig["risk_pct_at_entry"] == pytest.approx(1.0)


def test_per_timeframe_pnl_isolation_and_restart(tmp_path: Path):
    _, repo, eng, ep = _seed_engine(tmp_path, stamp="ISO1")
    assert eng.sleeves is not None
    eng.sleeves.apply_realized_net_pnl("M15", 2000.0)
    eng.sleeves.apply_realized_net_pnl("H1", -3000.0)
    assert eng.sleeves.get("M15").current_equity_usd == pytest.approx(102000.0)
    assert eng.sleeves.get("M15").next_risk_budget_usd == pytest.approx(1020.0)
    assert eng.sleeves.get("H1").current_equity_usd == pytest.approx(97000.0)
    assert eng.sleeves.get("H1").next_risk_budget_usd == pytest.approx(970.0)
    assert eng.sleeves.get("M30").current_equity_usd == pytest.approx(100000.0)
    assert eng.sleeves.get("H4").current_equity_usd == pytest.approx(100000.0)
    master = eng.sleeves.master_snapshot()
    assert master["master_initial_equity_usd"] == pytest.approx(400000.0)
    assert master["master_current_equity_usd"] == pytest.approx(399000.0)
    assert master["master_risk_capacity_usd"] == pytest.approx(1020 + 1000 + 970 + 1000)

    cfg = load_intrabar_paper_config(repo_root=repo)
    eng2 = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    assert eng2.sleeves is not None
    assert eng2.sleeves.get("M15").current_equity_usd == pytest.approx(102000.0)
    assert eng2.sleeves.get("H1").next_risk_budget_usd == pytest.approx(970.0)
    assert eng2.sleeves.get("M30").current_equity_usd == pytest.approx(100000.0)


def test_zero_diff_clone_still_matches(tmp_path: Path, isolated_source_repo: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=isolated_source_repo)
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_ZERO_DIFF_CLONE_SLEEVE2",
        {},
        repo_root=isolated_source_repo,
        output_root=tmp_path / "trading_contract_clones_test",
        source_manifest=source,
    )
    assert clone.diff == {}
    assert clone.fingerprint == clone.source_fingerprint


def test_activation_gate_blocks_with_open_positions(tmp_path: Path):
    import importlib.util

    path = REPO / "scripts/live/activate_per_tf_equity_epoch.py"
    spec = importlib.util.spec_from_file_location("activate_per_tf_equity_epoch", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    epoch_id = "TEST_OPEN_GATE"
    books = tmp_path / "data/trading/intrabar_paper" / epoch_id / "books"
    books.mkdir(parents=True)
    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "trades",
        "positions",
        "blocked",
        "metrics",
        "equity_snapshots",
    ):
        (books / f"{name}.jsonl").touch()
    (books / "positions.jsonl").write_text(
        json.dumps(
            {
                "position_id": "pos_x",
                "timeframe": "H4",
                "side": "LONG",
                "status": "OPEN",
                "quantity": 1.0,
                "entry_price": 64000,
                "stop_loss_price": 63000,
                "take_profit_price": 66000,
                "risk_amount_usd": 1000,
                "paper_epoch_id": epoch_id,
            }
        )
        + "\n"
    )
    flat = mod.evaluate_flat_state(paper_epoch_id=epoch_id, repo_root=tmp_path)
    assert flat["flat"] is False
    assert flat["open_positions"] == 1


def test_full_entry_exit_contract_match_zero_diff_engines(tmp_path: Path):
    _, _, a, _ = _seed_engine(tmp_path, stamp="A1")
    _, _, b, _ = _seed_engine(tmp_path, stamp="B1")
    start = _h4_start()
    end = {
        **_h4_start(3_000_000),
        "context_event_id": "CTX_end_h4",
        "event_type": "CONTEXT_END",
        "previous_context": "LONG_CONTEXT",
        "new_context": "OBSERVE",
        "best_bid": 64700.0,
        "best_ask": 64702.0,
        "bbo_receive_monotonic_ns": 2_999_000,
        "event_timestamp": start["event_timestamp"],
        "decision_available_at": start["decision_available_at"],
    }
    for eng in (a, b):
        eng.bbo.update_from_book_ticker(
            best_bid=64685.0,
            best_ask=64687.82,
            receive_monotonic_ns=1_900_000,
            book_update_id="b1",
            domain="context",
        )
        eng.process_context_event(dict(start))
        eng.process_context_event(dict(end))
    left = {t: a.books.read_all(t) for t in ("signals", "commands", "orders", "fills", "positions", "trades")}
    right = {t: b.books.read_all(t) for t in ("signals", "commands", "orders", "fills", "positions", "trades")}
    assert compare_replay_books(left, right)["status"] == ZERO_DIFF_MATCH


def test_sleeve2_runtime_isolation(tmp_path: Path):
    before = runtime_file_hashes()
    iso = make_isolated_contract_repo(tmp_path, stamp="SLEEVE_HASH", activate_source=True)
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=iso)
    clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_SLEEVE_HASH",
        sleeve2_capital_overrides(),
        repo_root=iso,
        output_root=tmp_path / "out",
        source_manifest=source,
    )
    _seed_engine(tmp_path, stamp="HASHENG")
    after = runtime_file_hashes()
    assert_no_runtime_touch(before, after)
