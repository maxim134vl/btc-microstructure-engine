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


BASE_TS = pd.Timestamp("2026-07-10 12:00:00", tz="UTC")


def _ts(i: int) -> str:
    return (BASE_TS + pd.Timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M:%S")


def _short_active(i: int) -> dict:
    return _bar(
        _ts(i),
        "SHORT_CONTEXT",
        "ACTIVE",
        auction_episode="UPPER_DISTRIBUTION",
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_direction="SHORT",
    )


def _long_active(i: int) -> dict:
    return _bar(
        _ts(i),
        "LONG_CONTEXT",
        "ACTIVE",
        auction_episode="LOWER_ABSORPTION",
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="LONG",
    )


def _neutral(i: int, *, auction: str = "BALANCE", **overrides) -> dict:
    return _bar(
        _ts(i),
        "OBSERVE",
        "OBSERVE",
        auction_episode=auction,
        cognitive_market_state="BALANCE",
        state_direction="NEUTRAL",
        **overrides,
    )


# Number of same-direction ACTIVE bars required so the last active bar has
# age >= MIN_ACTIVE_CONTEXT_HOLD_BARS (age is 0-indexed within the run).
def _active_bars_to_pass_hold() -> int:
    return mod.MIN_ACTIVE_CONTEXT_HOLD_BARS + 1


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


def test_short_auction_neutralization_invalidates_after_persistence():
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    # NEUTRALIZATION_CONFIRM_BARS consecutive neutral bars after min hold invalidate.
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    row = out.iloc[-1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "INVALIDATED"
    assert row["invalidation_type"] == "AUCTION_NEUTRALIZATION"
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"
    assert row["active_context_age_bars"] == 0
    assert pd.isna(row["active_context_started_at"]) or row["active_context_started_at"] is None
    assert "neutralization" in row["invalidation_reason"].lower()


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


def test_observe_no_active_context_reports_explicit_block_reason():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE", close=101.0),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert row["transition_block_reason"] == "NO_DIRECTIONAL_CONTEXT"
    assert row["observe_block_reason"] == "NO_DIRECTIONAL_CONTEXT"
    assert row["observe_escape_candidate"] is False or bool(row["observe_escape_candidate"]) is False
    assert float(row["market_activity_score"]) == 1.0
    assert float(row["state_age_minutes"]) == 15.0


def test_stale_runtime_cognition_marks_state_not_silent_observe():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:45:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 13:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE", close=101.0),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    out = mod.build_lifecycle_memory(src, cognition_frame=cognition)
    row = out.iloc[-1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "STALE_COGNITION"
    assert row["transition_block_reason"] == "STALE_COGNITION"
    assert row["observe_block_reason"] == "STALE_COGNITION"
    assert float(row["upstream_cognition_freshness_minutes"]) == 60.0
    assert float(row["cognition_state_age_minutes"]) == 60.0
    assert float(row["market_feed_age_minutes"]) == 15.0
    assert "stale upstream cognition" in row["lifecycle_state_reason"]
    assert "normal observe" not in str(row["observe_block_reason"]).lower()
    assert bool(row["observe_escape_candidate"]) is False


def test_directional_context_exits_observe_even_after_stale_observe_diagnostic():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:45:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 13:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar(
                "2026-07-10 13:15:00",
                "LONG_CONTEXT",
                "ACTIVE",
                auction_episode="LOWER_ABSORPTION",
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="BUYER_SUPPORT",
            ),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    out = mod.build_lifecycle_memory(src, cognition_frame=cognition)
    assert out.iloc[4]["lifecycle_state"] == "STALE_COGNITION"
    assert out.iloc[5]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[5]["lifecycle_state"] == "ACTIVE"
    assert out.iloc[5]["observe_block_reason"] is None or pd.isna(out.iloc[5]["observe_block_reason"])


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
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    row = out.iloc[-1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] in {"INVALIDATED", "NO_ACTIVE_CONTEXT"}
    assert int(row["active_context_age_bars"]) == 0
    assert pd.isna(row["active_context_started_at"]) or row["active_context_started_at"] is None
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"
    assert row["invalidation_type"] == "AUCTION_NEUTRALIZATION"


def test_long_auction_neutralization_invalidates_after_persistence():
    n_active = _active_bars_to_pass_hold()
    rows = [_long_active(i) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    row = out.iloc[-1]
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
    n_active = _active_bars_to_pass_hold()
    rows = [dict(_short_active(i), action_allowed=True) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j, action_allowed=True))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    # Invalidation still happens from auction confluence, not from action_allowed.
    assert out.iloc[-1]["lifecycle_state"] == "INVALIDATED"
    assert out.iloc[-1]["active_market_context"] == "OBSERVE"
    assert (~out["action_allowed"].astype(bool)).all()


def test_episodes_close_directional_on_invalidation_and_start_observe():
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    memory = mod.build_lifecycle_memory(pd.DataFrame(rows))
    episodes = mod.build_lifecycle_episodes(memory)
    contexts = memory["active_market_context"].tolist()
    # Directional context persists through the hold/challenge window, then closes to OBSERVE.
    assert contexts[0] == "SHORT_CONTEXT"
    assert contexts[-1] == "OBSERVE"
    assert len(episodes) == 2
    assert episodes.iloc[0]["active_market_context"] == "SHORT_CONTEXT"
    assert episodes.iloc[1]["active_market_context"] == "OBSERVE"
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
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    memory = mod.build_lifecycle_memory(pd.DataFrame(rows))
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


def test_single_balance_bar_challenges_long_not_invalidate():
    src = pd.DataFrame([_long_active(0), _neutral(1)])
    row = mod.build_lifecycle_memory(src).iloc[1]
    assert row["active_market_context"] == "LONG_CONTEXT"
    assert row["lifecycle_state"] == "CHALLENGED"
    assert row["invalidation_type"] == "NONE"


def test_single_balance_bar_challenges_short_not_invalidate():
    src = pd.DataFrame([_short_active(0), _neutral(1)])
    row = mod.build_lifecycle_memory(src).iloc[1]
    assert row["active_market_context"] == "SHORT_CONTEXT"
    assert row["lifecycle_state"] == "CHALLENGED"
    assert row["invalidation_type"] == "NONE"


def test_young_active_not_neutralized_before_min_hold():
    # Activate, then feed several neutralization bars while still under min hold.
    rows = [_long_active(0)]
    for j in range(mod.MIN_ACTIVE_CONTEXT_HOLD_BARS):
        rows.append(_neutral(1 + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    # Every bar within the minimum hold window keeps the directional context alive.
    for i in range(1, mod.MIN_ACTIVE_CONTEXT_HOLD_BARS):
        assert out.iloc[i]["active_market_context"] == "LONG_CONTEXT"
        assert out.iloc[i]["lifecycle_state"] == "CHALLENGED"
        assert out.iloc[i]["invalidation_type"] == "NONE"


def test_long_two_neutral_bars_after_min_hold_invalidate():
    n_active = _active_bars_to_pass_hold()
    rows = [_long_active(i) for i in range(n_active)]
    rows.append(_neutral(n_active))
    rows.append(_neutral(n_active + 1))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    # First neutral bar after hold challenges, second invalidates.
    assert out.iloc[n_active]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[n_active]["lifecycle_state"] == "CHALLENGED"
    assert out.iloc[n_active + 1]["active_market_context"] == "OBSERVE"
    assert out.iloc[n_active + 1]["lifecycle_state"] == "INVALIDATED"
    assert out.iloc[n_active + 1]["invalidation_type"] == "AUCTION_NEUTRALIZATION"


def test_opposite_confirmed_replaces_immediately_before_min_hold():
    # Fresh SHORT (age 0), then confirmed LONG on next bar replaces immediately.
    src = pd.DataFrame([_short_active(0), _long_active(1)])
    row = mod.build_lifecycle_memory(src).iloc[1]
    assert row["active_market_context"] == "LONG_CONTEXT"
    assert row["lifecycle_state"] == "ACTIVE"
    assert row["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    assert row["previous_active_market_context"] == "SHORT_CONTEXT"


def test_source_invalidated_before_min_hold_becomes_challenged():
    src = pd.DataFrame(
        [
            _short_active(0),
            _bar(
                _ts(1),
                "SHORT_CONTEXT",
                "INVALIDATED",
                auction_episode="BALANCE",
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
            ),
        ]
    )
    row = mod.build_lifecycle_memory(src).iloc[1]
    assert row["active_market_context"] == "SHORT_CONTEXT"
    assert row["lifecycle_state"] == "CHALLENGED"
    assert row["invalidation_type"] == "NONE"


def test_source_invalidated_after_min_hold_closes_to_observe():
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    rows.append(
        _bar(
            _ts(n_active),
            "SHORT_CONTEXT",
            "INVALIDATED",
            auction_episode="BALANCE",
            cognitive_market_state="BALANCE",
            state_direction="NEUTRAL",
        )
    )
    row = mod.build_lifecycle_memory(pd.DataFrame(rows)).iloc[-1]
    assert row["active_market_context"] == "OBSERVE"
    assert row["lifecycle_state"] == "INVALIDATED"
    assert row["invalidation_type"] == "THESIS_REJECTION"


def test_invalidation_type_not_carried_forward_after_event():
    n_active = _active_bars_to_pass_hold()
    rows = [_short_active(i) for i in range(n_active)]
    # Two neutral bars to invalidate, then extra neutral bars afterwards.
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS + 2):
        rows.append(_neutral(n_active + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    inv_rows = out.index[out["invalidation_type"] == "AUCTION_NEUTRALIZATION"].tolist()
    # AUCTION_NEUTRALIZATION labels exactly one event row, not every later OBSERVE bar.
    assert len(inv_rows) == 1
    # Rows after the invalidation event are plain NO_ACTIVE_CONTEXT with no repeat label.
    after = out.iloc[inv_rows[0] + 1 :]
    assert (after["invalidation_type"] == "NONE").all()
    assert (after["lifecycle_state"] == "NO_ACTIVE_CONTEXT").all()


def test_shadow_only_stays_true_through_persistence_protection():
    n_active = _active_bars_to_pass_hold()
    rows = [_long_active(i) for i in range(n_active)]
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n_active + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    assert out["shadow_only"].astype(bool).all()
    assert (~out["action_allowed"].astype(bool)).all()


def test_neutralization_streak_not_in_output_columns():
    src = pd.DataFrame([_long_active(0), _neutral(1)])
    out = mod.build_lifecycle_memory(src)
    assert "_neutralization_streak" not in out.columns
    assert list(out.columns) == mod.REQUIRED_MEMORY_COLUMNS


def test_persistence_constants_are_conservative_defaults():
    assert mod.NEUTRALIZATION_CONFIRM_BARS == 2
    assert mod.MIN_ACTIVE_CONTEXT_HOLD_BARS == 3


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


def test_cli_output_path_defaults_to_production_and_accepts_override(tmp_path: Path):
    args = mod.parse_args([])
    assert Path(args.output_path) == mod.MEMORY_OUTPUT_PATH
    assert Path(args.episodes_output_path) == mod.EPISODES_OUTPUT_PATH
    custom_mem = tmp_path / "market_context_lifecycle_memory.parquet.candidate"
    custom_ep = tmp_path / "market_context_lifecycle_episodes.parquet.candidate"
    args2 = mod.parse_args(
        ["--output-path", str(custom_mem), "--episodes-output-path", str(custom_ep)]
    )
    assert Path(args2.output_path) == custom_mem
    assert Path(args2.episodes_output_path) == custom_ep


def test_normalize_utc_ns_series_handles_mixed_inputs():
    ns = pd.Series(pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True).astype("datetime64[ns, UTC]"))
    us = pd.Series(pd.array(pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True), dtype="datetime64[us, UTC]"))
    naive = pd.Series(pd.to_datetime(["2026-07-10T12:00:00"]))
    iso = pd.Series(["2026-07-10T12:00:00Z", "not-a-time"])
    empty = pd.Series([], dtype="object")
    with_nat = pd.Series(
        pd.array(
            [pd.Timestamp("2026-07-10T12:00:00Z"), pd.NaT],
            dtype="datetime64[us, UTC]",
        )
    )

    for series in (ns, us, naive, iso, empty, with_nat):
        out = mod.normalize_utc_ns_series(series)
        assert str(out.dtype) == "datetime64[ns, UTC]"
    assert pd.isna(mod.normalize_utc_ns_series(iso).iloc[1])
    assert pd.isna(mod.normalize_utc_ns_series(with_nat).iloc[1])
    assert mod.normalize_utc_ns_series(us).iloc[0] == pd.Timestamp("2026-07-10T12:00:00Z")


def test_attach_runtime_cognition_freshness_ns_us_mismatch_regression():
    """Reproduce real merge_asof failure: lifecycle ns vs cognition us."""
    lifecycle = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-10T12:00:00Z", "2026-07-10T12:15:00Z", "2026-07-10T12:30:00Z"],
                utc=True,
            ).astype("datetime64[ns, UTC]"),
            "market_context": ["OBSERVE", "OBSERVE", "OBSERVE"],
            "close": [100.0, 100.5, 101.0],
        }
    )
    # Deliberately reverse order to prove output order is restored.
    lifecycle = lifecycle.iloc[::-1].reset_index(drop=True)
    original_ts = list(lifecycle["timestamp"])

    cognition = pd.DataFrame(
        {
            "timestamp": pd.array(
                pd.to_datetime(
                    ["2026-07-10T12:00:00Z", pd.NaT, "2026-07-10T12:15:00Z"],
                    utc=True,
                ),
                dtype="datetime64[us, UTC]",
            ),
            "synthesis_state": ["LOCAL_EXHAUSTION", "IGNORED", "LOCAL_EXHAUSTION"],
        }
    )

    assert str(lifecycle["timestamp"].dtype) == "datetime64[ns, UTC]"
    assert str(cognition["timestamp"].dtype) == "datetime64[us, UTC]"

    out = mod.attach_runtime_cognition_freshness(lifecycle, cognition_frame=cognition)
    assert len(out) == len(lifecycle)
    assert list(out["timestamp"]) == original_ts
    assert float(out.iloc[0]["upstream_cognition_freshness_minutes"]) == 15.0
    assert float(out.iloc[1]["upstream_cognition_freshness_minutes"]) == 0.0
    assert float(out.iloc[2]["upstream_cognition_freshness_minutes"]) == 0.0
    assert float(out.iloc[0]["cognition_state_age_minutes"]) == 15.0


def test_fresh_market_fresh_cognition_no_directional_is_normal_observe():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T11:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    evaluation = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-10T12:00:00Z", "2026-07-10T12:15:00Z"],
                utc=True,
            )
        }
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert row["observe_block_reason"] == "NO_DIRECTIONAL_CONTEXT"
    assert float(row["upstream_cognition_freshness_minutes"]) == 0.0
    assert float(row["cognition_state_age_minutes"]) == 75.0


