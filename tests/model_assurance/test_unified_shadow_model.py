"""SHADOW-MODEL1 — unified ACTIVE + EQCORR + STP2.1 contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from btc_ml.model_assurance.shadow import unified_snapshot as usm


EXPECTED_EPOCH = "PER_TF_EQUITY_1PCT_V1_20260729_181431"
EXPECTED_FP = "ca13177674222de7991dc26688ee2f91e018e5728a1660af6dc81c326acf7129"
STP_FP = "f632252bd77644ad48aa807f42c643c5add229ebc845b8c6a17f51b3bc6c51ab"
EQCORR_FP = "eqcorr_manifest_test_fp"
HIST_STP11 = usm.HISTORICAL_STP11_MANIFEST


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _seed_repo(tmp_path: Path, *, pending_stp: bool = False, hist_stp: bool = False) -> Path:
    repo = tmp_path / "repo"
    # Registry ACTIVE
    _write_json(
        repo / "data/model_assurance/registry/active/active_model.json",
        {
            "model_id": "BTC_INTRABAR_RULE_BASED",
            "model_version": "INTRABAR_RULES_V1",
            "model_role": "ACTIVE",
            "model_type": "RULE_BASED",
            "cognition_version": "LIVE1A_CANONICAL_INTRABAR_CONTEXT",
            "rule_contract_version": "INTRABAR_RULES_V1",
            "feature_schema_version": "FS1",
            "data_schema_version": "DS1",
            "source_commit": "abc123",
            "paper_epoch_id": "STALE_REGISTRY_EPOCH",
            "paper_only": True,
            "real_execution": False,
            "runtime_fingerprint": "rtfp",
        },
    )
    _write_json(
        repo / "data/trading/paper_epochs/active.json",
        {
            "paper_epoch_id": EXPECTED_EPOCH,
            "trading_contract_fingerprint": EXPECTED_FP,
            "activated_at": "2026-07-29T18:14:31Z",
            "paper_only": True,
            "real_execution": False,
        },
    )
    books = repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    trades = [
        {
            "trade_id": "trd_a",
            "position_id": "pos_a",
            "paper_epoch_id": EXPECTED_EPOCH,
            "exit_ts": "2026-07-30T01:00:00Z",
            "net_pnl_usd": -1.0,
        },
        {
            "trade_id": "trd_b",
            "position_id": "pos_b",
            "paper_epoch_id": EXPECTED_EPOCH,
            "exit_ts": "2026-07-30T02:00:00Z",
            "net_pnl_usd": 2.0,
        },
    ]
    _write_jsonl(books / "trades.jsonl", trades)
    _write_jsonl(books / "positions.jsonl", [])

    # EQCORR
    eq = repo / "data/trading/shadow_economic_correlation/epochs" / EXPECTED_EPOCH
    _write_json(
        eq / "health.json",
        {
            "status": "SHADOW_EQCORR1_1_ACTIVE_WITH_EXPLICIT_MISSING_FEATURES",
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "source_epoch_id": EXPECTED_EPOCH,
            "source_contract_fingerprint": EXPECTED_FP,
            "baseline_divergence_count": 0,
            "baseline_match_count": 2,
            "candidate_count": 2,
            "closed_outcome_count": 2,
            "open_virtual_positions": 0,
            "updated_at": "2026-07-30T16:00:00Z",
        },
    )
    _write_json(
        eq / "policy_manifest.json",
        {
            "shadow_policy_manifest_fingerprint": EQCORR_FP,
            "source_epoch_id": EXPECTED_EPOCH,
            "source_contract_fingerprint": EXPECTED_FP,
            "mode": "OBSERVE_ONLY",
            "enforcement_enabled": False,
            "policy_ids": ["BASELINE_ALL_ELIGIBLE", "H1_ONLY"],
        },
    )
    _write_jsonl(
        eq / "virtual_trades.jsonl",
        [
            {"policy_id": "BASELINE_ALL_ELIGIBLE", "trade_id": "trd_a", "candidate_id": f"{EXPECTED_EPOCH}|pos_a|f", "net_pnl_usd": -1.0, "exit_timestamp": "2026-07-30T01:00:00Z"},
            {"policy_id": "BASELINE_ALL_ELIGIBLE", "trade_id": "trd_b", "candidate_id": f"{EXPECTED_EPOCH}|pos_b|f", "net_pnl_usd": 2.0, "exit_timestamp": "2026-07-30T02:00:00Z"},
            {"policy_id": "H1_ONLY", "trade_id": "trd_a", "candidate_id": f"{EXPECTED_EPOCH}|pos_a|f", "net_pnl_usd": -0.5},
        ],
    )
    _write_jsonl(eq / "virtual_positions.jsonl", [])
    _write_jsonl(eq / "candidate_snapshots.jsonl", [{"candidate_id": "c1"}, {"candidate_id": "c2"}])
    _write_jsonl(eq / "policy_decisions.jsonl", [{"policy_id": "BASELINE_ALL_ELIGIBLE"}, {"policy_id": "H1_ONLY"}])
    _write_json(eq / "checkpoint.json", {})

    # STP
    stp_fp = HIST_STP11 if hist_stp else STP_FP
    stp = repo / "data/trading/shadow_structural_protection/epochs" / EXPECTED_EPOCH
    _write_json(
        stp / "health.json",
        {
            "status": "SHADOW_STP2_1_COVERAGE_INTEGRITY_PROVEN",
            "stp_generation": "SHADOW_STP2_1",
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "policy_manifest_fingerprint": stp_fp,
            "source_epoch_id": EXPECTED_EPOCH,
            "source_contract_fingerprint": EXPECTED_FP,
            "baseline_divergence_count": 0,
            "baseline_match_count": 2,
            "candidate_count": 2,
            "virtual_trades_closed": 4,
            "virtual_positions_open_valid": 0,
            "invalidated_manifest_fingerprints": [HIST_STP11],
            "updated_at": "2026-07-30T16:00:00Z",
        },
    )
    _write_json(
        stp / "policy_manifest.json",
        {
            "policy_manifest_fingerprint": stp_fp,
            "generation": "SHADOW_STP2_1",
            "shadow_model_version": "SHADOW_STP2_1_V1",
            "source_commit": "cadc86e",
            "source_epoch_id": EXPECTED_EPOCH,
            "source_trading_contract_fingerprint": EXPECTED_FP,
        },
    )
    stp_trades = [
        {
            "policy_id": "BASELINE_CANONICAL",
            "trade_id": "trd_a",
            "candidate_id": f"{EXPECTED_EPOCH}|pos_a|f",
            "policy_manifest_fingerprint": STP_FP,
            "net_pnl_usd": -1.0,
            "exit_timestamp": "2026-07-30T01:00:00Z",
        },
        {
            "policy_id": "STRUCTURAL_SL_CANONICAL_TP__X",
            "trade_id": "trd_a",
            "candidate_id": f"{EXPECTED_EPOCH}|pos_a|f",
            "policy_manifest_fingerprint": STP_FP,
            "net_pnl_usd": -0.2,
        },
        # historical contaminated row — must be excluded from current
        {
            "policy_id": "BASELINE_CANONICAL",
            "trade_id": "trd_hist",
            "candidate_id": "old|pos|f",
            "policy_manifest_fingerprint": HIST_STP11,
            "net_pnl_usd": 99.0,
        },
    ]
    if not pending_stp:
        stp_trades.append(
            {
                "policy_id": "BASELINE_CANONICAL",
                "trade_id": "trd_b",
                "candidate_id": f"{EXPECTED_EPOCH}|pos_b|f",
                "policy_manifest_fingerprint": STP_FP,
                "net_pnl_usd": 2.0,
                "exit_timestamp": "2026-07-30T02:00:00Z",
            }
        )
    _write_jsonl(stp / "virtual_trades.jsonl", stp_trades)
    _write_jsonl(stp / "virtual_positions.jsonl", [])
    _write_jsonl(
        stp / "candidate_snapshots.jsonl",
        [
            {"candidate_id": "c1", "policy_manifest_fingerprint": STP_FP},
            {"candidate_id": "c2", "policy_manifest_fingerprint": STP_FP},
        ],
    )
    _write_jsonl(
        stp / "policy_decisions.jsonl",
        [
            {"policy_id": "BASELINE_CANONICAL", "policy_manifest_fingerprint": STP_FP},
            {"policy_id": "STRUCTURAL_SL_CANONICAL_TP__X", "policy_manifest_fingerprint": STP_FP},
            {"policy_id": "BASELINE_CANONICAL", "policy_manifest_fingerprint": HIST_STP11},
        ],
    )
    _write_json(stp / "checkpoint.json", {"invalidated_manifest_fingerprints": [HIST_STP11]})

    # pid files (dead pids → DOWN → STALE unless we mock alive)
    for rel in (
        "run/intrabar_cognition.pid",
        "run/intrabar_paper_manager.pid",
        "run/shadow_economic_correlation.pid",
        "run/shadow_structural_protection.pid",
    ):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(os.getpid()) + "\n", encoding="utf-8")

    # MODEL-7 historical comparisons
    hist = repo / "data/model_assurance/shadow/comparisons/active_shadow_comparisons.jsonl"
    _write_jsonl(hist, [{"comparison_id": "h1"}, {"comparison_id": "h2"}])
    return repo


def test_schema_and_active_from_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="testcommit"
    )
    assert snap["snapshot_version"] == usm.SNAPSHOT_VERSION
    assert snap["active_model"]["model_id"] == "BTC_INTRABAR_RULE_BASED"
    assert snap["active_model"]["model_role"] == "ACTIVE"
    assert snap["active_model"]["paper_epoch_id"] == EXPECTED_EPOCH
    assert snap["active_model"]["trading_contract_fingerprint"] == EXPECTED_FP
    assert "snapshot_id" in snap and "created_at" in snap
    assert snap["promotion_eligible"] is False
    assert snap["promotion_ineligibility_reason"] == usm.PROMOTION_INELIGIBILITY_REASON


def test_eqcorr_and_stp_identity_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="testcommit"
    )
    eq = snap["shadow_components"]["EQCORR"]
    stp = snap["shadow_components"]["STP2.1"]
    assert eq["shadow_subject_type"] == "RISK_POLICY_OVERLAY"
    assert eq["manifest_fingerprint"] == EQCORR_FP
    assert eq["baseline_outcomes_attached"] == 2
    assert eq["baseline_outcomes_pending"] == 0
    assert eq["baseline_divergence_count"] == 0
    assert stp["shadow_subject_type"] == "EXIT_POLICY_OVERLAY"
    assert stp["manifest_fingerprint"] == STP_FP
    assert stp["baseline_outcomes_attached"] == 2
    assert stp["baseline_outcomes_pending"] == 0
    assert HIST_STP11 not in (stp.get("policy_ids") or [])
    assert snap["coverage"]["cross_layer_fully_covered_closed_trades"] == 2
    assert snap["coverage"]["cross_layer_total_closed_trades"] == 2


def test_historical_stp_manifest_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path, hist_stp=True)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    with pytest.raises(usm.ShadowModelBlocker) as exc:
        usm.build_unified_shadow_model_snapshot(
            repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
        )
    assert exc.value.status == "SHADOW_MODEL_HISTORICAL_CONTAMINATION"


def test_virtual_outcomes_not_independent_episodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    comps = snap["comparisons"]
    assert comps["sample_unit"] == "CANONICAL_MARKET_EPISODE"
    assert comps["independent_canonical_episode_count"] == 2
    assert comps["virtual_variant_count"] > comps["independent_canonical_episode_count"]
    assert comps["economic_comparison_status"] == "INSUFFICIENT_SAMPLE"


def test_current_and_insufficient_sample_coexist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    assert snap["operational_status"] == "SHADOW_CURRENT"
    assert snap["evidence_status"] == "INSUFFICIENT_SAMPLE"
    assert snap["status"] == usm.SCHEMA_STATUS_OK


def test_small_sample_not_missing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    assert snap["operational_status"] != "SHADOW_MISSING_DATA"
    assert snap["evidence_status"] == "INSUFFICIENT_SAMPLE"


def test_historical_separation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    hist = snap["historical_separation"]
    assert hist["historical_shadow_evaluations_count"] == 2
    assert hist["historical_in_current_status"] is False
    assert hist["current_stp_outcomes_count"] >= 1


def test_persist_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    r1 = usm.persist_unified_snapshot(snap, repo_root=repo)
    assert r1["wrote_immutable"] is True
    r2 = usm.persist_unified_snapshot(snap, repo_root=repo)
    assert r2["wrote_immutable"] is False
    assert (repo / "data/model_assurance/shadow/latest/current.json").exists()


def test_read_only_builder_does_not_change_source_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(usm, "_process_alive", lambda pid: True)
    paths = usm.unified_paths(repo)
    before = {
        "epoch": usm._file_sha256(paths["active_epoch"]),
        "eq": usm._file_sha256(paths["eqcorr_dir"] / "health.json"),
        "stp": usm._file_sha256(paths["stp_dir"] / "health.json"),
        "pids": {k: (paths[k].read_text() if paths[k].exists() else None) for k in ("live1a_pid", "live1b_pid", "eqcorr_pid", "stp_pid")},
    }
    snap = usm.build_unified_shadow_model_snapshot(
        repo_root=repo, now=usm.parse_ts("2026-07-30T16:00:10Z"), source_commit="x"
    )
    usm.persist_unified_snapshot(snap, repo_root=repo)
    after = {
        "epoch": usm._file_sha256(paths["active_epoch"]),
        "eq": usm._file_sha256(paths["eqcorr_dir"] / "health.json"),
        "stp": usm._file_sha256(paths["stp_dir"] / "health.json"),
        "pids": {k: (paths[k].read_text() if paths[k].exists() else None) for k in ("live1a_pid", "live1b_pid", "eqcorr_pid", "stp_pid")},
    }
    assert before == after


@pytest.mark.integration
def test_integration_live_repo_snapshot_if_available():
    """Optional live integration — skip if shadow journals absent."""
    root = Path(__file__).resolve().parents[2]
    paths = usm.unified_paths(root)
    eq_h = paths["eqcorr_dir"] / "health.json"
    stp_h = paths["stp_dir"] / "health.json"
    if not eq_h.exists() or not stp_h.exists():
        pytest.skip("live shadow health not present")
    snap = usm.build_unified_shadow_model_snapshot(repo_root=root)
    assert snap["shadow_components"]["EQCORR"]["baseline_divergence_count"] == 0
    assert snap["shadow_components"]["STP2.1"]["baseline_divergence_count"] == 0
    assert snap["comparisons"]["eqcorr_pending_baseline_outcomes"] == 0
    assert snap["comparisons"]["stp_pending_baseline_outcomes"] == 0
    cov = snap["coverage"]
    assert cov["cross_layer_fully_covered_closed_trades"] == cov["cross_layer_total_closed_trades"]
    assert snap["promotion_eligible"] is False
    assert snap["historical_separation"]["historical_in_current_status"] is False
