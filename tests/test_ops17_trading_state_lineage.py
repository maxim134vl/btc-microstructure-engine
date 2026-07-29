"""OPS1.7 — repair mixed LIVE1A trading-state lineage in OPS presentation."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import research_pipeline_service as svc  # noqa: E402


NOW = datetime(2026, 7, 29, 12, 0, 5, tzinfo=timezone.utc)


def _base_cog(evals: dict, *, updated_at: str = "2026-07-29T12:00:00Z") -> dict:
    bars = {tf: {"causal_cutoff_timestamp": updated_at} for tf in evals}
    return {
        "updated_at": updated_at,
        "pid": 42,
        "last_provisional_eval": evals,
        "partial_bars": bars,
        "last_context_event": {},
    }


def test_observe_with_legacy_challenged_becomes_no_active_context() -> None:
    """LIVE1A tip can carry residual CHALLENGED under OBSERVE; OPS must not."""
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT", "active": "OBSERVE"},
            "H4": {
                "market_context": "OBSERVE",
                "lifecycle": "CHALLENGED",
                "active": "LONG_CONTEXT",  # stale residual; must not drive trading_state
            },
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    h4 = payload["trading_states"]["timeframes"]["H4"]
    assert h4["trading_state"] == "OBSERVE"
    assert h4["market_state"] == "OBSERVE"
    assert h4["directional_bias"] == "NONE"
    assert h4["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert h4["lifecycle_episode_id"] is None
    assert h4["context_event_id"] is None
    assert payload["trading_states"]["directional_timeframes"] == 0


def test_long_challenged_with_active_episode_preserved() -> None:
    cog = _base_cog(
        {
            "M15": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT"},
            "M30": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT"},
            "H1": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT"},
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
    assert h4["trading_state"] == "LONG_CONTEXT"
    assert h4["directional_bias"] == "LONG"
    assert h4["lifecycle_state"] == "CHALLENGED"
    assert h4["lifecycle_episode_id"] == "H4:prov:1"
    assert h4["context_event_id"] == "CTX_d25c0ed08fd7b1d5c8af"
    assert payload["trading_states"]["directional_timeframes"] == 1


def test_independent_lineage_across_timeframes() -> None:
    cog = _base_cog(
        {
            "M15": {
                "market_context": "LONG_CONTEXT",
                "lifecycle": "ACTIVE",
                "lifecycle_episode_id": "M15:ep",
                "context_event_id": "CTX_m15",
            },
            "M30": {
                "market_context": "OBSERVE",
                "lifecycle": "CHALLENGED",  # residual — must normalize
                "active": "SHORT_CONTEXT",
            },
            "H1": {
                "market_context": "SHORT_CONTEXT",
                "lifecycle": "CHALLENGED",
                "lifecycle_episode_id": "H1:ep",
                "context_event_id": "CTX_h1",
            },
            "H4": {"market_context": "OBSERVE", "lifecycle": "NO_ACTIVE_CONTEXT"},
        }
    )
    payload = svc.build_live1a_decision_layer_payload(cog, {"paper_epoch_id": "EPOCH"}, now=NOW)
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert tfs["M15"]["trading_state"] == "LONG_CONTEXT"
    assert tfs["M15"]["lifecycle_episode_id"] == "M15:ep"
    assert tfs["M30"]["trading_state"] == "OBSERVE"
    assert tfs["M30"]["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert tfs["M30"]["lifecycle_episode_id"] is None
    assert tfs["H1"]["trading_state"] == "SHORT_CONTEXT"
    assert tfs["H1"]["lifecycle_state"] == "CHALLENGED"
    assert tfs["H1"]["lifecycle_episode_id"] == "H1:ep"
    assert tfs["H4"]["trading_state"] == "OBSERVE"
    assert tfs["H4"]["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    # CHALLENGED alone does not inflate directional count
    assert payload["trading_states"]["directional_timeframes"] == 2