def test_fresh_market_stale_cognition_is_stale_not_observe():
    # Regular M15 market cadence (fresh feed) with evaluations stopped at 12:00.
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:45:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 13:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    evaluation = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True)}
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "STALE_COGNITION"
    assert row["observe_block_reason"] == "STALE_COGNITION"
    assert row["transition_block_reason"] == "STALE_COGNITION"
    assert float(row["upstream_cognition_freshness_minutes"]) == 60.0
    assert float(row["market_feed_age_minutes"]) == 15.0


def test_stale_market_and_stale_cognition_reasons_are_separate():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            # Gap > canonical 45m stale threshold => stale market feed cadence.
            _bar("2026-07-10 13:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    evaluation = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True)}
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "STALE_COGNITION"
    assert row["transition_block_reason"] == "STALE_MARKET_AND_COGNITION"
    assert row["observe_block_reason"] == "STALE_MARKET_AND_COGNITION"
    assert "stale market feed" in row["lifecycle_state_reason"]
    assert "stale upstream cognition" in row["lifecycle_state_reason"]
    assert float(row["market_feed_age_minutes"]) == 90.0
    assert float(row["upstream_cognition_freshness_minutes"]) == 90.0


def test_sparse_event_log_with_fresh_evaluations_allows_carry_forward():
    # State unchanged for 4h, but evaluations continue every 15m.
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 16:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    evaluation = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-10T15:45:00Z", "2026-07-10T16:00:00Z"],
                utc=True,
            )
        }
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert row["observe_block_reason"] == "NO_DIRECTIONAL_CONTEXT"
    assert float(row["cognition_state_age_minutes"]) == 240.0
    assert float(row["upstream_cognition_freshness_minutes"]) == 0.0


