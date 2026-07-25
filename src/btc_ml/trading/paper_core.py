"""Canonical shared paper execution core (S4.1).

Single implementation rule: sizing / fees / slippage / P&L / stop-take / exit
preview / point-in-time fill guard all come from the already-proven paper
controller stack:

    scripts/live/paper_trade_economics.py                     (economics math)
    scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py
                                                              (exit preview, fill guard, ledger columns)

This module does NOT reimplement any of that math. It only re-exports the
canonical callables so that the legacy controller and the four timeframe
traders provably share one implementation.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
LIVE_SCRIPTS = ROOT / "scripts" / "live"

if str(LIVE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LIVE_SCRIPTS))

economics = importlib.import_module("paper_trade_economics")
legacy_controller = importlib.import_module(
    "bounded_paper_trading_controller_auto_ledger_no_real_execution"
)

# --- canonical economics constants (never redefined here) --------------------
INITIAL_CAPITAL_USD: float = economics.INITIAL_CAPITAL_USD
MAX_RISK_PER_TRADE_PCT: float = economics.MAX_RISK_PER_TRADE_PCT
MAX_RISK_USD: float = economics.MAX_RISK_USD
STOP_LOSS_BPS: float = economics.STOP_LOSS_BPS
TAKE_PROFIT_BPS: float = economics.TAKE_PROFIT_BPS
ENTRY_FEE_BPS: float = economics.ENTRY_FEE_BPS
EXIT_FEE_BPS: float = economics.EXIT_FEE_BPS
NORMAL_ENTRY_SLIPPAGE_BPS: float = economics.NORMAL_ENTRY_SLIPPAGE_BPS
NORMAL_EXIT_SLIPPAGE_BPS: float = economics.NORMAL_EXIT_SLIPPAGE_BPS
STOP_FORCED_EXIT_SLIPPAGE_BPS: float = economics.STOP_FORCED_EXIT_SLIPPAGE_BPS
SIZING_METHOD: str = economics.SIZING_METHOD
POSITION_SIZING_MODE: str = economics.POSITION_SIZING_MODE
ECONOMICS_SOURCE: str = economics.ECONOMICS_SOURCE

# --- canonical execution callables ------------------------------------------
stop_take_prices = economics.stop_take_prices
stop_distance = economics.stop_distance
resolve_risk_sizing = economics.resolve_risk_sizing
closed_trade_economics = economics.closed_trade_economics
execution_quality_status = economics.execution_quality_status
exit_slippage_bps_for_execution = economics.exit_slippage_bps_for_execution
safe_float = economics.safe_float
bps_to_rate = economics.bps_to_rate

evaluate_exit_preview = legacy_controller.evaluate_exit_preview
resolve_entry_risk_sizing = legacy_controller.resolve_entry_risk_sizing
sizing_metadata = legacy_controller.sizing_metadata
compute_stop_take = legacy_controller.compute_stop_take
make_id = legacy_controller.make_id
metadata_json = legacy_controller._metadata_json
ts_iso = legacy_controller._ts_iso
fill_after_decision_ok = legacy_controller._fill_after_decision_ok

# --- canonical ledger column contracts --------------------------------------
SIGNAL_COLUMNS: list[str] = list(legacy_controller.SIGNAL_COLUMNS)
ORDER_COLUMNS: list[str] = list(legacy_controller.ORDER_COLUMNS)
TRADE_COLUMNS: list[str] = list(legacy_controller.TRADE_COLUMNS)
POSITION_COLUMNS: list[str] = list(legacy_controller.POSITION_COLUMNS)

APPROVAL_PHRASE: str = legacy_controller.APPROVAL_PHRASE
PAPER_CONTEXT_HOLD_MODE: str = legacy_controller.PAPER_CONTEXT_HOLD_MODE
CONTEXT_EXIT_LIFECYCLES = set(legacy_controller.CONTEXT_EXIT_LIFECYCLES)

CORE_VERSION = "shared_paper_execution_core_v1"
CORE_SOURCES = (
    "scripts/live/paper_trade_economics.py",
    "scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py",
)


def core_fingerprint() -> dict[str, Any]:
    """Identity of the shared execution core (used by tests / proofs)."""
    return {
        "core_version": CORE_VERSION,
        "sources": list(CORE_SOURCES),
        "economics_source": ECONOMICS_SOURCE,
        "sizing_method": SIZING_METHOD,
        "initial_capital_usd": INITIAL_CAPITAL_USD,
        "max_risk_usd": MAX_RISK_USD,
        "entry_fee_bps": ENTRY_FEE_BPS,
        "exit_fee_bps": EXIT_FEE_BPS,
        "normal_entry_slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "normal_exit_slippage_bps": NORMAL_EXIT_SLIPPAGE_BPS,
        "stop_forced_exit_slippage_bps": STOP_FORCED_EXIT_SLIPPAGE_BPS,
        "stop_loss_bps": STOP_LOSS_BPS,
        "take_profit_bps": TAKE_PROFIT_BPS,
        "execution_enabled": False,
        "exchange_enabled": False,
    }


__all__ = [name for name in globals() if not name.startswith("_")]
