#!/usr/bin/env python3
"""Safely activate PER_TF_EQUITY_1PCT_V1 sleeves epoch (TRD-SLEEVE2).

Stops only LIVE1B, switches active epoch when flat, restarts LIVE1B.
Never restarts LIVE1A / feeds / OPS.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.intrabar_paper.books import EpochBooks  # noqa: E402
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.epoch import (  # noqa: E402
    PaperEpoch,
    activate_epoch,
    load_active_epoch,
    mark_epoch_status,
)
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger  # noqa: E402
from btc_ml.trading.intrabar_paper.trading_contract import (  # noqa: E402
    CANONICAL_SOURCE_EPOCH,
    EPOCH_PREFIX_SLEEVE2,
    EXPECTED_SOURCE_FINGERPRINT,
    SLEEVE2_ACTIVE,
    SLEEVE2_AWAITING_FLAT,
    SLEEVE2_FREEZE,
    SLEEVE2_SOURCE_MISMATCH,
    assert_source_fingerprint,
    build_trading_contract_manifest,
    clone_trading_epoch_contract,
    sleeve2_capital_overrides,
    validate_sleeve2_contract_diff,
)

CTL = REPO / "scripts" / "live" / "intrabar_paper_ctl.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run_ctl(action: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(CTL), action],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out) if out else {"raw": out}
    except json.JSONDecodeError:
        payload = {"raw": out, "stderr": proc.stderr}
    payload["_returncode"] = proc.returncode
    return payload


def evaluate_flat_state(*, paper_epoch_id: str, repo_root: Path = REPO) -> dict[str, Any]:
    books = repo_root / "data" / "trading" / "intrabar_paper" / paper_epoch_id / "books"
    eb = EpochBooks(books, paper_epoch_id=paper_epoch_id)
    opens = eb.open_positions()
    pending_orders = [
        o
        for o in eb.read_all("orders")
        if str(o.get("status") or "").upper() not in {"FILLED", "CANCELLED", "DONE", "REJECTED"}
    ]
    # LIVE1B writes signal→fill atomically; incomplete = order not FILLED.
    pending_fills = 0
    pending_commands = 0
    incomplete = len(pending_orders)
    blockers: list[dict[str, Any]] = []
    for p in opens:
        blockers.append(
            {
                "type": "OPEN_POSITION",
                "timeframe": p.get("timeframe"),
                "position_id": p.get("position_id"),
                "side": p.get("side"),
                "entry": p.get("entry_price"),
                "stop": p.get("stop_loss_price"),
                "take": p.get("take_profit_price"),
                "risk_amount_usd": p.get("risk_amount_usd"),
                "status": p.get("status"),
            }
        )
    for o in pending_orders:
        blockers.append({"type": "PENDING_ORDER", "order_id": o.get("order_id"), "status": o.get("status")})
    flat = not opens and not pending_orders and incomplete == 0
    return {
        "flat": flat,
        "open_positions": len(opens),
        "pending_signals": 0,
        "pending_commands": pending_commands,
        "pending_orders": len(pending_orders),
        "pending_fills": pending_fills,
        "incomplete_transactions": incomplete,
        "blockers": blockers,
        "opens": opens,
    }


def prepare_or_activate(*, execute: bool, force_await: bool = False) -> dict[str, Any]:
    cfg = load_intrabar_paper_config(repo_root=REPO)
    active = load_active_epoch(cfg.epochs_root)
    if active is None:
        return {"status": "NO_ACTIVE_EPOCH"}
    source_id = active.paper_epoch_id
    if source_id != CANONICAL_SOURCE_EPOCH and not source_id.startswith(EPOCH_PREFIX_SLEEVE2):
        # Allow only cloning from the proven parent.
        pass

    source_manifest = build_trading_contract_manifest(source_id, repo_root=REPO)
    try:
        source_fp = assert_source_fingerprint(source_manifest)
    except RuntimeError as exc:
        return {"status": SLEEVE2_SOURCE_MISMATCH, "error": str(exc)}

    flat = evaluate_flat_state(paper_epoch_id=source_id, repo_root=REPO)
    live1b = _run_ctl("status")
    live1b_alive = bool(live1b.get("alive"))

    report: dict[str, Any] = {
        "audit_timestamp_utc": _utc(),
        "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "active_paper_epoch": source_id,
        "live1b": {"pid": live1b.get("pid"), "alive": live1b_alive},
        "paper_only": True,
        "real_execution": False,
        "flat_state": flat,
        "source_fingerprint": source_fp,
        "expected_source_fingerprint": EXPECTED_SOURCE_FINGERPRINT,
    }

    if force_await or not flat["flat"]:
        report["status"] = SLEEVE2_AWAITING_FLAT
        report["blocking_objects"] = flat["blockers"]
        return report

    if not execute:
        # Dry-run clone proof only.
        new_id = f"{EPOCH_PREFIX_SLEEVE2}DRYRUN_{_stamp()}"
        clone = clone_trading_epoch_contract(
            source_id,
            new_id,
            sleeve2_capital_overrides(),
            repo_root=REPO,
            output_root=REPO / "tmp" / "trading_contract_clones",
            source_manifest=source_manifest,
        )
        validate_sleeve2_contract_diff(clone.diff)
        report["status"] = "TRD_SLEEVE2_DRY_RUN_READY"
        report["new_epoch_id"] = new_id
        report["parent_fingerprint"] = clone.source_fingerprint
        report["new_fingerprint"] = clone.fingerprint
        report["contract_diff"] = clone.diff
        return report

    # --- Activation sequence ---
    stop = _run_ctl("stop")
    report["live1b_stop"] = stop
    time.sleep(0.5)
    flat2 = evaluate_flat_state(paper_epoch_id=source_id, repo_root=REPO)
    report["flat_state_after_stop"] = flat2
    if not flat2["flat"]:
        # Restart old LIVE1B; do not switch epoch.
        start = _run_ctl("start")
        report["status"] = SLEEVE2_AWAITING_FLAT
        report["live1b_restart_old"] = start
        report["blocking_objects"] = flat2["blockers"]
        return report

    new_id = f"{EPOCH_PREFIX_SLEEVE2}{_stamp()}"
    clone = clone_trading_epoch_contract(
        source_id,
        new_id,
        sleeve2_capital_overrides(),
        repo_root=REPO,
        output_root=cfg.epochs_root,
        source_manifest=source_manifest,
    )
    try:
        validate_sleeve2_contract_diff(clone.diff)
    except RuntimeError as exc:
        _run_ctl("start")
        return {"status": str(exc).split(":")[0], "error": str(exc), **report}

    # Persist epoch record + books + sleeves + contract.
    epoch_root = cfg.books_root / new_id
    books_dir = epoch_root / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    for name in EpochBooks.TABLES:
        (books_dir / f"{name}.jsonl").touch(exist_ok=True)

    contract_path = epoch_root / "trading_contract.json"
    contract_payload = {
        "trading_contract_manifest": clone.manifest,
        "trading_contract_fingerprint": clone.fingerprint,
        "parent_epoch_id": source_id,
        "parent_trading_contract_fingerprint": clone.source_fingerprint,
        "allowlisted_contract_diff": clone.diff,
        "source_commit": report["head"],
        "activated_at": _utc(),
        "paper_only": True,
        "real_execution": False,
    }
    contract_path.write_text(json.dumps(contract_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    SleeveLedger.initialize(
        epoch_id=new_id,
        epoch_root=epoch_root,
        initial_equity_usd=100_000.0,
        risk_pct_per_trade=1.0,
    )

    epoch = PaperEpoch(
        paper_epoch_id=new_id,
        epoch_status="CREATED",
        created_at=_utc(),
        activated_at=None,
        closed_at=None,
        initial_equity_usd=400_000.0,
        rule_contract_version="INTRABAR_RULES_V1",
    )
    # Enrich on-disk record beyond PaperEpoch dataclass.
    epoch_path = cfg.epochs_root / f"{new_id}.json"
    epoch_doc = {
        **epoch.to_dict(),
        "parent_epoch_id": source_id,
        "parent_trading_contract_fingerprint": clone.source_fingerprint,
        "trading_contract_fingerprint": clone.fingerprint,
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": 400_000.0,
        "timeframe_initial_equity_usd": {
            "M15": 100000.0,
            "M30": 100000.0,
            "H1": 100000.0,
            "H4": 100000.0,
        },
        "allowlisted_contract_diff": clone.diff,
        "source_commit": report["head"],
        "paper_only": True,
        "real_execution": False,
        "trading_contract_path": str(contract_path.relative_to(REPO)),
    }
    epoch_path.write_text(json.dumps(epoch_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Close parent identity (history preserved; books untouched).
    mark_epoch_status(active, epochs_root=cfg.epochs_root, status="CLOSED")
    activate_epoch(epoch, epochs_root=cfg.epochs_root)
    # Rewrite active.json with enriched fields.
    active_doc = {
        **epoch.to_dict(),
        "epoch_status": "ACTIVE",
        "activated_at": _utc(),
        "parent_epoch_id": source_id,
        "parent_trading_contract_fingerprint": clone.source_fingerprint,
        "trading_contract_fingerprint": clone.fingerprint,
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": 400_000.0,
        "paper_only": True,
        "real_execution": False,
    }
    (cfg.epochs_root / "active.json").write_text(
        json.dumps(active_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    epoch_path.write_text(json.dumps({**epoch_doc, **active_doc}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    start = _run_ctl("start")
    report["live1b_start"] = start
    time.sleep(1.5)
    status = _run_ctl("status")
    health = status.get("health") or {}
    # Freeze if unexpected trading objects already appeared (should be empty).
    new_flat = evaluate_flat_state(paper_epoch_id=new_id, repo_root=REPO)
    if (
        int(health.get("signals_count") or 0) > 0
        or int(health.get("orders_count") or 0) > 0
        or int(health.get("fills_count") or 0) > 0
        or new_flat["open_positions"] > 0
    ):
        # New epoch already traded — freeze, do not auto-rollback.
        _run_ctl("stop")
        report["status"] = SLEEVE2_FREEZE
        report["new_epoch_id"] = new_id
        report["health"] = health
        return report

    ok = (
        bool(status.get("alive"))
        and health.get("paper_only") is True
        and health.get("real_execution_enabled") is False
        and str(health.get("paper_epoch_id")) == new_id
        and float(health.get("master_initial_equity_usd") or 0) == 400000.0
    )
    report.update(
        {
            "status": SLEEVE2_ACTIVE if ok else "TRD_SLEEVE2_ACTIVATION_VERIFY_FAILED",
            "old_epoch_id": source_id,
            "new_epoch_id": new_id,
            "parent_fingerprint": clone.source_fingerprint,
            "new_fingerprint": clone.fingerprint,
            "contract_diff": clone.diff,
            "live1b_status": status,
            "sleeves": health.get("sleeves"),
            "master": {
                "master_initial_equity_usd": health.get("master_initial_equity_usd"),
                "master_current_equity_usd": health.get("master_current_equity_usd"),
                "master_risk_capacity_usd": health.get("master_risk_capacity_usd"),
                "master_open_risk_usd": health.get("master_open_risk_usd"),
                "master_available_risk_usd": health.get("master_available_risk_usd"),
            },
        }
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true", help="Perform LIVE1B stop/switch/start")
    ap.add_argument("--force-await", action="store_true", help="Force AWAITING_FLAT without activating")
    args = ap.parse_args()
    result = prepare_or_activate(execute=bool(args.execute), force_await=bool(args.force_await))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    status = str(result.get("status") or "")
    if status in {SLEEVE2_ACTIVE, "TRD_SLEEVE2_DRY_RUN_READY"}:
        return 0
    if status == SLEEVE2_AWAITING_FLAT:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
