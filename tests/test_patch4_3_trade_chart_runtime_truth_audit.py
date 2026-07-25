"""Patch 4.3 — Trade chart runtime truth audit / parity contract tests."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import patch4_3_trade_chart_runtime_truth_audit as audit  # noqa: E402

CANDIDATE = ROOT / "data/research/patch4_3_candidate_trade_chart.json"
CHART_INV = ROOT / "data/research/patch4_3_chart_inventory.json"
LEDGER_INV = ROOT / "data/research/patch4_3_ledger_inventory.json"
PARITY = ROOT / "data/research/patch4_3_trade_chart_parity.csv"
GAPS = ROOT / "data/research/patch4_3_runtime_status_gaps.json"
FRONTEND = ROOT / "data/research/patch4_3_frontend_audit.json"


@pytest.fixture(scope="module", autouse=True)
def _ensure_artifacts():
    if not CANDIDATE.exists():
        assert audit.main() == 0
    assert CANDIDATE.exists()


@pytest.fixture(scope="module")
def candidate() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chart_inv() -> dict:
    return json.loads(CHART_INV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ledger_inv() -> dict:
    return json.loads(LEDGER_INV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parity_rows() -> list[dict]:
    with PARITY.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_01_production_ledger_ctrl_closed_count(ledger_inv):
    assert ledger_inv["controller_closed_positions"] == 4
    assert ledger_inv["open_positions"] == 0
    assert ledger_inv["duplicate_trade_ids"] == 0


def test_02_chart_uses_policy_context_not_ledger(chart_inv):
    assert chart_inv["policy_context_id_count"] == chart_inv["shape_count"]
    assert chart_inv["paper_trade_id_count"] == 0
    assert chart_inv["controller_ledger_used_for_render"] is False
    assert "policy_context_canonical_bar_policy_trades" in str(chart_inv["active_render_source_closed"])


def test_03_zero_id_intersection(chart_inv, candidate):
    chart_ids = set(map(str, chart_inv["shape_ids"]))
    cand_ids = {str(t["trade_id"]) for t in candidate["closed_trades"]}
    assert chart_ids.isdisjoint(cand_ids)


def test_04_candidate_closed_trades_from_ctrl_ledger(candidate, ledger_inv):
    assert len(candidate["closed_trades"]) == ledger_inv["controller_closed_positions"] == 4
    for trade in candidate["closed_trades"]:
        assert trade["classification"] == "CONTROLLER"
        assert str(trade["position_id"]).startswith("PAPER_POSITION_CTRL_")
        assert trade["source_of_truth"].startswith("data/research/paper_simulator/")
        assert trade["execution_enabled"] is False


def test_05_pnl_mismatch_explained(candidate, chart_inv, ledger_inv):
    assert candidate["pnl"]["chart_pnl_trusted"] is False
    assert abs(float(chart_inv["pnl_net_after_costs"]) - float(ledger_inv["realized_pnl_ctrl_closed_sum"])) > 1.0


def test_06_signal_and_order_layers_in_candidate(candidate):
    assert len(candidate["signals"]) >= 1
    assert len(candidate["orders"]) >= 1
    assert len(candidate["fills"]) >= 1
    assert all(s["should_render_marker"] for s in candidate["signals"])
    assert all(o["should_render_marker"] for o in candidate["orders"])


def test_07_frontend_missing_signal_order_markers():
    fe = json.loads(FRONTEND.read_text(encoding="utf-8"))
    assert fe["marker_capabilities"]["signal_markers"] is False
    assert fe["marker_capabilities"]["order_markers"] is False
    assert fe["loads"]["paper_trade_overlays"] is True
    assert fe["visual_preservation_required"] is True


def test_08_merge_helper_dead_code(chart_inv):
    assert chart_inv["merge_helper_defined"] is True
    assert chart_inv["merge_helper_dead_code"] is True
    assert chart_inv["merge_helper_call_count"] == 0


def test_09_parity_unexplained_zero(parity_rows):
    unexplained = [r for r in parity_rows if r["classification"] == "UNEXPLAINED"]
    assert unexplained == []
    assert any(r["classification"] == "SOURCE_MISMATCH" for r in parity_rows)
    assert any(r["classification"] == "ECONOMICS_MISMATCH" for r in parity_rows)


def test_10_gaps_file_present():
    gaps = json.loads(GAPS.read_text(encoding="utf-8"))
    assert gaps["unexplained_divergences"] == 0
    ids = {g["gap_id"] for g in gaps["gaps"]}
    assert "PRIMARY_SOURCE_IS_POLICY_CONTEXT" in ids
    assert "MERGE_HELPER_DEAD_CODE" in ids


def test_11_audit_read_only_contract():
    src = (ROOT / "scripts/ops/patch4_3_trade_chart_runtime_truth_audit.py").read_text(encoding="utf-8")
    assert "Read-only" in src
    assert "to_parquet(" not in src
    assert "activation_forbidden_in_this_phase" in src


def test_12_no_css_mutation_by_audit():
    # Audit artifacts only; CSS path must still exist with baseline hash recorded.
    css = ROOT / "apps/context_visualizer/public/lifecycle.css"
    assert css.exists()
    baseline = next((ROOT / "data/research").glob("patch4_3_visual_baseline_*.json"))
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["css_theme_preserved"] is True
    assert payload["font_family_changes"] == 0


def test_13_hardcoded_latest_context_flagged(chart_inv):
    assert chart_inv["hardcoded_latest_context_id_in_export"] is True


def test_14_taxonomy_and_hierarchy(candidate):
    for key in (
        "MARKET_SERIES",
        "PAPER_SIGNAL",
        "PAPER_ORDER",
        "SIMULATED_FILL",
        "CLOSED_TRADE",
        "LEGACY_VISUAL_LAYER",
    ):
        assert key in candidate["entity_taxonomy"]
    assert candidate["canonical_source_hierarchy"][0] == "production_paper_ledger"
    assert "policy_context_canonical_bar_policy_trades.parquet_as_production_truth" in candidate[
        "forbidden_primary_sources"
    ]


def test_15_status_contract_ready():
    summaries = sorted((ROOT / "data/research").glob("patch4_3_summary_*.json"))
    assert summaries
    summary = json.loads(summaries[-1].read_text(encoding="utf-8"))
    assert summary["status"] == "PATCH4_TRADE_CHART_PARITY_CONTRACT_READY"
    assert summary["gates"]["activation_performed"] is False
    assert summary["gates"]["frontend_visual_changes"] == 0
