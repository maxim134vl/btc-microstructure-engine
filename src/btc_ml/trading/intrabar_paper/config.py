"""Explicit LIVE1B paper execution configuration (no hidden defaults)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntrabarPaperConfig:
    schema_version: str
    rule_contract_version: str
    paper_only: bool
    real_execution_enabled: bool
    initial_equity_usd: float
    max_risk_per_trade_pct: float
    max_risk_per_trade_usd: float
    cost_aware_stop_sizing: bool
    fixed_notional: bool
    stop_loss_bps: float
    take_profit_bps: float
    entry_fee_bps: float
    exit_fee_bps: float
    entry_slippage_bps: float
    exit_slippage_bps: float
    stop_exit_slippage_bps: float
    max_bbo_age_ms: float
    max_entry_signal_age_seconds: float
    max_open_positions_per_timeframe: int
    timeframes: tuple[str, ...]
    context_journal_root: Path
    books_root: Path
    epochs_root: Path
    economics_source: str
    raw: dict[str, Any]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def load_intrabar_paper_config(
    path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
) -> IntrabarPaperConfig:
    root = repo_root or _repo_root()
    cfg_path = Path(path) if path else root / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    required = (
        "max_bbo_age_ms",
        "max_entry_signal_age_seconds",
        "initial_equity_usd",
        "max_risk_per_trade_usd",
        "entry_fee_bps",
        "exit_fee_bps",
        "entry_slippage_bps",
        "exit_slippage_bps",
        "stop_loss_bps",
        "take_profit_bps",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"intrabar_paper_execution.json missing required keys: {missing}")
    if bool(raw.get("real_execution_enabled", False)):
        raise ValueError("real_execution_enabled must be false for LIVE1B paper-only activation")
    return IntrabarPaperConfig(
        schema_version=str(raw["schema_version"]),
        rule_contract_version=str(raw["rule_contract_version"]),
        paper_only=bool(raw.get("paper_only", True)),
        real_execution_enabled=bool(raw.get("real_execution_enabled", False)),
        initial_equity_usd=float(raw["initial_equity_usd"]),
        max_risk_per_trade_pct=float(raw["max_risk_per_trade_pct"]),
        max_risk_per_trade_usd=float(raw["max_risk_per_trade_usd"]),
        cost_aware_stop_sizing=bool(raw["cost_aware_stop_sizing"]),
        fixed_notional=bool(raw["fixed_notional"]),
        stop_loss_bps=float(raw["stop_loss_bps"]),
        take_profit_bps=float(raw["take_profit_bps"]),
        entry_fee_bps=float(raw["entry_fee_bps"]),
        exit_fee_bps=float(raw["exit_fee_bps"]),
        entry_slippage_bps=float(raw["entry_slippage_bps"]),
        exit_slippage_bps=float(raw["exit_slippage_bps"]),
        stop_exit_slippage_bps=float(raw["stop_exit_slippage_bps"]),
        max_bbo_age_ms=float(raw["max_bbo_age_ms"]),
        max_entry_signal_age_seconds=float(raw["max_entry_signal_age_seconds"]),
        max_open_positions_per_timeframe=int(raw["max_open_positions_per_timeframe"]),
        timeframes=tuple(str(x) for x in raw["timeframes"]),
        context_journal_root=(root / str(raw["context_journal_root"])).resolve(),
        books_root=(root / str(raw["books_root"])).resolve(),
        epochs_root=(root / str(raw["epochs_root"])).resolve(),
        economics_source=str(raw.get("economics_source", "canonical_paper_trade_economics_v1")),
        raw=raw,
    )
