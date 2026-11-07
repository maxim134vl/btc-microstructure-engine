"""OKX Swap Bill History CSV → canonical fills (+ helpers for position rebuild)."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Any, Iterator

from btc_ml.external_traders.normalize import (
    clean_text,
    make_uid,
    normalize_symbol,
    parse_float,
    parse_ts_utc,
    warn_join,
)
from btc_ml.external_traders.schema import (
    QUALITY_OK,
    QUALITY_QUARANTINE,
    QUALITY_REJECTED,
    SCHEMA_VERSION,
)

SOURCE = "okx_swap_bill"


def _detect_header_line(lines: list[str]) -> int:
    for i, line in enumerate(lines[:20]):
        low = line.lstrip("\ufeff")
        if low.startswith("id,") or ",Order id," in low or low.startswith("id,Order id"):
            return i
    return 0


def _extract_account_uid(lines: list[str]) -> str:
    for line in lines[:5]:
        text = clean_text(line)
        if text.upper().startswith("UID:"):
            # UID:4797...,Account Type:...
            part = text.split(",", 1)[0]
            return clean_text(part.split(":", 1)[-1]) or "unknown"
    return "unknown"


def iter_okx_bill_fills(
    path: Path,
    *,
    import_batch_id: str,
    trader_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    raw_text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = raw_text.splitlines()
    account_uid = _extract_account_uid(lines)
    resolved_trader = trader_id or f"okx:{account_uid}"
    start = _detect_header_line(lines)
    reader = csv.DictReader(StringIO("\n".join(lines[start:])))
    for idx, raw in enumerate(reader):
        row = {clean_text(k): clean_text(v) for k, v in raw.items()}
        warnings: list[str] = []
        action_raw = row.get("Action", "")
        action_l = action_raw.lower()
        is_funding = "funding" in action_l
        if action_l in {"buy", "sell"}:
            action = action_raw.upper()
        elif is_funding:
            action = "FUNDING"
        else:
            action = action_raw.upper() or "UNKNOWN"

        symbol = normalize_symbol(row.get("Symbol"))
        fill_ts = parse_ts_utc(row.get("Time"))
        price = parse_float(row.get("Filled Price"))
        qty = parse_float(row.get("Amount"))
        pnl = parse_float(row.get("PnL"))
        fee = parse_float(row.get("Fee"))
        fill_id = row.get("id") or ""
        order_id = row.get("Order id") or ""

        quality = QUALITY_OK
        if is_funding:
            # Keep funding in fills table for audit; positions builder skips them.
            quality = QUALITY_OK
            warnings.append("FUNDING_EVENT")
        else:
            if action not in {"BUY", "SELL"}:
                quality = QUALITY_REJECTED
                warnings.append("BAD_ACTION")
            if symbol is None:
                quality = QUALITY_REJECTED
                warnings.append("BAD_SYMBOL")
            if fill_ts is None:
                quality = QUALITY_REJECTED
                warnings.append("BAD_FILL_TS")
            if price is None or price <= 0:
                quality = QUALITY_QUARANTINE if quality == QUALITY_OK else quality
                warnings.append("BAD_PRICE")
            if qty is None or qty <= 0:
                quality = QUALITY_QUARANTINE if quality == QUALITY_OK else quality
                warnings.append("BAD_QTY")

        fill_uid = make_uid(SOURCE, resolved_trader, fill_id or f"{path.name}:{idx}")
        yield {
            "fill_uid": fill_uid,
            "trader_id": resolved_trader,
            "source": SOURCE,
            "symbol": symbol or "",
            "action": action,
            "fill_ts": fill_ts or "",
            "price": price,
            "qty": qty,
            "pnl_quote": pnl,
            "fee_quote": fee,
            "order_id": order_id,
            "is_funding": bool(is_funding),
            "quality_status": quality,
            "parse_warnings": warn_join(warnings),
            "import_batch_id": import_batch_id,
            "raw_ref": f"{path.name}:row={idx}",
            "schema_version": SCHEMA_VERSION,
            "tz_assumption": "UTC0_DECLARED",
        }
