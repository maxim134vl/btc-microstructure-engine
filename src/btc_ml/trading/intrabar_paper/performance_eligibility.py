"""Canonical filters for strategy-performance eligibility."""

from __future__ import annotations

from typing import Any, Mapping

POSITION_STATUS_VOID = "VOID"
INVALIDATION_REASON_SYSTEM_BUG = "SYSTEM_BUG_INVALIDATION"


def row_status(row: Mapping[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("status") or row.get("void_status") or "").upper()


def is_void_status(status: str) -> bool:
    text = str(status or "").upper()
    return text == POSITION_STATUS_VOID or text.startswith("VOID_")


def is_void_position_row(row: Mapping[str, Any] | None) -> bool:
    return is_void_status(row_status(row))


def statistics_included(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    explicit = row.get("statistics_included")
    if explicit is not None:
        return bool(explicit)
    return not is_void_position_row(row)


def counts_toward_strategy_performance(row: Mapping[str, Any] | None) -> bool:
    """True only for canonical closed strategy trades."""
    if not isinstance(row, dict):
        return False
    if not statistics_included(row):
        return False
    if is_void_position_row(row):
        return False
    status = row_status(row)
    if status and status not in {"CLOSED", "CLOSE", ""}:
        return False
    return True


def performance_eligible_trades(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in (rows or []) if counts_toward_strategy_performance(row)]
