"""Shared normalization helpers for external trader imports."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

_NA = {"", "n/a", "н/д", "none", "null", "nan", "-"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip()


def is_missing(value: Any) -> bool:
    return clean_text(value).lower() in _NA


def parse_float(value: Any) -> float | None:
    text = clean_text(value).replace(",", "")
    if is_missing(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_ts_utc(value: Any, *, assume_utc: bool = True) -> str | None:
    """Parse common report timestamps to ISO-8601 UTC (Z)."""
    text = clean_text(value)
    if is_missing(text):
        return None
    text = text.replace("T", " ").replace("Z", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if assume_utc:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def normalize_symbol(value: Any) -> str | None:
    text = clean_text(value).upper().replace(" ", "")
    if not text:
        return None
    text = text.replace("-SWAP", "").replace("_SWAP", "")
    text = text.replace("-", "")
    # OKX BTCUSDT already; BTC-USDT → BTCUSDT
    if text.endswith("PERP"):
        text = text[: -len("PERP")]
    if not re.fullmatch(r"[A-Z0-9]{5,20}", text):
        return None
    return text


def normalize_side_from_buy_sell(value: Any) -> str | None:
    text = clean_text(value).upper()
    if text in {"BUY", "LONG", "B"}:
        return "LONG"
    if text in {"SELL", "SHORT", "S"}:
        return "SHORT"
    return None


def side_from_closing_fill_action(action: Any) -> str | None:
    """If row is a closing fill: BUY closes SHORT, SELL closes LONG."""
    text = clean_text(action).upper()
    if text in {"BUY", "B"}:
        return "SHORT"
    if text in {"SELL", "S"}:
        return "LONG"
    return None


def slug_trader(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def make_uid(*parts: Any) -> str:
    material = "|".join(clean_text(p) for p in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def warn_join(warnings: list[str]) -> str:
    return "|".join(dict.fromkeys(w for w in warnings if w))
