"""SHADOW-EQCORR1 — isolation, baseline, correlation, sleeves, causality, idempotency."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.shadow_economic_correlation import (
    BASELINE_DIVERGENCE,
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    LOOKAHEAD_VIOLATION,
    WRITE_BOUNDARY_VIOLATION,
)
from btc_ml.trading.shadow_economic_correlation.cluster import build_cluster_snapshot
from btc_ml.trading.shadow_economic_correlation.engine import ShadowEconomicCorrelationEngine
from btc_ml.trading.shadow_economic_correlation.marginal import marginal_contribution
from btc_ml.trading.shadow_economic_correlation.paths import assert_shadow_write_path
from btc_ml.trading.shadow_economic_correlation.policies import decide_policy
from btc_ml.trading.shadow_economic_correlation.sleeves import (
    apply_policy_sizing,
    apply_realized,
    initial_policy_sleeves,
)


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def shadow_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = REPO / "config" / "intrabar_paper_execution.json"
    shutil.copy(cfg_src, repo / "config" / "intrabar_paper_execution.json")
    books = repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    books.mkdir(parents=True)
    for name in ("signals", "commands", "orders", "fills", "positions", "trades"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    epochs = repo / "data" / "trading" / "paper_epochs"
    epochs.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EXPECTED_EPOCH,
                "trading_contract_fingerprint": EXPECTED_ACTIVE_FP,
                "parent_trading_contract_fingerprint": EXPECTED_PARENT_FP,
                "epoch_status": "ACTIVE",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl").write_text("", encoding="utf-8")
    (repo / "data" / "runtime").mkdir(parents=True)
    return repo


def _cand(**over):
    base = {
        "paper_epoch_id": EXPECTED_EPOCH,
        "candidate_id": "c1",
        "position_id": "pos1",
        "timeframe": "M15",
        "side": "LONG",
        "candidate_timestamp": "2026-07-29T19:00:00Z",
        "entry_timestamp": "2026-07-29T19:00:00Z",
        "entry_executable_price": 100_000.0,
        "stop_price": 99_000.0,
        "take_price": 102_000.0,
        "risk_budget_usd": 1000.0,
        "risk_amount_usd": 1000.0,
        "quantity": 1.0,
        "notional_usd": 100_000.0,
        "equity_at_entry_usd": 100_000.0,
        "risk_pct_at_entry": 1.0,
    }
    base.update(over)
    return base


def _seed_entry_chain(repo: Path, *, tf: str = "M15", side: str = "LONG", position_id: str = "pos1") -> None:
    books = repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    fill = {
        "fill_id": "fill1",
        "order_id": "ord1",
        "command_id": "cmd1",
        "action": "ENTRY",
        "timeframe": tf,
        "side": side,
        "quantity": 1.0,
        "paper_fill_price": 100_000.0,
        "ts": "2026-07-29T19:00:00Z",
        "context_event_id": "ctx1",
    }
    pos = {
        "position_id": position_id,
        "status": "OPEN",
        "timeframe": tf,
        "side": side,
        "quantity": 1.0,
        "entry_price": 100_000.0,
        "stop_loss_price": 99_000.0,
        "take_profit_price": 102_000.0,
        "entry_fill_id": "fill1",
        "entry_command_id": "cmd1",
        "entry_context_event_id": "ctx1",
        "lifecycle_episode_id": "ep1",
        "opened_at": "2026-07-29T19:00:00Z",
        "risk_budget_usd": 1000.0,
        "risk_amount_usd": 1000.0,
        "notional_usd": 100_000.0,
        "equity_at_entry_usd": 100_000.0,
        "risk_pct_at_entry": 1.0,
    }
    cmd = {"command_id": "cmd1", "signal_id": "sig1"}
    sig = {
        "signal_id": "sig1",
        "context_event_id": "ctx1",
        "lifecycle_episode_id": "ep1",
        "timeframe": tf,
        "risk_budget_usd": 1000.0,
    }
    for name, rows in (
        ("fills", [fill]),
        ("positions", [pos]),
        ("commands", [cmd]),
        ("signals", [sig]),
    ):
        (books / f"{name}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )


def test_write_boundary_blocks_non_shadow_path(shadow_repo: Path):
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_shadow_write_path(shadow_repo / "data" / "trading" / "intrabar_paper" / "x.json", repo=shadow_repo)


def test_write_boundary_allows_shadow_path(shadow_repo: Path):
    p = shadow_repo / "data" / "trading" / "shadow_economic_correlation" / "health.json"
    p.parent.mkdir(parents=True)
    assert assert_shadow_write_path(p, repo=shadow_repo) == p.resolve()


def test_engine_does_not_write_command_bus_or_positions(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    books = shadow_repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    before_cmd = (books / "commands.jsonl").read_text(encoding="utf-8")
    before_pos = (books / "positions.jsonl").read_text(encoding="utf-8")
    active_before = (shadow_repo / "data" / "trading" / "paper_epochs" / "active.json").read_text(encoding="utf-8")
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.poll_once()
    assert (books / "commands.jsonl").read_text(encoding="utf-8") == before_cmd
    assert (books / "positions.jsonl").read_text(encoding="utf-8") == before_pos
    assert (shadow_repo / "data" / "trading" / "paper_epochs" / "active.json").read_text(encoding="utf-8") == active_before
    # Shadow failure must not raise into caller in poll loop path — poll_once itself is safe.
    assert eng.write_health()["command_bus_write_capability"] is False


def test_source_epoch_mismatch_raises(shadow_repo: Path):
    active = shadow_repo / "data" / "trading" / "paper_epochs" / "active.json"
    active.write_text(json.dumps({"paper_epoch_id": "OTHER", "trading_contract_fingerprint": EXPECTED_ACTIVE_FP}) + "\n")
    with pytest.raises(RuntimeError, match="SOURCE_EPOCH_MISMATCH"):
        ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)


def test_baseline_matches_real_entry(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.poll_once()
    assert eng.baseline_divergence_count == 0
    assert eng.baseline_match_count >= 1
    vpos = [p for p in eng.store.read_all("virtual_positions") if p["policy_id"] == "BASELINE_ALL_ELIGIBLE"]
    assert len(vpos) == 1
    assert vpos[0]["quantity"] == 1.0
    assert vpos[0]["entry_executable_price"] == 100_000.0
    assert abs(vpos[0]["stop_price"] - 99_000.0) < 1e-9


def test_baseline_divergence_invalidates_research(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    cand = _cand(quantity=1.0)
    # Force mismatch via direct check
    eng._check_baseline_entry(cand, {"quantity": 2.0, "entry_executable_price": 100_000.0, "stop_price": 99_000.0, "take_price": 102_000.0})
    assert eng.baseline_divergence_count == 1
    assert eng.research_valid is False
    assert any(BASELINE_DIVERGENCE in e for e in eng.errors)


def test_baseline_sleeve_equity_independent_and_synced(shadow_repo: Path):
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    assert eng.sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]["M15"]["current_equity_usd"] == 100_000.0
    # Apply PnL to MAX_1 only — baseline unchanged
    apply_realized(eng.sleeves, policy_id="MAX_1_SAME_DIRECTION", timeframe="M15", net_pnl_usd=50.0)
    assert eng.sleeves["MAX_1_SAME_DIRECTION"]["sleeves"]["M15"]["current_equity_usd"] == 100_050.0
    assert eng.sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]["M15"]["current_equity_usd"] == 100_000.0
    assert eng.sleeves["MAX_1_SAME_DIRECTION"]["sleeves"]["H1"]["current_equity_usd"] == 100_000.0


def test_arrival_sequence_causal():
    cluster = build_cluster_snapshot(
        candidate=_cand(side="LONG", risk_amount_usd=1000),
        open_positions_before=[
            {"side": "LONG", "timeframe": "H1", "risk_amount_usd": 500, "notional_usd": 50_000},
            {"side": "SHORT", "timeframe": "M30", "risk_amount_usd": 800, "notional_usd": 40_000},
        ],
    )
    assert cluster["arrival_sequence_in_direction_cluster"] == 2
    assert cluster["same_direction_positions_before"] == 1
    assert cluster["opposite_direction_open_risk_before"] == 800
    # Opposite risk not netted from same-direction / master gross
    assert cluster["master_open_risk_before"] == 500 + 800
    assert cluster["gross_risk_before"] == 500 + 800
    assert cluster["opposite_risk_netting_forbidden"] is True


def test_max1_blocks_second_same_direction():
    open1 = [{"side": "LONG", "timeframe": "H1", "risk_amount_usd": 1000}]
    d1 = decide_policy(policy_id="MAX_1_SAME_DIRECTION", candidate=_cand(), cluster={"arrival_sequence_in_direction_cluster": 1}, policy_open_positions=[])
    d2 = decide_policy(policy_id="MAX_1_SAME_DIRECTION", candidate=_cand(timeframe="M30"), cluster={"arrival_sequence_in_direction_cluster": 2}, policy_open_positions=open1)
    assert d1.action == "EXECUTE_FULL"
    assert d2.action == "BLOCK_CORRELATED_EXPOSURE"


def test_max2_blocks_third():
    open2 = [
        {"side": "LONG", "timeframe": "H1", "risk_amount_usd": 1000},
        {"side": "LONG", "timeframe": "M30", "risk_amount_usd": 1000},
    ]
    d = decide_policy(policy_id="MAX_2_SAME_DIRECTION", candidate=_cand(), cluster={}, policy_open_positions=open2)
    assert d.action == "BLOCK_CORRELATED_EXPOSURE"


def test_tactical_structural_one_per_group():
    open_t = [{"side": "LONG", "timeframe": "M15", "risk_amount_usd": 1000}]
    d_m30 = decide_policy(
        policy_id="ONE_TACTICAL_ONE_STRUCTURAL",
        candidate=_cand(timeframe="M30"),
        cluster={},
        policy_open_positions=open_t,
    )
    d_h1 = decide_policy(
        policy_id="ONE_TACTICAL_ONE_STRUCTURAL",
        candidate=_cand(timeframe="H1"),
        cluster={},
        policy_open_positions=open_t,
    )
    assert d_m30.action == "BLOCK_CORRELATED_EXPOSURE"
    assert d_h1.action == "EXECUTE_FULL"


def test_opposite_direction_not_netted_for_caps():
    # Cap 0.25% of 400k = 1000. Same-dir risk 900 + new 1000 > cap → BLOCK.
    # Opposite risk 5000 must not free capacity.
    open_pos = [
        {"side": "LONG", "timeframe": "H1", "risk_amount_usd": 900},
        {"side": "SHORT", "timeframe": "M15", "risk_amount_usd": 5000},
    ]
    d = decide_policy(
        policy_id="DIRECTION_RISK_CAP_025_BLOCK",
        candidate=_cand(side="LONG", risk_budget_usd=1000),
        cluster={},
        policy_open_positions=open_pos,
        master_equity_usd=400_000.0,
    )
    assert d.action == "BLOCK_CORRELATED_EXPOSURE"


def test_gross_risk_absolute_sum():
    cluster = build_cluster_snapshot(
        candidate=_cand(side="LONG", risk_amount_usd=100),
        open_positions_before=[
            {"side": "LONG", "risk_amount_usd": 200, "notional_usd": 1},
            {"side": "SHORT", "risk_amount_usd": 300, "notional_usd": 1},
        ],
    )
    assert cluster["gross_risk_before"] == 500
    assert cluster["master_open_risk_after"] == 600


def test_independent_policy_capital_and_tf_sleeves(shadow_repo: Path):
    sleeves = initial_policy_sleeves()
    apply_realized(sleeves, policy_id="M15_ONLY", timeframe="M15", net_pnl_usd=25.0)
    assert sleeves["M15_ONLY"]["sleeves"]["M15"]["current_equity_usd"] == 100_025.0
    assert sleeves["H1_ONLY"]["sleeves"]["H1"]["current_equity_usd"] == 100_000.0
    assert sleeves["M15_ONLY"]["sleeves"]["H1"]["current_equity_usd"] == 100_000.0
    assert sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]["M15"]["current_equity_usd"] == 100_000.0


def test_reduced_risk_uses_canonical_sizing(shadow_repo: Path):
    cfg = load_intrabar_paper_config(repo_root=shadow_repo)
    sleeves = initial_policy_sleeves()
    full = apply_policy_sizing(
        cfg=cfg, candidate=_cand(), sleeves=sleeves, policy_id="PROGRESSIVE_RISK_REDUCTION", risk_multiplier=1.0
    )
    half = apply_policy_sizing(
        cfg=cfg, candidate=_cand(), sleeves=sleeves, policy_id="PROGRESSIVE_RISK_REDUCTION", risk_multiplier=0.5
    )
    assert full["sizing_path"] == "resolve_risk_sizing"
    assert half["sizing_path"] == "resolve_risk_sizing"
    assert half["effective_risk_budget_usd"] == pytest.approx(500.0)
    assert half["quantity"] is not None and half["quantity"] < full["quantity"]


def test_restart_restores_virtual_equity(shadow_repo: Path):
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    apply_realized(eng.sleeves, policy_id="MAX_2_SAME_DIRECTION", timeframe="M30", net_pnl_usd=10.0)
    eng._save_checkpoint()
    eng2 = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    assert eng2.sleeves["MAX_2_SAME_DIRECTION"]["sleeves"]["M30"]["current_equity_usd"] == 100_010.0


def test_outcome_absent_at_decision(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.poll_once()
    for d in eng.store.read_all("policy_decisions"):
        if d.get("record_type") == "OUTCOME_ATTACHMENT":
            continue
        assert d.get("outcome_fields_present_at_decision") is False
        assert "net_pnl_usd" not in d
        assert d.get("outcome_attached") is False


def test_lookahead_violation_flagged(shadow_repo: Path):
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    # Context event in the future relative to candidate
    ctx_path = shadow_repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
    ctx_path.write_text(
        json.dumps(
            {
                "context_event_id": "ctx1",
                "event_timestamp": "2026-07-29T20:00:00Z",
                "context_event_price": 100_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _seed_entry_chain(shadow_repo)
    eng.poll_once()
    assert eng.lookahead_violation_count >= 1
    decisions = eng.store.read_all("policy_decisions")
    assert any(d.get("lookahead_detected") for d in decisions)
    assert any(d.get("lookahead_status") == LOOKAHEAD_VIOLATION for d in decisions)


def test_decision_immutable_after_outcome(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    books = shadow_repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.poll_once()
    original = [d for d in eng.store.read_all("policy_decisions") if d.get("policy_id") == "BASELINE_ALL_ELIGIBLE"][0]
    trade = {
        "trade_id": "t1",
        "position_id": "pos1",
        "entry_ts": "2026-07-29T19:00:00Z",
        "exit_ts": "2026-07-29T19:30:00Z",
        "exit_price": 101_000.0,
        "exit_reason": "TAKE_PROFIT",
        "gross_pnl_usd": 1000.0,
        "fees_usd": 10.0,
        "slippage_usd": 5.0,
        "net_pnl_usd": 985.0,
        "risk_amount_usd": 1000.0,
    }
    (books / "trades.jsonl").write_text(json.dumps(trade) + "\n", encoding="utf-8")
    # Close position in books for realism
    eng.process_new_closes()
    after = [d for d in eng.store.read_all("policy_decisions") if d.get("policy_id") == "BASELINE_ALL_ELIGIBLE" and not d.get("record_type")]
    assert after[0]["action"] == original["action"]
    assert after[0]["decision_timestamp"] == original["decision_timestamp"]
    attachments = [d for d in eng.store.read_all("policy_decisions") if d.get("record_type") == "OUTCOME_ATTACHMENT"]
    assert attachments
    assert attachments[0].get("decision_immutable") is True


def test_idempotent_candidate_and_close(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    books = shadow_repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.poll_once()
    eng.poll_once()
    assert len(eng.processed_candidates) == 1
    baseline_opens = [p for p in eng.store.read_all("virtual_positions") if p["policy_id"] == "BASELINE_ALL_ELIGIBLE"]
    assert len(baseline_opens) == 1
    trade = {
        "trade_id": "t1",
        "position_id": "pos1",
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
    (books / "trades.jsonl").write_text(json.dumps(trade) + "\n", encoding="utf-8")
    eng.process_new_closes()
    eng.process_new_closes()
    assert len(eng.processed_closes) == 1
    eq = eng.sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]["M15"]["current_equity_usd"]
    # Restart must not duplicate open positions
    eng2 = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    assert eng2.virtual_open_counts()["BASELINE_ALL_ELIGIBLE"] == 0
    assert eng2.sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]["M15"]["current_equity_usd"] == eq


def test_marginal_contribution_blocked_vs_executed():
    blocked = marginal_contribution(
        with_candidate_net_pnl=0.0,
        without_candidate_net_pnl=0.0,
        with_candidate_peak_equity=None,
        without_candidate_peak_equity=None,
        with_candidate_trough_equity=None,
        without_candidate_trough_equity=None,
        risk_used_usd=0.0,
        capital_used_usd=0.0,
        blocked=True,
        counterfactual_net_pnl=-200.0,
    )
    assert blocked["loss_avoided_if_blocked"] == 200.0
    assert blocked["sharpe"] == "INSUFFICIENT_SAMPLE"


def test_shadow_failure_does_not_mutate_live1b_books(shadow_repo: Path):
    _seed_entry_chain(shadow_repo)
    books = shadow_repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    before_names = {p.name for p in books.glob("*")}
    before = {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    eng = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    eng.errors.append("synthetic_failure")
    eng.write_health()
    eng.poll_once()
    after_names = {p.name for p in books.glob("*")}
    after = {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    assert before_names == after_names
    assert before == after
