"""Regression coverage for closed-bar context event materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.live.intrabar.closed_bar_event_bridge import (
    EVENT_TIME_CONTRACT,
    PROVIDER_ID,
    materialize_closed_bar_events,
)
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


def _journal(tmp_path: Path) -> ContextEventJournal:
    return ContextEventJournal(tmp_path / "events")


def _bbo(ts: str = "2026-08-02T12:16:02Z", mono: int = 2_000_000) -> dict:
    return {
        "best_bid": 100.0,
        "best_ask": 100.2,
        "book_update_id": f"bbo-{mono}",
        "bbo_receive_timestamp": ts,
        "bbo_receive_monotonic_ns": mono,
    }


def _row(
    *,
    current: str,
    previous: str = "OBSERVE",
    tf: str = "M15",
    source_bar: str = "2026-08-02T12:15:00Z",
    decision_at: str = "2026-08-02T12:16:00Z",
    episode: str = "ep1",
    origin: str | None = None,
    action_allowed: bool = True,
    intent: str | None = None,
    stale: bool = False,
) -> dict:
    if intent is None:
        intent = "INTENT_OPEN_LONG" if current == "LONG_CONTEXT" else "INTENT_OPEN_SHORT"
    return {
        "decision_id": f"dec-{tf}-{source_bar}-{current}",
        "source_timeframe": tf,
        "candle_timestamp": source_bar,
        "decision_written_at_utc": decision_at,
        "active_market_context": current,
        "previous_active_market_context": previous,
        "lifecycle_state": "ACTIVE" if current in {"LONG_CONTEXT", "SHORT_CONTEXT"} else "NO_ACTIVE_CONTEXT",
        "lifecycle_episode_id": episode,
        "active_context_started_at": origin or source_bar,
        "action_allowed": action_allowed,
        "paper_action_candidate": intent,
        "intended_side": "LONG" if current == "LONG_CONTEXT" else ("SHORT" if current == "SHORT_CONTEXT" else "NONE"),
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL" if intent and intent.startswith("INTENT") else "BLOCKED_NOT_DIRECTIONAL",
        "decision_freshness_status": "STALE" if stale else "FRESH",
        "decision_stale": stale,
        "pipeline_pending": False,
        "close": 90.0,
    }


def _materialize(tmp_path: Path, rows: list[dict], **kwargs):
    journal = kwargs.pop("journal", _journal(tmp_path))
    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id=kwargs.pop("provider_id", PROVIDER_ID),
        epoch_id=kwargs.pop("epoch_id", "EPOCH1"),
        current_bbo=kwargs.pop("current_bbo", _bbo()),
        bridge_activated_at=kwargs.pop("bridge_activated_at", "2026-08-02T12:00:00Z"),
        active_positions_by_timeframe=kwargs.pop("active_positions_by_timeframe", set()),
        traded_episodes=kwargs.pop("traded_episodes", set()),
    )
    assert not kwargs
    return journal, result


def test_completed_bar_long_start_creates_one_event(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="LONG_CONTEXT")])
    assert result.emitted_count == 1
    ev = result.emitted[0]
    assert ev["event_type"] == "CONTEXT_START"
    assert ev["direction"] == "LONG"
    assert ev["event_time_contract"] == EVENT_TIME_CONTRACT


def test_completed_bar_short_start_creates_one_event(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="SHORT_CONTEXT")])
    assert result.emitted_count == 1
    assert result.emitted[0]["event_type"] == "CONTEXT_START"
    assert result.emitted[0]["direction"] == "SHORT"


def test_long_to_short_creates_one_flip(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="SHORT_CONTEXT", previous="LONG_CONTEXT")])
    assert result.emitted_count == 1
    assert result.emitted[0]["event_type"] == "CONTEXT_FLIP"
    assert result.emitted[0]["previous_context"] == "LONG_CONTEXT"
    assert result.emitted[0]["new_context"] == "SHORT_CONTEXT"


def test_short_to_long_creates_one_flip(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="LONG_CONTEXT", previous="SHORT_CONTEXT")])
    assert result.emitted_count == 1
    assert result.emitted[0]["event_type"] == "CONTEXT_FLIP"
    assert result.emitted[0]["direction"] == "LONG"


def test_directional_to_observe_creates_context_end(tmp_path: Path):
    row = _row(current="OBSERVE", previous="LONG_CONTEXT", intent="NO_TRADE_OBSERVE", action_allowed=False)
    _, result = _materialize(tmp_path, [row])
    assert result.emitted_count == 1
    assert result.emitted[0]["event_type"] == "CONTEXT_END"
    assert result.emitted[0]["direction"] == "LONG"


def test_rerunning_writer_produces_no_duplicate(tmp_path: Path):
    row = _row(current="LONG_CONTEXT")
    journal, first = _materialize(tmp_path, [row])
    _, second = _materialize(tmp_path, [row], journal=journal, current_bbo=_bbo(mono=3_000_000))
    assert first.emitted_count == 1
    assert second.emitted_count == 0
    assert second.duplicate_events == 1
    lines = (tmp_path / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_pre_activation_active_long_does_not_emit_retroactively(tmp_path: Path):
    row = _row(
        current="LONG_CONTEXT",
        previous="LONG_CONTEXT",
        source_bar="2026-08-02T11:45:00Z",
        decision_at="2026-08-02T11:46:00Z",
        origin="2026-08-02T08:30:00Z",
    )
    _, result = _materialize(tmp_path, [row], bridge_activated_at="2026-08-02T12:00:00Z")
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "PRE_BRIDGE_ACTIVATION_ROW"


def test_first_fresh_post_activation_bar_revalidates_active_long(tmp_path: Path):
    row = _row(
        current="LONG_CONTEXT",
        previous="LONG_CONTEXT",
        source_bar="2026-08-02T12:15:00Z",
        decision_at="2026-08-02T12:16:00Z",
        origin="2026-08-02T08:30:00Z",
    )
    _, result = _materialize(tmp_path, [row], bridge_activated_at="2026-08-02T12:00:00Z")
    assert result.emitted_count == 1
    ev = result.emitted[0]
    assert ev["event_type"] == "CONTEXT_START"
    assert ev["revalidated_after_restart"] is True
    assert ev["revalidation_event_type"] == "CONTEXT_START"
    assert ev["historical_context_origin_timestamp"] == "2026-08-02T08:30:00Z"


def test_revalidated_timestamp_preserves_decision_available_at(tmp_path: Path):
    row = _row(current="LONG_CONTEXT", previous="LONG_CONTEXT", origin="2026-08-02T08:30:00Z")
    _, result = _materialize(tmp_path, [row])
    ev = result.emitted[0]
    assert ev["event_timestamp"] == ev["decision_available_at"]
    assert ev["event_timestamp"] != ev["historical_context_origin_timestamp"]
    assert ev["execution_not_before"] == "2026-08-02T12:16:02Z"
    assert ev["execution_not_before"] != ev["decision_available_at"]
    assert ev["restart_backfill"] is True
    assert ev["materialization_class"] == "RESTART_BACKFILL"


def test_bbo_before_decision_available_is_rejected(tmp_path: Path):
    row = _row(current="LONG_CONTEXT")
    _, result = _materialize(tmp_path, [row], current_bbo=_bbo(ts="2026-08-02T12:15:59Z"))
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "STALE_BBO_BEFORE_DECISION_AVAILABLE"


def _tmp_intrabar_config(tmp_path: Path) -> tuple[object, object, Path]:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    for rel in ("data/cognition/intrabar_context_events", "data/trading/intrabar_paper", "data/trading/paper_epochs"):
        (repo / rel).mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=repo)
    epoch = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="MAT1"),
        epochs_root=cfg.epochs_root,
    )
    return cfg, epoch, repo


def test_live1b_uses_causal_bbo_not_source_bar_close(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    fresh_decision = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    fresh_bbo = (datetime.now(timezone.utc) - timedelta(seconds=25)).isoformat().replace("+00:00", "Z")
    fresh_bar = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    row = _row(current="LONG_CONTEXT", decision_at=fresh_decision, source_bar=fresh_bar, origin=fresh_bar)
    _, result = _materialize(tmp_path, [row], current_bbo=_bbo(ts=fresh_bbo, mono=2_000_000))
    ev = result.emitted[0]
    assert ev["source_bar_close"] == 90.0
    assert float(ev["context_event_price"]) == pytest.approx(100.1)
    cfg, epoch, _ = _tmp_intrabar_config(tmp_path)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=epoch, activation_monotonic_ns=1_000_000)
    acts = eng.process_context_event(ev)
    assert acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.2)
    assert acts[0]["fill"]["paper_fill_price"] != pytest.approx(90.0)


def test_old_epoch_dedup_does_not_block_new_epoch(tmp_path: Path):
    row = _row(current="LONG_CONTEXT")
    journal, old = _materialize(tmp_path, [row], epoch_id="OLD_EPOCH")
    _, new = _materialize(tmp_path, [row], journal=journal, epoch_id="NEW_EPOCH")
    assert old.emitted_count == 1
    assert new.emitted_count == 1
    assert old.emitted[0]["context_event_id"] != new.emitted[0]["context_event_id"]


def test_stale_input_fails_closed(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="LONG_CONTEXT", stale=True)])
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "STALE_OR_PENDING_INPUT"



def test_shadow_only_action_allowed_false_with_directional_paper_intent_still_materializes(tmp_path: Path):
    row = _row(current="LONG_CONTEXT", action_allowed=False, intent="INTENT_OPEN_LONG")
    _, result = _materialize(tmp_path, [row])
    assert result.emitted_count == 1
    ev = result.emitted[0]
    assert ev["event_type"] == "CONTEXT_START"
    assert ev["paper_action_candidate"] == "INTENT_OPEN_LONG"

def test_action_not_allowed_without_paper_intent_fails_closed(tmp_path: Path):
    row = _row(current="LONG_CONTEXT", action_allowed=False, intent="NO_TRADE_OBSERVE")
    _, result = _materialize(tmp_path, [row])
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "ACTION_NOT_ALLOWED"


def test_active_sleeve_position_blocks_second_entry(tmp_path: Path):
    _, result = _materialize(
        tmp_path,
        [_row(current="LONG_CONTEXT")],
        active_positions_by_timeframe={"M15"},
    )
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "ACTIVE_POSITION"


def test_already_traded_episode_blocks_second_start_same_epoch(tmp_path: Path):
    _, result = _materialize(tmp_path, [_row(current="LONG_CONTEXT", episode="ep1")], traded_episodes={"ep1"})
    assert result.emitted_count == 0
    assert result.skipped[-1]["reason"] == "EPISODE_ALREADY_TRADED"


def test_timeframe_identities_are_independent(tmp_path: Path):
    rows = [
        _row(current="LONG_CONTEXT", tf=tf, source_bar="2026-08-02T12:15:00Z", episode="same-episode")
        for tf in ("M15", "M30", "H1", "H4")
    ]
    _, result = _materialize(tmp_path, rows)
    assert result.emitted_count == 4
    assert {ev["timeframe"] for ev in result.emitted} == {"M15", "M30", "H1", "H4"}
    assert len({ev["context_event_id"] for ev in result.emitted}) == 4


def test_long_short_identity_symmetry_and_no_short_disabled_reason(tmp_path: Path):
    rows = [
        _row(current="LONG_CONTEXT", tf="M15", episode="ep-long"),
        _row(current="SHORT_CONTEXT", tf="M30", episode="ep-short"),
    ]
    _, result = _materialize(tmp_path, rows)
    assert [ev["direction"] for ev in result.emitted] == ["LONG", "SHORT"]
    payload = json.dumps(result.to_dict(), sort_keys=True) + json.dumps(result.emitted, sort_keys=True)
    assert "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE" not in payload


def test_risk_cost_stop_take_and_real_execution_config_unchanged():
    cfg = load_intrabar_paper_config()
    assert cfg.real_execution_enabled is False
    assert cfg.paper_only is True
    assert cfg.max_risk_per_trade_usd == pytest.approx(1000.0)
    assert cfg.max_risk_per_trade_pct == pytest.approx(1.0)
    assert cfg.entry_fee_bps == pytest.approx(2.0)
    assert cfg.exit_fee_bps == pytest.approx(5.0)
    assert cfg.entry_slippage_bps == pytest.approx(3.0)
    assert cfg.exit_slippage_bps == pytest.approx(3.0)
    assert cfg.stop_loss_bps == pytest.approx(100.0)
    assert cfg.take_profit_bps == pytest.approx(150.0)


def test_revalidation_uses_existing_live1b_entry_contract():
    from btc_ml.trading.intrabar_paper.consumer import ENTRY_EVENTS
    from btc_ml.trading.intrabar_paper.trading_contract import (
        CANONICAL_SOURCE_EPOCH,
        EXPECTED_SOURCE_FINGERPRINT,
        build_trading_contract_manifest,
        trading_contract_fingerprint,
    )

    assert ENTRY_EVENTS == frozenset({"CONTEXT_START", "CONTEXT_FLIP"})
    assert "CONTEXT_REVALIDATED_START" not in ENTRY_EVENTS
    manifest = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH)
    assert trading_contract_fingerprint(manifest) == EXPECTED_SOURCE_FINGERPRINT
