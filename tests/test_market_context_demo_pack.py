"""Tests for market context demo pack builder."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_market_context_demo_pack.py"

spec = importlib.util.spec_from_file_location("build_market_context_demo_pack", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_market_context_demo_pack"] = mod
spec.loader.exec_module(mod)


def _pq(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _minimal_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, action_allowed: bool = False) -> dict:
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "sandbox" / "market_state_context_visualizer" / "public" / "data"

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "COGNITION", cognition)
    monkeypatch.setattr(mod, "VISUAL_DATA", visual)
    monkeypatch.setattr(mod, "AUCTION_PATH", cognition / "auction_episode_memory.parquet")
    monkeypatch.setattr(mod, "COGNITIVE_PATH", cognition / "cognitive_market_state_memory.parquet")
    monkeypatch.setattr(mod, "FINAL_PATH", cognition / "final_market_context_memory.parquet")
    monkeypatch.setattr(mod, "LIFECYCLE_MEMORY_PATH", cognition / "market_context_lifecycle_memory.parquet")
    monkeypatch.setattr(mod, "LIFECYCLE_EPISODES_PATH", cognition / "market_context_lifecycle_episodes.parquet")
    monkeypatch.setattr(mod, "SHADOW_STATUS_PATH", cognition / "market_context_shadow_chain_status.json")
    monkeypatch.setattr(mod, "OUTPUT_JSON", cognition / "market_context_demo_pack.json")
    monkeypatch.setattr(mod, "OUTPUT_MD", tmp_path / "docs" / "MARKET_CONTEXT_DEMO_PACK_OUTPUT.md")
    monkeypatch.setattr(
        mod,
        "VISUAL_JSONS",
        [
            visual / "lifecycle_candles.json",
            visual / "lifecycle_context_episodes.json",
            visual / "lifecycle_latest.json",
        ],
    )

    ts0 = pd.Timestamp("2026-07-10 01:00:00", tz="UTC")
    ts1 = pd.Timestamp("2026-07-10 02:00:00", tz="UTC")
    ts2 = pd.Timestamp("2026-07-10 12:00:00", tz="UTC")

    _pq(
        cognition / "auction_episode_memory.parquet",
        [
            {
                "timestamp": ts0,
                "auction_episode": "UPPER_DISTRIBUTION",
                "episode_status": "ACTIVE",
                "episode_reason": "seller pressure",
                "source_freshness": "fresh",
                "shadow_only": True,
            },
            {
                "timestamp": ts2,
                "auction_episode": "BALANCE",
                "episode_status": "DEVELOPING",
                "episode_reason": "balance",
                "source_freshness": "fresh",
                "shadow_only": True,
            },
        ],
    )
    _pq(
        cognition / "cognitive_market_state_memory.parquet",
        [
            {
                "timestamp": ts0,
                "cognitive_market_state": "UPPER_DISTRIBUTION",
                "state_direction": "SHORT",
                "state_status": "ACTIVE",
                "source_episode_freshness": "fresh",
                "shadow_only": True,
            },
            {
                "timestamp": ts2,
                "cognitive_market_state": "BALANCE",
                "state_direction": "NEUTRAL",
                "state_status": "DEVELOPING",
                "source_episode_freshness": "fresh",
                "shadow_only": True,
            },
        ],
    )
    _pq(
        cognition / "final_market_context_memory.parquet",
        [
            {
                "timestamp": ts0,
                "market_context": "SHORT_CONTEXT",
                "context_status": "ACTIVE",
                "action_allowed": action_allowed,
                "action_reason": "shadow market context only; execution disabled",
                "source_state_freshness": "fresh",
                "shadow_only": True,
            },
            {
                "timestamp": ts1,
                "market_context": "OBSERVE",
                "context_status": "OBSERVE",
                "action_allowed": False,
                "action_reason": "shadow market context only; execution disabled",
                "source_state_freshness": "fresh",
                "shadow_only": True,
            },
            {
                "timestamp": ts2,
                "market_context": "OBSERVE",
                "context_status": "OBSERVE",
                "action_allowed": False,
                "action_reason": "shadow market context only; execution disabled",
                "source_state_freshness": "fresh",
                "shadow_only": True,
            },
        ],
    )
    _pq(
        cognition / "market_context_lifecycle_memory.parquet",
        [
            {
                "timestamp": ts0,
                "close": 100.0,
                "raw_market_context": "SHORT_CONTEXT",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "active_context_age_bars": 0,
                "challenge_context": None,
                "transition_reason": "confirmed directional context became active",
                "action_allowed": False,
                "action_reason": "shadow market context only; execution disabled",
                "shadow_only": True,
            },
            {
                "timestamp": ts2,
                "close": 99.0,
                "raw_market_context": "OBSERVE",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "CHALLENGED",
                "active_context_age_bars": 10,
                "challenge_context": "OBSERVE",
                "transition_reason": "observe challenged active context",
                "action_allowed": False,
                "action_reason": "shadow market context only; execution disabled",
                "shadow_only": True,
            },
        ],
    )
    _pq(
        cognition / "market_context_lifecycle_episodes.parquet",
        [
            {
                "episode_id": 1,
                "active_market_context": "SHORT_CONTEXT",
                "start_time": ts0,
                "end_time": ts2,
                "bars_count": 10,
                "duration_minutes": 660.0,
                "challenged_bars_count": 6,
                "dominant_lifecycle_state": "CHALLENGED",
                "start_reason": "confirmed directional context became active",
                "end_reason": "latest open lifecycle episode",
                "action_allowed_any": False,
                "shadow_only": True,
            }
        ],
    )
    _json(
        cognition / "market_context_shadow_chain_status.json",
        {
            "status": "PASS",
            "raw_episodes_count": 20,
            "lifecycle_episodes_count": 1,
            "latest_context": {
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "CHALLENGED",
                "active_context_age_bars": 10,
                "action_allowed": False,
                "challenge_ratio": 0.6,
            },
            "shadow_only": True,
        },
    )
    _json(visual / "lifecycle_candles.json", {"rows": [{"timestamp": "2026-07-10T12:00:00Z"}]})
    _json(visual / "lifecycle_context_episodes.json", [{"episode_id": 1, "context": "SHORT_CONTEXT"}])
    _json(
        visual / "lifecycle_latest.json",
        {
            "active_market_context": "SHORT_CONTEXT",
            "lifecycle_state": "CHALLENGED",
            "active_context_age_bars": 10,
            "action_allowed": False,
        },
    )
    return mod.load_inputs()


def test_demo_pack_from_minimal_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    assert pack["status"] == "PASS"
    assert pack["shadow_only"] is True
    assert len(pack["latest_episodes"]) == 1


def test_latest_context_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    for field in mod.REQUIRED_LATEST_CONTEXT_FIELDS:
        assert field in pack["latest_context"]


def test_latest_episodes_contain_explanation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    ep = pack["latest_episodes"][0]
    assert "explanation" in ep
    assert "SHORT_CONTEXT" in ep["explanation"]
    assert "challenged" in ep["explanation"].lower()


def test_source_trace_uses_start_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    trace = pack["source_trace"][0]
    assert trace["start"]["auction_episode"] == "UPPER_DISTRIBUTION"
    assert trace["start"]["cognitive_market_state"] == "UPPER_DISTRIBUTION"
    assert trace["start"]["market_context"] == "SHORT_CONTEXT"
    assert trace["end"]["auction_episode"] == "BALANCE"
    assert trace["end"]["lifecycle_state"] == "CHALLENGED"
    assert trace["summary"]["auction_episode"] == "UPPER_DISTRIBUTION"


def test_acceptance_checks_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    assert pack["status"] == "PASS"
    assert all(pack["acceptance_checks"].values())


def test_no_failed_short_reprice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    assert pack["acceptance_checks"]["no_failed_short_reprice"] is True
    hits = mod.scan_forbidden({"note": "clean"})
    assert "FAILED_SHORT_REPRICE" not in hits
    hits_bad = mod.scan_forbidden({"reason": "FAILED_SHORT_REPRICE"})
    assert "FAILED_SHORT_REPRICE" in hits_bad


def test_action_allowed_false_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch, action_allowed=True)
    pack = mod.build_demo_pack(inputs)
    assert pack["acceptance_checks"]["action_allowed_false"] is False
    assert pack["status"] == "FAIL"


def test_markdown_report_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    pack = mod.build_demo_pack(inputs)
    json_path, md_path = mod.write_outputs(pack)
    assert json_path.exists()
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "# Market Context Demo Pack" in text
    assert "## 6. Acceptance checks" in text
    assert "SHORT_CONTEXT" in text


def test_demo_pack_explanation_includes_invalidation_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _minimal_inputs(tmp_path, monkeypatch)
    # Rewrite latest lifecycle row as INVALIDATED after SHORT.
    life = inputs["life_mem"].copy()
    life.loc[life.index[-1], "active_market_context"] = "OBSERVE"
    life.loc[life.index[-1], "lifecycle_state"] = "INVALIDATED"
    life.loc[life.index[-1], "active_context_age_bars"] = 0
    life.loc[life.index[-1], "active_context_started_at"] = pd.NaT
    life.loc[life.index[-1], "previous_active_market_context"] = "SHORT_CONTEXT"
    life.loc[life.index[-1], "invalidation_type"] = "AUCTION_NEUTRALIZATION"
    life.loc[life.index[-1], "invalidation_reason"] = (
        "SHORT_CONTEXT invalidated because auction and cognitive state moved to "
        "BALANCE / NEUTRAL / OBSERVE; no confirmed opposite context required."
    )
    life.loc[life.index[-1], "invalidated_by_auction_episode"] = "BALANCE"
    life.loc[life.index[-1], "invalidated_by_cognitive_state"] = "BALANCE"
    life.loc[life.index[-1], "invalidated_by_market_context"] = "OBSERVE"
    inputs["life_mem"] = life
    # Matching open OBSERVE episode after invalidation.
    ep = inputs["life_ep"].copy()
    ep.loc[ep.index[-1], "active_market_context"] = "OBSERVE"
    ep.loc[ep.index[-1], "start_lifecycle_state"] = "INVALIDATED"
    ep.loc[ep.index[-1], "end_lifecycle_state"] = "INVALIDATED"
    ep.loc[ep.index[-1], "dominant_lifecycle_state"] = "INVALIDATED"
    ep.loc[ep.index[-1], "end_reason"] = "latest open lifecycle episode"
    inputs["life_ep"] = ep

    pack = mod.build_demo_pack(inputs)
    assert pack["latest_context"]["lifecycle_state"] == "INVALIDATED"
    assert pack["latest_context"]["active_context_age_bars"] == 0
    assert "invalidation_reason" in pack["latest_context"]
    assert "No active directional context" in pack["latest_context_explanation"]
    assert "AUCTION_NEUTRALIZATION" in pack["latest_context_explanation"]
    assert "age" not in pack["latest_context_explanation"].lower()
    assert "action_allowed=False" in pack["latest_context_explanation"]
