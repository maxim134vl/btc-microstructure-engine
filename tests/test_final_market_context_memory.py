"""Tests for shadow final market context memory builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_final_market_context_memory.py"

spec = importlib.util.spec_from_file_location("build_final_market_context_memory", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_final_market_context_memory"] = mod
spec.loader.exec_module(mod)


def _state_row(**overrides) -> dict:
    base = {
        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
        "close": 64000.0,
        "cognitive_market_state": "BALANCE",
        "state_direction": "NEUTRAL",
        "state_status": "DEVELOPING",
        "state_reason": "test",
    }
    base.update(overrides)
    return base


def test_lower_absorption_to_long():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="BUYER_SUPPORT",
        state_status="CONFIRMED",
    )
    assert ctx == "LONG_CONTEXT"
    assert reason == "LOWER_ABSORPTION implies LONG_CONTEXT"


def test_acceptance_higher_to_long():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="DEVELOPING",
    )
    assert ctx == "LONG_CONTEXT"
    assert reason == "ACCEPTANCE_HIGHER implies LONG_CONTEXT"


def test_buyer_control_to_long():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="BUYER_CONTROL",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
    )
    assert ctx == "LONG_CONTEXT"
    assert reason == "BUYER_CONTROL implies LONG_CONTEXT"


def test_upper_distribution_to_short():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_direction="SELLER_PRESSURE",
        state_status="CONFIRMED",
    )
    assert ctx == "SHORT_CONTEXT"
    assert reason == "UPPER_DISTRIBUTION implies SHORT_CONTEXT"


def test_acceptance_lower_to_short():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="DEVELOPING",
    )
    assert ctx == "SHORT_CONTEXT"
    assert reason == "ACCEPTANCE_LOWER implies SHORT_CONTEXT"


def test_seller_control_to_short():
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="SELLER_CONTROL",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
    )
    assert ctx == "SHORT_CONTEXT"
    assert reason == "SELLER_CONTROL implies SHORT_CONTEXT"


def test_balance_and_uncertain_to_observe():
    bal, bal_reason = mod.classify_market_context(
        cognitive_market_state="BALANCE",
        state_direction="NEUTRAL",
        state_status="DEVELOPING",
    )
    unc, unc_reason = mod.classify_market_context(
        cognitive_market_state="UNCERTAIN",
        state_direction="UNKNOWN",
        state_status="UNKNOWN",
    )
    assert bal == "OBSERVE"
    assert bal_reason == "BALANCE implies OBSERVE"
    assert unc == "OBSERVE"
    assert unc_reason == "UNCERTAIN implies OBSERVE"


def test_invalidated_state_to_observe_with_invalidated_status():
    ctx, _ = mod.classify_market_context(
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_direction="SELLER_PRESSURE",
        state_status="INVALIDATED",
    )
    status = mod.classify_context_status(market_context=ctx, state_status="INVALIDATED")
    assert ctx == "OBSERVE"
    assert status == "INVALIDATED"


def test_short_context_not_erased_by_trade_ban():
    """Trading disable must not rewrite SHORT_CONTEXT to OBSERVE."""
    ctx, reason = mod.classify_market_context(
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_direction="SELLER_PRESSURE",
        state_status="CONFIRMED",
    )
    assert ctx == "SHORT_CONTEXT"
    assert "SHORT_DISABLED" not in reason
    assert "execution" not in reason.lower()
    # Even if we later set action_allowed=False, market_context stays SHORT.
    row = mod.build_final_market_context_rows(
        pd.DataFrame(
            [
                _state_row(
                    cognitive_market_state="UPPER_DISTRIBUTION",
                    state_direction="SELLER_PRESSURE",
                    state_status="CONFIRMED",
                )
            ]
        )
    ).iloc[0]
    assert row["market_context"] == "SHORT_CONTEXT"
    assert row["action_allowed"] is False or bool(row["action_allowed"]) is False
    assert row["action_reason"] == mod.ACTION_REASON


def test_build_rows_invariants_and_required_fields():
    src = pd.DataFrame(
        [
            _state_row(
                cognitive_market_state="LOWER_ABSORPTION",
                state_direction="BUYER_SUPPORT",
                state_status="CONFIRMED",
            ),
            _state_row(
                timestamp=pd.Timestamp("2026-07-10 12:15:00", tz="UTC"),
                cognitive_market_state="UPPER_DISTRIBUTION",
                state_direction="SELLER_PRESSURE",
                state_status="DEVELOPING",
            ),
            _state_row(
                timestamp=pd.Timestamp("2026-07-10 12:30:00", tz="UTC"),
                cognitive_market_state="BALANCE",
                state_direction="NEUTRAL",
                state_status="STARTED",
            ),
        ]
    )
    out = mod.build_final_market_context_rows(src)
    assert set(mod.REQUIRED_OUTPUT_COLUMNS).issubset(out.columns)
    assert out["market_context"].tolist() == ["LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"]
    assert out["context_status"].tolist() == ["ACTIVE", "DEVELOPING", "OBSERVE"]
    assert out["action_allowed"].tolist() == [False, False, False]
    assert out["shadow_only"].tolist() == [True, True, True]
    assert (out["action_reason"] == mod.ACTION_REASON).all()


def test_context_status_mapping():
    assert mod.classify_context_status(market_context="LONG_CONTEXT", state_status="CONFIRMED") == "ACTIVE"
    assert mod.classify_context_status(market_context="SHORT_CONTEXT", state_status="DEVELOPING") == "DEVELOPING"
    assert mod.classify_context_status(market_context="OBSERVE", state_status="DEVELOPING") == "OBSERVE"
    assert mod.classify_context_status(market_context="LONG_CONTEXT", state_status="UNKNOWN") == "UNKNOWN"


def test_atomic_write(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 13:00:00", tz="UTC"),
                "close": 1.0,
                "cognitive_market_state": "BALANCE",
                "state_direction": "NEUTRAL",
                "state_status": "DEVELOPING",
                "state_reason": "test",
                "market_context": "OBSERVE",
                "context_status": "OBSERVE",
                "context_reason": "BALANCE implies OBSERVE",
                "action_allowed": False,
                "action_reason": mod.ACTION_REASON,
                "source_state_freshness": "fresh",
                "builder_version": mod.BUILDER_VERSION,
                "shadow_only": True,
            }
        ]
    )
    out = tmp_path / "final_market_context_memory.parquet"
    path = mod.write_atomic_parquet(frame, out)
    assert path.exists()
    loaded = pd.read_parquet(path)
    assert bool(loaded.iloc[0]["shadow_only"]) is True
    assert bool(loaded.iloc[0]["action_allowed"]) is False
