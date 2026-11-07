"""filtered_rounded_trades.csv → canonical positions (closing-fill interpretation)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterator

from btc_ml.external_traders.normalize import (
    clean_text,
    make_uid,
    normalize_symbol,
    parse_float,
    parse_ts_utc,
    side_from_closing_fill_action,
    warn_join,
)
from btc_ml.external_traders.schema import (
    QUALITY_OK,
    QUALITY_QUARANTINE,
    QUALITY_REJECTED,
    SCHEMA_VERSION,
)

SOURCE = "filtered_rounded"
TRADER_ID = "unknown:filtered_rounded"


def iter_filtered_rounded_positions(
    path: Path,
    *,
    import_batch_id: str,
) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text.splitlines())
    for idx, raw in enumerate(reader):
        row = {clean_text(k): clean_text(v) for k, v in raw.items()}
        warnings = ["CLOSING_FILL_INTERPRETED", "ENTRY_TS_UNKNOWN"]
        symbol = normalize_symbol(row.get("Contracts"))
        side = side_from_closing_fill_action(row.get("Trade Type"))
        exit_ts = parse_ts_utc(row.get("Filled"))
        exit_price = parse_float(row.get("Filled Price"))
        qty = parse_float(row.get("Qty"))
        pnl = parse_float(row.get("Realized P&L"))

        quality = QUALITY_OK
        if symbol is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_SYMBOL")
        if side is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_SIDE")
        if exit_ts is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_EXIT_TS")
        if exit_price is None or exit_price <= 0:
            quality = QUALITY_QUARANTINE if quality == QUALITY_OK else quality
            warnings.append("BAD_EXIT_PRICE")
        if pnl is None:
            quality = QUALITY_QUARANTINE if quality == QUALITY_OK else quality
            warnings.append("PNL_MISSING")

        # No entry time/price in source → quarantine soft fields but keep usable for distill later.
        if quality == QUALITY_OK:
            quality = QUALITY_QUARANTINE
            warnings.append("MISSING_ENTRY_LEG")

        position_uid = make_uid(SOURCE, TRADER_ID, symbol, side, exit_ts, exit_price, qty, idx)
        yield {
            "position_uid": position_uid,
            "trader_id": TRADER_ID,
            "source": SOURCE,
            "symbol": symbol or "",
            "side": side or "",
            "entry_ts": "",
            "exit_ts": exit_ts or "",
            "entry_price": None,
            "exit_price": exit_price,
            "qty": qty,
            "pnl_quote": pnl,
            "fee_quote": None,
            "leverage": None,
            "strategy_label": "",
            "exit_ts_source": "explicit",
            "quality_status": quality,
            "parse_warnings": warn_join(warnings),
            "import_batch_id": import_batch_id,
            "raw_ref": f"{path.name}:row={idx}",
            "schema_version": SCHEMA_VERSION,
            "tz_assumption": "UTC_ASSUMED",
        }
