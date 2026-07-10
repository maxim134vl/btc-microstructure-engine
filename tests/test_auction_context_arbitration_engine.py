"""Tests for shadow-only auction_context_arbitration_engine_v1."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    memory_path = tmp_path / "auction_context_arbitration_memory.parquet"

    import storage.path_registry as path_registry

    def _resolve_write(name: str) -> str:
        base = os.path.basename(str(name))
        if base == "auction_context_arbitration_memory.parquet":
            return str(memory_path)
        return str(tmp_path / base)

    def _resolve_read(name: str) -> str:
        base = os.path.basename(str(name))
        candidate = tmp_path / base
        return str(candidate)

    monkeypatch.setattr(path_registry, "resolve_write", _resolve_write)
    monkeypatch.setattr(path_registry, "resolve_read", _resolve_read)
    monkeypatch.setattr(path_registry, "is_registered", lambda name: True)

    import parquet_utils

    importlib.reload(parquet_utils)

    import auction_context_arbitration_engine_v1 as engine

    importlib.reload(engine)
    monkeypatch.setattr(engine, "MEMORY_FILE", "auction_context_arbitration_memory.parquet")
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    monkeypatch.setattr(engine, "_FALLBACK_PATHS", {})

    return tmp_path, memory_path, engine


def _write_parquet(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def _base_inputs(tmp_path: Path, *, held_stopping: bool = False, shortish: bool = False) -> None:
    ts = pd.Timestamp("2026-07-08 12:00:00", tz="UTC")
    closes = [61_800.0, 61_850.0, 61_900.0, 61_950.0, 62_000.0]
    candle_rows = []
    for i, close in enumerate(closes):
        candle_rows.append(
            {
                "timestamp": ts - pd.Timedelta(minutes=15 * (len(closes) - 1 - i)),
                "open": close - 10,
                "high": close + 20,
                "low": close - 30,
                "close": close,
                "volume": 100.0 + i,
            }
        )
    _write_parquet(tmp_path / "candle_structure_memory.parquet", candle_rows)

    if held_stopping:
        volume_event = "STOPPING_VOLUME"
        effort = "ABSORPTION_RESPONSE"
        location = "LOWER_ABSORPTION"
        trigger = "STOPPING_VOLUME"
        market_state = "REVERSAL"
        market_bias = "BULLISH"
        trading_state = "REVERSAL_WATCH"
        convergence = "LOCAL_ABSORPTION"
    elif shortish:
        volume_event = "CONTINUATION_VOLUME"
        effort = "EFFICIENT_CONTINUATION"
        location = "UPPER_DISTRIBUTION"
        trigger = "BUYING_CLIMAX"
        market_state = "DISTRIBUTION"
        market_bias = "BEARISH"
        trading_state = "SHORT_CONTEXT"
        convergence = "PERSISTENT_DISTRIBUTION"
    else:
        volume_event = "NEUTRAL_VOLUME"
        effort = "BALANCED_RESPONSE"
        location = ""
        trigger = ""
        market_state = "NEUTRAL"
        market_bias = "NEUTRAL"
        trading_state = "OBSERVE"
        convergence = ""

    _write_parquet(
        tmp_path / "volume_response_state.parquet",
        [
            {
                "timestamp": ts,
                "volume_event": volume_event,
                "climax_state": "NO_CLIMAX",
                "effort_result_state": effort,
                "continuation_quality": "WEAK_CONTINUATION",
                "localized_behavior": location or "NONE",
            }
        ],
    )
    _write_parquet(
        tmp_path / "auction_convergence_memory.parquet",
        [
            {
                "timestamp": ts,
                "convergence_state": convergence,
                "distribution_events": 0,
                "localized_behavior": location or "NONE",
            }
        ],
    )
    _write_parquet(
        tmp_path / "runtime_cognition_composite.parquet",
        [
            {
                "evaluation_timestamp": ts,
                "tier1_trigger_event": trigger,
                "tier1_location_bias": location,
                "anchor_age_bars": 2.0 if held_stopping else 0.0,
                "tier2_anchor_timestamp": ts - pd.Timedelta(minutes=30) if held_stopping else None,
                "effective_state": "LOCAL_EXHAUSTION" if held_stopping else "",
            }
        ],
    )
    _write_parquet(
        tmp_path / "runtime_cognition_memory.parquet",
        [
            {
                "timestamp": ts,
                "trigger_event": trigger,
                "location_bias": location,
                "synthesis_state": "LOCAL_EXHAUSTION" if held_stopping else "",
            }
        ],
    )
    _write_parquet(
        tmp_path / "probabilistic_auction_memory.parquet",
        [
            {
                "timestamp": ts,
                "auction_regime": market_state,
                "absorption_probability": 0.7 if held_stopping else 0.3,
                "distribution_probability": 0.7 if shortish else 0.3,
                "absorption_behavior_share": 0.6 if held_stopping else 0.2,
                "supply_behavior_share": 0.6 if shortish else 0.2,
            }
        ],
    )
    _write_parquet(
        tmp_path / "trading_state_memory.parquet",
        [
            {
                "timestamp": ts,
                "trading_state": trading_state,
                "market_state": market_state,
            }
        ],
    )
    _write_parquet(
        tmp_path / "market_state_memory.parquet",
        [
            {
                "timestamp": ts,
                "market_state": market_state,
                "market_bias": market_bias,
            }
        ],
    )


def test_engine_writes_memory_row(engine_env) -> None:
    tmp_path, memory_path, engine = engine_env
    _base_inputs(tmp_path)
    assert engine.run() == 0
    assert memory_path.exists()
    frame = pd.read_parquet(memory_path)
    assert len(frame) == 1
    assert bool(frame.iloc[0]["shadow_only"]) is True
    assert frame.iloc[0]["mode"] == "calibrated_v3"
    assert frame.iloc[0]["calibrated_context"] in {"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"}


def test_missing_inputs_do_not_crash(engine_env) -> None:
    _tmp_path, memory_path, engine = engine_env
    # No input parquets written.
    assert engine.run() == 0
    assert memory_path.exists()
    frame = pd.read_parquet(memory_path)
    assert len(frame) >= 1
    assert frame.iloc[-1]["calibrated_context"] == "OBSERVE"


def test_calibrated_v3_never_writes_final_short_context(engine_env) -> None:
    tmp_path, memory_path, engine = engine_env
    _base_inputs(tmp_path, shortish=True)
    assert engine.run() == 0
    frame = pd.read_parquet(memory_path)
    assert (frame["calibrated_context"] == "SHORT_CONTEXT").sum() == 0
    # If raw was short-ish, diagnostics may preserve short_candidate / suppress_reason.
    row = frame.iloc[-1]
    assert row["calibrated_context"] == "OBSERVE" or row["calibrated_context"] == "LONG_CONTEXT"


def test_held_stopping_volume_reversal_can_write_long_context(engine_env) -> None:
    tmp_path, memory_path, engine = engine_env
    _base_inputs(tmp_path, held_stopping=True)
    assert engine.run() == 0
    frame = pd.read_parquet(memory_path)
    row = frame.iloc[-1]
    assert row["calibrated_context"] == "LONG_CONTEXT"
    assert row["long_subtype"] == "HELD_STOPPING_VOLUME_REVERSAL"
    assert row["mode"] == "calibrated_v3"
    assert bool(row["shadow_only"]) is True


def test_corrupted_input_parquet_does_not_crash(engine_env) -> None:
    tmp_path, memory_path, engine = engine_env
    # Corrupt candle input; other files absent.
    (tmp_path / "candle_structure_memory.parquet").write_bytes(b"NOTPARQUET")
    assert engine.run() == 0
    assert memory_path.exists()
    frame = pd.read_parquet(memory_path)
    assert frame.iloc[-1]["calibrated_context"] == "OBSERVE"
