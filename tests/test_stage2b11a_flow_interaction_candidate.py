"""Stage 2B1.1A — canonical flow / interaction path + candidate acceptance."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from storage.path_registry import (  # noqa: E402
    PARQUET_REGISTRY,
    resolve_read,
    resolve_write,
)

MAY_CUT = pd.Timestamp("2026-05-13 12:45:00", tz="UTC")
CANDIDATE_DIR = (
    REPO
    / "data/candidate/architecture_recovery/stage2b11a_flow_interaction_candidate"
)
FLOW_ENGINE = REPO / "live_volume_flow_engine_v1.py"
INTERACTION_ENGINE = REPO / "flow_liquidity_interaction_engine_v3.py"


def _load_candidate(name: str) -> pd.DataFrame:
    path = CANDIDATE_DIR / "cognition" / name
    if name.startswith("htf"):
        path = CANDIDATE_DIR / "diagnostics" / name
    if not path.exists():
        pytest.skip(f"candidate artifact missing: {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _source_uses_resolve_write(path: Path, filename: str) -> bool:
    tree = ast.parse(path.read_text())
    text = path.read_text()
    return (
        "resolve_write" in text
        and f'resolve_write("{filename}")' in text
        and f'to_parquet(\n    "{filename}"' not in text
        and f'to_parquet(\n\n    "{filename}"' not in text
    )


def test_path_registry_contains_exact_flow_interaction_keys():
    assert PARQUET_REGISTRY["live_volume_flow_memory.parquet"] == "cognition"
    assert PARQUET_REGISTRY["flow_liquidity_interaction_memory.parquet"] == "cognition"


def test_flow_writer_path_equals_reader_path():
    w = Path(resolve_write("live_volume_flow_memory.parquet"))
    r = Path(resolve_read("live_volume_flow_memory.parquet"))
    assert w == REPO / "data/cognition/live_volume_flow_memory.parquet"
    assert r == w or r.exists()


def test_interaction_writer_path_equals_reader_path():
    w = Path(resolve_write("flow_liquidity_interaction_memory.parquet"))
    r = Path(resolve_read("flow_liquidity_interaction_memory.parquet"))
    assert w == REPO / "data/cognition/flow_liquidity_interaction_memory.parquet"
    assert r == w or r.exists()


def test_flow_engine_uses_resolve_write_not_cwd_filename():
    src = FLOW_ENGINE.read_text()
    assert 'resolve_write("live_volume_flow_memory.parquet")' in src
    assert 'resolve_read("live_market_feed.parquet")' in src
    # bare CWD output rejected
    assert 'to_parquet(\n    "live_volume_flow_memory.parquet"' not in src


def test_interaction_engine_v3_uses_resolve_write_not_cwd_filename():
    src = INTERACTION_ENGINE.read_text()
    assert 'resolve_write("flow_liquidity_interaction_memory.parquet")' in src
    assert 'resolve_read("live_volume_flow_memory.parquet")' in src
    assert 'to_parquet(\n\n    "flow_liquidity_interaction_memory.parquet"' not in src


def test_negative_hardcoded_cwd_output_absent_in_canonical_producers():
    for path, fname in (
        (FLOW_ENGINE, "live_volume_flow_memory.parquet"),
        (INTERACTION_ENGINE, "flow_liquidity_interaction_memory.parquet"),
    ):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "to_parquet":
                if node.args and isinstance(node.args[0], ast.Constant):
                    assert node.args[0].value != fname


def test_flow_historical_source_contract_labels():
    """Feature-level deterministic parity of current flow formulas vs May artifact."""
    hist = pd.read_parquet(REPO / "data/cognition/live_volume_flow_memory.parquet")
    hist = hist.dropna(subset=["volume_ratio", "spread_ratio"])

    def state(vr, sr, change, spread):
        if vr > 1.8 and sr > 1.5:
            return "aggressive_expansion"
        if vr < 0.8 and sr < 0.8:
            return "compression"
        if vr < 1 and sr < 1 and change < (spread * 0.3):
            return "passive_pullback"
        if vr > 1.5 and sr < 0.8:
            return "exhaustion"
        if sr > 1.5 and vr < 1:
            return "failed_expansion"
        return "neutral"

    pred = [
        state(r.volume_ratio, r.spread_ratio, abs(r.price_change), r.spread)
        for r in hist.itertuples()
    ]
    assert float((pd.Series(pred).values == hist["flow_state"].astype(str).values).mean()) == 1.0


def test_interaction_v3_historical_label_parity():
    hist = pd.read_parquet(
        REPO / "data/cognition/flow_liquidity_interaction_memory.parquet"
    ).drop_duplicates("timestamp", keep="last")
    clusters = pd.read_parquet(REPO / "liquidity_clusters_memory.parquet")

    def classify(level, flow_state):
        interaction_type = "neutral"
        for _, cluster in clusters.iterrows():
            lo, hi = float(cluster["zone_low"]), float(cluster["zone_high"])
            if lo <= level <= hi:
                dom = str(cluster["dominant_behavior"])
                if flow_state == "compression":
                    interaction_type = "compression_inside_liquidity"
                elif (
                    flow_state == "aggressive_expansion"
                    and dom == "localized_absorption"
                ):
                    interaction_type = "expansion_into_absorption"
                elif (
                    flow_state == "aggressive_expansion"
                    and dom == "localized_distribution"
                ):
                    interaction_type = "expansion_into_distribution"
                elif flow_state == "failed_expansion":
                    interaction_type = "failed_breakout_behavior"
                elif flow_state == "exhaustion":
                    interaction_type = "exhaustion_at_liquidity"
                break
        return interaction_type

    ok = sum(
        1
        for _, r in hist.iterrows()
        if classify(float(r["market_level"]), str(r["flow_state"]))
        == str(r["interaction_type"])
    )
    assert ok == len(hist)


def test_candidate_flow_tip_advances_unique_monotonic():
    flow = _load_candidate("live_volume_flow_memory.parquet")
    assert flow["timestamp"].max() > MAY_CUT
    assert int(flow["timestamp"].duplicated().sum()) == 0
    assert int((flow["timestamp"] <= MAY_CUT).sum()) == 0
    assert flow["timestamp"].is_monotonic_increasing or flow["timestamp"].equals(
        flow["timestamp"].sort_values().reset_index(drop=True)
    )


def test_candidate_interaction_tip_advances_unique():
    inter = _load_candidate("flow_liquidity_interaction_memory.parquet")
    assert inter["timestamp"].max() > MAY_CUT
    assert int(inter["timestamp"].duplicated().sum()) == 0
    assert int((inter["timestamp"] <= MAY_CUT).sum()) == 0


def test_candidate_intersection_nonempty_beyond_may():
    flow = _load_candidate("live_volume_flow_memory.parquet")
    inter = _load_candidate("flow_liquidity_interaction_memory.parquet")
    htf = _load_candidate("htf_structure_memory.parquet")
    common = sorted(
        set(flow["timestamp"]) & set(inter["timestamp"]) & set(htf["timestamp"])
    )
    assert len(common) > 0
    assert common[-1] > MAY_CUT


def test_candidate_htf_ltf_context_tip_advances():
    ctx = _load_candidate("htf_ltf_context_memory.parquet")
    assert len(ctx) > 0
    assert ctx["timestamp"].max() > MAY_CUT
    assert int(ctx["timestamp"].duplicated().sum()) == 0


def test_evidence_status_ready():
    evidence_path = CANDIDATE_DIR / "evidence.json"
    if not evidence_path.exists():
        pytest.skip("evidence.json missing")
    evidence = json.loads(evidence_path.read_text())
    assert evidence["acceptance"]["status"] == (
        "STAGE2B11A_FLOW_INTERACTION_CANDIDATE_READY"
    )
    assert evidence["compliance"]["live_cognition_mtime_changes"] == 0


def test_negative_may_fallback_not_in_candidate_tips():
    flow = _load_candidate("live_volume_flow_memory.parquet")
    inter = _load_candidate("flow_liquidity_interaction_memory.parquet")
    assert str(flow["timestamp"].max())[:10] != "2026-05-13"
    assert str(inter["timestamp"].max())[:10] != "2026-05-13"


def test_negative_fuzzy_join_helpers_absent_from_canonical_producers():
    for path in (FLOW_ENGINE, INTERACTION_ENGINE):
        src = path.read_text()
        assert "merge_asof" not in src
        assert "ffill" not in src
        assert "bfill" not in src
