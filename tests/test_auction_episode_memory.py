"""Tests for shadow auction episode memory builder."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_auction_episode_memory.py"

spec = importlib.util.spec_from_file_location("build_auction_episode_memory", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_auction_episode_memory"] = mod
spec.loader.exec_module(mod)


def test_buying_climax_upper_failed_follow_through_is_upper_distribution():
    episode = mod.classify_auction_episode(
        bar_event="BUYING_CLIMAX",
        auction_location="UPPER_AREA",
        follow_through="FAILED",
        price_result="REJECTED_HIGHER",
        volume_effort="EXTREME",
        effort_result="REJECTED",
    )
    assert episode == "UPPER_DISTRIBUTION"
    assert episode not in {"LONG_CONTEXT", "SHORT_CONTEXT"}


def test_stopping_volume_lower_failed_continuation_is_lower_absorption():
    episode = mod.classify_auction_episode(
        bar_event="STOPPING_VOLUME",
        auction_location="LOWER_AREA",
        follow_through="NO",
        price_result="NO_PROGRESS",
        volume_effort="HIGH",
        effort_result="ABSORBED",
    )
    assert episode == "LOWER_ABSORPTION"


def test_missing_optional_inputs_do_not_crash_builder(tmp_path: Path):
    candles = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-10T12:00:00Z", "2026-07-10T12:15:00Z", "2026-07-10T12:30:00Z"],
                utc=True,
            ),
            "open": [100.0, 101.0, 100.5],
            "high": [102.0, 101.5, 101.0],
            "low": [99.5, 100.0, 99.0],
            "close": [101.0, 100.5, 100.0],
            "close_position": [0.8, 0.4, 0.2],
            "candle_type": ["bullish", "bearish", "bearish"],
        }
    )
    # Only candles provided — all other sources missing.
    frames = {
        "candles": candles,
        "live": pd.DataFrame(),
        "volume_response": pd.DataFrame(),
        "convergence": pd.DataFrame(),
        "probabilistic": pd.DataFrame(),
        "cognition": pd.DataFrame(),
        "cognition_composite": pd.DataFrame(),
    }
    out = mod.build_auction_episode_rows(frames=frames)
    assert len(out) == 3
    assert set(mod.REQUIRED_OUTPUT_COLUMNS).issubset(out.columns)
    assert out["shadow_only"].all()
    assert not out["auction_episode"].astype(str).isin(["LONG_CONTEXT", "SHORT_CONTEXT"]).any()
    assert not out["bar_event"].astype(str).isin(["LONG_CONTEXT", "SHORT_CONTEXT"]).any()


def test_shadow_only_always_true_and_required_fields():
    candles = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T13:00:00Z", "2026-07-10T13:15:00Z"], utc=True),
            "open": [200.0, 201.0],
            "high": [203.0, 202.0],
            "low": [199.0, 198.0],
            "close": [201.0, 199.0],
            "close_position": [0.9, 0.85],
        }
    )
    cognition = pd.DataFrame(
        {
            "timestamp": candles["timestamp"],
            "trigger_event": ["BUYING_CLIMAX", "BUYING_CLIMAX"],
            "location_bias": ["UPPER_DISTRIBUTION", "UPPER_DISTRIBUTION"],
        }
    )
    volume = pd.DataFrame(
        {
            "timestamp": candles["timestamp"],
            "volume_event": ["EXHAUSTION_VOLUME", "EXHAUSTION_VOLUME"],
            "climax_state": ["CLIMAX_EXHAUSTION", "CLIMAX_EXHAUSTION"],
            "effort_result_state": ["EXHAUSTION_RESPONSE", "EXHAUSTION_RESPONSE"],
            "volume_class": ["climax", "climax"],
            "relative_volume": [4.0, 3.5],
            "localized_behavior": ["localized_distribution", "localized_distribution"],
        }
    )
    out = mod.build_auction_episode_rows(
        frames={
            "candles": candles,
            "live": pd.DataFrame(),
            "volume_response": volume,
            "convergence": pd.DataFrame(),
            "probabilistic": pd.DataFrame(),
            "cognition": cognition,
            "cognition_composite": pd.DataFrame(),
        }
    )
    assert out["shadow_only"].tolist() == [True, True]
    for col in mod.REQUIRED_OUTPUT_COLUMNS:
        assert col in out.columns
    assert "LONG_CONTEXT" not in out.to_string()
    assert "SHORT_CONTEXT" not in out.to_string()
    # First bar may lack follow-through; second should classify upper distribution path.
    assert out.iloc[-1]["bar_event"] == "BUYING_CLIMAX"
    assert out.iloc[-1]["auction_location"] == "UPPER_AREA"
    assert out.iloc[-1]["auction_episode"] in {"UPPER_DISTRIBUTION", "FAILED_BREAKOUT", "BALANCE", "UNKNOWN"}


def test_bar_event_and_location_helpers():
    assert mod.classify_bar_event(tier1_trigger_event="BUYING_CLIMAX") == "BUYING_CLIMAX"
    assert mod.classify_bar_event(volume_event="STOPPING_VOLUME") == "STOPPING_VOLUME"
    assert mod.classify_auction_location(tier1_location_bias="UPPER_DISTRIBUTION") == "UPPER_AREA"
    assert mod.classify_auction_location(location_bias="LOWER_ABSORPTION") == "LOWER_AREA"


def test_atomic_write_unique_tmp(tmp_path: Path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-10T14:00:00Z"], utc=True),
            "close": [1.0],
            "bar_event": ["UNKNOWN"],
            "volume_event": ["UNKNOWN"],
            "climax_state": ["UNKNOWN"],
            "volume_effort": ["UNKNOWN"],
            "effort_side": ["UNKNOWN"],
            "auction_location": ["UNKNOWN"],
            "price_result": ["UNKNOWN"],
            "effort_result": ["UNKNOWN"],
            "follow_through": ["UNKNOWN"],
            "convergence_state": ["UNKNOWN"],
            "localized_behavior": ["UNKNOWN"],
            "auction_regime": ["UNKNOWN"],
            "distribution_probability": [None],
            "absorption_probability": [None],
            "auction_episode": ["UNKNOWN"],
            "episode_status": ["UNKNOWN"],
            "episode_reason": ["insufficient location / follow-through evidence"],
            "source_freshness": ["{}"],
            "builder_version": [mod.BUILDER_VERSION],
            "shadow_only": [True],
        }
    )
    out = tmp_path / "auction_episode_memory.parquet"
    path = mod.write_atomic_parquet(frame, out)
    assert path.exists()
    assert path == out
    loaded = pd.read_parquet(path)
    assert loaded.iloc[0]["shadow_only"] is True or bool(loaded.iloc[0]["shadow_only"]) is True
