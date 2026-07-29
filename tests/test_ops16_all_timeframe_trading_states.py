"""OPS1.6 — Trading State for all LIVE1A timeframes."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import research_pipeline_service as svc  # noqa: E402
import pytest


@pytest.fixture(autouse=True)
def _no_production_journal(monkeypatch):
    monkeypatch.setattr(svc, "_open_context_lineage_from_journal", lambda tf: None)


def _cog(
    *,
    states: dict[str, tuple[str, str]],
    updated_at: str = "2026-07-28T18:40:00Z",
    drop: set[str] | None = None,
) -> dict:
    drop = drop or set()
    evals = {}
    bars = {}
    for tf, (ctx, life) in states.items():
        if tf in drop:
            continue
        evals[tf] = {
            "market_context": ctx,
            "lifecycle": life,
            "active": ctx,
            "lifecycle_episode_id": None if ctx == "OBSERVE" else f"{tf}:ep",
            "context_event_id": None if ctx == "OBSERVE" else f"{tf}:evt",
        }
        bars[tf] = {"causal_cutoff_timestamp": updated_at}
    return {
        "updated_at": updated_at,
        "pid": 1,
        "last_provisional_eval": evals,
        "partial_bars": bars,
        "last_context_event": {},
    }


def test_backend_returns_independent_m15_m30_h1_h4() -> None:
    payload = svc.build_live1a_decision_layer_payload(
        _cog(states={tf: ("OBSERVE", "NO_ACTIVE_CONTEXT") for tf in ("M15", "M30", "H1", "H4")}),
        {"paper_epoch_id": "EPOCH"},
        now=datetime(2026, 7, 28, 18, 40, 5, tzinfo=timezone.utc),
    )
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert set(tfs) == {"M15", "M30", "H1", "H4"}
    for tf, row in tfs.items():
        assert row["timeframe"] == tf
        assert row["trading_state"] == "OBSERVE"
        assert row["directional_bias"] == "NONE"
        assert row["source"] == "LIVE1A_INTRABAR_CONTEXT"


def test_mixed_states_are_not_collapsed() -> None:
    payload = svc.build_live1a_decision_layer_payload(
        _cog(
            states={
                "M15": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
                "M30": ("LONG", "ACTIVE"),
                "H1": ("SHORT", "ACTIVE"),
                "H4": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
            }
        ),
        {"paper_epoch_id": "EPOCH"},
        now=datetime(2026, 7, 28, 18, 40, 5, tzinfo=timezone.utc),
    )
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert tfs["M15"]["trading_state"] == "OBSERVE"
    assert tfs["M30"]["trading_state"] == "LONG_CONTEXT"
    assert tfs["M30"]["directional_bias"] == "LONG"
    assert tfs["H1"]["trading_state"] == "SHORT_CONTEXT"
    assert tfs["H1"]["directional_bias"] == "SHORT"
    assert tfs["H4"]["trading_state"] == "OBSERVE"
    assert payload["trading_states"]["directional_timeframes"] == 2


def test_live1b_m30_decision_does_not_leak_to_other_tfs() -> None:
    paper = {
        "paper_epoch_id": "EPOCH",
        "last_decision": {
            "paper_epoch_id": "EPOCH",
            "timeframe": "M30",
            "lifecycle_episode_id": "M30:ep",
            "context_event_id": "M30:evt",
            "entry_eligible": True,
            "intent": "INTENT_OPEN_LONG",
            "decision_reason": "EDGE_OK",
        },
    }
    payload = svc.build_live1a_decision_layer_payload(
        _cog(
            states={
                "M15": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
                "M30": ("LONG", "ACTIVE"),
                "H1": ("SHORT", "ACTIVE"),
                "H4": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
            }
        ),
        paper,
        now=datetime(2026, 7, 28, 18, 40, 5, tzinfo=timezone.utc),
    )
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert tfs["M30"]["intent"] == "INTENT_OPEN_LONG"
    assert tfs["M30"]["entry_eligible"] is True
    assert tfs["M15"]["intent"] == "NONE"
    assert tfs["M15"]["entry_eligible"] is False
    assert tfs["H1"]["intent"] == "NONE"
    assert tfs["H4"]["intent"] == "NONE"


def test_missing_h4_is_unavailable_others_remain() -> None:
    payload = svc.build_live1a_decision_layer_payload(
        _cog(
            states={
                "M15": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
                "M30": ("LONG", "ACTIVE"),
                "H1": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
                "H4": ("OBSERVE", "NO_ACTIVE_CONTEXT"),
            },
            drop={"H4"},
        ),
        {"paper_epoch_id": "EPOCH"},
        now=datetime(2026, 7, 28, 18, 40, 5, tzinfo=timezone.utc),
    )
    assert payload is not None
    tfs = payload["trading_states"]["timeframes"]
    assert tfs["H4"]["trading_state"] == "UNAVAILABLE"
    assert tfs["H4"]["stale"] is True
    assert tfs["M15"]["trading_state"] == "OBSERVE"
    assert tfs["M30"]["trading_state"] == "LONG_CONTEXT"
    assert tfs["H1"]["trading_state"] == "OBSERVE"
