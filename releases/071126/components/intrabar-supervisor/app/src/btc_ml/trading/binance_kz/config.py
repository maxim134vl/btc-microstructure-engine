"""Fail-closed Binance KZ config. Live PAPI is the only trade host."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    ALLOWED_ACCOUNT_MODES,
    ALLOWED_NETWORKS,
    ALLOWED_TIMEFRAMES,
    ENV_API_KEY,
    ENV_API_SECRET,
    ENV_ED25519_KEY_PATH,
    ENV_LIVE_ENABLED,
    FAPI_PUBLIC_WS_URL,
    FAPI_REST_URL,
    KILL_UNIMMR,
    LEVERAGE,
    LEVERAGE_CAP,
    MAX_BBO_AGE_MS,
    MIN_UNIMMR_OPEN,
    PAPI_REST_URL,
    PAPI_USER_WS_URL,
    RISK_PCT,
    SCHEMA_VERSION,
    SYMBOL,
)


class BinanceKzConfigError(ValueError):
    """Invalid or unsafe Binance KZ config."""


@dataclass(frozen=True)
class BinanceKzConfig:
    schema_version: str
    network: str
    account_mode: str
    real_execution_enabled: bool
    symbol: str
    timeframes: tuple[str, ...]
    leverage: int
    stop_loss_bps: float
    take_profit_bps: float
    ioc_slippage_bps: float
    max_risk_per_trade_pct: float
    min_unimmr_open: float
    kill_unimmr: float
    max_bbo_age_ms: float
    max_consecutive_exchange_errors: int
    qty_step: float
    tick_size: float
    command_bus: str
    s41_consume_commands_after: str | None
    books_root: Path
    paper_books_root: Path
    paper_epochs_root: Path
    kill_flag_path: Path
    papi_url: str
    fapi_url: str
    user_ws_url: str
    public_ws_url: str
    raw: dict[str, Any]

    @property
    def live_armed(self) -> bool:
        return bool(self.real_execution_enabled)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def live_explicitly_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get(ENV_LIVE_ENABLED, "")).strip().lower() in {"1", "true", "yes"}


def _norm_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def load_binance_kz_config(
    path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> BinanceKzConfig:
    root = repo_root or _repo_root()
    env = environ if environ is not None else dict(os.environ)
    cfg_path = Path(path) if path else root / "config" / "binance_kz_live.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    network = str(raw.get("network") or "").strip().lower()
    if network not in ALLOWED_NETWORKS:
        raise BinanceKzConfigError(f"unsupported network={network!r}")
    account_mode = str(raw.get("account_mode") or "").strip().lower()
    if account_mode not in ALLOWED_ACCOUNT_MODES:
        raise BinanceKzConfigError(f"unsupported account_mode={account_mode!r}")
    papi_url = _norm_url(str(raw.get("papi_url") or PAPI_REST_URL))
    fapi_url = _norm_url(str(raw.get("fapi_url") or FAPI_REST_URL))
    if papi_url != PAPI_REST_URL:
        raise BinanceKzConfigError(f"papi_url must be {PAPI_REST_URL}, got {papi_url}")
    if fapi_url != FAPI_REST_URL:
        raise BinanceKzConfigError(f"fapi_url must be {FAPI_REST_URL}, got {fapi_url}")
    if "fapi.binance.com" in papi_url:
        raise BinanceKzConfigError("papi_url must not point at fapi")
    leverage = int(raw.get("leverage") or 0)
    if leverage != LEVERAGE or leverage > LEVERAGE_CAP:
        raise BinanceKzConfigError(f"leverage must be {LEVERAGE}, got {leverage}")
    timeframes = tuple(str(x).upper() for x in (raw.get("timeframes") or ALLOWED_TIMEFRAMES))
    if timeframes != ALLOWED_TIMEFRAMES:
        raise BinanceKzConfigError(f"timeframes must be {ALLOWED_TIMEFRAMES}, got {timeframes}")
    symbol = str(raw.get("symbol") or SYMBOL).upper()
    if symbol != SYMBOL:
        raise BinanceKzConfigError(f"symbol must be {SYMBOL}")
    risk_pct = float(raw.get("max_risk_per_trade_pct") if raw.get("max_risk_per_trade_pct") is not None else RISK_PCT)
    if abs(risk_pct - RISK_PCT) > 1e-9:
        raise BinanceKzConfigError(f"max_risk_per_trade_pct must be {RISK_PCT}")
    real = bool(raw.get("real_execution_enabled", False))
    if real and not live_explicitly_enabled(env):
        raise BinanceKzConfigError(
            f"live config refused: set {ENV_LIVE_ENABLED}=true to arm real execution"
        )
    books_root = (root / str(raw.get("books_root") or "data/trading/binance_kz")).resolve()
    paper_books = (root / str(raw.get("paper_books_root") or "data/trading/intrabar_paper")).resolve()
    if books_root == paper_books or paper_books in books_root.parents or books_root in paper_books.parents:
        raise BinanceKzConfigError("books_root must not share LIVE1B paper books")
    after = raw.get("s41_consume_commands_after")
    kill_rel = str(raw.get("kill_flag_relpath") or "data/trading/binance_kz/KILL")
    return BinanceKzConfig(
        schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
        network=network,
        account_mode=account_mode,
        real_execution_enabled=real,
        symbol=symbol,
        timeframes=timeframes,
        leverage=leverage,
        stop_loss_bps=float(raw.get("stop_loss_bps") or 100.0),
        take_profit_bps=float(raw.get("take_profit_bps") or 150.0),
        ioc_slippage_bps=float(raw.get("ioc_slippage_bps") or 10.0),
        max_risk_per_trade_pct=risk_pct,
        min_unimmr_open=float(raw.get("min_unimmr_open") if raw.get("min_unimmr_open") is not None else MIN_UNIMMR_OPEN),
        kill_unimmr=float(raw.get("kill_unimmr") if raw.get("kill_unimmr") is not None else KILL_UNIMMR),
        max_bbo_age_ms=float(raw.get("max_bbo_age_ms") if raw.get("max_bbo_age_ms") is not None else MAX_BBO_AGE_MS),
        max_consecutive_exchange_errors=int(raw.get("max_consecutive_exchange_errors") or 5),
        qty_step=float(raw.get("qty_step") or 0.001),
        tick_size=float(raw.get("tick_size") or 0.1),
        command_bus=str(raw.get("command_bus") or "production").strip().lower(),
        s41_consume_commands_after=None if after in (None, "") else str(after),
        books_root=books_root,
        paper_books_root=paper_books,
        paper_epochs_root=(root / str(raw.get("paper_epochs_root") or "data/trading/paper_epochs")).resolve(),
        kill_flag_path=(root / kill_rel).resolve(),
        papi_url=papi_url,
        fapi_url=fapi_url,
        user_ws_url=_norm_url(str(raw.get("user_ws_url") or PAPI_USER_WS_URL)),
        public_ws_url=_norm_url(str(raw.get("public_ws_url") or FAPI_PUBLIC_WS_URL)),
        raw=raw,
    )


def credentials_from_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = environ if environ is not None else dict(os.environ)
    out: dict[str, str] = {}
    key = str(env.get(ENV_API_KEY) or "").strip()
    secret = str(env.get(ENV_API_SECRET) or "").strip()
    pem = str(env.get(ENV_ED25519_KEY_PATH) or "").strip()
    if key:
        out["api_key"] = key
    if secret:
        out["api_secret"] = secret
    if pem:
        out["ed25519_key_path"] = pem
    return out
