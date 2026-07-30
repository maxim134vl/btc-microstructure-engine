"""TRD-OUTCOME1 — epoch isolation + first-close audit readiness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from epoch_isolation_helpers import (
    WORKSPACE,
    assert_no_runtime_touch,
    make_isolated_contract_repo,
    runtime_file_hashes,
)

REPO = WORKSPACE


def test_epoch_isolation_helper_does_not_touch_runtime(tmp_path: Path):
    before = runtime_file_hashes()
    iso = make_isolated_contract_repo(tmp_path, stamp="OUT1", activate_source=True)
    assert (iso / "data/trading/paper_epochs/active.json").exists()
    after = runtime_file_hashes()
    assert_no_runtime_touch(before, after)


def test_audit_script_runs_read_only(tmp_path: Path):
    import os

    before = runtime_file_hashes()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/live/audit_first_closed_trade_cross_layer.py")],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, proc.stdout
    # last JSON object line may be pretty-printed; parse full stdout JSON block
    raw = proc.stdout[proc.stdout.find("{") :]
    payload = json.loads(raw)
    assert payload["status"].startswith("TRD_OUTCOME1_")
    assert Path(payload["json"]).exists()
    after = runtime_file_hashes()
    assert_no_runtime_touch(before, after)


def test_stp_stale_close_repair_reclaims_processed(tmp_path: Path):
    from btc_ml.trading.shadow_structural_protection import (
        EXPECTED_ACTIVE_FP,
        EXPECTED_EPOCH,
        EXPECTED_PARENT_FP,
    )
    from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine

    repo = tmp_path / "stp_repo"
    (repo / "config").mkdir(parents=True)
    import shutil

    shutil.copy(REPO / "config/intrabar_paper_execution.json", repo / "config/intrabar_paper_execution.json")
    books = repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    books.mkdir(parents=True)
    for name in ("signals", "commands", "orders", "fills", "positions", "trades"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    (books / "trades.jsonl").write_text(
        json.dumps(
            {
                "trade_id": "trd_test_1",
                "position_id": "pos_test_1",
                "timeframe": "M15",
                "side": "LONG",
                "exit_ts": "2026-07-29T19:24:54Z",
                "exit_price": 64000.0,
                "exit_reason": "CONTEXT_END",
                "entry_price": 64100.0,
                "quantity": 1.0,
                "net_pnl_usd": -10.0,
                "gross_pnl_usd": -5.0,
                "fees_usd": 3.0,
                "slippage_usd": 2.0,
                "risk_amount_usd": 1000.0,
                "paper_epoch_id": EXPECTED_EPOCH,
            }
        )
        + "\n"
    )
    epochs = repo / "data/trading/paper_epochs"
    epochs.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EXPECTED_EPOCH,
                "trading_contract_fingerprint": EXPECTED_ACTIVE_FP,
                "parent_trading_contract_fingerprint": EXPECTED_PARENT_FP,
            }
        )
        + "\n"
    )
    # Minimal agg_trade so exact_ok can be true or false; allow_start_without_exact
    (repo / "data/raw_market_events_v2/agg_trade").mkdir(parents=True)
    shadow = repo / "data/trading/shadow_structural_protection"
    shadow.mkdir(parents=True)
    (shadow / "virtual_positions.jsonl").write_text(
        json.dumps(
            {
                "virtual_position_id": "vpos_BASELINE_CANONICAL_pos_test_1",
                "policy_id": "BASELINE_CANONICAL",
                "candidate_id": f"{EXPECTED_EPOCH}|pos_test_1|fill_x",
                "position_id": "pos_test_1",
                "timeframe": "M15",
                "side": "LONG",
                "status": "OPEN",
                "entry_timestamp": "2026-07-29T18:39:54Z",
                "entry_executable_price": 64100.0,
                "structural_stop_price": 63500.0,
                "structural_take_price": 65000.0,
                "quantity": 1.0,
                "notional_usd": 64100.0,
                "risk_budget_usd": 1000.0,
                "policy_manifest_fingerprint": "testfp",
                "research_valid": True,
                "invalidated": False,
            }
        )
        + "\n"
    )
    (shadow / "checkpoint.json").write_text(
        json.dumps(
            {
                "processed_candidates": [],
                "processed_closes": ["trd_test_1"],
                "stp11_migrated": True,
                "research_valid": True,
                "baseline_match_count": 0,
                "baseline_divergence_count": 0,
                "lookahead_violation_count": 0,
                "write_boundary_violation_count": 0,
                "insufficient_causal_data_count": 0,
            }
        )
        + "\n"
    )
    for name in (
        "policy_decisions",
        "candidate_snapshots",
        "virtual_trades",
        "economic_outcomes",
        "volume_zones",
        "volume_profiles",
        "source_candles",
        "causal_market_snapshots",
    ):
        (shadow / f"{name}.jsonl").write_text("", encoding="utf-8")

    eng = StructuralProtectionEngine(
        repo=repo,
        shadow_dir=shadow,
        strict_epoch=True,
        allow_start_without_exact=True,
    )
    # Force open index + repair using the seeded OPEN row under eng.manifest_fp
    # Seeded fingerprint may differ; patch open index directly then repair.
    eng.open_by_policy["BASELINE_CANONICAL"] = [
        {
            "virtual_position_id": "vpos_BASELINE_CANONICAL_pos_test_1",
            "policy_id": "BASELINE_CANONICAL",
            "position_id": "pos_test_1",
            "status": "OPEN",
            "policy_manifest_fingerprint": eng.manifest_fp,
            "research_valid": True,
        }
    ]
    eng.processed_closes.add("trd_test_1")
    eng._repair_stale_processed_closes()
    assert "trd_test_1" not in eng.processed_closes
