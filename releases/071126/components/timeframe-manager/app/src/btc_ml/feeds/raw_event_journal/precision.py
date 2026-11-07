"""Decimal-safe numeric helpers — no float round-trip of exchange strings."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional


def decimal_from_payload(value: Any) -> Optional[str]:
    """Parse exchange numeric string into canonical Decimal string.

    Returns None if missing/invalid. Never routes through float.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    # Normalize without scientific notation when possible; preserve exact value.
    return format(dec, "f")


def decimal_equal(a: Optional[str], b: Optional[str]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return Decimal(a) == Decimal(b)
    except (InvalidOperation, ValueError):
        return False


def compute_spread_mid(
    bid: Optional[str], ask: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    if bid is None or ask is None:
        return None, None
    try:
        b = Decimal(bid)
        a = Decimal(ask)
    except (InvalidOperation, ValueError):
        return None, None
    spread = a - b
    mid = (a + b) / Decimal(2)
    return format(spread, "f"), format(mid, "f")
