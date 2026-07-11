"""Tests for shadow cognitive market state memory builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_cognitive_market_state_memory.py"

spec = importlib.util.spec_from_file_location("build_cognitive_market_state_memory", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_cognitive_market_state_memory"] = mod
spec.loader.exec_module(mod)


def _episode_row(**overrides) -> dict:
    base = {
        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
        "close": 64000.0,
        "auction_episode": "BALANCE",
        "episode_status": "DEVELOPING",
        "episode_reason": "test",
        "auction_location": "MIDDLE_AREA",
        "effort_side": "UNKNOWN",
        "effort_result": "UNKNOWN",
        "price_result": "RANGE",
        "follow_through": "UNKNOWN",
    }
    base.update(overrides)
    return base


def test_upper_distribution_maps_to_seller_pressure():
    state, direction, reason = mod.classify_cognitive_market_state(
        auction_episode="UPPER_DISTRIBUTION",
        episode_status="CONFIRMED",
    )
    assert state == "UPPER_DISTRIBUTION"
    assert direction == "SELLER_PRESSURE"
    assert "seller pressure" in reason


def test_failed_breakout_maps_to_upper_distribution():
    state, direction, _ = mod.classify_cognitive_market_state(
        auction_episode="FAILED_BREAKOUT",
        episode_status="DEVELOPING",
    )
    assert state == "UPPER_DISTRIBUTION"
    assert direction == "SELLER_PRESSURE"


def test_lower_absorption_maps_to_buyer_support():
    state, direction, reason = mod.classify_cognitive_market_state(
        auction_episode="LOWER_ABSORPTION",
        episode_status="CONFIRMED",
    )
    assert state == "LOWER_ABSORPTION"
    assert direction == "BUYER_SUPPORT"
    assert "buyer support" in reason


def test_acceptance_higher_and_lower():
    hi, hi_dir, _ = mod.classify_cognitive_market_state(
        auction_episode="ACCEPTANCE_HIGHER",
        episode_status="DEVELOPING",
    )
    lo, lo_dir, _ = mod.classify_cognitive_market_state(
        auction_episode="ACCEPTANCE_LOWER",
        episode_status="DEVELOPING",
    )
    assert hi == "ACCEPTANCE_HIGHER"
    assert hi_dir == "BUYER_CONTROL"
    assert lo == "ACCEPTANCE_LOWER"
    assert lo_dir == "SELLER_CONTROL"


def test_balance_and_unknown():
    bal, bal_dir, bal_reason = mod.classify_cognitive_market_state(
        auction_episode="BALANCE",
        episode_status="DEVELOPING",
    )
    unc, unc_dir, unc_reason = mod.classify_cognitive_market_state(
        auction_episode="UNKNOWN",
        episode_status="UNKNOWN",
    )
    assert bal == "BALANCE"
    assert bal_dir == "NEUTRAL"
    assert "no directional dominance" in bal_reason
    assert unc == "UNCERTAIN"
    assert unc_dir == "UNKNOWN"
    assert "insufficient" in unc_reason


def test_continuation_buyer_seller_control():
    buyer, buyer_dir, _ = mod.classify_cognitive_market_state(
        auction_episode="CONTINUATION",
        episode_status="CONFIRMED",
        effort_side="BUYER",
        effort_result="ACCEPTED",
    )
    seller, seller_dir, _ = mod.classify_cognitive_market_state(
        auction_episode="CONTINUATION",
        episode_status="CONFIRMED",
        effort_side="SELLER",
        effort_result="CONTINUED",
    )
    assert buyer == "BUYER_CONTROL"
    assert buyer_dir == "BUYER_CONTROL"
    assert seller == "SELLER_CONTROL"
    assert seller_dir == "SELLER_CONTROL"


def test_build_rows_invariants_and_required_fields():
    src = pd.DataFrame(
        [
            _episode_row(auction_episode="UPPER_DISTRIBUTION", episode_status="CONFIRMED"),
            _episode_row(
                timestamp=pd.Timestamp("2026-07-10 12:15:00", tz="UTC"),
                auction_episode="LOWER_ABSORPTION",
                episode_status="DEVELOPING",
            ),
            _episode_row(
                timestamp=pd.Timestamp("2026-07-10 12:30:00", tz="UTC"),
                auction_episode="BALANCE",
                episode_status="STARTED",
            ),
            _episode_row(
                timestamp=pd.Timestamp("2026-07-10 12:45:00", tz="UTC"),
                auction_episode="UNKNOWN",
                episode_status="UNKNOWN",
            ),
        ]
    )
    out = mod.build_cognitive_market_state_rows(src)
    assert set(mod.REQUIRED_OUTPUT_COLUMNS).issubset(out.columns)
    assert out["shadow_only"].tolist() == [True, True, True, True]
    assert out["cognitive_market_state"].tolist() == [
        "UPPER_DISTRIBUTION",
        "LOWER_ABSORPTION",
        "BALANCE",
        "UNCERTAIN",
    ]
    assert out["state_direction"].tolist() == [
        "SELLER_PRESSURE",
        "BUYER_SUPPORT",
        "NEUTRAL",
        "UNKNOWN",
    ]
    assert out["state_status"].tolist() == [
        "CONFIRMED",
        "DEVELOPING",
        "DEVELOPING",
        "UNKNOWN",
    ]
    blob = out.to_string()
    assert "LONG_CONTEXT" not in blob
    assert "SHORT_CONTEXT" not in blob


def test_invalidated_upper_distribution_becomes_uncertain():
    state, direction, _ = mod.classify_cognitive_market_state(
        auction_episode="UPPER_DISTRIBUTION",
        episode_status="INVALIDATED",
    )
    assert state == "UNCERTAIN"
    assert direction == "UNKNOWN"


def test_atomic_write(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 13:00:00", tz="UTC"),
                "close": 1.0,
                "primary_auction_episode": "BALANCE",
                "primary_episode_status": "DEVELOPING",
                "primary_episode_reason": "test",
                "cognitive_market_state": "BALANCE",
                "state_direction": "NEUTRAL",
                "state_status": "DEVELOPING",
                "state_reason": "auction episode BALANCE has no directional dominance",
                "auction_location": "MIDDLE_AREA",
                "effort_side": "UNKNOWN",
                "effort_result": "UNKNOWN",
                "price_result": "RANGE",
                "follow_through": "UNKNOWN",
                "source_episode_freshness": "fresh",
                "source_episode_row_count": 1,
                "builder_version": mod.BUILDER_VERSION,
                "shadow_only": True,
            }
        ]
    )
    out = tmp_path / "cognitive_market_state_memory.parquet"
    path = mod.write_atomic_parquet(frame, out)
    assert path.exists()
    loaded = pd.read_parquet(path)
    assert bool(loaded.iloc[0]["shadow_only"]) is True
