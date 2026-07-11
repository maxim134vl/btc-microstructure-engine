"""Tests for market context lifecycle memory builder (incl. auction invalidation)."""

from __future__ import annotations

import importlib.util
import json
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
        "auction_episode": "UNKNOWN",
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
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "ACTIVE"


def test_short_auction_neutralization_invalidates_to_observe():
    src = pd.DataFrame(
        [
            _bar(
                "2026-07-10 12:00:00",
                "SHORT_CONTEXT",
                "ACTIVE",
                cognitive_market_state="UPPER_DISTRIBUTION",
                state_direction="SHORT",
                auction_episode="UPPER_DISTRIBUTION",
            ),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="BALANCE",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "INVALIDATED"
    assert row["invalidation_type"] == "AUCTION_NEUTRALIZATION"
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"
    assert row["active_context_age_bars"] == 0
    assert pd.isna(row["active_context_started_at"]) or row["active_context_started_at"] is None
    assert "BALANCE / NEUTRAL / OBSERVE" in row["invalidation_reason"]


def test_observe_no_active_context_age_always_zero():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert (out["active_market_context"] == "OBSERVE").all()
    assert (out["lifecycle_state"] == "NO_ACTIVE_CONTEXT").all()
    assert (out["active_context_age_bars"] == 0).all()
    assert out["active_context_started_at"].isna().all()


def test_active_long_age_grows():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
            _bar("2026-07-10 12:30:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["active_context_age_bars"] == 0
    assert out.iloc[1]["active_context_age_bars"] == 1
    assert out.iloc[2]["active_context_age_bars"] == 2


def test_active_short_age_grows():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
            _bar("2026-07-10 12:15:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["active_context_age_bars"] == 0
    assert out.iloc[1]["active_context_age_bars"] == 1


def test_neutralization_then_observe_keeps_age_zero_and_invalidation_fields():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                auction_episode="BALANCE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
            ),
            _bar(
                "2026-07-10 12:30:00",
                "OBSERVE",
                "OBSERVE",
                auction_episode="BALANCE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[-1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] in {"INVALIDATED", "NO_ACTIVE_CONTEXT"}
    assert int(row["active_context_age_bars"]) == 0
    assert pd.isna(row["active_context_started_at"]) or row["active_context_started_at"] is None
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"
    assert row["invalidation_type"] == "AUCTION_NEUTRALIZATION"

def test_long_auction_neutralization_invalidates_to_observe():
    src = pd.DataFrame(
        [
            _bar(
                "2026-07-10 12:00:00",
                "LONG_CONTEXT",
                "ACTIVE",
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="LONG",
                auction_episode="LOWER_ABSORPTION",
            ),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="BALANCE",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "INVALIDATED"
    assert row["invalidation_type"] == "AUCTION_NEUTRALIZATION"
    assert row["previous_active_market_context"] == "LONG_CONTEXT"


def test_short_observe_without_auction_balance_stays_challenged():
    src = pd.DataFrame(
        [
            _bar(
                "2026-07-10 12:00:00",
                "SHORT_CONTEXT",
                "ACTIVE",
                cognitive_market_state="UPPER_DISTRIBUTION",
                state_direction="SHORT",
                auction_episode="UPPER_DISTRIBUTION",
            ),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="UPPER_DISTRIBUTION",  # not BALANCE
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[1]
    assert row["active_market_context"] == "SHORT_CONTEXT"
    assert row["lifecycle_state"] == "CHALLENGED"
    assert row["invalidation_type"] == "NONE"


def test_long_observe_without_auction_balance_stays_challenged():
    src = pd.DataFrame(
        [
            _bar(
                "2026-07-10 12:00:00",
                "LONG_CONTEXT",
                "ACTIVE",
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="LONG",
                auction_episode="LOWER_ABSORPTION",
            ),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="LOWER_ABSORPTION",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "CHALLENGED"
    assert out.iloc[1]["invalidation_type"] == "NONE"


def test_short_replaced_by_active_long_opposite_replacement():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[1]
    assert row["active_market_context"] == "LONG_CONTEXT"
    assert row["lifecycle_state"] == "ACTIVE"
    assert row["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"


def test_long_replaced_by_active_short_opposite_replacement():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
            _bar("2026-07-10 12:15:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[1]
    assert row["active_market_context"] == "SHORT_CONTEXT"
    assert row["lifecycle_state"] == "ACTIVE"
    assert row["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    assert row["previous_active_market_context"] == "LONG_CONTEXT"


def test_age_bars_not_used_as_invalidation_rule():
    # Many challenged OBSERVE bars without auction BALANCE must stay SHORT.
    rows = [
        _bar(
            "2026-07-10 12:00:00",
            "SHORT_CONTEXT",
            "ACTIVE",
            cognitive_market_state="UPPER_DISTRIBUTION",
            state_direction="SHORT",
            auction_episode="UPPER_DISTRIBUTION",
        )
    ]
    for i in range(1, 40):
        rows.append(
            _bar(
                f"2026-07-10 {12 + (i * 15) // 60:02d}:{(i * 15) % 60:02d}:00",
                "OBSERVE",
                "OBSERVE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="UPPER_DISTRIBUTION",
            )
        )
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    assert out.iloc[-1]["active_market_context"] == "SHORT_CONTEXT"
    assert out.iloc[-1]["lifecycle_state"] == "CHALLENGED"
    assert int(out.iloc[-1]["active_context_age_bars"]) >= 30
    assert out.iloc[-1]["invalidation_type"] == "NONE"


def test_challenge_ratio_not_used_as_invalidation_rule():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", "ACTIVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="LOWER_ABSORPTION", state_direction="LONG"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="BALANCE", state_direction="NEUTRAL"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="BALANCE", state_direction="NEUTRAL"),
            _bar("2026-07-10 12:45:00", "OBSERVE", "OBSERVE", auction_episode="LOWER_ABSORPTION", cognitive_market_state="BALANCE", state_direction="NEUTRAL"),
        ]
    )
    memory = mod.build_lifecycle_memory(src)
    episodes = mod.build_lifecycle_episodes(memory)
    assert memory.iloc[-1]["active_market_context"] == "LONG_CONTEXT"
    assert memory.iloc[-1]["lifecycle_state"] == "CHALLENGED"
    # High challenge ratio inside episode, still not invalidated.
    assert episodes.iloc[0]["challenged_bars_count"] / episodes.iloc[0]["bars_count"] > 0.5
    assert memory.iloc[-1]["invalidation_type"] == "NONE"


def test_action_allowed_does_not_drive_invalidation_and_stays_false():
    src = pd.DataFrame(
        [
            _bar(
                "2026-07-10 12:00:00",
                "SHORT_CONTEXT",
                "ACTIVE",
                action_allowed=True,
                auction_episode="UPPER_DISTRIBUTION",
                cognitive_market_state="UPPER_DISTRIBUTION",
                state_direction="SHORT",
            ),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                action_allowed=True,
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                auction_episode="BALANCE",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    # Invalidation still happens from auction confluence, not from action_allowed.
    assert out.iloc[1]["lifecycle_state"] == "INVALIDATED"
    assert out.iloc[1]["active_market_context"] == "OBSERVE"
    assert bool(out.iloc[0]["action_allowed"]) is False
    assert bool(out.iloc[1]["action_allowed"]) is False


def test_episodes_close_directional_on_invalidation_and_start_observe():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="BALANCE", state_direction="NEUTRAL"),
            _bar(
                "2026-07-10 12:30:00",
                "OBSERVE",
                "OBSERVE",
                auction_episode="BALANCE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
            ),
        ]
    )
    memory = mod.build_lifecycle_memory(src)
    episodes = mod.build_lifecycle_episodes(memory)
    assert memory["active_market_context"].tolist() == ["SHORT_CONTEXT", "SHORT_CONTEXT", "OBSERVE"]
    assert len(episodes) == 2
    assert episodes.iloc[0]["active_market_context"] == "SHORT_CONTEXT"
    assert episodes.iloc[0]["end_time"] == pd.Timestamp("2026-07-10 12:15:00", tz="UTC")
    assert episodes.iloc[1]["active_market_context"] == "OBSERVE"
    assert episodes.iloc[1]["start_time"] == pd.Timestamp("2026-07-10 12:30:00", tz="UTC")
    assert "neutralization" in episodes.iloc[0]["end_reason"].lower()


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


def test_visual_latest_matches_lifecycle_invalidation_fields(tmp_path: Path):
    # Build memory, then mimic visual latest payload fields.
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "SHORT_CONTEXT", "ACTIVE", auction_episode="UPPER_DISTRIBUTION", cognitive_market_state="UPPER_DISTRIBUTION", state_direction="SHORT"),
            _bar(
                "2026-07-10 12:15:00",
                "OBSERVE",
                "OBSERVE",
                auction_episode="BALANCE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
            ),
        ]
    )
    memory = mod.build_lifecycle_memory(src)
    latest = memory.iloc[-1]
    prev = latest["previous_active_market_context"]
    inv_type = latest["invalidation_type"]
    status_line = (
        f"{latest['active_market_context']} · {latest['lifecycle_state']} · "
        f"previous {prev} invalidated · {inv_type}"
    )
    visual_latest = {
        "active_market_context": latest["active_market_context"],
        "lifecycle_state": latest["lifecycle_state"],
        "invalidation_type": inv_type,
        "previous_active_market_context": prev,
        "active_context_age_bars": int(latest["active_context_age_bars"]),
        "status_line": status_line,
    }
    path = tmp_path / "lifecycle_latest.json"
    path.write_text(json.dumps(visual_latest), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["active_market_context"] == "OBSERVE"
    assert loaded["lifecycle_state"] == "INVALIDATED"
    assert loaded["invalidation_type"] == "AUCTION_NEUTRALIZATION"
    assert loaded["previous_active_market_context"] == "SHORT_CONTEXT"
    assert loaded["active_context_age_bars"] == 0
    assert "age" not in loaded["status_line"].lower()
    assert "previous SHORT_CONTEXT invalidated" in loaded["status_line"]


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
                "raw_auction_episode": "BALANCE",
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
                "previous_active_market_context": None,
                "invalidation_reason": None,
                "invalidated_at": None,
                "invalidated_by_auction_episode": None,
                "invalidated_by_cognitive_state": None,
                "invalidated_by_market_context": None,
                "invalidation_type": "NONE",
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