def test_sparse_event_log_with_stopped_evaluations_becomes_stale():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:30:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:45:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 13:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T10:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    evaluation = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-07-10T12:00:00Z"], utc=True)}
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    row = out.iloc[-1]
    assert row["lifecycle_state"] == "STALE_COGNITION"
    assert float(row["cognition_state_age_minutes"]) == 180.0
    assert float(row["upstream_cognition_freshness_minutes"]) == 60.0
    assert float(row["market_feed_age_minutes"]) == 15.0


def test_fresh_long_short_not_destroyed_by_stale_control():
    src = pd.DataFrame(
        [
            _long_active(0),
            _long_active(1),
            _short_active(2),
            _short_active(3),
        ]
    )
    cognition = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T11:00:00Z"], utc=True),
            "synthesis_state": ["LOCAL_EXHAUSTION"],
        }
    )
    # Evaluations stopped on purpose; directional contexts must still survive.
    evaluation = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-07-10T11:00:00Z"], utc=True)}
    )
    out = mod.build_lifecycle_memory(
        src, cognition_frame=cognition, evaluation_frame=evaluation
    )
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "ACTIVE"
    assert out.iloc[3]["active_market_context"] == "SHORT_CONTEXT"
    assert out.iloc[3]["lifecycle_state"] == "ACTIVE"


