"""Lock: M15 must not wait 45 minutes after painted context start/change.

Live tape: context painted at 03:30, M15_7 OPEN LONG at 04:15; context change
at 09:00, flip/close at 09:49. That is MIN_ACTIVE_CONTEXT_HOLD_BARS=3
(3 * 15m) plus live anti-saw M15 4/4. Do not restore either delay.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

from btc_ml.trading.timeframe_manager import ANTI_SAW_ENABLED

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "research" / "build_market_context_lifecycle_memory.py"
spec = importlib.util.spec_from_file_location("build_market_context_lifecycle_memory", MODULE_PATH)
assert spec and spec.loader
_mod = importlib.util.module_from_spec(spec)
sys.modules.setdefault("build_market_context_lifecycle_memory", _mod)
spec.loader.exec_module(_mod)

BASE_TS = pd.Timestamp("2026-09-09 03:30:00", tz="UTC")


def _ts(i: int) -> str:
    return (BASE_TS + pd.Timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M:%S")


def _bar(i: int, context: str, status: str, **overrides) -> dict:
    direction = "LONG" if "LONG" in context else "SHORT" if "SHORT" in context else "NEUTRAL"
    auction = {
        "LONG_CONTEXT": "LOWER_ABSORPTION",
        "SHORT_CONTEXT": "UPPER_DISTRIBUTION",
    }.get(context, "BALANCE")
    base = {
        "timestamp": pd.Timestamp(_ts(i), tz="UTC"),
        "close": 100.0,
        "market_context": context,
        "context_status": status,
        "cognitive_market_state": auction,
        "state_direction": direction,
        "context_reason": f"{context}/{status}",
        "auction_episode": auction,
        "action_allowed": False,
        "action_reason": "shadow market context only; execution disabled",
    }
    base.update(overrides)
    return base


def test_production_live_fills_from_context_journal() -> None:
    raw = json.loads((ROOT / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    assert raw["entry_source"] == "context_journal"


def test_lifecycle_constants_forbid_m15_45min_hold() -> None:
    assert _mod.MIN_ACTIVE_CONTEXT_HOLD_BARS == 0
    assert _mod.CONFIRMED_OPPOSITE_CONFIRM_BARS == 1
    assert ANTI_SAW_ENABLED is False


def test_m15_open_follows_first_confirmed_context_not_plus_45m() -> None:
    out = _mod.build_lifecycle_memory(pd.DataFrame([_bar(0, "LONG_CONTEXT", "ACTIVE"), _bar(1, "LONG_CONTEXT", "ACTIVE")]))
    assert out.iloc[0]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[0]["lifecycle_state"] == "ACTIVE"
    start = pd.Timestamp(out.iloc[0]["active_context_started_at"])
    later = pd.Timestamp(out.iloc[1]["timestamp"])
    assert (later - start) == pd.Timedelta(minutes=15)


def test_m15_close_follows_first_confirmed_opposite_not_plus_45m() -> None:
    out = _mod.build_lifecycle_memory(
        pd.DataFrame([_bar(0, "LONG_CONTEXT", "ACTIVE"), _bar(1, "SHORT_CONTEXT", "ACTIVE")])
    )
    assert out.iloc[0]["active_market_context"] == "LONG_CONTEXT"
    flip = out.iloc[1]
    assert flip["active_market_context"] == "SHORT_CONTEXT"
    assert flip["lifecycle_state"] == "ACTIVE"
    assert flip["invalidation_type"] == "OPPOSITE_CONTEXT_REPLACEMENT"
    origin = pd.Timestamp(out.iloc[0]["timestamp"])
    change = pd.Timestamp(flip["timestamp"])
    assert (change - origin) == pd.Timedelta(minutes=15)


def test_m15_developing_opposite_still_does_not_replace() -> None:
    out = _mod.build_lifecycle_memory(
        pd.DataFrame([_bar(0, "LONG_CONTEXT", "ACTIVE"), _bar(1, "SHORT_CONTEXT", "DEVELOPING")])
    )
    assert out.iloc[1]["active_market_context"] == "LONG_CONTEXT"
    assert out.iloc[1]["lifecycle_state"] == "CHALLENGED"


def test_anti_saw_off_does_not_hold_m15_flip_or_reentry() -> None:
    assert ANTI_SAW_ENABLED is False
    src = (ROOT / "src/btc_ml/trading/timeframe_manager.py").read_text(encoding="utf-8")
    assert "_anti_saw_block_context_close" not in src
    assert "_anti_saw_block_entry" not in src
