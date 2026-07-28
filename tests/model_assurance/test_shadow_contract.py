"""Minimal MODEL-7 shadow contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.model_assurance import registry as reg
from btc_ml.model_assurance.shadow import comparison as cmp
from btc_ml.model_assurance.shadow import monitor as mon
from btc_ml.model_assurance.shadow.candidate_adapter import load_candidate_adapter
from btc_ml.model_assurance.shadow.prediction_contract import build_shadow_prediction
from btc_ml.model_assurance.toxic_box.common import read_jsonl


ACTIVE = {
    "registry_record_id": "REG_ACTIVE",
    "model_id": "ACTIVE_M",
    "model_version": "V1",
    "runtime_fingerprint": "fp_active",
    "paper_epoch_id": "EPOCH",
    "paper_only": True,
    "real_execution": False,
    "feature_schema_version": "FS",
    "data_schema_version": "DS",
}


def _safe_candidate(**kwargs) -> dict:
    base = {
        "model_id": "SAFE_CANDIDATE",
        "model_version": "C1",
        "model_type": "RESEARCH_CANDIDATE",
        "cognition_version": "TEST",
        "rule_contract_version": "SHADOW_NO_EXECUTION",
        "prediction_only": True,
        "shadow_only": True,
        "execution_enabled": False,
        "real_execution": False,
        "paper_execution": False,
        "order_routing": False,
    }
    base.update(kwargs)
    return base


class _StubAdapter:
    """Test-only adapter — not a production directional detector."""

    def __init__(self, context: str = "OBSERVE"):
        self.context = context

    def predict(self, shadow_input):
        return {"predicted_context": self.context, "confidence": 0.55, "prediction_payload": {}}


def test_no_candidate_no_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mon, "read_active_runtime", lambda repo_root=None: ACTIVE)
    monkeypatch.setattr(mon, "read_candidate", lambda repo_root=None: None)
    monkeypatch.setattr(mon, "_promotion_blockers", lambda repo_root: ["INPUT_DRIFT_CRITICAL"])
    monkeypatch.setattr(mon, "paths", lambda repo_root=None: {
        "inputs": tmp_path / "inputs.jsonl",
        "predictions": tmp_path / "predictions.jsonl",
        "comparisons": tmp_path / "comparisons.jsonl",
        "summary": tmp_path / "summary.json",
        "checkpoint": tmp_path / "checkpoint.json",
        "health": tmp_path / "health.json",
        "drift_summary": tmp_path / "drift.json",
        "books_root": tmp_path / "books",
    })
    summary = mon.run_once(repo_root=tmp_path)
    assert summary["status"] == "NO_CANDIDATE_REGISTERED"
    assert summary["shadow_status"] == "NOT_APPLICABLE_NO_CANDIDATE"
    assert summary["shadow_predictions"] == 0
    assert summary["shadow_created_orders"] == 0
    assert summary["shadow_created_fills"] == 0
    assert summary["shadow_created_positions"] == 0
    assert not (tmp_path / "predictions.jsonl").exists()
    assert "INPUT_DRIFT_CRITICAL" in summary["promotion_blockers"]


def test_safe_prediction_only_candidate_registers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reg, "registry_paths", lambda repo_root=None: {
        "root": tmp_path / "registry",
        "models_jsonl": tmp_path / "registry" / "models" / "model_registry.jsonl",
        "active_model": tmp_path / "registry" / "active" / "active_model.json",
        "candidate_model": tmp_path / "registry" / "candidate" / "candidate_model.json",
        "registry_status": tmp_path / "registry" / "registry_status.json",
        "identity_config": tmp_path / "identity.json",
        "execution_config": tmp_path / "exec.json",
        "active_epoch": tmp_path / "epoch.json",
        "candidates_dir": tmp_path / "candidates",
    })
    monkeypatch.setattr(reg, "read_active_runtime", lambda repo_root=None: ACTIVE)
    cfg = tmp_path / "cand.json"
    cfg.write_text(json.dumps(_safe_candidate()), encoding="utf-8")
    result = reg.register_candidate(config_path=cfg, repo_root=tmp_path)
    assert result["status"] == "CANDIDATE_REGISTERED"
    cand = result["candidate"]
    assert cand["model_role"] == "CANDIDATE"
    assert cand["execution_capability"] == "NONE"
    assert cand["execution_enabled"] is False
    assert "paper_epoch_id" not in cand
    assert reg.read_candidate_status(repo_root=tmp_path)["candidate_status"] == "CANDIDATE_REGISTERED"


def test_execution_enabled_candidate_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(reg, "registry_paths", lambda repo_root=None: {
        "root": tmp_path / "registry",
        "models_jsonl": tmp_path / "registry" / "models" / "model_registry.jsonl",
        "active_model": tmp_path / "registry" / "active" / "active_model.json",
        "candidate_model": tmp_path / "registry" / "candidate" / "candidate_model.json",
        "registry_status": tmp_path / "registry" / "registry_status.json",
        "identity_config": tmp_path / "identity.json",
        "execution_config": tmp_path / "exec.json",
        "active_epoch": tmp_path / "epoch.json",
        "candidates_dir": tmp_path / "candidates",
    })
    bad = _safe_candidate(execution_enabled=True)
    result = reg.register_candidate(bad, repo_root=tmp_path)
    assert result["status"] == "CANDIDATE_REJECTED_EXECUTION_ENABLED_TRUE"
    assert result["candidate"] is None
    assert reg.read_candidate(repo_root=tmp_path) is None


def test_adapter_prediction_does_not_create_paper_entities(tmp_path: Path):
    candidate = reg.build_candidate_record(_safe_candidate(), repo_root=tmp_path)
    books = tmp_path / "books" / "EPOCH" / "books"
    books.mkdir(parents=True)
    for name in ("orders", "fills", "positions"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    before = {n: (books / f"{n}.jsonl").read_text(encoding="utf-8") for n in ("orders", "fills", "positions")}

    shadow_in = {
        "shadow_input_id": "IN1",
        "timeframe": "M15",
        "causal_cutoff_timestamp": "2026-07-28T12:00:00Z",
        "causal_cutoff_monotonic_ns": 1,
    }
    adapter = _StubAdapter("SHORT")
    result = adapter.predict(shadow_in)
    pred = build_shadow_prediction(
        active=ACTIVE,
        candidate=candidate,
        shadow_input=shadow_in,
        predicted_context=result["predicted_context"],
        confidence=result["confidence"],
        prediction_payload=result["prediction_payload"],
    )
    assert pred["predicted_context"] == "SHORT"
    assert pred["creates_order"] is False
    assert pred["creates_fill"] is False
    assert pred["creates_position"] is False
    assert pred["creates_paper_command"] is False
    after = {n: (books / f"{n}.jsonl").read_text(encoding="utf-8") for n in ("orders", "fills", "positions")}
    assert after == before
    # Unavailable without adapter_module
    bare = dict(candidate)
    bare["adapter_module"] = None
    assert isinstance(load_candidate_adapter(bare), object)


def test_agree_disagree_and_no_duplicate_comparisons(tmp_path: Path):
    candidate = reg.build_candidate_record(_safe_candidate(model_id="CMP_C"), repo_root=tmp_path)
    agree = cmp.compare_active_shadow(
        active=ACTIVE,
        candidate=candidate,
        timeframe="M15",
        causal_cutoff_timestamp="2026-07-28T12:00:00Z",
        causal_cutoff_monotonic_ns=100,
        active_context="LONG",
        shadow_context="LONG",
        shadow_prediction_id="P1",
    )
    disagree = cmp.compare_active_shadow(
        active=ACTIVE,
        candidate=candidate,
        timeframe="M15",
        causal_cutoff_timestamp="2026-07-28T12:00:00Z",
        causal_cutoff_monotonic_ns=200,
        active_context="LONG",
        shadow_context="SHORT",
        shadow_prediction_id="P2",
    )
    assert agree["comparison_status"] == "AGREE"
    assert agree["context_agreement"] is True
    assert disagree["comparison_status"] == "DISAGREE"
    assert disagree["context_agreement"] is False

    path = tmp_path / "comparisons.jsonl"
    existing: set[str] = set()
    for row in (agree, disagree, agree, disagree):
        cid = row["comparison_id"]
        if cid in existing:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        existing.add(cid)
    rows = read_jsonl(path)
    assert len(rows) == 2
    assert {r["comparison_id"] for r in rows} == {agree["comparison_id"], disagree["comparison_id"]}
