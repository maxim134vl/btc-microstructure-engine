#!/usr/bin/env python3
"""Pre-start paper-only guard for VPS paper-manager.

Writes /app/data/deployment/paper_only_contract.json
Exits non-zero on any safety violation. Never enables real execution.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")).resolve()
DATA_ROOT = (REPO / "data").resolve()
CONTRACT_PATH = DATA_ROOT / "deployment" / "paper_only_contract.json"

FORBIDDEN_ENV = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "EXCHANGE_API_KEY",
    "EXCHANGE_API_SECRET",
    "API_SECRET",
    "API_KEY_SECRET",
    "TRADING_API_KEY",
    "TRADING_API_SECRET",
    "HL_TESTNET_AGENT_PK",
    "HL_MAINNET_AGENT_PK",
    "HL_AGENT_PK",
    "HL_MASTER_PK",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fail(reason: str, *, details: dict | None = None) -> int:
    payload = {
        "status": "FAILED",
        "checked_at": _utc(),
        "paper_only": True,
        "real_execution_enabled": False,
        "reason": reason,
        "details": details or {},
        "data_root": str(DATA_ROOT),
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"error": reason, "details": details or {}}), flush=True)
    return 1


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO))

    if not DATA_ROOT.is_dir():
        return _fail("data_root_missing", details={"path": str(DATA_ROOT)})

    # Refuse host Mac live data path leakage
    if "/Users/fontecrypto/btc-ml/data" in str(DATA_ROOT):
        return _fail("forbidden_host_live_data_root", details={"path": str(DATA_ROOT)})

    present_creds = [k for k in FORBIDDEN_ENV if os.environ.get(k)]
    if present_creds:
        return _fail("live_execution_credentials_present", details={"vars": present_creds})

    cfg_path = REPO / "config" / "intrabar_paper_execution.json"
    if not cfg_path.is_file():
        return _fail("missing_trading_config", details={"path": str(cfg_path)})

    try:
        from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
        from btc_ml.trading.intrabar_paper.epoch import load_active_epoch
    except Exception as exc:  # noqa: BLE001
        return _fail("import_failure", details={"error": str(exc)})

    try:
        cfg = load_intrabar_paper_config(repo_root=REPO)
    except Exception as exc:  # noqa: BLE001
        return _fail("config_load_failure", details={"error": str(exc)})

    if not cfg.paper_only:
        return _fail("paper_only_false_in_config")
    if cfg.real_execution_enabled:
        return _fail("real_execution_enabled_true_in_config")

    # Paths must resolve under /app/data
    for label, path in (
        ("books_root", cfg.books_root),
        ("epochs_root", cfg.epochs_root),
        ("context_journal_root", cfg.context_journal_root),
    ):
        try:
            resolved = path.resolve()
            resolved.relative_to(DATA_ROOT)
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "path_escapes_data_root",
                details={"field": label, "path": str(path), "error": str(exc)},
            )

    epoch = load_active_epoch(cfg.epochs_root)
    if epoch is None or epoch.epoch_status != "ACTIVE":
        return _fail(
            "no_active_paper_epoch",
            details={"epoch": None if epoch is None else epoch.to_dict()},
        )

    active_path = cfg.epochs_root / "active.json"
    try:
        active_path.resolve().relative_to(DATA_ROOT)
    except Exception:
        return _fail("active_epoch_outside_data_root", details={"path": str(active_path)})

    active_raw = json.loads(active_path.read_text(encoding="utf-8"))
    fingerprint = active_raw.get("trading_contract_fingerprint")
    if not fingerprint:
        return _fail("missing_trading_contract_fingerprint_on_active_epoch")

    # Optional operator env mirrors (not sole authority)
    env_paper = os.environ.get("PAPER_ONLY", "true").strip().lower()
    env_real = os.environ.get("REAL_EXECUTION_ENABLED", "false").strip().lower()
    env_exec = os.environ.get("EXECUTION_ENABLED", "false").strip().lower()
    if env_paper not in {"1", "true", "yes"}:
        return _fail("PAPER_ONLY_env_not_true", details={"value": env_paper})
    if env_real in {"1", "true", "yes"}:
        return _fail("REAL_EXECUTION_ENABLED_env_true")
    if env_exec in {"1", "true", "yes"}:
        return _fail("EXECUTION_ENABLED_env_true")

    payload = {
        "status": "PASSED",
        "checked_at": _utc(),
        "paper_only": True,
        "real_execution_enabled": False,
        "execution_enabled": False,
        "paper_epoch_id": epoch.paper_epoch_id,
        "trading_contract_fingerprint": fingerprint,
        "data_root": str(DATA_ROOT),
        "books_root": str(cfg.books_root),
        "epochs_root": str(cfg.epochs_root),
        "deployment_tag": os.environ.get("VPS_DEPLOYMENT_TAG", "VPS_DEPLOY"),
        "reason": "ok",
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASSED", "paper_epoch_id": epoch.paper_epoch_id}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
