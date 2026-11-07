"""Pre-start safety contract for the Binance KZ executor. Isolated from paper-only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BinanceKzConfigError, credentials_from_env, load_binance_kz_config, live_explicitly_enabled
from .constants import ENV_API_KEY, ENV_ED25519_KEY_PATH, LEVERAGE, PAPI_REST_URL


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_contract(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate_start(
    *,
    config_path: Path | None = None,
    repo_root: Path | None = None,
    environ: dict[str, str] | None = None,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(environ or {})
    try:
        cfg = load_binance_kz_config(config_path, repo_root=repo_root, environ=env)
    except BinanceKzConfigError as exc:
        return {"status": "FAILED", "checked_at": _utc(), "reason": str(exc), "real_execution_enabled": False}
    if cfg.leverage != LEVERAGE:
        return {"status": "FAILED", "checked_at": _utc(), "reason": "leverage_not_2"}
    if cfg.papi_url != PAPI_REST_URL:
        return {"status": "FAILED", "checked_at": _utc(), "reason": "papi_host_mismatch"}
    if cfg.books_root == cfg.paper_books_root:
        return {"status": "FAILED", "checked_at": _utc(), "reason": "paper_books_collision"}
    if cfg.real_execution_enabled:
        if not live_explicitly_enabled(env):
            return {"status": "FAILED", "checked_at": _utc(), "reason": "live_not_explicitly_enabled"}
        creds = credentials_from_env(env)
        if not creds.get("api_key"):
            return {"status": "FAILED", "checked_at": _utc(), "reason": "missing_api_key", "env": ENV_API_KEY}
        if not creds.get("api_secret") and not creds.get("ed25519_key_path"):
            return {"status": "FAILED", "checked_at": _utc(), "reason": "missing_signing_material", "env": ENV_ED25519_KEY_PATH}
    payload = {
        "status": "PASSED",
        "checked_at": _utc(),
        "reason": "ok",
        "network": cfg.network,
        "account_mode": cfg.account_mode,
        "real_execution_enabled": cfg.real_execution_enabled,
        "live_armed": bool(cfg.real_execution_enabled and live_explicitly_enabled(env)),
        "symbol": cfg.symbol,
        "timeframes": list(cfg.timeframes),
        "leverage": cfg.leverage,
        "papi_url": cfg.papi_url,
        "books_root": str(cfg.books_root),
    }
    if contract_path is not None:
        write_contract(contract_path, payload)
    return payload
