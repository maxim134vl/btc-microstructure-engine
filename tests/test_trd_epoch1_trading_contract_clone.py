"""TRD-EPOCH1: full trading-contract clone + zero-diff / risk-delta proofs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import resolve_risk_sizing
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch, load_active_epoch
from btc_ml.trading.intrabar_paper.trading_contract import (
    CANONICAL_SOURCE_EPOCH,
    NEW_EPOCH_ACTIVATION_BLOCKED,
    RISK_DELTA_VIOLATION,
    ZERO_DIFF_MATCH,
    active_epoch_unchanged,
    build_trading_contract_manifest,
    check_new_epoch_activation_gate,
    clone_trading_epoch_contract,
    compare_replay_books,
    compute_risk_budget_usd,
    current_equity_usd_for_timeframe,
    prepare_new_epoch_activation_plan,
    risk_delta_overrides_per_tf_equity,
    size_with_contract,
    trading_contract_fingerprint,
    validate_risk_only_diff,
)

REPO = Path(__file__).resolve().parents[1]


def _ctx(
    *,
    eid: str,
    etype: str,
    tf: str,
    new: str,
    mono: int,
    episode: str,
    bid: float = 64685.0,
    ask: float = 64687.82,
    prev: str = "OBSERVE",
) -> dict:
    return {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": "2026-07-29T09:40:34.724226Z",
        "context_event_price": 64690.19,
        "best_bid": bid,
        "best_ask": ask,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": episode,
    }


def _make_engine(tmp_path: Path, *, epoch_id_stamp: str, equity: float = 100000.0):
    repo = tmp_path / f"repo_{epoch_id_stamp}"
    (repo / "config").mkdir(parents=True)
    cfg_src = REPO / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["initial_equity_usd"] = equity
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=repo)
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=equity,
        utc_stamp=epoch_id_stamp,
    )
    ep = activate_epoch(ep, epochs_root=cfg.epochs_root)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=64685.0,
        best_ask=64687.82,
        receive_monotonic_ns=1_000_000,
        receive_timestamp="2026-07-29T09:40:00Z",
        book_update_id="seed",
        domain="context",
    )
    return cfg, repo, eng


def _run_scenario(eng: IntrabarPaperEngine) -> None:
    events = [
        _ctx(
            eid="CTX_d25c0ed08fd7b1d5c8af",
            etype="CONTEXT_START",
            tf="H4",
            new="LONG_CONTEXT",
            mono=2_000_000,
            episode="H4:prov:1",
        ),
        _ctx(
            eid="CTX_end_h4_1",
            etype="CONTEXT_END",
            tf="H4",
            new="OBSERVE",
            prev="LONG_CONTEXT",
            mono=3_000_000,
            episode="H4:prov:1",
            bid=64700.0,
            ask=64702.0,
        ),
        _ctx(
            eid="CTX_start_m15",
            etype="CONTEXT_START",
            tf="M15",
            new="LONG_CONTEXT",
            mono=4_000_000,
            episode="M15:prov:1",
        ),
        _ctx(
            eid="CTX_end_m15",
            etype="CONTEXT_END",
            tf="M15",
            new="OBSERVE",
            prev="LONG_CONTEXT",
            mono=4_500_000,
            episode="M15:prov:1",
            bid=64710.0,
            ask=64712.0,
        ),
        # Same episode after flat → episode dedup
        _ctx(
            eid="CTX_start_m15_dup",
            etype="CONTEXT_START",
            tf="M15",
            new="LONG_CONTEXT",
            mono=5_000_000,
            episode="M15:prov:1",
        ),
        _ctx(
            eid="CTX_start_m15_b",
            etype="CONTEXT_START",
            tf="M15",
            new="LONG_CONTEXT",
            mono=5_500_000,
            episode="M15:prov:2",
        ),
        _ctx(
            eid="CTX_flip_m15",
            etype="CONTEXT_FLIP",
            tf="M15",
            new="SHORT_CONTEXT",
            prev="LONG_CONTEXT",
            mono=6_000_000,
            episode="M15:prov:2",
            bid=64680.0,
            ask=64682.0,
        ),
    ]
    for ev in events:
        eng.bbo.update_from_book_ticker(
            best_bid=float(ev["best_bid"]),
            best_ask=float(ev["best_ask"]),
            receive_monotonic_ns=int(ev["bbo_receive_monotonic_ns"]),
            receive_timestamp=ev["event_timestamp"],
            book_update_id=str(ev["book_update_id"]),
            domain="context",
        )
        eng.process_context_event(ev)
    if "M15" in eng.positions:
        pos = eng.positions["M15"]
        if pos.side == "SHORT":
            sl = float(pos.stop_loss_price)
            eng.update_bbo_from_market(
                best_bid=sl,
                best_ask=sl + 1.0,
                receive_monotonic_ns=7_000_000,
                receive_timestamp="2026-07-29T10:00:00Z",
                book_update_id="sl",
                source_event_id="sl_tick",
            )
        else:
            sl = float(pos.stop_loss_price)
            eng.update_bbo_from_market(
                best_bid=sl - 1.0,
                best_ask=sl,
                receive_monotonic_ns=7_000_000,
                receive_timestamp="2026-07-29T10:00:00Z",
                book_update_id="sl",
                source_event_id="sl_tick",
            )


def _books(eng: IntrabarPaperEngine) -> dict:
    return {
        "signals": eng.books.read_all("signals"),
        "commands": eng.books.read_all("commands"),
        "orders": eng.books.read_all("orders"),
        "fills": eng.books.read_all("fills"),
        "positions": eng.books.read_all("positions"),
        "trades": eng.books.read_all("trades"),
        "blocked": eng.books.read_all("blocked"),
    }


def test_01_full_manifest_no_unknown_critical():
    manifest = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    assert manifest["completeness"]["status"] == "COMPLETE"
    assert manifest["completeness"]["critical_unknown"] == []
    assert manifest["capital"]["capital_model"] == "SHARED_MASTER_REALIZED_EQUITY"
    assert manifest["protection_geometry"]["risk_reward_ratio"] == pytest.approx(1.5)
    assert "execution_config_snapshot" in manifest["legacy_epoch_gaps"]["not_in_epoch_json_before_clone"]


def test_02_03_zero_diff_clone_manifest_and_fingerprint(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_ZERO_DIFF_CLONE",
        {},
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    assert clone.diff == {}
    assert clone.fingerprint == clone.source_fingerprint
    assert clone.fingerprint == trading_contract_fingerprint(source)
    active = load_active_epoch(load_intrabar_paper_config(repo_root=REPO).epochs_root)
    assert active is not None
    assert active.paper_epoch_id == CANONICAL_SOURCE_EPOCH
    assert clone.new_epoch_id != active.paper_epoch_id


def test_04_zero_diff_replay(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_ZERO_DIFF_CLONE",
        {},
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    assert clone.fingerprint == clone.source_fingerprint

    _, _, eng_a = _make_engine(tmp_path, epoch_id_stamp="SRCZERO")
    _, _, eng_b = _make_engine(tmp_path, epoch_id_stamp="CLNZERO")
    _run_scenario(eng_a)
    _run_scenario(eng_b)
    result = compare_replay_books(_books(eng_a), _books(eng_b))
    assert result["status"] == ZERO_DIFF_MATCH, result


def test_05_risk_only_clone_allowlisted_diff(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    overrides = risk_delta_overrides_per_tf_equity()
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_RISK_DELTA_CLONE",
        overrides,
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    validate_risk_only_diff(clone.diff)
    assert "capital.capital_model" in clone.diff
    assert clone.diff["capital.capital_model"]["to"] == "PER_TIMEFRAME_REALIZED_EQUITY"
    with pytest.raises(RuntimeError, match=RISK_DELTA_VIOLATION):
        clone_trading_epoch_contract(
            CANONICAL_SOURCE_EPOCH,
            "TEST_BAD",
            {"exit_rules.context_end": "CHANGED"},
            repo_root=REPO,
            output_root=tmp_path / "clones",
            source_manifest=source,
        )


def test_06_07_risk_budget_and_quantity_match_at_100k(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    risk = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_RISK_DELTA_CLONE",
        risk_delta_overrides_per_tf_equity(),
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    budget = compute_risk_budget_usd(risk.manifest, timeframe="H4", current_equity_usd=100_000.0)
    assert budget == pytest.approx(1000.0)

    cfg = load_intrabar_paper_config(repo_root=REPO)
    entry = 64687.82
    cur = resolve_risk_sizing(cfg=cfg, side="LONG", entry_price=entry, equity_usd=100_000.0)
    der = size_with_contract(
        cfg=cfg,
        manifest=risk.manifest,
        side="LONG",
        entry_price=entry,
        timeframe="H4",
        current_equity_usd=100_000.0,
    )
    assert der.risk_amount_usd == pytest.approx(1000.0)
    assert der.quantity == pytest.approx(cur.quantity)
    assert der.entry_price == pytest.approx(cur.entry_price)
    assert der.stop_loss_price == pytest.approx(64040.9418)
    assert der.take_profit_price == pytest.approx(65658.1373)
    assert der.stop_loss_price == pytest.approx(cur.stop_loss_price)
    assert der.take_profit_price == pytest.approx(cur.take_profit_price)
    from btc_ml.trading.intrabar_paper import economics as eco
    from btc_ml.trading.intrabar_paper import trading_contract as tc

    assert tc.resolve_risk_sizing is eco.resolve_risk_sizing


def test_08_09_10_different_equity_only_quantity_fields_change(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    risk = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_RISK_DELTA_CLONE_EQ",
        risk_delta_overrides_per_tf_equity(),
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    cfg = load_intrabar_paper_config(repo_root=REPO)
    entry = 64687.82
    a = size_with_contract(
        cfg=cfg,
        manifest=source,
        side="LONG",
        entry_price=entry,
        timeframe="H4",
        current_equity_usd=100_000.0,
    )
    b = size_with_contract(
        cfg=cfg,
        manifest=risk.manifest,
        side="LONG",
        entry_price=entry,
        timeframe="H4",
        current_equity_usd=200_000.0,
    )
    assert a.entry_price == pytest.approx(b.entry_price)
    assert a.stop_loss_price == pytest.approx(b.stop_loss_price)
    assert a.take_profit_price == pytest.approx(b.take_profit_price)
    assert b.risk_amount_usd == pytest.approx(2000.0)
    assert b.quantity != pytest.approx(a.quantity)
    assert b.entry_notional != pytest.approx(a.entry_notional)


def test_11_13_14_context_dedup_end_flip_tpsl_unchanged_in_zero_diff(tmp_path: Path):
    _, _, eng_a = _make_engine(tmp_path, epoch_id_stamp="DEDUPA")
    _, _, eng_b = _make_engine(tmp_path, epoch_id_stamp="DEDUPB")
    _run_scenario(eng_a)
    _run_scenario(eng_b)
    ba, bb = _books(eng_a), _books(eng_b)
    assert any(r.get("reason") == "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED" for r in ba["blocked"])
    assert compare_replay_books(ba, bb)["status"] == ZERO_DIFF_MATCH
    assert len(ba["trades"]) >= 1


def test_12_context_end_flip_rules_in_manifest_stable(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    zero = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_ZERO_DIFF_CLONE2",
        {},
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    assert zero.manifest["exit_rules"]["context_end"] == source["exit_rules"]["context_end"]
    assert zero.manifest["exit_rules"]["context_flip"] == source["exit_rules"]["context_flip"]
    risk = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_RISK_DELTA_CLONE2",
        risk_delta_overrides_per_tf_equity(),
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    assert risk.manifest["exit_rules"] == source["exit_rules"]
    assert (
        risk.manifest["context_consumption"]["episode_dedup_key"]
        == source["context_consumption"]["episode_dedup_key"]
    )
    assert risk.manifest["costs"] == source["costs"]
    assert risk.manifest["protection_geometry"] == source["protection_geometry"]
    assert risk.manifest["market_execution"] == source["market_execution"]


def test_15_current_positions_and_epoch_unchanged():
    info = active_epoch_unchanged(repo_root=REPO)
    assert info["unchanged"] is True
    assert info["active_paper_epoch_id"] == CANONICAL_SOURCE_EPOCH
    books = REPO / "data" / "trading" / "intrabar_paper" / CANONICAL_SOURCE_EPOCH / "books"
    assert books.exists()


def test_16_activation_blocked_with_open_positions(tmp_path: Path):
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=REPO)
    risk = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        "TEST_RISK_DELTA_CLONE_ACT",
        risk_delta_overrides_per_tf_equity(),
        repo_root=REPO,
        output_root=tmp_path / "clones",
        source_manifest=source,
    )
    epoch_id = "TEST_GATE_THREE_OPENS"
    books_root = tmp_path / "data" / "trading" / "intrabar_paper" / epoch_id / "books"
    books_root.mkdir(parents=True)
    lines = []
    for i, tf in enumerate(("M15", "M30", "H4")):
        lines.append(
            json.dumps(
                {
                    "position_id": f"pos_open_{i}",
                    "timeframe": tf,
                    "side": "LONG",
                    "status": "OPEN",
                    "quantity": 1.0,
                    "entry_price": 64000.0,
                    "stop_loss_price": 63000.0,
                    "take_profit_price": 66000.0,
                    "paper_epoch_id": epoch_id,
                }
            )
        )
    (books_root / "positions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "trades",
        "blocked",
        "metrics",
        "equity_snapshots",
    ):
        (books_root / f"{name}.jsonl").touch()

    gate = check_new_epoch_activation_gate(
        source_epoch_id=epoch_id,
        source_fingerprint=risk.source_fingerprint,
        expected_source_fingerprint=risk.source_fingerprint,
        risk_only_diff=risk.diff,
        live1b_running=True,
        repo_root=tmp_path,
    )
    assert gate.allowed is False
    assert gate.status == NEW_EPOCH_ACTIVATION_BLOCKED
    assert gate.open_positions == 3

    live_gate = check_new_epoch_activation_gate(
        source_epoch_id=CANONICAL_SOURCE_EPOCH,
        source_fingerprint=risk.source_fingerprint,
        expected_source_fingerprint=risk.source_fingerprint,
        risk_only_diff=risk.diff,
        live1b_running=None,
        repo_root=REPO,
    )
    assert live_gate.status == NEW_EPOCH_ACTIVATION_BLOCKED

    plan = prepare_new_epoch_activation_plan(
        source_epoch_id=CANONICAL_SOURCE_EPOCH,
        new_epoch_id=risk.new_epoch_id,
        clone=risk,
        repo_root=REPO,
    )
    assert plan["allowed"] is False
    assert plan["status"] == NEW_EPOCH_ACTIVATION_BLOCKED


def test_realized_equity_semantics_no_double_fee():
    eq = current_equity_usd_for_timeframe(
        initial_equity_usd=100_000.0,
        cumulative_realized_net_pnl_usd=-50.0,
    )
    assert eq == pytest.approx(99_950.0)
