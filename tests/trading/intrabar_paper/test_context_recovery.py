"""Durable per-timeframe context recovery after downtime (Fix 2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.live.intrabar.closed_bar_event_bridge import (
    DELIVERY_MODE_LIVE,
    DELIVERY_MODE_RECOVERY,
    ClosedBarContextEventBridge,
    PerTfRecoveryWatermark,
    load_per_tf_recovery_watermarks,
    materialize_closed_bar_events,
)
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch

PRODUCTION_JOURNAL = (
    Path(__file__).resolve().parents[3] / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
)


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _journal(tmp_path: Path) -> ContextEventJournal:
    return ContextEventJournal(tmp_path / "events")


def _bbo(*, ts: str, mono: int, bid: float = 64900.0, ask: float = 64900.01) -> dict:
    return {
        "best_bid": bid,
        "best_ask": ask,
        "book_update_id": f"book-{mono}",
        "bbo_receive_monotonic_ns": mono,
        "bbo_receive_timestamp": ts,
    }


def _decision_row(
    *,
    candle: str,
    written: str,
    current: str,
    previous: str | None,
    episode: str,
    decision_id: str,
    tf: str = "15m",
    close: float = 64850.0,
) -> dict:
    side = "LONG" if current == "LONG_CONTEXT" else "SHORT"
    return {
        "source_timeframe": tf,
        "candle_timestamp": candle,
        "decision_written_at_utc": written,
        "decision_id": decision_id,
        "active_market_context": current,
        "previous_active_market_context": previous,
        "lifecycle_episode_id": episode,
        "paper_action_candidate": f"INTENT_OPEN_{side}",
        "intended_side": side,
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL",
        "context_origin_timestamp": candle,
        "close": close,
    }


def _seed_m15_short_journal(journal: ContextEventJournal, *, epoch_id: str = "TEST_EPOCH") -> None:
  event = {
      "context_event_id": "CTX_6822f717283be583126f",
      "event_type": "CONTEXT_START",
      "timeframe": "M15",
      "previous_context": "OBSERVE",
      "new_context": "SHORT_CONTEXT",
      "lifecycle_episode_id": "960.0",
      "source_bar_timestamp": "2026-08-05T17:45:00Z",
      "decision_available_at": "2026-08-05T18:01:52.335375Z",
      "event_timestamp": "2026-08-05T18:01:52.335375Z",
      "event_monotonic_ns": 1_000_000,
      "context_event_price": "64796.005",
      "direction": "SHORT",
      "provider_id": "LIVE1A_CANONICAL_INTRABAR_CONTEXT",
      "epoch_id": epoch_id,
      "event_identity_key": (
          "LIVE1A_CANONICAL_INTRABAR_CONTEXT|TEST_EPOCH|M15|960.0|CONTEXT_START|"
          "2026-08-05T17:45:00Z|SHORT"
      ),
      "source_decision_id": "ba8ff62d-0ce2-4281-8d36-79f50a005c7c",
      "ingested_at": "2026-08-05T18:15:04.034358Z",
  }
  journal.append(event)


def _watermarks(journal: ContextEventJournal) -> dict[str, PerTfRecoveryWatermark]:
    return load_per_tf_recovery_watermarks(journal.path)


@pytest.fixture
def cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n",
        encoding="utf-8",
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    return load_intrabar_paper_config(repo_root=repo), repo


def _epoch(cfg) -> object:
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        utc_stamp="FIX2",
    )
    return activate_epoch(ep, epochs_root=cfg.epochs_root)


def _engine(cfg, activation_mono: int = 5_000_000) -> IntrabarPaperEngine:
    eng = IntrabarPaperEngine(cfg=cfg, epoch=_epoch(cfg), activation_monotonic_ns=activation_mono)
    eng.bbo.update_from_book_ticker(
        best_bid=65100.0,
        best_ask=65100.01,
        receive_monotonic_ns=activation_mono - 1_000_000,
        receive_timestamp="2026-08-06T06:00:00Z",
        book_update_id="recovery-live-bbo",
        domain="context",
    )
    return eng


def _open_short_position(eng: IntrabarPaperEngine, *, mono: int) -> None:
    fresh = _utc_z(datetime.now(timezone.utc) - timedelta(seconds=60))
    eng.bbo.update_from_book_ticker(
        best_bid=64796.0,
        best_ask=64796.01,
        receive_monotonic_ns=mono - 200_000,
        receive_timestamp=fresh,
        book_update_id="seed-bbo",
        domain="context",
    )
    act = eng.process_context_event(
        {
            "context_event_id": "seed_short",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "previous_context": "OBSERVE",
            "new_context": "SHORT_CONTEXT",
            "event_monotonic_ns": mono - 100_000,
            "event_timestamp": fresh,
            "decision_available_at": fresh,
            "context_event_price": "64796.005",
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "bbo_receive_monotonic_ns": mono - 200_000,
            "book_update_id": "seed",
            "lifecycle_episode_id": "960.0",
            "direction": "SHORT",
            "delivery_mode": DELIVERY_MODE_LIVE,
        }
    )
    assert act and act[0]["status"] == "ENTERED"


def test_a_exact_m15_8_missed_flip_recovered_after_restart(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    assert watermarks["M15"].active_context == "SHORT_CONTEXT"
    assert watermarks["M15"].lifecycle_episode_id == "960.0"

    flip_row = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    result = materialize_closed_bar_events(
        [flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe={"M15"},
        traded_episodes={"960.0"},
    )

    assert result.emitted_count == 1
    event = result.emitted[0]
    assert event["event_type"] == "CONTEXT_FLIP"
    assert event["previous_context"] == "SHORT_CONTEXT"
    assert event["new_context"] == "LONG_CONTEXT"
    assert event["lifecycle_episode_id"] == "963.0"
    assert event["source_bar_timestamp"] == "2026-08-06T05:00:00Z"
    assert event["decision_available_at"] == "2026-08-06T05:16:59.773003Z"
    assert event["delivery_mode"] == DELIVERY_MODE_RECOVERY
    assert event["recovered_after_restart"] is True
    assert not any(x.get("reason") == "PRE_BRIDGE_ACTIVATION_ROW" for x in result.skipped)


def test_b_recovered_flip_closes_short_but_blocks_reverse_long(cfg, tmp_path: Path):
    c, repo = cfg
    journal = _journal(repo / "data" / "cognition" / "intrabar_context_events")
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    flip_row = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    bridge_result = materialize_closed_bar_events(
        [flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    recovered = bridge_result.emitted[0]
    recovered["event_monotonic_ns"] = 6_000_000
    recovered["best_bid"] = 65100.0
    recovered["best_ask"] = 65100.01
    recovered["bbo_receive_monotonic_ns"] = 6_000_000

    eng = _engine(c, activation_mono=6_000_000)
    _open_short_position(eng, mono=6_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=65100.0,
        best_ask=65100.01,
        receive_monotonic_ns=6_000_000,
        receive_timestamp="2026-08-06T06:00:00Z",
        book_update_id="recovery-live-bbo",
        domain="context",
    )
    acts = eng.process_context_event(recovered)
    assert [a.get("status") for a in acts] == []
    pos = eng.positions["M15"]
    assert pos.side == "SHORT"
    assert pos.lifecycle_episode_id == "960.0"
    assert not eng.pending_exits


def test_c_recovered_end_closes_existing_position(cfg, tmp_path: Path):
    c, repo = cfg
    journal = _journal(repo / "data" / "cognition" / "intrabar_context_events")
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    end_row = _decision_row(
        candle="2026-08-06T06:00:00Z",
        written="2026-08-06T06:16:59Z",
        current="OBSERVE",
        previous="SHORT_CONTEXT",
        episode="960.0",
        decision_id="recovery-end",
        close=64910.0,
    )
    end_row["paper_action_candidate"] = "NO_TRADE_OBSERVE"
    end_row["intended_side"] = "NONE"
    end_row["signal_eligibility_status"] = "BLOCKED_NOT_DIRECTIONAL"
    result = materialize_closed_bar_events(
        [end_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T07:00:00Z", mono=7_000_000),
        bridge_activated_at="2026-08-06T07:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe={"M15"},
        traded_episodes={"960.0"},
    )
    event = result.emitted[0]
    assert event["event_type"] == "CONTEXT_END"
    event["event_monotonic_ns"] = 7_000_000
    event["best_bid"] = 65100.0
    event["best_ask"] = 65100.01
    event["bbo_receive_monotonic_ns"] = 7_000_000

    eng = _engine(c, activation_mono=7_000_000)
    _open_short_position(eng, mono=7_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=65100.0,
        best_ask=65100.01,
        receive_monotonic_ns=7_000_000,
        receive_timestamp="2026-08-06T07:00:00Z",
        book_update_id="recovery-end-bbo",
        domain="context",
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions


def test_d_recovered_start_with_no_position_does_not_create_exposure(tmp_path: Path):
    journal = _journal(tmp_path)
    event = {
        "context_event_id": "CTX_observe_seed",
        "event_type": "CONTEXT_END",
        "timeframe": "M15",
        "previous_context": "LONG_CONTEXT",
        "new_context": "OBSERVE",
        "lifecycle_episode_id": "900.0",
        "source_bar_timestamp": "2026-08-05T10:00:00Z",
        "decision_available_at": "2026-08-05T10:16:00Z",
        "event_timestamp": "2026-08-05T10:16:00Z",
        "event_monotonic_ns": 1,
        "context_event_price": "64000",
        "direction": "LONG",
        "provider_id": "LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        "epoch_id": "TEST_EPOCH",
        "source_decision_id": "observe-seed",
    }
    journal.append(event)
    watermarks = _watermarks(journal)
    start_row = _decision_row(
        candle="2026-08-06T08:00:00Z",
        written="2026-08-06T08:16:00Z",
        current="LONG_CONTEXT",
        previous="OBSERVE",
        episode="964.0",
        decision_id="recovery-start",
        close=65000.0,
    )
    result = materialize_closed_bar_events(
        [start_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T09:00:00Z", mono=9_000_000),
        bridge_activated_at="2026-08-06T09:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    recovered = result.emitted[0]
    assert recovered["event_type"] == "CONTEXT_START"
    assert recovered["delivery_mode"] == DELIVERY_MODE_RECOVERY


def test_e_repeated_restart_produces_no_duplicate_event(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    flip_row = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    kwargs = dict(
        rows=[flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    first = materialize_closed_bar_events(**kwargs)
    second = materialize_closed_bar_events(**kwargs)
    assert first.emitted_count == 1
    assert second.emitted_count == 0
    assert second.duplicate_events == 1
    assert len(journal.path.read_text(encoding="utf-8").splitlines()) == 2


def test_f_multiple_missed_transitions_reconstructed_chronologically(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    rows = [
        _decision_row(
            candle="2026-08-06T05:00:00Z",
            written="2026-08-06T05:16:59Z",
            current="LONG_CONTEXT",
            previous=None,
            episode="963.0",
            decision_id="flip-1",
            close=64920.0,
        ),
        _decision_row(
            candle="2026-08-06T06:00:00Z",
            written="2026-08-06T06:16:59Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="964.0",
            decision_id="flip-2",
            close=64880.0,
        ),
        _decision_row(
            candle="2026-08-06T07:00:00Z",
            written="2026-08-06T07:16:59Z",
            current="OBSERVE",
            previous="SHORT_CONTEXT",
            episode="964.0",
            decision_id="end-1",
            close=64850.0,
        ),
    ]
    rows[-1]["paper_action_candidate"] = "NO_TRADE_OBSERVE"
    rows[-1]["intended_side"] = "NONE"
    rows[-1]["signal_eligibility_status"] = "BLOCKED_NOT_DIRECTIONAL"
    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T08:00:00Z", mono=8_000_000),
        bridge_activated_at="2026-08-06T08:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    types = [e["event_type"] for e in result.emitted]
    assert types == ["CONTEXT_FLIP", "CONTEXT_FLIP", "CONTEXT_END"]
    assert result.emitted[0]["new_context"] == "LONG_CONTEXT"
    assert result.emitted[1]["new_context"] == "SHORT_CONTEXT"
    assert result.emitted[2]["new_context"] == "OBSERVE"
    assert all(e["delivery_mode"] == DELIVERY_MODE_RECOVERY for e in result.emitted[:2])


def test_g_no_transition_no_recovery_output(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    continuation = _decision_row(
        candle="2026-08-06T04:45:00Z",
        written="2026-08-06T05:01:54Z",
        current="SHORT_CONTEXT",
        previous="SHORT_CONTEXT",
        episode="960.0",
        decision_id="same-short",
        close=64890.0,
    )
    result = materialize_closed_bar_events(
        [continuation],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    assert result.emitted_count == 0


def test_h_new_event_after_recovery_classified_live(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    flip_row = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    materialize_closed_bar_events(
        [flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    live_row = _decision_row(
        candle="2026-08-06T08:00:00Z",
        written="2026-08-06T08:16:59Z",
        current="SHORT_CONTEXT",
        previous="LONG_CONTEXT",
        episode="965.0",
        decision_id="live-flip",
        close=65010.0,
    )
    live_result = materialize_closed_bar_events(
        [live_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T08:17:00Z", mono=8_170_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        previous_bridge_invocation_at="2026-08-06T08:16:30Z",
        recovery_watermarks=_watermarks(journal),
        active_positions_by_timeframe=set(),
        traded_episodes={"963.0"},
    )
    assert live_result.emitted_count == 1
    assert live_result.emitted[0]["delivery_mode"] == DELIVERY_MODE_LIVE


def test_i_more_than_256_rows_during_downtime_still_recovers_first_missing_transition(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    rows = []
    base = datetime(2026, 8, 5, 18, 2, tzinfo=timezone.utc)
    for idx in range(300):
        ts = base + timedelta(minutes=15 * idx)
        rows.append(
            _decision_row(
                candle=_utc_z(ts),
                written=_utc_z(ts + timedelta(seconds=90)),
                current="SHORT_CONTEXT",
                previous="SHORT_CONTEXT",
                episode="960.0",
                decision_id=f"noise-{idx:03d}",
                close=64800.0 + idx,
            )
        )
    target = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    frame = pd.DataFrame(rows + [target])
    from btc_ml.live.intrabar.closed_bar_event_bridge import _candidate_decision_rows

    candidate_rows = _candidate_decision_rows(frame, watermarks)
    assert any(r["decision_id"] == "m15-8-causal-long" for r in candidate_rows)
    result = materialize_closed_bar_events(
        candidate_rows,
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    flips = [e for e in result.emitted if e["event_type"] == "CONTEXT_FLIP"]
    assert len(flips) == 1
    assert flips[0]["source_decision_id"] == "m15-8-causal-long"


def test_j_partial_recovery_failure_resumes_idempotently(tmp_path: Path):
    class PartialFailJournal(ContextEventJournal):
        def __init__(self, root: Path, fail_after: int) -> None:
            super().__init__(root)
            self.fail_after = fail_after
            self.attempts = 0

        def append(self, event):
            self.attempts += 1
            if self.attempts > self.fail_after:
                raise RuntimeError("simulated recovery failure")
            return super().append(event)

    journal = PartialFailJournal(tmp_path / "events", fail_after=2)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    rows = [
        _decision_row(
            candle="2026-08-06T05:00:00Z",
            written="2026-08-06T05:16:59Z",
            current="LONG_CONTEXT",
            previous=None,
            episode="963.0",
            decision_id="flip-1",
            close=64920.0,
        ),
        _decision_row(
            candle="2026-08-06T06:00:00Z",
            written="2026-08-06T06:16:59Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="964.0",
            decision_id="flip-2",
            close=64880.0,
        ),
        _decision_row(
            candle="2026-08-06T07:00:00Z",
            written="2026-08-06T07:16:59Z",
            current="OBSERVE",
            previous="SHORT_CONTEXT",
            episode="964.0",
            decision_id="end-1",
            close=64850.0,
        ),
    ]
    rows[-1]["paper_action_candidate"] = "NO_TRADE_OBSERVE"
    rows[-1]["intended_side"] = "NONE"
    rows[-1]["signal_eligibility_status"] = "BLOCKED_NOT_DIRECTIONAL"
    kwargs = dict(
        rows=rows,
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T08:00:00Z", mono=8_000_000),
        bridge_activated_at="2026-08-06T08:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    with pytest.raises(RuntimeError):
        materialize_closed_bar_events(**kwargs)
    resume_journal = ContextEventJournal(tmp_path / "events")
    resumed = materialize_closed_bar_events(**{**kwargs, "journal": resume_journal})
    assert resumed.emitted_count == 2
    assert len(resume_journal.path.read_text(encoding="utf-8").splitlines()) == 4


def test_k_recovery_event_does_not_use_current_bbo_as_historical_context_price(tmp_path: Path):
    journal = _journal(tmp_path)
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    flip_row = _decision_row(
        candle="2026-08-06T05:00:00Z",
        written="2026-08-06T05:16:59.773003Z",
        current="LONG_CONTEXT",
        previous=None,
        episode="963.0",
        decision_id="m15-8-causal-long",
        close=64920.5,
    )
    result = materialize_closed_bar_events(
        [flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T06:00:00Z", mono=6_000_000, bid=65100.0, ask=65100.01),
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    event = result.emitted[0]
    assert float(event["context_event_price"]) == pytest.approx(64920.5)
    assert event["context_event_price_source"] == "source_bar_close_recovery"
    assert float(event["context_event_price"]) != pytest.approx(65100.005)


def test_l_current_executable_bbo_used_for_recovery_exit_fill(cfg, tmp_path: Path):
    c, repo = cfg
    journal = _journal(repo / "data" / "cognition" / "intrabar_context_events")
    _seed_m15_short_journal(journal)
    watermarks = _watermarks(journal)
    end_row = _decision_row(
        candle="2026-08-06T06:00:00Z",
        written="2026-08-06T06:16:59Z",
        current="OBSERVE",
        previous="SHORT_CONTEXT",
        episode="960.0",
        decision_id="recovery-end-bbo",
        close=64920.5,
    )
    end_row["paper_action_candidate"] = "NO_TRADE_OBSERVE"
    end_row["intended_side"] = "NONE"
    end_row["signal_eligibility_status"] = "BLOCKED_NOT_DIRECTIONAL"
    bridge_result = materialize_closed_bar_events(
        [end_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo(ts="2026-08-06T07:00:00Z", mono=7_000_000, bid=65100.0, ask=65100.01),
        bridge_activated_at="2026-08-06T07:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe={"M15"},
        traded_episodes={"960.0"},
    )
    recovered = bridge_result.emitted[0]
    recovered["event_monotonic_ns"] = 7_000_000
    recovered["best_bid"] = 65100.0
    recovered["best_ask"] = 65100.01
    recovered["bbo_receive_monotonic_ns"] = 7_000_000

    eng = _engine(c, activation_mono=7_000_000)
    _open_short_position(eng, mono=7_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=65100.0,
        best_ask=65100.01,
        receive_monotonic_ns=7_000_000,
        receive_timestamp="2026-08-06T07:00:00Z",
        book_update_id="recovery-live-bbo",
        domain="context",
    )
    acts = eng.process_context_event(recovered)
    exit_fill = acts[0]["fill"]["paper_fill_price"]
    assert acts[0]["status"] == "EXITED"
    assert acts[0]["trade"]["lifecycle_episode_id"] == "960.0"
    assert exit_fill == pytest.approx(65100.01)
    assert exit_fill != pytest.approx(64920.5)
