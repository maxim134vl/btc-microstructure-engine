"""OPS1.4 — visual current state prefers LIVE1A over closed-bar tip."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIS = ROOT / "apps" / "context_visualizer"
if str(VIS) not in sys.path:
    sys.path.insert(0, str(VIS))

import timeframe_chart_truth as tct  # noqa: E402


def test_load_tf_state_prefers_live1a_observe(tmp_path, monkeypatch) -> None:
    health = tmp_path / "intrabar_cognition_health.json"
    health.write_text(
        json.dumps(
            {
                "updated_at": "2026-07-28T17:52:00Z",
                "last_provisional_eval": {
                    "M15": {
                        "market_context": "OBSERVE",
                        "lifecycle": "NO_ACTIVE_CONTEXT",
                        "active": "OBSERVE",
                    }
                },
                "partial_bars": {
                    "M15": {"causal_cutoff_timestamp": "2026-07-28T17:52:00Z"},
                },
                "last_context_event": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tct, "LIVE1A_HEALTH", health)
    monkeypatch.setattr(tct, "MTF_AVAILABILITY", tmp_path / "missing_mtf.json")
    monkeypatch.setattr(tct, "MANAGER_LATEST", tmp_path / "missing_manager.json")

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "OBSERVE"
    assert state["context_source"] == "LIVE1A_INTRABAR_CONTEXT"
    assert state["manager_lifecycle_episode_id"] is None
    assert state["manager_instruction"] == "NO_ACTION"
