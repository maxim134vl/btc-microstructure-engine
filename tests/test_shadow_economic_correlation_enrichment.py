"""SHADOW-EQCORR1.1 — causal cognition feature enrichment tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.trading.shadow_economic_correlation import (
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    POLICY_IDS,
)
from btc_ml.trading.shadow_economic_correlation.enrichment import (
    STATUS_FUTURE_ROW_REJECTED,
    STATUS_MISSING,
    STATUS_NOT_AVAILABLE_AT_DECISION_TIME,
    STATUS_NOT_CANONICALLY_AVAILABLE,
    STATUS_STALE,
    STATUS_VALID,
    CausalFeatureEnricher,
    SOURCE_SPECS,
)
from btc_ml.trading.shadow_economic_correlation.engine import ShadowEconomicCorrelationEngine


REPO = Path(__file__).resolve().parents[1]


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


@pytest.fixture
def enrich_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "intrabar_paper_execution.json", repo / "config" / "intrabar_paper_execution.json")
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

    # Cognition sources with known causal rows
    _write_parquet(
        repo / "data/cognition/runtime_cognition_memory.parquet",
        [
            {
                "timestamp": "2026-07-29T18:00:00Z",
                "synthesis_state": "OLD",
                "trigger_event": "OLD_TRIGGER",
                "persistence": "NONE",
                "persistence_score": 0.1,
                "structural_rank": "LOW",
                "alignment_score": 0.1,
                "location_bias": "NONE",
                "auction_state": "NEUTRAL",
            },
            {
                "timestamp": "2026-07-29T18:30:00Z",
                "synthesis_state": "LOCAL_EXHAUSTION",
                "trigger_event": "STOPPING_VOLUME",
                "persistence": "M15_ONLY",
                "persistence_score": 0.25,
                "structural_rank": "LOW",
                "alignment_score": 0.25,
                "location_bias": "LOWER_ABSORPTION",
                "auction_state": "NEUTRAL",
            },
            {
                "timestamp": "2026-07-29T19:00:00Z",  # future vs decision 18:40
                "synthesis_state": "FUTURE_SHOULD_NOT_JOIN",
                "trigger_event": "FUTURE",
                "persistence": "ALL",
                "persistence_score": 0.99,
                "structural_rank": "HIGH",
                "alignment_score": 0.99,
                "location_bias": "FUTURE_BIAS",
                "auction_state": "BULLISH",
            },
        ],
    )
    _write_parquet(
        repo / "data/cognition/multi_timeframe_synthesis.parquet",
        [
            {
                "timestamp": "2026-07-29T18:15:00Z",
                "synthesis_state": "MTF",
                "trigger_event": "T",
                "persistence": "M15_ONLY",
                "persistence_score": 0.2,
                "structural_rank": "LOW",
                "alignment_score": 0.2,
                "location_bias": "LOWER_ABSORPTION",
            }
        ],
    )
    _write_parquet(
        repo / "data/reinforcement/auction_reinforcement_memory.parquet",
        [
            {
                "timestamp": "2026-07-29T18:30:00Z",
                "alignment_status": "MISSING",
                "auction_state": "NEUTRAL",
                "localized_behavior": "localized_absorption",
                "effort_result_state": "ABSORPTION_RESPONSE",
            }
        ],
    )
    _write_parquet(
        repo / "data/probabilistic/probabilistic_auction_memory.parquet",
        [
            {
                "timestamp": "2026-07-29T18:30:00Z",
                "auction_regime": "UNCERTAIN",
                "absorption_probability": 0.2,
                "distribution_probability": 0.28,
                "conviction_probability": 0.0,
                "alignment_status": "MISSING",
                "trigger_event": None,
            }
        ],
    )
    _write_parquet(
        repo / "data/reinforcement/auction_synthesis_memory.parquet",
        [{"timestamp": "2026-07-29T17:45:00Z", "auction_state": "NEUTRAL"}],
    )
    _write_parquet(
        repo / "data/cognition/volume_response_state.parquet",
        [
            {
                "timestamp": "2026-07-29T18:20:00Z",
                "source_timeframe": "M15",
                "unfinished_auction": True,
                "localized_behavior": "localized_absorption",
                "effort_result_state": "ABSORPTION_RESPONSE",
                "volume_event": "NEUTRAL_VOLUME",
            },
            {
                "timestamp": "2026-07-29T18:25:00Z",
                "source_timeframe": "H1",
                "unfinished_auction": False,
                "localized_behavior": "other",
                "effort_result_state": "OTHER",
                "volume_event": "CLIMAX",
            },
            {
                "timestamp": "2026-07-29T19:10:00Z",
                "source_timeframe": "M15",
                "unfinished_auction": False,
                "localized_behavior": "FUTURE",
                "effort_result_state": "FUTURE",
                "volume_event": "FUTURE",
            },
        ],
    )
    return repo


def _seed_entry(repo: Path, *, tf: str = "M15", position_id: str = "pos1", fill_id: str = "fill1") -> None:
    books = repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    fill = {
        "fill_id": fill_id,
        "order_id": "ord1",
        "command_id": "cmd1",
        "action": "ENTRY",
        "timeframe": tf,
        "side": "LONG",
        "quantity": 1.0,
        "paper_fill_price": 100_000.0,
        "ts": "2026-07-29T18:40:00Z",
        "context_event_id": "ctx1",
    }
    pos = {
        "position_id": position_id,
        "status": "OPEN",
        "timeframe": tf,
        "side": "LONG",
        "quantity": 1.0,
        "entry_price": 100_000.0,
        "stop_loss_price": 99_000.0,
        "take_profit_price": 102_000.0,
        "entry_fill_id": fill_id,
        "entry_command_id": "cmd1",
        "entry_context_event_id": "ctx1",
        "lifecycle_episode_id": "ep1",
        "opened_at": "2026-07-29T18:40:00Z",
        "risk_budget_usd": 1000.0,
        "risk_amount_usd": 1000.0,
        "notional_usd": 100_000.0,
        "equity_at_entry_usd": 100_000.0,
    }
    for name, rows in (
        ("fills", [fill]),
        ("positions", [pos]),
        ("commands", [{"command_id": "cmd1", "signal_id": "sig1"}]),
        ("signals", [{"signal_id": "sig1", "context_event_id": "ctx1", "timeframe": tf}]),
    ):
        (books / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_backward_asof_never_selects_future(enrich_repo: Path):
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    spec = next(s for s in SOURCE_SPECS if s.artifact_id == "runtime_cognition_memory")
    join = enricher.backward_asof(spec=spec, decision_timestamp="2026-07-29T18:40:00Z", timeframe="M15")
    assert join["status"] == STATUS_VALID
    assert join["source_row_timestamp"].startswith("2026-07-29T18:30:00")
    assert join["row"]["synthesis_state"] == "LOCAL_EXHAUSTION"
    assert join["row"]["synthesis_state"] != "FUTURE_SHOULD_NOT_JOIN"
    assert str(join["max_input_timestamp"]) <= "2026-07-29T18:40:00Z"


def test_same_timeframe_required_for_volume_response(enrich_repo: Path):
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    spec = next(s for s in SOURCE_SPECS if s.artifact_id == "volume_response_state")
    join_m15 = enricher.backward_asof(spec=spec, decision_timestamp="2026-07-29T18:40:00Z", timeframe="M15")
    join_h4 = enricher.backward_asof(spec=spec, decision_timestamp="2026-07-29T18:40:00Z", timeframe="H4")
    assert join_m15["same_timeframe_match"] is True
    assert join_m15["row"]["volume_event"] == "NEUTRAL_VOLUME"
    assert join_h4["status"] in (STATUS_MISSING, "WRONG_TIMEFRAME")
    assert join_h4.get("row") is None


def test_later_row_rejected(enrich_repo: Path):
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    spec = next(s for s in SOURCE_SPECS if s.artifact_id == "runtime_cognition_memory")
    join = enricher.backward_asof(spec=spec, decision_timestamp="2026-07-29T18:40:00Z", timeframe="M15")
    assert join["row"]["location_bias"] != "FUTURE_BIAS"
    assert enricher.future_row_rejected_count >= 1


def test_missing_not_neutralized(enrich_repo: Path):
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    row = enricher.enrich_candidate(
        candidate={"candidate_id": "c1", "timeframe": "M15", "side": "LONG"},
        decision_timestamp="2026-07-29T18:40:00Z",
        source_epoch_id=EXPECTED_EPOCH,
        source_contract_fingerprint=EXPECTED_ACTIVE_FP,
        shadow_policy_manifest_fingerprint="fp",
    )
    feats = row["features"]
    assert feats["reinforcement_state_value"] is None
    assert feats["reinforcement_state_status"] == STATUS_NOT_CANONICALLY_AVAILABLE
    assert feats["validation_state_status"] == STATUS_NOT_AVAILABLE_AT_DECISION_TIME
    assert feats["conviction_strength_value"] is None


def test_stale_keeps_value_and_age(enrich_repo: Path):
    # Force stale by rewriting reinforcement with old timestamp beyond 1800s budget
    _write_parquet(
        enrich_repo / "data/reinforcement/auction_reinforcement_memory.parquet",
        [
            {
                "timestamp": "2026-07-29T17:00:00Z",  # age at 18:40 = 6000s > 1800
                "alignment_status": "ALIGNED",
                "auction_state": "NEUTRAL",
                "localized_behavior": "localized_absorption",
                "effort_result_state": "ABSORPTION_RESPONSE",
            }
        ],
    )
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    row = enricher.enrich_candidate(
        candidate={"candidate_id": "c1", "timeframe": "M15", "side": "LONG"},
        decision_timestamp="2026-07-29T18:40:00Z",
        source_epoch_id=EXPECTED_EPOCH,
        source_contract_fingerprint=EXPECTED_ACTIVE_FP,
        shadow_policy_manifest_fingerprint="fp",
    )
    feats = row["features"]
    assert feats["alignment_status_value"] == "ALIGNED"
    assert feats["alignment_status_status"] == STATUS_STALE
    assert feats["alignment_status_age_seconds_at_decision"] == pytest.approx(6000.0)


def test_policy_decision_immutable_and_no_outcome_in_enrichment(enrich_repo: Path):
    _seed_entry(enrich_repo)
    eng = ShadowEconomicCorrelationEngine(repo=enrich_repo, strict_epoch=True)
    eng.poll_once()
    decisions = [d for d in eng.store.read_all("policy_decisions") if not d.get("record_type")]
    assert len(decisions) == len(POLICY_IDS)
    # Re-run must not mutate original decision rows
    original = json.dumps(decisions[0], sort_keys=True)
    eng.poll_once()
    again = [d for d in eng.store.read_all("policy_decisions") if not d.get("record_type")]
    assert json.dumps(again[0], sort_keys=True) == original
    enrich = eng.store.read_all("candidate_feature_enrichments")
    assert enrich
    assert enrich[0]["outcome_fields_present"] is False
    assert "net_pnl_usd" not in enrich[0]
    assert "quality_score" not in enrich[0]


def test_enrichment_idempotent(enrich_repo: Path):
    _seed_entry(enrich_repo)
    eng = ShadowEconomicCorrelationEngine(repo=enrich_repo, strict_epoch=True)
    eng.poll_once()
    n1 = len(eng.store.read_all("candidate_feature_enrichments"))
    eng.poll_once()
    eng.backfill_enrichments()
    n2 = len(eng.store.read_all("candidate_feature_enrichments"))
    assert n1 == n2 == 1


def test_historical_candidate_not_enriched_with_current_tip(enrich_repo: Path):
    enricher = CausalFeatureEnricher(repo=enrich_repo)
    row = enricher.enrich_candidate(
        candidate={"candidate_id": "hist", "timeframe": "M15", "side": "LONG"},
        decision_timestamp="2026-07-29T18:40:00Z",
        source_epoch_id=EXPECTED_EPOCH,
        source_contract_fingerprint=EXPECTED_ACTIVE_FP,
        shadow_policy_manifest_fingerprint="fp",
        historical=True,
    )
    assert row["features"]["synthesis_state_value"] == "LOCAL_EXHAUSTION"
    assert row["features"]["synthesis_state_value"] != "FUTURE_SHOULD_NOT_JOIN"
    assert str(row["max_input_timestamp"]) <= "2026-07-29T18:40:00Z"


def test_baseline_parity_and_virtuals_unchanged_by_enrichment(enrich_repo: Path):
    _seed_entry(enrich_repo)
    eng = ShadowEconomicCorrelationEngine(repo=enrich_repo, strict_epoch=True)
    eng.poll_once()
    baseline_div = eng.baseline_divergence_count
    baseline_match = eng.baseline_match_count
    sleeves_before = json.dumps(eng.sleeves, sort_keys=True)
    vpos_before = len(eng.store.read_all("virtual_positions"))
    # Force enrichment path again
    eng.backfill_enrichments()
    assert eng.baseline_divergence_count == baseline_div
    assert eng.baseline_match_count == baseline_match
    assert json.dumps(eng.sleeves, sort_keys=True) == sleeves_before
    assert len(eng.store.read_all("virtual_positions")) == vpos_before


def test_snapshots_and_decisions_not_rewritten(enrich_repo: Path):
    _seed_entry(enrich_repo)
    eng = ShadowEconomicCorrelationEngine(repo=enrich_repo, strict_epoch=True)
    eng.poll_once()
    snap_path = eng.store.root / "candidate_snapshots.jsonl"
    dec_path = eng.store.root / "policy_decisions.jsonl"
    snap_bytes = snap_path.read_bytes()
    # Only count immutable decision rows content length before backfill
    dec_lines_before = [ln for ln in dec_path.read_text().splitlines() if ln.strip()]
    eng.backfill_enrichments()
    assert snap_path.read_bytes() == snap_bytes
    dec_lines_after = [ln for ln in dec_path.read_text().splitlines() if ln.strip()]
    assert dec_lines_after == dec_lines_before
