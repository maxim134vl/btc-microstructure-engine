"""TRD-OUTCOME2 — all closed trades cross-layer reconciliation tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from epoch_isolation_helpers import (  # noqa: E402
    WORKSPACE,
    assert_no_runtime_touch,
    runtime_file_hashes,
)

REPO = WORKSPACE
ACTIVE = json.loads(
    (REPO / "data/trading/paper_epochs/active.json").read_text(encoding="utf-8")
)
EPOCH = str(ACTIVE["paper_epoch_id"])
CONTRACT_FP = "ca13177674222de7991dc26688ee2f91e018e5728a1660af6dc81c326acf7129"
HISTORICAL_STP11 = "e300d491fe470df4df754369ebbaedac25e66505950b555e76d0579467f7115b"
SCRIPT = REPO / "scripts/live/audit_all_closed_trades_cross_layer.py"


@pytest.fixture(scope="module")
def audit_module():
    sys.path.insert(0, str(REPO / "scripts/live"))
    import audit_all_closed_trades_cross_layer as mod  # type: ignore

    return mod


def test_script_exists():
    assert SCRIPT.exists()


def test_closed_trades_discovered_once_sorted(audit_module):
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    ids = [t["trade_id"] for t in trades]
    assert len(ids) == len(set(ids))
    assert all(str(t.get("paper_epoch_id") or EPOCH) == EPOCH for t in trades)
    exits = [str(t.get("exit_ts") or "") for t in trades]
    assert exits == sorted(exits)
    # Old epoch excluded by path + paper_epoch_id filter
    assert not any("INTRABAR_RULES_V1" in str(t.get("paper_epoch_id") or "") for t in trades)


def test_active_stp_manifest_not_historical_stp11(audit_module):
    meta = audit_module.resolve_active_stp_manifest(REPO, EPOCH)
    assert meta["active_stp_manifest_fingerprint"]
    assert meta["active_stp_manifest_fingerprint"] != HISTORICAL_STP11
    assert meta["is_historical_stp11"] is False
    assert HISTORICAL_STP11 in (meta.get("invalidated_manifest_fingerprints") or [])


def test_pnl_and_sleeve_reconstruction(audit_module):
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    if not trades:
        pytest.skip("no closed trades")
    for t in trades:
        pnl = audit_module.recompute_pnl(REPO, t)
        assert pnl["within_tolerance"], (t["trade_id"], pnl["diffs"])
    sleeves = json.loads(
        (REPO / f"data/trading/intrabar_paper/{EPOCH}/sleeves.json").read_text(encoding="utf-8")
    )
    recon = audit_module.reconstruct_sleeves(trades, sleeves)
    assert all(v["match"] for v in recon["sleeve_checks"].values())
    assert recon["master"]["equity_match"]
    assert recon["master"]["pnl_match"]
    assert abs(recon["master"]["reconstructed_equity"] - sum(recon["final_equity_by_tf"].values())) < 1e-6


def test_lifecycle_and_executable_sides(audit_module):
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    for t in trades:
        chain = audit_module.reconstruct_chain(REPO, EPOCH, t)
        assert chain["lifecycle_ok"], t["trade_id"]
        assert chain["counts"]["entry_fills"] == 1
        assert chain["counts"]["exit_fills"] == 1
        assert chain["lookahead_violation"] is False
        assert chain["executable_prices"]["entry_side_ok"] is not False
        assert chain["executable_prices"]["exit_side_ok"] is not False


def test_eqcorr_baseline_at_most_one(audit_module):
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    for t in trades:
        chain = audit_module.reconstruct_chain(REPO, EPOCH, t)
        eq = audit_module.eqcorr_for_trade(REPO, EPOCH, t, chain)
        bases = [p for p in eq["policies"] if p.get("policy_id") == "BASELINE_ALL_ELIGIBLE"]
        assert len(bases) <= 1
        if bases:
            assert eq["baseline_status"] in {"MATCH", "DIVERGENCE"}


def test_stp_excludes_other_manifests(audit_module):
    meta = audit_module.resolve_active_stp_manifest(REPO, EPOCH)
    fp = meta["active_stp_manifest_fingerprint"]
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    for t in trades:
        chain = audit_module.reconstruct_chain(REPO, EPOCH, t)
        stp = audit_module.stp_for_trade(REPO, EPOCH, t, chain, fp)
        assert stp["active_manifest"] == fp
        if stp["baseline_row"]:
            assert stp["baseline_row"].get("policy_manifest_fingerprint") == fp


def test_audit_script_read_only_and_status(tmp_path: Path):
    before = runtime_file_hashes()
    out = tmp_path / "out"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(REPO),
            "--paper-epoch-id",
            EPOCH,
            "--output-dir",
            str(out),
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    raw = proc.stdout[proc.stdout.find("{") :]
    payload = json.loads(raw)
    assert payload["status"].startswith("TRD_OUTCOME2_")
    assert Path(payload["json"]).exists()
    after = runtime_file_hashes()
    assert_no_runtime_touch(before, after)


def test_idempotent_sleeve_reconstruction(audit_module):
    trades = audit_module.find_closed_trades(REPO, EPOCH)
    idem = audit_module.idempotency_check(REPO, EPOCH, trades)
    assert idem["paper_trade_ids_unique"]
    assert idem["sleeve_equity_stable_across_passes"]
    assert idem["master_equity_first"] == idem["master_equity_second"]


def test_active_epoch_and_contract_match():
    active = json.loads((REPO / "data/trading/paper_epochs/active.json").read_text(encoding="utf-8"))
    assert active["paper_epoch_id"] == EPOCH
    assert active["trading_contract_fingerprint"] == CONTRACT_FP
    assert active.get("paper_only") is True
