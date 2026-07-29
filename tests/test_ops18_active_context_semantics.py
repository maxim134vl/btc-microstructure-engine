"""OPS1.8 — separate provisional market evaluation from active trading context."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import research_pipeline_service as svc  # noqa: E402

NOW = datetime(2026, 7, 29, 12, 0, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_production_journal(monkeypatch):
    monkeypatch.setattr(svc, "_open_context_lineage_from_journal", lambda tf: None)


def _base_cog(evals: dict, *, last_events: dict | None = None, updated_at: str = "2026-07-29T12:00:00Z") -> dict:
    bars = {tf: {"causal_cutoff_timestamp": updated_at} for tf in evals}
    return {
        "updated_at": updated_at,
        "pid": 42,
        "last_provisional_eval": evals,
        "partial_bars": bars,
        "last_context_event": last_events or {},
    }


def test_provisional_observe_keeps_active_long_challenged() -> None:
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H4": {
                "market_context": "OBSERVE",
                "provisional_market_context": "OBSERVE",
                "lifecycle": "CHALLENGED",
                "active": "LONG_CONTEXT",
                "active_market_context": "LONG_CONTEXT",
            },
        },
        last_events={
            "H4": {
                "context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
                "event_type": "CONTEXT_START",
                "timeframe": "H4",
                "event_timestamp": "2026-07-29T09:40:34.724226Z",
                "lifecycle_episode_id": "H4:prov:1",
                "context_event_price": "64690.19",
                "new_context": "LONG_CONTEXT",
            }
        },
    )
    paper = {
        "paper_epoch_id": "EPOCH",
        "active_positions_by_timeframe": {
            "H4": {"position_id": "pos_022f1ab19b904bed", "side": "LONG"},
        },
    }
    payload = svc.build_live1a_decision_layer_payload(cog, paper, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["provisional_market_context"] == "OBSERVE"
    assert h4["active_market_context"] == "LONG_CONTEXT"
    assert h4["lifecycle_state"] == "CHALLENGED"
    assert h4["directional_bias"] == "LONG"
    assert h4["entry_eligible"] is False
    assert h4["lifecycle_episode_id"] == "H4:prov:1"
    assert h4["context_event_id"] == "CTX_d25c0ed08fd7b1d5c8af"
    assert h4["open_position_side"] == "LONG"
    assert payload["trading_states"]["active_directional_contexts"] == 1
    assert payload["trading_states"]["current_directional_evaluations"] == 0


def test_provisional_observe_with_null_active_is_no_active_context() -> None:
    cog = _base_cog(
        {
            tf: {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"}
            for tf in ("M15", "M30", "H1", "H4")
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["active_market_context"] is None
    assert h4["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert h4["directional_bias"] == "NONE"
    assert payload["trading_states"]["active_directional_contexts"] == 0


def test_context_end_clears_active_via_journal_lineage(tmp_path, monkeypatch) -> None:
    journal = tmp_path / "events.jsonl"
    rows = [
        {
            "context_event_id": "CTX_start",
            "timeframe": "H4",
            "event_type": "CONTEXT_START",
            "new_context": "LONG_CONTEXT",
            "event_timestamp": "2026-07-29T09:40:34.724226Z",
            "lifecycle_episode_id": "H4:prov:1",
            "context_event_price": "64690.19",
        },
        {
            "context_event_id": "CTX_end",
            "timeframe": "H4",
            "event_type": "CONTEXT_END",
            "previous_context": "LONG_CONTEXT",
            "new_context": "OBSERVE",
            "event_timestamp": "2026-07-29T12:00:00Z",
            "lifecycle_episode_id": "H4:prov:1",
        },
    ]
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(svc, "LIVE1A_CONTEXT_JOURNAL_REL", journal.relative_to(Path(svc.REPO_ROOT)) if False else Path("x"))
    # Patch absolute reader path by monkeypatching helper
    monkeypatch.setattr(svc, "_open_context_lineage_from_journal", lambda tf: None)
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H4": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["active_market_context"] is None
    assert h4["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert h4["lifecycle_episode_id"] is None
    assert h4["context_event_id"] is None


def test_lineage_restored_from_unfinished_start_without_tip_ids(tmp_path, monkeypatch) -> None:
    journal = tmp_path / "events.jsonl"
    journal.write_text(
        json.dumps(
            {
                "context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
                "timeframe": "H4",
                "event_type": "CONTEXT_START",
                "new_context": "LONG_CONTEXT",
                "event_timestamp": "2026-07-29T09:40:34.724226Z",
                "lifecycle_episode_id": "H4:prov:1",
                "context_event_price": "64690.19",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_open(tf: str):
        if tf != "H4":
            return None
        return json.loads(journal.read_text().splitlines()[0])

    monkeypatch.setattr(svc, "_open_context_lineage_from_journal", _fake_open)
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H4": {
                "market_context": "OBSERVE",
                "lifecycle": "NO_ACTIVE_CONTEXT",
                "active": "OBSERVE",
            },
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["active_market_context"] == "LONG_CONTEXT"
    assert h4["lifecycle_state"] == "ACTIVE"
    assert h4["context_event_id"] == "CTX_d25c0ed08fd7b1d5c8af"
    assert h4["lifecycle_episode_id"] == "H4:prov:1"
    assert h4["context_started_at"] == "2026-07-29T09:40:34.724226Z"
    assert h4["context_price"] == 64690.19
    assert h4["directional_bias"] == "LONG"
    assert payload["trading_states"]["active_directional_contexts"] == 1
    assert payload["trading_states"]["current_directional_evaluations"] == 0