def test_empty_cognition_frame_returns_degraded_without_exception():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
            _bar("2026-07-10 12:15:00", "OBSERVE", "OBSERVE", auction_episode="BALANCE"),
        ]
    )
    out = mod.build_lifecycle_memory(src, cognition_frame=pd.DataFrame())
    assert len(out) == 2
    assert out.iloc[-1]["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert pd.isna(out.iloc[-1]["upstream_cognition_freshness_minutes"])
    assert out.iloc[-1]["observe_block_reason"] == "NO_DIRECTIONAL_CONTEXT"


def test_origin_created_on_first_long_episode_bar():
    src = pd.DataFrame(
        [
            _bar("2026-07-10 12:00:00", "OBSERVE", "OBSERVE"),
            _bar(
                "2026-07-10 12:15:00",
                "LONG_CONTEXT",
                "ACTIVE",
                close=101.0,
                auction_episode="LOWER_ABSORPTION",
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="LONG",
            ),
            _bar(
                "2026-07-10 12:30:00",
                "LONG_CONTEXT",
                "ACTIVE",
                close=102.0,
                auction_episode="LOWER_ABSORPTION",
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="LONG",
            ),
        ]
    )
    out = mod.build_lifecycle_memory(src)
    long_rows = out[out["active_market_context"] == "LONG_CONTEXT"]
    assert len(long_rows) >= 2
    assert float(long_rows.iloc[0]["context_origin_price"]) == 101.0
    assert long_rows.iloc[0]["context_direction"] == "LONG_CONTEXT"
    assert long_rows.iloc[0]["context_entered_at"] == long_rows.iloc[0]["timestamp"]


def test_origin_created_on_first_short_episode_bar():
    rows = [_short_active(0), _short_active(1)]
    rows[0]["close"] = 200.0
    rows[1]["close"] = 199.0
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    short_rows = out[out["active_market_context"] == "SHORT_CONTEXT"]
    assert float(short_rows.iloc[0]["context_origin_price"]) == 200.0
    assert short_rows.iloc[0]["context_direction"] == "SHORT_CONTEXT"


def test_origin_immutable_within_episode():
    rows = [_long_active(i) for i in range(4)]
    rows[0]["close"] = 100.0
    rows[1]["close"] = 101.0
    rows[2]["close"] = 102.5
    rows[3]["close"] = 99.5
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    origins = out.loc[out["active_market_context"] == "LONG_CONTEXT", "context_origin_price"]
    assert origins.nunique() == 1
    assert float(origins.iloc[0]) == 100.0


def test_new_episode_gets_new_origin():
    n = mod.MIN_ACTIVE_CONTEXT_HOLD_BARS + 1
    rows = [_long_active(i) for i in range(n)]
    for i in range(n):
        rows[i]["close"] = 100.0 + i
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n + j))
    short_start = n + mod.NEUTRALIZATION_CONFIRM_BARS
    rows.append(_short_active(short_start))
    rows[-1]["close"] = 90.0
    rows.append(_short_active(short_start + 1))
    rows[-1]["close"] = 89.0
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    long_origin = out.loc[out["active_market_context"] == "LONG_CONTEXT", "context_origin_price"].iloc[0]
    short_origin = out.loc[out["active_market_context"] == "SHORT_CONTEXT", "context_origin_price"].iloc[0]
    assert float(long_origin) == 100.0
    assert float(short_origin) == 90.0
    assert float(long_origin) != float(short_origin)


