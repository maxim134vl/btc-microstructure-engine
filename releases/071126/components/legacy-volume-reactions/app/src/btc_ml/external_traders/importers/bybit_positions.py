"""Bybit positions CSV → canonical positions."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterator

from btc_ml.external_traders.normalize import (
    clean_text,
    is_missing,
    make_uid,
    normalize_side_from_buy_sell,
    normalize_symbol,
    parse_float,
    parse_ts_utc,
    slug_trader,
    warn_join,
)
from btc_ml.external_traders.schema import (
    QUALITY_OK,
    QUALITY_QUARANTINE,
    QUALITY_REJECTED,
    SCHEMA_VERSION,
)


SOURCE = "bybit_positions"


def _row_get(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] != "":
            return row[name]
        # BOM / quoted variants
        for key, value in row.items():
            if clean_text(key).strip('"') == name:
                return value
    return ""


def iter_bybit_positions(
    path: Path,
    *,
    import_batch_id: str,
) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text.splitlines())
    for idx, raw in enumerate(reader):
        row = {clean_text(k).strip('"'): clean_text(v) for k, v in raw.items()}
        warnings: list[str] = []
        created = _row_get(row, "Дата создания")
        updated = _row_get(row, "Дата обновления")
        symbol = normalize_symbol(_row_get(row, "Монета"))
        side = normalize_side_from_buy_sell(_row_get(row, "Тип"))
        status = clean_text(_row_get(row, "Статус")).lower()
        strategy = _row_get(row, "Стратегия") or "unknown"
        trader_id = f"bybit:{slug_trader(strategy)}"
        entry_ts = parse_ts_utc(created)
        exit_ts = parse_ts_utc(updated)
        entry_price = parse_float(_row_get(row, "Цена входа"))
        qty = parse_float(_row_get(row, "Объем"))
        pnl = parse_float(_row_get(row, "PnL"))
        leverage = parse_float(_row_get(row, "Плечо"))

        quality = QUALITY_OK
        if status != "closed":
            quality = QUALITY_QUARANTINE
            warnings.append("NOT_CLOSED")
        if symbol is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_SYMBOL")
        if side is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_SIDE")
        if entry_ts is None:
            quality = QUALITY_REJECTED
            warnings.append("BAD_ENTRY_TS")
        if exit_ts is None and status == "closed":
            quality = QUALITY_QUARANTINE
            warnings.append("MISSING_EXIT_TS")
        if entry_price is None or entry_price <= 0:
            quality = QUALITY_QUARANTINE if quality == QUALITY_OK else quality
            warnings.append("BAD_ENTRY_PRICE")
        if pnl is None and status == "closed" and not is_missing(_row_get(row, "PnL")):
            warnings.append("PNL_UNPARSEABLE")
        elif pnl is None and status == "closed":
            warnings.append("PNL_MISSING")
            if quality == QUALITY_OK:
                quality = QUALITY_QUARANTINE

        exit_ts_source = "updated_at" if exit_ts else ""
        position_uid = make_uid(
            SOURCE,
            trader_id,
            symbol,
            side,
            entry_ts,
            exit_ts,
            entry_price,
            qty,
            idx,
        )
        yield {
            "position_uid": position_uid,
            "trader_id": trader_id,
            "source": SOURCE,
            "symbol": symbol or "",
            "side": side or "",
            "entry_ts": entry_ts or "",
            "exit_ts": exit_ts or "",
            "entry_price": entry_price,
            "exit_price": None,
            "qty": qty,
            "pnl_quote": pnl,
            "fee_quote": None,
            "leverage": leverage,
            "strategy_label": strategy,
            "exit_ts_source": exit_ts_source,
            "quality_status": quality,
            "parse_warnings": warn_join(warnings),
            "import_batch_id": import_batch_id,
            "raw_ref": f"{path.name}:row={idx}",
            "schema_version": SCHEMA_VERSION,
            "tz_assumption": "UTC_ASSUMED",
        }
