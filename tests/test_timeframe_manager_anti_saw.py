"""Lock: bar-count anti-saw stays archived and unwired.

That implementation delayed every flip CLOSE and re-OPEN by N bars
(M15 4/4 = 60 minutes) without asking whether the market was in a saw.
Do not restore it. The surviving saw signal is auction path-density.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from btc_ml.trading.timeframe_manager import ANTI_SAW_ENABLED, _is_context_flip_close

ROOT = Path(__file__).resolve().parents[1]
MANAGER = (ROOT / "src/btc_ml/trading/timeframe_manager.py").read_text(encoding="utf-8")


def test_bar_count_anti_saw_flag_stays_off() -> None:
    assert ANTI_SAW_ENABLED is False


def test_manager_does_not_import_or_call_bar_count_rails() -> None:
    assert "ANTI_SAW_SUPPRESS_CONTEXT_FLIP_CLOSE" not in MANAGER
    assert "_anti_saw_block_context_close" not in MANAGER
    assert "_anti_saw_block_entry" not in MANAGER
    assert "ANTI_SAW_MIN_HOLD" not in MANAGER
    assert "ANTI_SAW_ENTRY_COOLDOWN" not in MANAGER


def test_archive_corpse_refuses_import() -> None:
    with pytest.raises(ImportError, match="archived"):
        from btc_ml.trading.archive import anti_saw_bar_count_rails  # noqa: F401


def test_flip_close_still_detected_without_anti_saw() -> None:
    assert _is_context_flip_close(
        {
            "is_close": True,
            "exited_on_flip": True,
            "exit_preview_action": "PREVIEW_CLOSE_LONG_CONTEXT_EXIT",
            "exit_preview_reason": "CONTEXT_FLIP_LONG_TO_SHORT",
            "context_exit_preview": True,
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
