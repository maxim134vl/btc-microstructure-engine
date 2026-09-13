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
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", tmp_path / "missing_journal.jsonl")
    monkeypatch.setattr(tct, "paper_uses_context_journal", lambda: True)

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "OBSERVE"
    assert state["context_source"] == "LIVE1A_INTRABAR_CONTEXT"
    assert state["manager_lifecycle_episode_id"] is None
    assert state["manager_instruction"] == "NO_ACTION"


def _write_live1a_observe(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "updated_at": "2026-09-10T05:11:00Z",
                "last_provisional_eval": {
                    "M15": {
                        "market_context": "OBSERVE",
                        "lifecycle": "NO_ACTIVE_CONTEXT",
                        "active": "OBSERVE",
                    }
                },
                "partial_bars": {
                    "M15": {"causal_cutoff_timestamp": "2026-09-10T05:11:00Z"},
                },
                "last_context_event": {},
            }
        ),
        encoding="utf-8",
    )


def _write_manager_long(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "evaluation_timestamp": "2026-09-10T05:00:00Z",
                "commands": {
                    "M15": {
                        "timeframe_state": "LONG_CONTEXT",
                        "timeframe_direction": "LONG",
                        "intent": "OPEN_LONG",
                        "lifecycle_episode_id": "M15:265",
                        "lifecycle_phase": "ACTIVE",
                        "evaluation_timestamp": "2026-09-10T05:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_journal_paper_tip_does_not_keep_manager_long(tmp_path, monkeypatch) -> None:
    health = tmp_path / "intrabar_cognition_health.json"
    manager = tmp_path / "timeframe_manager_latest.json"
    _write_live1a_observe(health)
    _write_manager_long(manager)
    monkeypatch.setattr(tct, "LIVE1A_HEALTH", health)
    monkeypatch.setattr(tct, "MTF_AVAILABILITY", tmp_path / "missing_mtf.json")
    monkeypatch.setattr(tct, "MANAGER_LATEST", manager)
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", tmp_path / "missing_journal.jsonl")
    monkeypatch.setattr(tct, "paper_uses_context_journal", lambda: True)

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "OBSERVE"
    assert state["context_source"] == "LIVE1A_INTRABAR_CONTEXT"
    assert state["manager_instruction"] == "NO_ACTION"
    assert state["manager_lifecycle_episode_id"] is None
    assert state["active_market_context"] is None


def test_s41_paper_tip_keeps_manager_long_over_observe(tmp_path, monkeypatch) -> None:
    health = tmp_path / "intrabar_cognition_health.json"
    manager = tmp_path / "timeframe_manager_latest.json"
    _write_live1a_observe(health)
    _write_manager_long(manager)
    monkeypatch.setattr(tct, "LIVE1A_HEALTH", health)
    monkeypatch.setattr(tct, "MTF_AVAILABILITY", tmp_path / "missing_mtf.json")
    monkeypatch.setattr(tct, "MANAGER_LATEST", manager)
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", tmp_path / "missing_journal.jsonl")
    monkeypatch.setattr(tct, "LIFECYCLE_MEMORY", tmp_path / "missing_lifecycle.parquet")
    monkeypatch.setattr(tct, "paper_uses_context_journal", lambda: False)

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "LONG_CONTEXT"
    assert state["context_source"] == "timeframe_command_memory"
    assert state["manager_instruction"] == "OPEN_LONG"
    assert state["manager_lifecycle_episode_id"] == "M15:265"


def test_s41_paper_tip_keeps_manager_long_over_live1a_short(tmp_path, monkeypatch) -> None:
    health = tmp_path / "intrabar_cognition_health.json"
    manager = tmp_path / "timeframe_manager_latest.json"
    health.write_text(
        json.dumps(
            {
                "updated_at": "2026-09-13T11:30:00Z",
                "last_provisional_eval": {
                    "M15": {
                        "market_context": "OBSERVE",
                        "lifecycle": "CHALLENGED",
                        "active": "SHORT_CONTEXT",
                        "provisional_market_context": "OBSERVE",
                        "active_market_context": "SHORT_CONTEXT",
                        "lifecycle_state": "CHALLENGED",
                        "lifecycle_episode_id": "M15:prov:1",
                        "context_started_at": "2026-09-11T15:55:42Z",
                    }
                },
                "partial_bars": {"M15": {"causal_cutoff_timestamp": "2026-09-13T11:30:00Z"}},
                "last_context_event": {
                    "M15": {
                        "event_type": "CONTEXT_FLIP",
                        "new_context": "SHORT_CONTEXT",
                        "event_timestamp": "2026-09-11T15:55:42Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _write_manager_long(manager)
    monkeypatch.setattr(tct, "LIVE1A_HEALTH", health)
    monkeypatch.setattr(tct, "MTF_AVAILABILITY", tmp_path / "missing_mtf.json")
    monkeypatch.setattr(tct, "MANAGER_LATEST", manager)
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", tmp_path / "missing_journal.jsonl")
    monkeypatch.setattr(tct, "LIFECYCLE_MEMORY", tmp_path / "missing_lifecycle.parquet")
    monkeypatch.setattr(tct, "paper_uses_context_journal", lambda: False)

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "LONG_CONTEXT"
    assert state["context_source"] == "timeframe_command_memory"
    assert state["manager_lifecycle_episode_id"] == "M15:265"


def test_s41_memory_tip_overrides_manager_and_stale_live1a(tmp_path, monkeypatch) -> None:
    import pandas as pd

    health = tmp_path / "intrabar_cognition_health.json"
    manager = tmp_path / "timeframe_manager_latest.json"
    memory = tmp_path / "lifecycle.parquet"
    _write_live1a_observe(health)
    _write_manager_long(manager)
    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-10T05:00:00Z"),
                "timeframe": "M15",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 88,
            }
        ]
    ).to_parquet(memory, index=False)
    monkeypatch.setattr(tct, "LIVE1A_HEALTH", health)
    monkeypatch.setattr(tct, "MTF_AVAILABILITY", tmp_path / "missing_mtf.json")
    monkeypatch.setattr(tct, "MANAGER_LATEST", manager)
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", tmp_path / "missing_journal.jsonl")
    monkeypatch.setattr(tct, "LIFECYCLE_MEMORY", memory)
    monkeypatch.setattr(tct, "paper_uses_context_journal", lambda: False)

    state = tct.load_tf_state("M15")
    assert state["directional_state"] == "SHORT_CONTEXT"
    assert state["context_source"] == "market_context_lifecycle_memory"
    assert state["manager_lifecycle_episode_id"] == "M15:88"
    assert state["manager_instruction"] == "OPEN_LONG"