def test_invalidation_clears_origin_on_observe():
    n = mod.MIN_ACTIVE_CONTEXT_HOLD_BARS + 1
    rows = [_long_active(i) for i in range(n)]
    rows[0]["close"] = 111.0
    for j in range(mod.NEUTRALIZATION_CONFIRM_BARS):
        rows.append(_neutral(n + j))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    observe = out[out["active_market_context"] == "OBSERVE"]
    assert len(observe) >= 1
    assert observe.iloc[-1]["context_origin_price"] is None or pd.isna(observe.iloc[-1]["context_origin_price"])
    assert observe.iloc[-1]["context_direction"] is None or pd.isna(observe.iloc[-1]["context_direction"])


def test_signed_distance_symmetric_long_short():
    long_d = mod.signed_context_distance_bps("LONG_CONTEXT", 100.0, 101.0)
    short_d = mod.signed_context_distance_bps("SHORT_CONTEXT", 100.0, 99.0)
    assert long_d == 100.0
    assert short_d == 100.0
    assert mod.signed_context_distance_bps("LONG_CONTEXT", 100.0, 99.0) == -100.0
    assert mod.signed_context_distance_bps("SHORT_CONTEXT", 100.0, 101.0) == -100.0


def test_lifecycle_origin_matches_episode_start_close():
    rows = [_long_active(i) for i in range(3)]
    rows[0]["close"] = 123.45
    rows[1]["close"] = 124.0
    rows[2]["close"] = 125.0
    memory = mod.build_lifecycle_memory(pd.DataFrame(rows))
    episodes = mod.build_lifecycle_episodes(memory)
    long_ep = episodes[episodes["active_market_context"] == "LONG_CONTEXT"].iloc[0]
    long_bars = memory[memory["active_market_context"] == "LONG_CONTEXT"]
    assert float(long_bars.iloc[0]["context_origin_price"]) == float(long_ep["start_close"])
    assert int(long_bars.iloc[0]["context_episode_id"]) == int(long_ep["episode_id"])


