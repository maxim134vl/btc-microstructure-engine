"""Tests for shadow final market context episodes builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_final_market_context_episodes.py"

spec = importlib.util.spec_from_file_location("build_final_market_context_episodes", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_final_market_context_episodes"] = mod
spec.loader.exec_module(mod)


def _bar(ts: str, context: str, **overrides) -> dict:
    base = {
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "close": 100.0,
        "market_context": context,
        "cognitive_market_state": "BALANCE",
        "state_direction": "NEUTRAL",
        "context_status": "OBSERVE" if context == "OBSERVE" else "DEVELOPING",
        "context_reason": f"{context} reason",
        "action_allowed": False,
    }
    base.update(overrides)
    return base


def test_three_long_bars_one_episode():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT", close=100.0, cognitive_market_state="LOWER_ABSORPTION", state_direction="BUYER_SUPPORT", context_status="ACTIVE"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT", close=101.0, cognitive_market_state="LOWER_ABSORPTION", state_direction="BUYER_SUPPORT", context_status="ACTIVE"),
            _bar("2026-07-10 12:30:00", "LONG_CONTEXT", close=102.0, cognitive_market_state="ACCEPTANCE_HIGHER", state_direction="BUYER_CONTROL", context_status="DEVELOPING"),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert len(out) == 1
    ep = out.iloc[0]
    assert ep["episode_id"] == 1
    assert ep["market_context"] == "LONG_CONTEXT"
    assert ep["bars_count"] == 3
    assert ep["start_time"] == pd.Timestamp("2026-07-10 12:00:00", tz="UTC")
    assert ep["end_time"] == pd.Timestamp("2026-07-10 12:30:00", tz="UTC")
    assert ep["duration_minutes"] == 30.0
    assert ep["end_reason"] == "latest open episode"
    assert ep["dominant_context_status"] == "ACTIVE"
    assert ep["dominant_state_direction"] == "BUYER_SUPPORT"


def test_long_long_observe_two_episodes():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "LONG_CONTEXT"),
            _bar("2026-07-10 12:15:00", "LONG_CONTEXT"),
            _bar("2026-07-10 12:30:00", "OBSERVE"),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert len(out) == 2
    assert out["market_context"].tolist() == ["LONG_CONTEXT", "OBSERVE"]
    assert out["bars_count"].tolist() == [2, 1]
    assert out.iloc[0]["end_reason"] == "market_context changed from LONG_CONTEXT to OBSERVE"
    assert out.iloc[1]["end_reason"] == "latest open episode"


def test_short_short_long_two_episodes():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 13:00:00", "SHORT_CONTEXT"),
            _bar("2026-07-10 13:15:00", "SHORT_CONTEXT"),
            _bar("2026-07-10 13:30:00", "LONG_CONTEXT"),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert out["market_context"].tolist() == ["SHORT_CONTEXT", "LONG_CONTEXT"]
    assert out["episode_id"].tolist() == [1, 2]


def test_observe_between_long_creates_three_episodes():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 14:00:00", "LONG_CONTEXT"),
            _bar("2026-07-10 14:15:00", "OBSERVE"),
            _bar("2026-07-10 14:30:00", "LONG_CONTEXT"),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert len(out) == 3
    assert out["market_context"].tolist() == ["LONG_CONTEXT", "OBSERVE", "LONG_CONTEXT"]
    assert out["episode_id"].tolist() == [1, 2, 3]
    assert out["bars_count"].tolist() == [1, 1, 1]


def test_action_allowed_flags_and_shadow_only():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 15:00:00", "SHORT_CONTEXT", action_allowed=False),
            _bar("2026-07-10 15:15:00", "SHORT_CONTEXT", action_allowed=True),
            _bar("2026-07-10 15:30:00", "OBSERVE", action_allowed=False),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert bool(out.iloc[0]["action_allowed_any"]) is True
    assert bool(out.iloc[0]["action_allowed_all"]) is False
    assert bool(out.iloc[1]["action_allowed_any"]) is False
    assert bool(out.iloc[1]["action_allowed_all"]) is False
    assert out["shadow_only"].astype(bool).tolist() == [True, True]


def test_does_not_alter_market_context_values_and_has_required_fields():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 16:00:00", "OBSERVE"),
            _bar("2026-07-10 16:15:00", "SHORT_CONTEXT"),
            _bar("2026-07-10 16:30:00", "SHORT_CONTEXT"),
        ]
    )
    out = mod.build_final_market_context_episodes(src)
    assert set(mod.REQUIRED_OUTPUT_COLUMNS).issubset(out.columns)
    assert set(out["market_context"]) <= {"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"}
    assert out["market_context"].tolist() == ["OBSERVE", "SHORT_CONTEXT"]


def test_atomic_write(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "episode_id": 1,
                "market_context": "OBSERVE",
                "start_time": pd.Timestamp("2026-07-10 17:00:00", tz="UTC"),
                "end_time": pd.Timestamp("2026-07-10 17:00:00", tz="UTC"),
                "start_close": 1.0,
                "end_close": 1.0,
                "bars_count": 1,
                "duration_minutes": 0.0,
                "start_cognitive_market_state": "BALANCE",
                "end_cognitive_market_state": "BALANCE",
                "start_context_status": "OBSERVE",
                "end_context_status": "OBSERVE",
                "dominant_context_status": "OBSERVE",
                "dominant_state_direction": "NEUTRAL",
                "action_allowed_any": False,
                "action_allowed_all": False,
                "shadow_only": True,
                "start_reason": "BALANCE implies OBSERVE",
                "end_reason": "latest open episode",
                "builder_version": mod.BUILDER_VERSION,
            }
        ]
    )
    out = tmp_path / "final_market_context_episodes.parquet"
    path = mod.write_atomic_parquet(frame, out)
    assert path.exists()
    loaded = pd.read_parquet(path)
    assert bool(loaded.iloc[0]["shadow_only"]) is True
