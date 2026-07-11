"""Tests for market context lifecycle memory builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_market_context_lifecycle_memory.py"

spec = importlib.util.spec_from_file_location("build_market_context_lifecycle_memory", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_market_context_lifecycle_memory"] = mod
spec.loader.exec_module(mod)


def _bar(ts: str, context: str, status: str, **overrides) -> dict:
    base = {
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "close": 100.0,
        "market_context": context,
        "context_status": status,
        "cognitive_market_state": "BALANCE",
        "state_direction": "NEUTRAL",
        "context_reason": f"{context}/{status}",
        "action_allowed": False,
        "action_reason": "shadow market context only; execution disabled",
    }
    base.update(overrides)
    return base


def test_developing_long_creates_candidate_active_stays_observe():
    src = pd.DataFrame([_bar("2026-07-10 12:00:00", "LONG_CONTEXT", "DEVELOPING")])
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[0]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "CANDIDATE"
    assert row["candidate_context"] == "LONG_CONTEXT"


def test_active_long_promotes_from_observe():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "DEVELOPING"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT", "ACTIVE"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["lifecycle_state"] == "CANDIDATE"
    assert out.iloc[0]["active_market_context"] == "OBSERVE"
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "ACTIVE"
    assert "became active" in out.iloc[1]["transition_reason"]


def test_observe_after_active_long_challenges_but_keeps_long():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "CHALLENGED"
    assert out.iloc[1]["challenge_context"] == "OBSERVE"


def test_developing_short_after_active_long_challenges_keeps_long():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE"),
            _bar("2026-07-10 12:15:00", "SHORT_CONTEXT", "DEVELOPING"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "CHALLENGED"
    assert out.iloc[1]["challenge_context"] == "SHORT_CONTEXT"


def test_active_short_replaces_active_long():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE"),
            _bar("2026-07-10 12:15:00", "SHORT_CONTEXT", "ACTIVE"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[1]["active_market_context"] == "SHORT_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "ACTIVE"
    assert "replaced active context" in out.iloc[1]["transition_reason"]


def test_invalidated_resets_to_observe():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT", "INVALIDATED"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[1]["active_market_context"] == "OBSERVE"
    assert out.iloc[1]["lifecycle_state"] == "INVALIDATED"


def test_action_allowed_does_not_change_active_context():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", action_allowed=False),
            _bar("2026-07-10 12:15:00", "SHORT_CONTEXT", "ACTIVE", action_allowed=True),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["active_market_context"] == "SHORT_CONTEXT"
    assert out.iloc[1]["active_market_context"] == "SHORT_CONTEXT"
    assert bool(out.iloc[1]["action_allowed"]) is True


def test_episodes_follow_active_not_raw_and_challenged_does_not_split():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE"),  # challenge, same active
            _bar("2026-07-10 12:30:00", "SHORT_CONTEXT", "DEVELOPING"),  # challenge, same active
            _bar("2026-07-10 12:45:00", "SHORT_CONTEXT", "ACTIVE"),  # replace
        ]
    )
    memory = mod.build_lifecycle_memory(src)
    episodes = mod.build_lifecycle_episodes(memory)
    # active path: LONG, LONG(challenged), LONG(challenged), SHORT
    assert memory["active_market_context"].tolist() == [
        "LONG_CONTEXT",
        "LONG_CONTEXT",
        "LONG_CONTEXT",
        "SHORT_CONTEXT",
    ]
    assert len(episodes) == 2
    assert episodes["active_market_context"].tolist() == ["LONG_CONTEXT", "SHORT_CONTEXT"]
    assert episodes.iloc[0]["bars_count"] == 3
    assert episodes.iloc[0]["challenged_bars_count"] == 2
    assert episodes.iloc[1]["bars_count"] == 1


def test_shadow_only_and_required_fields():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 13:00:00", "OBSERVE", "OBSERVE"),
            _bar("2026-07-10 13:15:00", "LONG_CONTEXT", "ACTIVE"),
        ]
    )
    memory = mod.build_lifecycle_memory(src)
    episodes = mod.build_lifecycle_episodes(memory)
    assert set(mod.REQUIRED_MEMORY_COLUMNS).issubset(memory.columns)
    assert set(mod.REQUIRED_EPISODE_COLUMNS).issubset(episodes.columns)
    assert memory["shadow_only"].astype(bool).all()
    assert episodes["shadow_only"].astype(bool).all()


def test_atomic_write(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 14:00:00", tz="UTC"),
                "close": 1.0,
                "raw_market_context": "OBSERVE",
                "raw_context_status": "OBSERVE",
                "raw_cognitive_market_state": "BALANCE",
                "raw_state_direction": "NEUTRAL",
                "raw_context_reason": "x",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "active_context_started_at": pd.Timestamp("2026-07-10 14:00:00", tz="UTC"),
                "active_context_age_bars": 0,
                "candidate_context": None,
                "candidate_started_at": None,
                "candidate_reason": None,
                "challenge_context": None,
                "challenge_started_at": None,
                "challenge_reason": None,
                "transition_reason": "initial",
                "action_allowed": False,
                "action_reason": "shadow",
                "shadow_only": True,
                "builder_version": mod.BUILDER_VERSION,
            }
        ]
    )
    path = mod.write_atomic_parquet(frame, tmp_path / "market_context_lifecycle_memory.parquet")
    assert path.exists()