def test_candidate_does_not_create_trading_origin():
    src = pd.DataFrame([_bar("2026-07-10 12:00:00", "LONG_CONTEXT", "DEVELOPING", close=150.0)])
    out = mod.build_lifecycle_memory(src)
    assert out.iloc[0]["lifecycle_state"] == "CANDIDATE"
    assert out.iloc[0]["active_market_context"] == "OBSERVE"
    assert out.iloc[0]["context_origin_price"] is None or pd.isna(out.iloc[0]["context_origin_price"])


def _short_developing(i: int) -> dict:
    return _bar(
        _ts(i),
        "SHORT_CONTEXT",
        "DEVELOPING",
        auction_episode="ACCEPTANCE_LOWER",
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
    )


def _long_developing(i: int) -> dict:
    return _bar(
        _ts(i),
        "LONG_CONTEXT",
        "DEVELOPING",
        auction_episode="LOWER_ABSORPTION",
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="BUYER_SUPPORT",
    )


def test_single_developing_opposite_challenges_not_replaces():
    """One DEVELOPING opposite bar must only CHALLENGE, never replace."""
    rows = [_long_active(i) for i in range(_active_bars_to_pass_hold())]
    rows.append(_short_developing(len(rows)))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    last = out.iloc[-1]
    assert last["active_market_context"] == "LONG_CONTEXT"
    assert last["lifecycle_state"] == "CHALLENGED"
    assert last["invalidation_type"] == "NONE"


