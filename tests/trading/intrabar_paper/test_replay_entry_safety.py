"""Regression tests for replay/catch-up CONTEXT_START entry safety (Fix 1)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_ml.live.intrabar.closed_bar_event_bridge import (
    DELIVERY_MODE_LIVE,
    DELIVERY_MODE_RECOVERY,
    materialize_closed_bar_events,
)
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch

PRODUCTION_JOURNAL = (
    Path(__file__).resolve().parents[3] / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
)


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
        utc_stamp="REPLAY1",
    )
    return activate_epoch(ep, epochs_root=cfg.epochs_root)


def _engine(cfg, activation_mono: int = 1_000_000) -> IntrabarPaperEngine:
    eng = IntrabarPaperEngine(cfg=cfg, epoch=_epoch(cfg), activation_monotonic_ns=activation_mono)
    eng.bbo.update_from_book_ticker(
        best_bid=64796.0,
        best_ask=64796.01,
        receive_monotonic_ns=activation_mono,
        receive_timestamp=_utc_z(datetime.now(timezone.utc)),
        book_update_id="seed",
        domain="context",
    )
    return eng


def _ctx(
    *,
    eid: str,
    etype: str,
    tf: str = "M15",
    prev: str = "OBSERVE",
    new: str = "SHORT_CONTEXT",
    mono: int,
    episode: str = "960.0",
    decision_available_at: str,
    ingested_at: str | None = None,
    delivery_mode: str | None = None,
) -> dict:
    payload = {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": decision_available_at,
        "decision_available_at": decision_available_at,
        "context_event_price": "64796.005",
        "best_bid": 64796.0,
        "best_ask": 64796.01,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": episode,
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "ingested_at": ingested_at or _utc_z(datetime.now(timezone.utc)),
        "direction": "SHORT" if "SHORT" in new else "LONG",
    }
    if delivery_mode is not None:
        payload["delivery_mode"] = delivery_mode
    return payload


def _append_journal(cfg, event: dict) -> None:
    journal = cfg.context_journal_root / "events.jsonl"
    if journal.resolve() == PRODUCTION_JOURNAL.resolve():
        raise RuntimeError(f"refusing to write production journal: {journal}")
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


class FakeJournal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def build_event(self, **kwargs):
        return {"context_event_id": f"TEST_CTX_{len(self.events) + 1}", **kwargs}

    def append(self, event: dict) -> bool:
        self.events.append(event)
        return True


def _bridge_row(
    *,
    candle: str,
    written: str,
    episode: str,
    decision_id: str,
    current: str = "SHORT_CONTEXT",
    tf: str = "15m",
) -> dict:
    side = "LONG" if current == "LONG_CONTEXT" else "SHORT"
    return {
        "source_timeframe": tf,
        "candle_timestamp": candle,
        "decision_written_at_utc": written,
        "decision_id": decision_id,
        "active_market_context": current,
        "previous_active_market_context": "OBSERVE",
        "lifecycle_episode_id": episode,
        "paper_action_candidate": f"INTENT_OPEN_{side}",
        "intended_side": side,
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL",
        "context_origin_timestamp": candle,
    }


def test_a_m15_8_bridge_classifies_recovery_via_prior_poll_watermark():
    """Test A (bridge) — M15_8 decision predates prior poll watermark => RECOVERY."""
    journal = FakeJournal()
    row = _bridge_row(
        candle="2026-08-05T17:45:00Z",
        written="2026-08-05T18:01:52.335375Z",
        episode="960.0",
        decision_id="m15-8-incident",
        current="SHORT_CONTEXT",
    )
    result = materialize_closed_bar_events(
        [row],
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:04Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    assert len(result.emitted) == 1
    emitted = result.emitted[0]
    assert emitted["event_type"] == "CONTEXT_START"
    assert emitted["delivery_mode"] == DELIVERY_MODE_RECOVERY
    assert emitted["decision_available_at"] == "2026-08-05T18:01:52.335375Z"


@pytest.mark.parametrize("current", ["LONG_CONTEXT", "SHORT_CONTEXT"])
def test_decision_published_between_bridge_polls_stays_live(current: str):
    """A just-published decision must not become replay solely due to poll timing."""
    journal = FakeJournal()
    row = _bridge_row(
        candle="2026-08-05T18:00:00Z",
        written="2026-08-05T18:14:59.250000Z",
        episode=f"poll-race-{current}",
        decision_id=f"poll-race-{current}",
        current=current,
    )
    result = materialize_closed_bar_events(
        [row],
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:01Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:15:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    assert result.emitted_count == 1
    assert result.emitted[0]["delivery_mode"] == DELIVERY_MODE_LIVE


def test_a_m15_8_replay_context_start_blocked_despite_fresh_age(cfg):
    """Test A (consumer) — recovery START inside stale window must not open."""
    c, _ = cfg
    eng = _engine(c)
    materialized = datetime(2026, 8, 5, 18, 15, 4, tzinfo=timezone.utc)
    decision_at = materialized - timedelta(seconds=791.88)
    journal = FakeJournal()
    row = _bridge_row(
        candle="2026-08-05T17:45:00Z",
        written=_utc_z(decision_at),
        episode="960.0",
        decision_id="m15-8-consumer",
        current="SHORT_CONTEXT",
    )
    bridge_result = materialize_closed_bar_events(
        [row],
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 2_203_065_966_062_833,
            "bbo_receive_timestamp": _utc_z(materialized),
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    event = bridge_result.emitted[0]
    assert event["delivery_mode"] == DELIVERY_MODE_RECOVERY
    event["context_event_id"] = "m15_8_replay"
    event["event_monotonic_ns"] = 2_203_065_966_062_833
    event["ingested_at"] = _utc_z(materialized)
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert len(acts) == 1
    assert acts[0]["status"] == "ENTRY_BLOCKED_REPLAY_SIGNAL"
    assert eng.positions == {}
    blocked = eng.books.read_all("blocked")
    assert blocked[-1]["reason"] == "ENTRY_BLOCKED_REPLAY_SIGNAL"


def test_b_live_context_start_within_stale_window_can_enter(cfg):
    """Test B — live delivery applies normal eligibility."""
    c, _ = cfg
    eng = _engine(c)
    decision_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    event = _ctx(
        eid="live_start",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_utc_z(decision_at),
        delivery_mode=DELIVERY_MODE_LIVE,
    )
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTERED"
    assert eng.positions["M15"].side == "SHORT"


def test_c_replay_start_with_active_position_blocked(cfg):
    """Test C — recovery START with active position does not add exposure."""
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(
        _ctx(
            eid="existing",
            etype="CONTEXT_START",
            mono=1_500_000,
            decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(seconds=60)),
            delivery_mode=DELIVERY_MODE_LIVE,
            episode="open_ep",
        )
    )
    assert "M15" in eng.positions
    replay = _ctx(
        eid="replay_with_open",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(seconds=120)),
        delivery_mode=DELIVERY_MODE_RECOVERY,
        episode="960.0",
    )
    acts = eng.process_context_event(replay)
    assert acts == [{"status": "ENTRY_BLOCKED_REPLAY_SIGNAL", "timeframe": "M15", "context_event_id": "replay_with_open"}]
    blocked = eng.books.read_all("blocked")
    assert blocked[-1]["reason"] == "ENTRY_BLOCKED_REPLAY_SIGNAL"
    assert len(eng.positions) == 1


def test_d_recovery_context_end_closes_open_position(cfg):
    """Test D — recovery CONTEXT_END still exits."""
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(
        _ctx(
            eid="open_live",
            etype="CONTEXT_START",
            mono=1_500_000,
            decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(seconds=60)),
            delivery_mode=DELIVERY_MODE_LIVE,
            episode="ep_end",
            new="LONG_CONTEXT",
        )
    )
    assert "M15" in eng.positions
    end = _ctx(
        eid="recovery_end",
        etype="CONTEXT_END",
        prev="LONG_CONTEXT",
        new="OBSERVE",
        mono=2_000_000,
        decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(hours=8)),
        delivery_mode=DELIVERY_MODE_RECOVERY,
        episode="ep_end",
    )
    acts = eng.process_context_event(end)
    assert acts and acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions


def test_e_recovery_context_flip_exits_but_blocks_reverse_entry(cfg):
    """Test E — recovery FLIP closes but does not open reverse leg."""
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(
        _ctx(
            eid="flip_open",
            etype="CONTEXT_START",
            mono=1_500_000,
            decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(seconds=60)),
            delivery_mode=DELIVERY_MODE_LIVE,
            episode="ep_flip",
            new="LONG_CONTEXT",
        )
    )
    assert eng.positions["M15"].side == "LONG"
    flip = _ctx(
        eid="recovery_flip",
        etype="CONTEXT_FLIP",
        prev="LONG_CONTEXT",
        new="SHORT_CONTEXT",
        mono=2_000_000,
        decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(hours=2)),
        delivery_mode=DELIVERY_MODE_RECOVERY,
        episode="ep_flip",
    )
    acts = eng.process_context_event(flip)
    assert [a["status"] for a in acts] == ["EXITED", "ENTRY_BLOCKED_REPLAY_SIGNAL"]
    assert "M15" not in eng.positions


def test_f_stale_live_signal_still_blocked_by_age(cfg):
    """Test F — live START older than 900s still uses stale gate."""
    c, _ = cfg
    eng = _engine(c)
    stale = _ctx(
        eid="stale_live",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_utc_z(datetime.now(timezone.utc) - timedelta(hours=2)),
        delivery_mode=DELIVERY_MODE_LIVE,
    )
    _append_journal(c, stale)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}


def test_bridge_catch_up_batch_classifies_recovery_via_prior_poll_watermark():
    """Catch-up decisions predating the prior poll watermark are RECOVERY."""
    rows_many = [
        _bridge_row(
            candle="2026-08-05T02:15:00Z",
            written="2026-08-05T02:31:49Z",
            episode="956.0",
            decision_id="multi-1",
            current="SHORT_CONTEXT",
        ),
        _bridge_row(
            candle="2026-08-05T12:15:00Z",
            written="2026-08-05T12:31:49Z",
            episode="957.0",
            decision_id="multi-2",
            current="LONG_CONTEXT",
            tf="1h",
        ),
        _bridge_row(
            candle="2026-08-05T17:45:00Z",
            written="2026-08-05T18:01:52Z",
            episode="960.0",
            decision_id="multi-3",
            current="SHORT_CONTEXT",
            tf="4h",
        ),
    ]
    journal = FakeJournal()
    result = materialize_closed_bar_events(
        rows_many,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:04Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    starts = [e for e in result.emitted if e.get("event_type") == "CONTEXT_START"]
    assert len(starts) == 3
    assert all(e.get("delivery_mode") == DELIVERY_MODE_RECOVERY for e in starts)
    assert all(e.get("materialization_batch_entry_count") == 3 for e in starts)


def test_g_multiple_legitimate_live_starts_in_same_batch():
    """Test G — batch cardinality must not force RECOVERY."""
    rows = [
        _bridge_row(
            candle="2026-08-05T18:00:00Z",
            written="2026-08-05T18:14:30Z",
            episode="961.0",
            decision_id="live-1",
            current="LONG_CONTEXT",
            tf="15m",
        ),
        _bridge_row(
            candle="2026-08-05T18:00:00Z",
            written="2026-08-05T18:14:45Z",
            episode="962.0",
            decision_id="live-2",
            current="SHORT_CONTEXT",
            tf="1h",
        ),
    ]
    journal = FakeJournal()
    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:00Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    starts = [e for e in result.emitted if e.get("event_type") == "CONTEXT_START"]
    assert len(starts) == 2
    assert all(e.get("delivery_mode") == DELIVERY_MODE_LIVE for e in starts)


def test_h_multi_timeframe_simultaneous_live_starts():
    """Test H — simultaneous valid starts across TFs remain LIVE."""
    rows = [
        _bridge_row(
            candle="2026-08-05T18:00:00Z",
            written="2026-08-05T18:14:30Z",
            episode=f"ep-{tf}",
            decision_id=f"live-{tf}",
            current="LONG_CONTEXT" if idx % 2 == 0 else "SHORT_CONTEXT",
            tf=tf,
        )
        for idx, tf in enumerate(("15m", "30m", "1h", "4h"))
    ]
    journal = FakeJournal()
    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:00Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    starts = [e for e in result.emitted if e.get("event_type") == "CONTEXT_START"]
    assert len(starts) == 4
    assert all(e.get("delivery_mode") == DELIVERY_MODE_LIVE for e in starts)


def test_i_recovery_batch_via_explicit_restart_markers():
    """Test I — explicit restart/backfill markers classify RECOVERY."""
    journal = FakeJournal()
    row = _bridge_row(
        candle="2026-08-05T12:15:00Z",
        written="2026-08-05T18:15:00Z",
        episode="963.0",
        decision_id="restart-1",
        current="LONG_CONTEXT",
    )
    result = materialize_closed_bar_events(
        [
            {
                **row,
                "active_context_started_at": "2026-08-05T08:30:00Z",
                "previous_active_market_context": "LONG_CONTEXT",
            }
        ],
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:30Z",
        },
        bridge_activated_at="2026-08-05T18:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:15:10Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    assert len(result.emitted) == 1
    emitted = result.emitted[0]
    assert emitted["delivery_mode"] == DELIVERY_MODE_RECOVERY
    assert emitted["extra_metadata"]["restart_backfill"] is True


def test_j_mixed_batch_classifies_per_event_not_globally():
    """Test J — LIVE and RECOVERY can coexist in one poll batch."""
    rows = [
        _bridge_row(
            candle="2026-08-05T18:00:00Z",
            written="2026-08-05T18:14:30Z",
            episode="live-ep",
            decision_id="mixed-live",
            current="LONG_CONTEXT",
            tf="15m",
        ),
        _bridge_row(
            candle="2026-08-05T17:45:00Z",
            written="2026-08-05T17:47:52Z",
            episode="recovery-ep",
            decision_id="mixed-recovery",
            current="SHORT_CONTEXT",
            tf="1h",
        ),
    ]
    journal = FakeJournal()
    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo={
            "best_bid": 64796.0,
            "best_ask": 64796.01,
            "book_update_id": "test",
            "bbo_receive_monotonic_ns": 9_000_000_000,
            "bbo_receive_timestamp": "2026-08-05T18:15:00Z",
        },
        bridge_activated_at="2026-08-05T01:00:00Z",
        previous_bridge_invocation_at="2026-08-05T18:14:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    by_id = {e["extra_metadata"]["source_decision_id"]: e for e in result.emitted}
    assert by_id["mixed-live"]["delivery_mode"] == DELIVERY_MODE_LIVE
    assert by_id["mixed-recovery"]["delivery_mode"] == DELIVERY_MODE_RECOVERY
