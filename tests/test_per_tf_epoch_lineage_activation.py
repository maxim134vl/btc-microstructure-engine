"""PER-TF epoch lineage: source contract vs derived capital contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
from btc_ml.trading.intrabar_paper.trading_contract import (
    CANONICAL_SOURCE_EPOCH,
    EPOCH_PREFIX_SLEEVE2,
    EXPECTED_SOURCE_FINGERPRINT,
    SLEEVE2_ACTIVE,
    SLEEVE2_CAPITAL_CONTRACT_MISMATCH,
    SLEEVE2_SOURCE_LINEAGE_MISSING,
    SLEEVE2_SOURCE_LINEAGE_MISMATCH,
    SLEEVE2_SOURCE_MISMATCH,
    SLEEVE2_NON_CAPITAL_DIFF,
    assert_source_fingerprint,
    build_trading_contract_manifest,
    clone_trading_epoch_contract,
    resolve_sleeve2_source_contract,
    sleeve2_capital_overrides,
    trading_contract_fingerprint,
)

REPO = Path(__file__).resolve().parents[1]
DERIVED_EPOCH = "PER_TF_EQUITY_1PCT_V1_TEST_ACTIVE"
SHORT_PATCH = "b7b7804a37f9e44e41c94c805a8fcf4bdd866ef4"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_repo(tmp_path: Path, *, active: str = CANONICAL_SOURCE_EPOCH) -> Path:
    repo = tmp_path / "repo"
    raw = json.loads((REPO / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    _write_json(repo / "config" / "intrabar_paper_execution.json", raw)
    for rel in (
        "data/cognition/intrabar_context_events",
        "data/trading/intrabar_paper",
        "data/trading/paper_epochs",
    ):
        (repo / rel).mkdir(parents=True, exist_ok=True)
    source_epoch = {
        "paper_epoch_id": CANONICAL_SOURCE_EPOCH,
        "epoch_status": "CLOSED" if active != CANONICAL_SOURCE_EPOCH else "ACTIVE",
        "created_at": "2026-07-28T11:06:45Z",
        "activated_at": "2026-07-28T11:06:45Z",
        "closed_at": "2026-07-29T18:14:31Z" if active != CANONICAL_SOURCE_EPOCH else None,
        "initial_equity_usd": 100000.0,
        "rule_contract_version": "INTRABAR_RULES_V1",
        "void_reason": None,
        "failed_reason": None,
        "activated_at_monotonic_ns": None,
    }
    _write_json(repo / "data/trading/paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json", source_epoch)
    if active == CANONICAL_SOURCE_EPOCH:
        _write_json(repo / "data/trading/paper_epochs/active.json", {**source_epoch, "epoch_status": "ACTIVE"})
    return repo


def _install_empty_books(repo: Path, epoch_id: str) -> None:
    books = repo / "data/trading/intrabar_paper" / epoch_id / "books"
    books.mkdir(parents=True, exist_ok=True)
    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "trades",
        "positions",
        "blocked",
        "metrics",
        "equity_snapshots",
    ):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")


def _install_derived_epoch(repo: Path, *, epoch_id: str = DERIVED_EPOCH) -> dict[str, Any]:
    cfg = load_intrabar_paper_config(repo_root=repo)
    source = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=repo)
    assert assert_source_fingerprint(source) == EXPECTED_SOURCE_FINGERPRINT
    epoch_root = cfg.books_root / epoch_id
    clone = clone_trading_epoch_contract(
        CANONICAL_SOURCE_EPOCH,
        epoch_id,
        sleeve2_capital_overrides(),
        repo_root=repo,
        output_root=epoch_root,
        source_manifest=source,
    )
    contract_payload = {
        "trading_contract_manifest": clone.manifest,
        "trading_contract_fingerprint": clone.fingerprint,
        "parent_epoch_id": CANONICAL_SOURCE_EPOCH,
        "parent_trading_contract_fingerprint": clone.source_fingerprint,
        "allowlisted_contract_diff": clone.diff,
        "paper_only": True,
        "real_execution": False,
    }
    _write_json(epoch_root / "trading_contract.json", contract_payload)
    _write_json(
        cfg.epochs_root / f"{epoch_id}.trading_contract.json",
        {
            "paper_epoch_id": epoch_id,
            "parent_epoch_id": CANONICAL_SOURCE_EPOCH,
            "trading_contract_fingerprint": clone.fingerprint,
            "trading_contract_manifest": clone.manifest,
            "manifest_diff": clone.diff,
        },
    )
    epoch_doc = {
        "paper_epoch_id": epoch_id,
        "epoch_status": "ACTIVE",
        "created_at": "2026-07-29T18:14:31Z",
        "activated_at": "2026-07-29T18:14:31Z",
        "closed_at": None,
        "initial_equity_usd": 400000.0,
        "rule_contract_version": "INTRABAR_RULES_V1",
        "void_reason": None,
        "failed_reason": None,
        "activated_at_monotonic_ns": None,
        "parent_epoch_id": CANONICAL_SOURCE_EPOCH,
        "parent_trading_contract_fingerprint": clone.source_fingerprint,
        "trading_contract_fingerprint": clone.fingerprint,
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": 400000.0,
        "timeframe_initial_equity_usd": {
            "M15": 100000.0,
            "M30": 100000.0,
            "H1": 100000.0,
            "H4": 100000.0,
        },
        "allowlisted_contract_diff": clone.diff,
        "paper_only": True,
        "real_execution": False,
        "trading_contract_path": str((epoch_root / "trading_contract.json").relative_to(repo)),
    }
    _write_json(cfg.epochs_root / f"{epoch_id}.json", epoch_doc)
    _write_json(cfg.epochs_root / "active.json", epoch_doc)
    _install_empty_books(repo, epoch_id)
    SleeveLedger.initialize(epoch_id=epoch_id, epoch_root=epoch_root)
    return {"clone": clone, "epoch_doc": epoch_doc, "contract_payload": contract_payload}


def _mutate_contract(repo: Path, mutator) -> None:
    epoch_path = repo / "data/trading/paper_epochs" / f"{DERIVED_EPOCH}.json"
    payload_path = repo / "data/trading/intrabar_paper" / DERIVED_EPOCH / "trading_contract.json"
    sidecar_path = repo / "data/trading/paper_epochs" / f"{DERIVED_EPOCH}.trading_contract.json"
    epoch_doc = json.loads(epoch_path.read_text(encoding="utf-8"))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    manifest = payload["trading_contract_manifest"]
    mutator(epoch_doc, payload, manifest)
    fp = trading_contract_fingerprint(manifest)
    payload["trading_contract_fingerprint"] = fp
    sidecar["trading_contract_fingerprint"] = fp
    sidecar["trading_contract_manifest"] = manifest
    # Drop persisted diffs so the recomputed manifest-diff path is tested, not stale diff metadata.
    epoch_doc.pop("allowlisted_contract_diff", None)
    payload.pop("allowlisted_contract_diff", None)
    sidecar.pop("manifest_diff", None)
    epoch_doc["trading_contract_fingerprint"] = fp
    _write_json(epoch_path, epoch_doc)
    _write_json(repo / "data/trading/paper_epochs/active.json", epoch_doc)
    _write_json(payload_path, payload)
    _write_json(sidecar_path, sidecar)


def _activation_module():
    path = REPO / "scripts/live/activate_per_tf_equity_epoch.py"
    spec = importlib.util.spec_from_file_location("activate_per_tf_equity_epoch", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_canonical_source_contract_validates_against_expected_hash(tmp_path: Path):
    repo = _make_repo(tmp_path)
    manifest = build_trading_contract_manifest(CANONICAL_SOURCE_EPOCH, repo_root=repo)
    assert assert_source_fingerprint(manifest) == EXPECTED_SOURCE_FINGERPRINT
    res = resolve_sleeve2_source_contract(CANONICAL_SOURCE_EPOCH, repo_root=repo)
    assert res.source_contract_id == CANONICAL_SOURCE_EPOCH
    assert res.source_contract_hash == EXPECTED_SOURCE_FINGERPRINT


def test_active_derived_epoch_resolves_parent_and_400k_capital_is_not_source_mismatch(tmp_path: Path):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)
    res = resolve_sleeve2_source_contract(DERIVED_EPOCH, repo_root=repo)
    assert res.source_contract_id == CANONICAL_SOURCE_EPOCH
    assert res.source_contract_hash == EXPECTED_SOURCE_FINGERPRINT
    assert res.derived_epoch_id == DERIVED_EPOCH
    assert res.capital_contract["master_initial_equity_usd"] == pytest.approx(400000.0)
    assert res.capital_contract["timeframe_initial_equity_usd"] == {
        "M15": 100000.0,
        "M30": 100000.0,
        "H1": 100000.0,
        "H4": 100000.0,
    }
    mod = _activation_module()
    result = mod.prepare_or_activate(execute=False, repo_root=repo, skip_live_control=True)
    assert result["status"] == "TRD_SLEEVE2_DRY_RUN_READY"
    assert result["source_contract_hash"] == EXPECTED_SOURCE_FINGERPRINT


@pytest.mark.parametrize(
    "mutator, status",
    [
        (lambda _e, _p, m: m["entry_rules"].__setitem__("entry_eligibility", "CHANGED"), SLEEVE2_NON_CAPITAL_DIFF),
        (lambda _e, _p, m: m["protection_geometry"].__setitem__("stop_loss_bps", 200.0), SLEEVE2_NON_CAPITAL_DIFF),
        (lambda _e, _p, m: m["position_sizing"].__setitem__("max_risk_per_trade_pct", 2.0), SLEEVE2_NON_CAPITAL_DIFF),
        (lambda _e, _p, m: m["costs"].__setitem__("entry_fee_bps", 3.0), SLEEVE2_NON_CAPITAL_DIFF),
        (lambda _e, _p, m: m["protection_geometry"].__setitem__("take_profit_bps", 250.0), SLEEVE2_NON_CAPITAL_DIFF),
    ],
)
def test_unexplained_rule_risk_fee_slippage_stop_take_drift_fails_closed(tmp_path: Path, mutator, status: str):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)
    _mutate_contract(repo, mutator)
    with pytest.raises(RuntimeError, match=status):
        resolve_sleeve2_source_contract(DERIVED_EPOCH, repo_root=repo)


def test_arbitrary_capital_difference_fails_closed(tmp_path: Path):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)

    def mutate(epoch_doc, _payload, manifest):
        epoch_doc["initial_equity_usd"] = 500000.0
        epoch_doc["master_initial_equity_usd"] = 500000.0
        manifest["capital"]["master_initial_equity_usd"] = 500000.0
        manifest["capital"]["timeframe_initial_equity_usd"]["M15"] = 200000.0

    _mutate_contract(repo, mutate)
    with pytest.raises(RuntimeError, match=SLEEVE2_CAPITAL_CONTRACT_MISMATCH):
        resolve_sleeve2_source_contract(DERIVED_EPOCH, repo_root=repo)


def test_missing_parent_lineage_and_forged_parent_hash_fail_closed(tmp_path: Path):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)
    epoch_path = repo / "data/trading/paper_epochs" / f"{DERIVED_EPOCH}.json"
    active_path = repo / "data/trading/paper_epochs/active.json"
    epoch_doc = json.loads(epoch_path.read_text(encoding="utf-8"))
    epoch_doc.pop("parent_epoch_id", None)
    epoch_doc.pop("source_contract_id", None)
    _write_json(epoch_path, epoch_doc)
    _write_json(active_path, epoch_doc)
    with pytest.raises(RuntimeError, match=SLEEVE2_SOURCE_LINEAGE_MISSING):
        resolve_sleeve2_source_contract(DERIVED_EPOCH, repo_root=repo)

    _install_derived_epoch(repo)
    epoch_doc = json.loads(epoch_path.read_text(encoding="utf-8"))
    epoch_doc["parent_trading_contract_fingerprint"] = "0" * 64
    _write_json(epoch_path, epoch_doc)
    _write_json(active_path, epoch_doc)
    with pytest.raises(RuntimeError, match=SLEEVE2_SOURCE_LINEAGE_MISMATCH):
        resolve_sleeve2_source_contract(DERIVED_EPOCH, repo_root=repo)


def test_old_epoch_manifest_readable_and_short_provenance_persisted_without_source_hash_change(tmp_path: Path):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)
    before_source = (repo / "data/trading/paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json").read_text(encoding="utf-8")
    mod = _activation_module()
    result = mod.prepare_or_activate(
        execute=True,
        source_epoch_id=DERIVED_EPOCH,
        activation_reason="SHORT_SYMMETRY_RESTORE",
        patch_commit=SHORT_PATCH,
        repo_root=repo,
        skip_live_control=True,
    )
    assert result["status"] == SLEEVE2_ACTIVE
    assert result["source_contract_id"] == CANONICAL_SOURCE_EPOCH
    assert result["source_contract_hash"] == EXPECTED_SOURCE_FINGERPRINT
    assert (repo / "data/trading/paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json").read_text(encoding="utf-8") == before_source
    new_id = result["new_epoch_id"]
    assert new_id.startswith(EPOCH_PREFIX_SLEEVE2)
    active = json.loads((repo / "data/trading/paper_epochs/active.json").read_text(encoding="utf-8"))
    assert active["paper_epoch_id"] == new_id
    assert active["activation_reason"] == "SHORT_SYMMETRY_RESTORE"
    assert active["patch_commit"] == SHORT_PATCH
    assert active["source_contract_id"] == CANONICAL_SOURCE_EPOCH
    assert active["source_contract_hash"] == EXPECTED_SOURCE_FINGERPRINT
    sleeves = json.loads((repo / "data/trading/intrabar_paper" / new_id / "sleeves.json").read_text(encoding="utf-8"))
    assert {tf: row["initial_equity_usd"] for tf, row in sleeves["sleeves"].items()} == {
        "M15": 100000.0,
        "M30": 100000.0,
        "H1": 100000.0,
        "H4": 100000.0,
    }
    assert {tf: row["risk_pct_per_trade"] for tf, row in sleeves["sleeves"].items()} == {
        "M15": 1.0,
        "M30": 1.0,
        "H1": 1.0,
        "H4": 1.0,
    }


def test_real_execution_enabled_fails_closed(tmp_path: Path):
    repo = _make_repo(tmp_path, active=DERIVED_EPOCH)
    _install_derived_epoch(repo)
    cfg_path = repo / "config/intrabar_paper_execution.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["real_execution_enabled"] = True
    _write_json(cfg_path, cfg)
    mod = _activation_module()
    with pytest.raises(ValueError, match="real_execution_enabled must be false"):
        mod.prepare_or_activate(execute=False, repo_root=repo, skip_live_control=True)
