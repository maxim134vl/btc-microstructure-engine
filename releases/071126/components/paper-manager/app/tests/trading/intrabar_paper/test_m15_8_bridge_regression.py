from __future__ import annotations

from typing import Any

from btc_ml.live.intrabar.closed_bar_event_bridge import materialize_closed_bar_events


class FakeJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def build_event(self, **kwargs: Any) -> dict[str, Any]:
        return {"context_event_id": f"TEST_CTX_{len(self.events) + 1}", **kwargs}

    def append(self, event: dict[str, Any]) -> bool:
        self.events.append(event)
        return True


def _row(
    *,
    candle: str,
    written: str,
    current: str,
    previous: str | None,
    episode: str,
    decision_id: str,
    tf: str = "15m",
) -> dict[str, Any]:
    side = "LONG" if current == "LONG_CONTEXT" else "SHORT"
    return {
        "source_timeframe": tf,
        "candle_timestamp": candle,
        "decision_written_at_utc": written,
        "decision_id": decision_id,
        "active_market_context": current,
        "previous_active_market_context": previous,
        "lifecycle_state": "ACTIVE",
        "lifecycle_episode_id": episode,
        "transition_reason": "test",
        "paper_action_candidate": f"INTENT_OPEN_{side}",
        "intended_side": side,
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL",
        "decision_stale": False,
        "pipeline_pending": False,
        "context_origin_timestamp": candle,
    }


def _bbo(ts: str) -> dict[str, Any]:
    return {
        "best_bid": 64900.00,
        "best_ask": 64900.01,
        "book_update_id": "test-book",
        "bbo_receive_monotonic_ns": 9_000_000_000,
        "bbo_receive_timestamp": ts,
        "connection_session_id": "test-session",
        "reconnect_generation": 1,
    }


def test_m15_8_missing_previous_still_materializes_causal_flip() -> None:
    journal = FakeJournal()
    rows = [
        _row(
            candle="2026-08-06T04:45:00Z",
            written="2026-08-06T05:01:54.649403Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="960.0",
            decision_id="before-short",
        ),
        _row(
            candle="2026-08-06T05:00:00Z",
            written="2026-08-06T05:16:59.773003Z",
            current="LONG_CONTEXT",
            previous=None,
            episode="963.0",
            decision_id="m15-8-causal-long",
        ),
    ]

    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo("2026-08-06T05:17:00Z"),
        bridge_activated_at="2026-08-06T04:00:00Z",
        active_positions_by_timeframe={"M15"},
        traded_episodes={"960.0"},
    )

    assert result.emitted_count == 1
    event = result.emitted[0]
    assert event["event_type"] == "CONTEXT_FLIP"
    assert event["previous_context"] == "SHORT_CONTEXT"
    assert event["new_context"] == "LONG_CONTEXT"
    assert event["extra_metadata"]["source_decision_id"] == "m15-8-causal-long"
    assert event["extra_metadata"]["previous_context_source"] == "previous_published_decision"


def test_same_episode_same_tf_emits_only_one_context_start_per_batch() -> None:
    journal = FakeJournal()
    rows = [
        _row(
            candle="2026-08-05T17:15:00Z",
            written="2026-08-05T17:32:52Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="960.0",
            decision_id="start-1",
        ),
        _row(
            candle="2026-08-05T17:30:00Z",
            written="2026-08-05T17:47:52Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="960.0",
            decision_id="start-2",
        ),
        _row(
            candle="2026-08-05T17:45:00Z",
            written="2026-08-05T18:01:52Z",
            current="SHORT_CONTEXT",
            previous=None,
            episode="960.0",
            decision_id="start-3",
        ),
    ]

    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo("2026-08-05T18:02:00Z"),
        bridge_activated_at="2026-08-05T17:00:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )

    starts = [e for e in result.emitted if e["event_type"] == "CONTEXT_START"]
    assert len(starts) == 1
    assert starts[0]["timeframe"] == "M15"


def test_same_episode_id_remains_independent_across_timeframes() -> None:
    journal = FakeJournal()
    rows = [
        _row(
            candle="2026-08-05T17:15:00Z",
            written="2026-08-05T17:32:52Z",
            current="LONG_CONTEXT",
            previous="OBSERVE",
            episode="same-episode",
            decision_id=f"start-{tf}",
            tf=tf,
        )
        for tf in ("M15", "M30", "H1", "H4")
    ]

    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo("2026-08-05T18:02:00Z"),
        bridge_activated_at="2026-08-05T17:00:00Z",
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )

    assert result.emitted_count == 4
    assert {e["timeframe"] for e in result.emitted} == {"M15", "M30", "H1", "H4"}


def test_explicit_previous_context_remains_authoritative() -> None:
    journal = FakeJournal()
    rows = [
        _row(
            candle="2026-08-06T04:45:00Z",
            written="2026-08-06T05:01:54Z",
            current="SHORT_CONTEXT",
            previous="OBSERVE",
            episode="960.0",
            decision_id="short-row",
        ),
        _row(
            candle="2026-08-06T05:00:00Z",
            written="2026-08-06T05:16:59Z",
            current="LONG_CONTEXT",
            previous="OBSERVE",
            episode="963.0",
            decision_id="explicit-observe-long",
        ),
    ]

    result = materialize_closed_bar_events(
        rows,
        journal=journal,
        provider_id="TEST",
        epoch_id="TEST_EPOCH",
        current_bbo=_bbo("2026-08-06T05:17:00Z"),
        bridge_activated_at="2026-08-06T04:00:00Z",
        active_positions_by_timeframe={"M15"},
        traded_episodes={"960.0"},
    )

    assert not any(e["event_type"] == "CONTEXT_FLIP" for e in result.emitted)
    assert any(x["reason"] == "ACTIVE_POSITION" for x in result.skipped)
