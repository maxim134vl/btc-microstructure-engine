"""Venue-side kill switch. Flatten + refuse new opens until reset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import account_value_usd, margin_used_usd
from .config import HlVaultConfig
from .ledger import utc_now


@dataclass(frozen=True)
class KillDecision:
    tripped: bool
    reason: str | None
    flatten: bool


def kill_flag_present(path: Path) -> bool:
    return Path(path).is_file()


def evaluate_kill(
    *,
    cfg: HlVaultConfig,
    user_state: dict[str, Any] | None,
    consecutive_errors: int,
    already_tripped: bool,
    flag_present: bool,
    kill_switch_tested: bool = False,
) -> KillDecision:
    _ = kill_switch_tested
    if already_tripped:
        return KillDecision(True, "ALREADY_TRIPPED", False)
    if flag_present:
        return KillDecision(True, "KILL_FLAG", True)
    if consecutive_errors >= int(cfg.max_consecutive_exchange_errors):
        return KillDecision(True, "EXCHANGE_ERRORS", True)
    if user_state is None:
        return KillDecision(False, None, False)
    equity = account_value_usd(user_state)
    used = margin_used_usd(user_state)
    if equity > 0 and (used / equity) * 100.0 >= float(cfg.max_margin_usage_pct):
        return KillDecision(True, "MARGIN_USAGE", True)
    return KillDecision(False, None, False)


def kill_record(reason: str) -> dict[str, Any]:
    return {"tripped": True, "reason": reason, "tripped_at": utc_now()}
