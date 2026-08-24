"""Anti-saw rails on S4.1 timeframe manager (flip close + entry cooldown)."""

from __future__ import annotations

from btc_ml.trading.timeframe_manager import (
    ANTI_SAW_ENTRY_COOLDOWN_BARS,
    ANTI_SAW_MIN_HOLD_BARS,
    _anti_saw_block_context_close,
    _anti_saw_block_entry,
    _bars_elapsed,
    _is_context_flip_close,
    _record_anti_saw_context_close,
    _record_anti_saw_entry,
)


def test_bars_elapsed_m15() -> None:
    assert _bars_elapsed("M15", "2026-08-22T10:00:00Z", "2026-08-22T11:00:00Z") == 4.0
    assert _bars_elapsed("H1", "2026-08-22T10:00:00Z", "2026-08-22T12:00:00Z") == 2.0


def test_is_context_flip_close_detects_flip_not_hold() -> None:
    assert _is_context_flip_close(
        {
            "is_close": True,
            "exited_on_flip": True,
            "exit_preview_action": "PREVIEW_CLOSE_LONG_CONTEXT_EXIT",
            "exit_preview_reason": "CONTEXT_FLIP_LONG_TO_SHORT|HOLD_UNTIL_DIRECTIONAL_CONTEXT_END:SHORT_CONTEXT/ACTIVE",
            "context_exit_preview": True,
        }
    )
    assert not _is_context_flip_close(
        {
            "is_close": False,
            "exit_preview_action": "PREVIEW_HOLD_LONG",
            "exit_preview_reason": "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END",
        }
    )
    assert not _is_context_flip_close(
        {
            "is_close": True,
            "exit_preview_action": "PREVIEW_CLOSE_LONG_STOP_LOSS",
            "exit_preview_reason": "STOP_LOSS_HIT",
            "context_exit_preview": False,
        }
    )


def test_min_hold_blocks_young_context_flip() -> None:
    per_tf = {"anti_saw_entry_at": "2026-08-22T10:00:00Z"}
    blocked, reason = _anti_saw_block_context_close(
        timeframe="M15",
        evaluation_timestamp="2026-08-22T10:30:00Z",  # 2 bars < 4
        open_position={},
        per_tf_state=per_tf,
        meta={},
    )
    assert blocked is True
    assert reason and reason.startswith("ANTI_SAW_MIN_HOLD:")


def test_min_hold_allows_mature_context_flip() -> None:
    per_tf = {"anti_saw_entry_at": "2026-08-22T10:00:00Z"}
    blocked, reason = _anti_saw_block_context_close(
        timeframe="M15",
        evaluation_timestamp="2026-08-22T11:00:00Z",  # 4 bars == threshold
        open_position={},
        per_tf_state=per_tf,
        meta={},
    )
    assert blocked is False
    assert reason is None
    assert ANTI_SAW_MIN_HOLD_BARS["M15"] == 4


def test_entry_cooldown_after_context_close() -> None:
    per_tf: dict = {}
    _record_anti_saw_context_close(
        per_tf,
        evaluation_timestamp="2026-08-22T12:00:00Z",
        side="LONG",
        episode="M15:547",
    )
    blocked, reason = _anti_saw_block_entry(
        timeframe="M15",
        evaluation_timestamp="2026-08-22T12:30:00Z",  # 2 bars < 4
        per_tf_state=per_tf,
    )
    assert blocked is True
    assert reason and reason.startswith("ANTI_SAW_ENTRY_COOLDOWN:")

    blocked_ok, _ = _anti_saw_block_entry(
        timeframe="M15",
        evaluation_timestamp="2026-08-22T13:00:00Z",  # 4 bars
        per_tf_state=per_tf,
    )
    assert blocked_ok is False
    assert ANTI_SAW_ENTRY_COOLDOWN_BARS["M15"] == 4


def test_entry_record_sets_anchor_for_later_min_hold() -> None:
    per_tf: dict = {}
    _record_anti_saw_entry(
        per_tf,
        evaluation_timestamp="2026-08-22T08:00:00Z",
        side="SHORT",
        episode="M15:550",
        context_started_at="2026-08-22T07:30:00Z",
    )
    assert per_tf["anti_saw_entry_at"] == "2026-08-22T08:00:00Z"
    assert per_tf["anti_saw_entry_side"] == "SHORT"
    blocked, _ = _anti_saw_block_context_close(
        timeframe="M15",
        evaluation_timestamp="2026-08-22T08:15:00Z",
        open_position={},
        per_tf_state=per_tf,
        meta={},
    )
    assert blocked is True
