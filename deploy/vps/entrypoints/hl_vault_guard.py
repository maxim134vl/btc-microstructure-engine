#!/usr/bin/env python3
"""Pre-start guard for the Hyperliquid vault executor. Isolated from paper-only."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")).resolve()
CONTRACT_PATH = REPO / "data" / "deployment" / "hl_vault_contract.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fail(reason: str, *, details: dict | None = None) -> int:
    payload = {"status": "FAILED", "checked_at": _utc(), "reason": reason, "details": details or {}}
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"error": reason, "details": details or {}}), flush=True)
    return 1


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO))
    cfg_path = Path(os.environ.get("HL_VAULT_CONFIG") or (REPO / "config" / "hl_vault_testnet.json"))
    try:
        from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config
        from btc_ml.trading.hyperliquid_vault.constants import ENV_AGENT_PK, ENV_MAINNET_AGENT_PK
    except Exception as exc:  # noqa: BLE001
        return _fail("import_failure", details={"error": str(exc)})
    try:
        cfg = load_hl_vault_config(cfg_path, repo_root=REPO)
    except Exception as exc:  # noqa: BLE001
        return _fail("config_load_failure", details={"error": str(exc)})
    if cfg.is_mainnet and os.environ.get("HL_MAINNET_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return _fail("mainnet_not_explicitly_enabled")
    if not cfg.vault_address:
        if os.environ.get("HL_VAULT_FAKE") in {"1", "true", "yes"}:
            pass
        else:
            return _fail("missing_vault_address")
    env_key = ENV_MAINNET_AGENT_PK if cfg.is_mainnet else ENV_AGENT_PK
    if not os.environ.get(env_key) and not os.environ.get("HL_AGENT_PK"):
        if os.environ.get("HL_VAULT_FAKE") in {"1", "true", "yes"}:
            pass
        else:
            return _fail("missing_agent_key", details={"env": env_key})
    if os.environ.get("HL_MASTER_PK"):
        return _fail("master_key_forbidden_on_executor")
    payload = {
        "status": "PASSED",
        "checked_at": _utc(),
        "network": cfg.network,
        "vault_address": cfg.vault_address,
        "reason": "ok",
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASSED", "network": cfg.network}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