def test_two_consecutive_developing_opposite_replaces_mature_active():
    """Two consecutive DEVELOPING opposite bars replace a mature active context."""
    rows = [_long_active(i) for i in range(_active_bars_to_pass_hold())]
    n = len(rows)
    rows.append(_short_developing(n))
    rows.append(_short_developing(n + 1))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    last = out.iloc[-1]
    assert last["active_market_context"] == "SHORT_CONTEXT"
    assert last["lifecycle_state"] == "ACTIVE"
    assert last["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    assert last["previous_active_market_context"] == "LONG_CONTEXT"


def test_developing_opposite_does_not_replace_young_active():
    """Even two consecutive DEVELOPING opposite bars cannot replace a young active."""
    rows = [_long_active(0), _short_developing(1), _short_developing(2)]
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    last = out.iloc[-1]
    assert last["active_market_context"] == "LONG_CONTEXT"
    assert last["lifecycle_state"] == "CHALLENGED"


def test_developing_opposite_streak_resets_on_gap():
    """A non-opposite bar between two DEVELOPING opposite bars resets the streak."""
    rows = [_long_active(i) for i in range(_active_bars_to_pass_hold())]
    n = len(rows)
    rows.append(_short_developing(n))
    rows.append(_long_active(n + 1))
    rows.append(_short_developing(n + 2))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    last = out.iloc[-1]
    assert last["active_market_context"] == "LONG_CONTEXT"
    assert last["lifecycle_state"] == "CHALLENGED"


def test_developing_opposite_short_to_long_symmetric():
    """Developing LONG opposite replaces mature SHORT the same way."""
    rows = [_short_active(i) for i in range(_active_bars_to_pass_hold())]
    n = len(rows)
    rows.append(_long_developing(n))
    rows.append(_long_developing(n + 1))
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    last = out.iloc[-1]
    assert last["active_market_context"] == "LONG_CONTEXT"
    assert last["lifecycle_state"] == "ACTIVE"
    assert last["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    assert last["previous_active_market_context"] == "SHORT_CONTEXT"


def test_developing_opposite_streak_not_in_output():
    """Internal streak counter must not leak into output columns."""
    rows = [_long_active(0), _short_developing(1)]
    out = mod.build_lifecycle_memory(pd.DataFrame(rows))
    assert "_developing_opposite_streak" not in out.columns


def test_developing_opposite_confirm_bars_constant():
    assert mod.DEVELOPING_OPPOSITE_CONFIRM_BARS == 2
