"""Account-level kill switch. Flatten + refuse opens until manual reset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import KILL_UNIMMR
from .ledger import utc_now


@dataclass(frozen=True)
class KillDecision:
    tripped: bool
    reason: str | None
    flatten: bool


def kill_flag_present(path: Path) -> bool:
    return Path(path).is_file()


def parse_unimmr(account: dict[str, Any] | None) -> float | None:
    if not account:
        return None
    raw = account.get("uniMMR")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_equity_usd(account: dict[str, Any] | None) -> float:
    if not account:
        return 0.0
    for key in ("actualEquity", "accountEquity", "totalAvailableBalance"):
        raw = account.get(key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def evaluate_kill(
    *,
    consecutive_errors: int,
    max_consecutive_errors: int,
    already_tripped: bool,
    flag_present: bool,
    account: dict[str, Any] | None,
    kill_unimmr: float = KILL_UNIMMR,
    ip_banned: bool = False,
    clock_skew_ms: float | None = None,
    max_clock_skew_ms: float = 1000.0,
    auto_borrow: bool = False,
    venue_leverage: int | None = None,
    required_leverage: int = 2,
) -> KillDecision:
    if already_tripped:
        return KillDecision(True, "ALREADY_TRIPPED", False)
    if flag_present:
        return KillDecision(True, "KILL_FLAG", True)
    if ip_banned:
        return KillDecision(True, "IP_BANNED_418", True)
    if auto_borrow:
        return KillDecision(True, "AUTO_BORROW_DETECTED", True)
    if venue_leverage is not None and int(venue_leverage) != int(required_leverage):
        return KillDecision(True, "VENUE_LEVERAGE_NOT_2", True)
    if consecutive_errors >= int(max_consecutive_errors):
        return KillDecision(True, "EXCHANGE_ERRORS", True)
    if clock_skew_ms is not None and abs(float(clock_skew_ms)) > float(max_clock_skew_ms):
        return KillDecision(True, "CLOCK_SKEW", True)
    uni = parse_unimmr(account)
    if uni is not None and uni <= float(kill_unimmr):
        return KillDecision(True, "UNIMMR_KILL", True)
    return KillDecision(False, None, False)


def can_open(*, unimmr: float | None, min_unimmr_open: float) -> tuple[bool, str | None]:
    if unimmr is None:
        return False, "ENTRY_BLOCKED_UNIMMR_MISSING"
    if float(unimmr) < float(min_unimmr_open):
        return False, "ENTRY_BLOCKED_UNIMMR"
    return True, None


def kill_record(reason: str) -> dict[str, Any]:
    return {"tripped": True, "reason": reason, "tripped_at": utc_now()}
