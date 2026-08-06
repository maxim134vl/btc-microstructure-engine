from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.model_assurance import registry
from btc_ml.model_assurance import behavioral_validation as bv
from btc_ml.model_assurance.toxic_box import current_toxicity as ct
from btc_ml.trading.intrabar_paper.trading_contract import (
    trading_contract_fingerprint,
)


def _write_json(
    path: Path,
    value: object,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: list[dict],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "".join(
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _contract(
    *,
    epoch_id: str,
    source_commit: str,
) -> dict:
    snapshot = {
        "paper_only": True,
        "real_execution_enabled": False,
        "rule_contract_version":
            "INTRABAR_RULES_V1",
        "entry_fee_bps": 2.0,
        "exit_fee_bps": 5.0,
        "max_risk_per_trade_pct": 1.0,
        "max_risk_per_trade_usd": 1000.0,
        "stop_loss_bps": 100.0,
        "take_profit_bps": 150.0,
    }

    manifest = {
        "schema_version":
            "trading_contract_manifest_v1",
        "epoch_identity": {
            "paper_epoch_id": epoch_id,
            "epoch_id": epoch_id,
            "rule_contract_version":
                "INTRABAR_RULES_V1",
        },
        "execution_config_snapshot":
            snapshot,
        "capital": {
            "capital_model":
                "PER_TIMEFRAME_REALIZED_EQUITY",
        },
        "position_sizing": {
            "risk_percentage": 1.0,
        },
        "protection_geometry": {
            "stop_loss_bps": 100.0,
            "take_profit_bps": 150.0,
        },
    }

    fingerprint = (
        trading_contract_fingerprint(
            manifest
        )
    )
    manifest[
        "trading_contract_fingerprint"
    ] = fingerprint

    return {
        "paper_only": True,
        "real_execution": False,
        "real_execution_enabled": False,
        "source_commit": source_commit,
        "canonical_commit": source_commit,
        "patch_commit": source_commit,
        "trading_contract_fingerprint":
            fingerprint,
        "trading_contract_manifest":
            manifest,
    }


def test_registry_rollover_uses_immutable_epoch_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path
    epoch_id = "EPOCH_NEW"
    contract_rel = (
        "data/trading/intrabar_paper/"
        f"{epoch_id}/trading_contract.json"
    )
    contract = _contract(
        epoch_id=epoch_id,
        source_commit="epoch-commit",
    )

    _write_json(
        root
        / "config/"
        "model_assurance_active_runtime.json",
        {
            "model_id": "MODEL",
            "model_version": "V1",
            "model_role": "ACTIVE",
            "model_type": "RULE_BASED",
            "cognition_version": "CTX",
            "rule_contract_version":
                "INTRABAR_RULES_V1",
        },
    )
    _write_json(
        root
        / "config/"
        "intrabar_paper_execution.json",
        {
            "paper_only": True,
            "real_execution_enabled": False,
            "rule_contract_version":
                "INTRABAR_RULES_V1",
            "entry_fee_bps": 999.0,
        },
    )
    _write_json(
        root
        / "data/trading/"
        "paper_epochs/active.json",
        {
            "paper_epoch_id": epoch_id,
            "epoch_status": "ACTIVE",
            "activated_at":
                "2026-08-02T00:00:00Z",
            "rule_contract_version":
                "INTRABAR_RULES_V1",
            "trading_contract_path":
                contract_rel,
            "trading_contract_fingerprint":
                contract[
                    "trading_contract_fingerprint"
                ],
        },
    )
    _write_json(
        root / contract_rel,
        contract,
    )

    monkeypatch.setattr(
        registry,
        "compute_feature_schema_hash",
        lambda: "feature",
    )
    monkeypatch.setattr(
        registry,
        "compute_data_schema_hash",
        lambda: "data",
    )

    first = registry.build_active_runtime_record(
        repo_root=root
    )

    assert first["paper_epoch_id"] == epoch_id
    assert (
        first["source_commit"]
        == "epoch-commit"
    )
    assert (
        first[
            "trading_contract_fingerprint"
        ]
        == contract[
            "trading_contract_fingerprint"
        ]
    )

    mutable_hash = registry._sha256_bytes(
        (
            root
            / "config/"
            "intrabar_paper_execution.json"
        ).read_bytes()
    )

    assert (
        first["execution_config_hash"]
        != mutable_hash
    )

    mutable_config_path = (
        root
        / "config/"
        "intrabar_paper_execution.json"
    )
    mutable_config = json.loads(
        mutable_config_path.read_text(
            encoding="utf-8"
        )
    )

    # Mutable economic changes must not alter immutable epoch identity.
    mutable_config[
        "entry_fee_bps"
    ] = 12345.0
    _write_json(
        mutable_config_path,
        mutable_config,
    )

    after_mutable_change = (
        registry.build_active_runtime_record(
            repo_root=root
        )
    )

    for key in (
        "paper_epoch_id",
        "source_commit",
        "runtime_fingerprint",
        "trading_contract_fingerprint",
        "execution_config_hash",
        "risk_config_hash",
    ):
        assert (
            after_mutable_change[key]
            == first[key]
        )

    # A dangerous current global flag must still block registration.
    mutable_config[
        "real_execution_enabled"
    ] = True
    _write_json(
        mutable_config_path,
        mutable_config,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "REGISTRATION_BLOCKED_"
            "SAFETY_FLAGS"
        ),
    ):
        registry.build_active_runtime_record(
            repo_root=root
        )

    mutable_config[
        "real_execution_enabled"
    ] = False
    _write_json(
        mutable_config_path,
        mutable_config,
    )

    old = {
        **first,
        "registry_record_id": "REG_OLD",
        "paper_epoch_id": "EPOCH_OLD",
        "runtime_fingerprint":
            "old-fingerprint",
    }

    _write_jsonl(
        root
        / "data/model_assurance/"
        "registry/models/"
        "model_registry.jsonl",
        [old],
    )

    result = registry.register_active_runtime(
        repo_root=root
    )

    assert (
        result["status"]
        == "ACTIVE_REGISTERED"
    )
    assert (
        result["active_model"][
            "paper_epoch_id"
        ]
        == epoch_id
    )


def test_behavioral_state_isolated_and_history_preserved(
    tmp_path: Path,
) -> None:
    predictions = (
        tmp_path / "predictions.jsonl"
    )
    outcomes = (
        tmp_path / "outcomes.jsonl"
    )
    checkpoint = (
        tmp_path / "checkpoint.json"
    )

    old_prediction = {
        "prediction_id": "P_OLD",
        "paper_epoch_id": "OLD",
        "registry_record_id": "REG_OLD",
        "prediction_status": "OPEN",
        "timeframe": "H1",
        "context_event_id": "CTX_OLD",
        "created_at":
            "2026-08-01T00:00:00Z",
    }
    current_prediction = {
        "prediction_id": "P_NEW",
        "paper_epoch_id": "NEW",
        "registry_record_id": "REG_NEW",
        "prediction_status": "OPEN",
        "timeframe": "M15",
        "context_event_id": "CTX_NEW",
        "created_at":
            "2026-08-02T00:00:00Z",
    }

    _write_jsonl(
        predictions,
        [
            old_prediction,
            current_prediction,
        ],
    )
    _write_jsonl(
        outcomes,
        [
            {
                "outcome_id": "O_OLD",
                "paper_epoch_id": "OLD",
                "registry_record_id":
                    "REG_OLD",
            },
            {
                "outcome_id": "O_NEW",
                "paper_epoch_id": "NEW",
                "registry_record_id":
                    "REG_NEW",
            },
        ],
    )
    _write_json(
        checkpoint,
        {
            "paper_epoch_id": "OLD",
            "registry_record_id": "REG_OLD",
            "processed_event_ids": [
                "CTX_OLD_CHECKPOINT"
            ],
        },
    )

    active = {
        "paper_epoch_id": "NEW",
        "registry_record_id": "REG_NEW",
    }
    state = bv.load_state(
        {
            "predictions": predictions,
            "outcomes": outcomes,
            "checkpoint": checkpoint,
        },
        active=active,
    )

    assert set(state.predictions) == {
        "P_NEW"
    }
    assert set(state.outcomes) == {
        "O_NEW"
    }
    assert state.open_by_tf == {
        "M15": "P_NEW"
    }
    assert (
        "CTX_OLD_CHECKPOINT"
        not in state.processed_event_ids
    )

    merged = (
        bv.merge_prediction_rows_for_binding(
            existing_rows=[
                old_prediction,
                current_prediction,
            ],
            active_rows=[
                {
                    **current_prediction,
                    "prediction_status":
                        "CLOSED",
                }
            ],
            active=active,
        )
    )

    assert len(merged) == 2
    assert any(
        row["prediction_id"] == "P_OLD"
        for row in merged
    )
    assert any(
        row["prediction_id"] == "P_NEW"
        and row["prediction_status"]
        == "CLOSED"
        for row in merged
    )


def test_current_toxicity_summary_excludes_old_binding() -> None:
    active = {
        "paper_epoch_id": "NEW",
        "registry_record_id": "REG_NEW",
    }

    rows = [
        {
            "toxic_event_id": "OLD",
            "branch": "CONTEXT",
            "paper_epoch_id": "OLD",
            "registry_record_id": "REG_OLD",
            "status": "CANDIDATE",
        },
        {
            "toxic_event_id": "NEW",
            "branch": "CONTEXT",
            "paper_epoch_id": "NEW",
            "registry_record_id": "REG_NEW",
            "status": "CANDIDATE",
        },
        {
            "toxic_event_id": "WRONG_REG",
            "branch": "CONTEXT",
            "paper_epoch_id": "NEW",
            "registry_record_id": "REG_OTHER",
            "status": "CONFIRMED",
        },
    ]

    selected = (
        ct.events_for_active_binding(
            rows,
            branch="CONTEXT",
            active=active,
        )
    )

    assert [
        row["toxic_event_id"]
        for row in selected
    ] == ["NEW"]
