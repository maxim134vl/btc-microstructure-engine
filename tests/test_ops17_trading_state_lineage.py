"""OPS1.7 lineage helpers retained; OBSERVE no longer wipes active CHALLENGED (OPS1.8)."""

from __future__ import annotations

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


def _base_cog(evals: dict, *, updated_at: str = "2026-07-29T12:00:00Z") -> dict:
    bars = {tf: {"causal_cutoff_timestamp": updated_at} for tf in evals}
    return {
        "updated_at": updated_at,
        "pid": 42,
        "last_provisional_eval": evals,
        "partial_bars": bars,
        "last_context_event": {},
    }


def test_observe_without_active_is_no_active_context() -> None:
    cog = _base_cog(
        {
            tf: {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"}
            for tf in ("M15", "M30", "H1", "H4")
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["provisional_market_context"] == "OBSERVE"
    assert h4["active_market_context"] is None
    assert h4["lifecycle_state"] == "NO_ACTIVE_CONTEXT"


def test_long_challenged_with_active_episode_preserved() -> None:
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H4": {
                "market_context": "LONG_CONTEXT",
                "lifecycle": "CHALLENGED",
                "active": "LONG_CONTEXT",
                "lifecycle_episode_id": "H4:prov:1",
                "context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
                "context_started_at": "2026-07-29T09:40:34.724226Z",
            },
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["active_market_context"] == "LONG_CONTEXT"
    assert h4["directional_bias"] == "LONG"
    assert h4["lifecycle_state"] == "CHALLENGED"
    assert h4["lifecycle_episode_id"] == "H4:prov:1"
    assert payload["trading_states"]["active_directional_contexts"] == 1


def test_independent_lineage_across_timeframes() -> None:
    cog = _base_cog(
        {
            "M15": {
                "market_context": "LONG_CONTEXT",
                "lifecycle": "ACTIVE",
                "active": "LONG_CONTEXT",
                "lifecycle_episode_id": "M15:ep",
                "context_event_id": "CTX_m15",
            },
            "M30": {
                "market_context": "OBSERVE",
                "lifecycle": "CHALLENGED",
                "active": "SHORT_CONTEXT",
                "lifecycle_episode_id": "M30:ep",
                "context_event_id": "CTX_m30",
            },
            "H1": {
                "market_context": "SHORT_CONTEXT",
                "lifecycle": "CHALLENGED",
                "active": "SHORT_CONTEXT",
                "lifecycle_episode_id": "H1:ep",
                "context_event_id": "CTX_h1",
            },
            "H4": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert tfs["M15"]["active_market_context"] == "LONG_CONTEXT"
    assert tfs["M30"]["provisional_market_context"] == "OBSERVE"
    assert tfs["M30"]["active_market_context"] == "SHORT_CONTEXT"
    assert tfs["M30"]["lifecycle_state"] == "CHALLENGED"
    assert tfs["H1"]["active_market_context"] == "SHORT_CONTEXT"
    assert tfs["H4"]["active_market_context"] is None
    assert payload["trading_states"]["active_directional_contexts"] == 3
    assert payload["trading_states"]["current_directional_evaluations"] == 2
