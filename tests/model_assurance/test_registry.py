"""Minimal Model Assurance registry tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.model_assurance import registry as reg


def _seed_repo(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    identity = {
        "model_id": "BTC_INTRABAR_RULE_BASED",
        "model_version": "INTRABAR_RULES_V1",
        "model_role": "ACTIVE",
        "model_type": "RULE_BASED_INTRABAR",
        "cognition_version": "LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        "rule_contract_version": "INTRABAR_RULES_V1",
    }
    (tmp_path / "config" / "model_assurance_active_runtime.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    execution = {
        "schema_version": "intrabar_paper_execution_v1",
        "rule_contract_version": "INTRABAR_RULES_V1",
        "paper_only": True,
        "real_execution_enabled": False,
        "max_risk_per_trade_pct": 1.0,
        "max_risk_per_trade_usd": 1000.0,
        "cost_aware_stop_sizing": True,
        "fixed_notional": False,
        "stop_loss_bps": 100.0,
        "take_profit_bps": 150.0,
        "entry_fee_bps": 2.0,
        "exit_fee_bps": 5.0,
        "entry_slippage_bps": 3.0,
        "exit_slippage_bps": 3.0,
        "stop_exit_slippage_bps": 5.0,
        "economics_source": "canonical_paper_trade_economics_v1",
    }
    (tmp_path / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(execution, indent=2) + "\n", encoding="utf-8"
    )
    epoch = {
        "paper_epoch_id": "INTRABAR_RULES_V1_TEST_EPOCH",
        "epoch_status": "ACTIVE",
        "activated_at": "2026-07-28T11:06:45.374645Z",
        "rule_contract_version": "INTRABAR_RULES_V1",
        "initial_equity_usd": 100000.0,
    }
    (tmp_path / "data" / "trading" / "paper_epochs" / "active.json").write_text(
        json.dumps(epoch, indent=2) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_valid_active_runtime_registers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_repo(tmp_path)
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "abc123")
    result = reg.register_active_runtime(repo_root=root)
    assert result["status"] == "ACTIVE_REGISTERED"
    active = result["active_model"]
    assert active["model_id"] == "BTC_INTRABAR_RULE_BASED"
    assert active["model_version"] == "INTRABAR_RULES_V1"
    assert active["record_status"] == "ACTIVE_REGISTERED"
    assert active["paper_epoch_id"] == "INTRABAR_RULES_V1_TEST_EPOCH"
    assert active["source_commit"] == "abc123"
    assert active["paper_only"] is True
    assert active["real_execution"] is False
    paths = reg.registry_paths(root)
    assert paths["models_jsonl"].exists()
    assert paths["active_model"].exists()
    rows = paths["models_jsonl"].read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1


def test_identical_rerun_already_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_repo(tmp_path)
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "abc123")
    first = reg.register_active_runtime(repo_root=root)
    second = reg.register_active_runtime(repo_root=root)
    assert first["status"] == "ACTIVE_REGISTERED"
    assert second["status"] == "ALREADY_REGISTERED"
    assert second["registry_record_id"] == first["registry_record_id"]
    rows = reg.registry_paths(root)["models_jsonl"].read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1


def test_same_version_different_fingerprint_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_repo(tmp_path)
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "commit_a")
    first = reg.register_active_runtime(repo_root=root)
    assert first["status"] == "ACTIVE_REGISTERED"
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "commit_b")
    conflict = reg.register_active_runtime(repo_root=root)
    assert conflict["status"] == "VERSION_CONFLICT"
    rows = reg.registry_paths(root)["models_jsonl"].read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1


def test_real_execution_blocks_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_repo(tmp_path)
    cfg_path = root / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["real_execution_enabled"] = True
    cfg_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "abc123")
    result = reg.register_active_runtime(repo_root=root)
    assert result["status"] == "REGISTRATION_BLOCKED_SAFETY_FLAGS"
    assert not reg.registry_paths(root)["models_jsonl"].exists()


def test_read_active_runtime_returns_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _seed_repo(tmp_path)
    monkeypatch.setattr(reg, "resolve_source_commit", lambda repo_root=None: "abc123")
    registered = reg.register_active_runtime(repo_root=root)
    active = reg.read_active_runtime(repo_root=root)
    assert active is not None
    assert active["registry_record_id"] == registered["registry_record_id"]
    assert active["runtime_fingerprint"] == registered["active_model"]["runtime_fingerprint"]
    status = reg.read_registry_status(repo_root=root)
    assert status["status"] == "ACTIVE_REGISTERED"
    assert status["candidate_status"] == "NONE_REGISTERED"
    assert status["shadow_status"] == "NONE_REGISTERED"
