"""Patch 2B.3 — production paper activation contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "data" / "research" / "paper_simulator"
TAG_PATH = ROOT / "data" / "research" / "patch2b3_active_ts.txt"
CTL = ROOT / "scripts" / "bounded_paper_trading_controller_ctl.sh"
S4_ACTIVATION = ROOT / "data" / "trading" / "manager" / "activation.json"


def _tag() -> str:
    if not TAG_PATH.exists():
        pytest.skip("no patch2b3 active tag")
    return TAG_PATH.read_text(encoding="utf-8").strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_01_migration_comparison_matches_production():
    tag = _tag()
    mig = json.loads(
        (ROOT / "data" / "research" / f"patch2b3_migration_comparison_{tag}.json").read_text(
            encoding="utf-8"
        )
    )
    assert mig["mode"] == "CLOSED_HISTORY_ONLY"
    assert mig.get("activated")
    for row in mig["activated"]:
        path = Path(row["path"])
        assert path.exists()
        assert _sha(path) == row["sha256_after"]


def test_02_backup_manifest_readable():
    tag = _tag()
    man = json.loads(
        (ROOT / "data" / "research" / f"patch2b3_backup_manifest_{tag}.json").read_text(
            encoding="utf-8"
        )
    )
    items = man.get("items") or man.get("files") or man.get("entries") or man.get("backups")
    assert items
    backup_dir = Path(man.get("backup_dir") or (ROOT / "data" / "research" / f"patch2b3_production_backups_{tag}"))
    assert backup_dir.is_dir()
    assert (backup_dir / "paper_trades.parquet").exists()


def test_03_production_preservation_flags():
    tag = _tag()
    doc = json.loads(
        (
            ROOT / "data" / "research" / f"patch2b3_production_preservation_{tag}.json"
        ).read_text(encoding="utf-8")
    )
    assert doc.get("historical_market_model_changed") is False
    assert doc.get("historical_context_changed") is False
    assert doc.get("historical_lifecycle_changed") is False
    assert doc.get("historical_decisions_changed") is False


def test_04_ctl_default_skip_refresh():
    src = CTL.read_text(encoding="utf-8")
    assert "--skip-refresh" in src
    # Production ctl must not pass enable-context-refresh in its start argv.
    assert "--enable-context-refresh" not in src


def test_05_controller_running_one_pid_skip_refresh():
    out = subprocess.check_output(["bash", str(CTL), "status"], text=True, cwd=str(ROOT))
    if S4_ACTIVATION.exists():
        # S4.1 cutover: the legacy global controller is retired in favour of the
        # manager plus four independent timeframe traders and must stay stopped.
        assert "status=RUNNING" not in out
        assert "live_controller_count=0" in out
        assert "duplicate_controller_count=0" in out
        return
    assert "status=RUNNING" in out
    assert "live_controller_count=1" in out
    assert "duplicate_controller_count=0" in out
    ps = subprocess.check_output(
        ["ps", "-axo", "pid,command"],
        text=True,
    )
    paper = []
    for ln in ps.splitlines():
        if "bounded_paper_trading_controller_auto_ledger_no_real_execution.py" not in ln:
            continue
        # Ignore scanners / test runners that merely mention the script path.
        if any(
            tok in ln
            for tok in (
                "rg ",
                "zsh -c",
                "pytest",
                "-m pytest",
                "test_patch2b3",
                "tests/test_",
            )
        ):
            continue
        paper.append(ln)
    assert len(paper) == 1, paper
    assert "--skip-refresh" in paper[0]
    assert "--enable-context-refresh" not in paper[0]
    assert "--no-real-execution" in paper[0]


def test_06_continuation_and_price_gate_off():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") in {"0", "false", "False", ""}
    assert os.environ.get("PRICE_GATE", "OFF") in {"OFF", "0", "false", "False", ""}


def test_07_paper_ownership_not_broken():
    reg = json.loads((ROOT / "config" / "runtime_dataset_ownership.json").read_text())
    by_id = {d["dataset_id"]: d for d in reg["datasets"]}
    for did in ("paper_signals", "paper_orders", "paper_trades"):
        assert by_id[did]["operational_status"] != "BROKEN"
        assert by_id[did]["operational_status"] in {"ACTIVE", "ACTIVE_STALE"}


def test_08_restart_proof_artifact():
    tag = _tag()
    doc = json.loads(
        (ROOT / "data" / "research" / f"patch2b3_restart_proof_{tag}.json").read_text(
            encoding="utf-8"
        )
    )
    assert doc.get("duplicate_signals", 0) == 0
    assert doc.get("duplicate_orders", 0) == 0
    assert doc.get("duplicate_trades", 0) == 0
    assert doc.get("ledger_unchanged_on_restart", True) in {True, 1}
