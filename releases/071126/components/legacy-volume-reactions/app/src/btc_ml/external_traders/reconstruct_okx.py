"""FIFO reconstruct closed positions from OKX Buy/Sell fills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from btc_ml.external_traders.normalize import make_uid, warn_join
from btc_ml.external_traders.schema import (
    QUALITY_OK,
    QUALITY_QUARANTINE,
    SCHEMA_VERSION,
)

SOURCE = "okx_swap_bill"


@dataclass
class _Lot:
    side: str  # LONG / SHORT
    qty: float
    price: float
    ts: str
    fill_uid: str
    fees: float = 0.0


@dataclass
class _Book:
    lots: list[_Lot] = field(default_factory=list)


def reconstruct_okx_positions(
    fills: Iterable[dict[str, Any]],
    *,
    import_batch_id: str,
) -> list[dict[str, Any]]:
    """Match Buy/Sell fills into closed positions via FIFO inventory per symbol+trader."""
    books: dict[tuple[str, str], _Book] = {}
    closed: list[dict[str, Any]] = []

    trade_fills = [
        f
        for f in fills
        if not f.get("is_funding")
        and f.get("action") in {"BUY", "SELL"}
        and f.get("quality_status") != "REJECTED"
        and f.get("symbol")
        and f.get("fill_ts")
        and f.get("price") is not None
        and f.get("qty") is not None
        and float(f["qty"]) > 0
    ]
    trade_fills.sort(key=lambda f: (f["trader_id"], f["symbol"], f["fill_ts"], f["fill_uid"]))

    for fill in trade_fills:
        trader_id = str(fill["trader_id"])
        symbol = str(fill["symbol"])
        key = (trader_id, symbol)
        book = books.setdefault(key, _Book())
        action = fill["action"]
        qty_left = float(fill["qty"])
        price = float(fill["price"])
        ts = str(fill["fill_ts"])
        fee = float(fill["fee_quote"] or 0.0)
        fill_pnl = float(fill["pnl_quote"] or 0.0)
        # Allocate reported fill PnL across closing matches proportionally by qty.
        pnl_per_unit = (fill_pnl / float(fill["qty"])) if fill["qty"] else 0.0
        fee_per_unit = (fee / float(fill["qty"])) if fill["qty"] else 0.0

        # BUY opens/adds LONG or closes SHORT; SELL opens/adds SHORT or closes LONG.
        closing_side = "SHORT" if action == "BUY" else "LONG"
        opening_side = "LONG" if action == "BUY" else "SHORT"

        i = 0
        while qty_left > 1e-12 and i < len(book.lots):
            lot = book.lots[i]
            if lot.side != closing_side:
                i += 1
                continue
            matched = min(lot.qty, qty_left)
            warnings = ["FIFO_RECONSTRUCTED"]
            pnl = pnl_per_unit * matched
            fee_part = fee_per_unit * matched + (lot.fees * (matched / lot.qty) if lot.qty else 0.0)
            quality = QUALITY_OK
            if abs(pnl) < 1e-12 and abs(fill_pnl) < 1e-12:
                warnings.append("PNL_ZERO_OR_MISSING")
            position_uid = make_uid(
                SOURCE,
                trader_id,
                symbol,
                closing_side,
                lot.ts,
                ts,
                lot.price,
                price,
                matched,
                lot.fill_uid,
                fill["fill_uid"],
            )
            closed.append(
                {
                    "position_uid": position_uid,
                    "trader_id": trader_id,
                    "source": SOURCE,
                    "symbol": symbol,
                    "side": closing_side,
                    "entry_ts": lot.ts,
                    "exit_ts": ts,
                    "entry_price": lot.price,
                    "exit_price": price,
                    "qty": matched,
                    "pnl_quote": pnl,
                    "fee_quote": fee_part,
                    "leverage": None,
                    "strategy_label": "",
                    "exit_ts_source": "reconstructed",
                    "quality_status": quality,
                    "parse_warnings": warn_join(warnings),
                    "import_batch_id": import_batch_id,
                    "raw_ref": f"{lot.fill_uid}->{fill['fill_uid']}",
                    "schema_version": SCHEMA_VERSION,
                    "tz_assumption": "UTC0_DECLARED",
                }
            )
            lot.qty -= matched
            qty_left -= matched
            if lot.qty <= 1e-12:
                book.lots.pop(i)
            else:
                # residual lot keeps remaining fee share
                lot.fees = max(0.0, lot.fees - fee_part)
                i += 1

        if qty_left > 1e-12:
            book.lots.append(
                _Lot(
                    side=opening_side,
                    qty=qty_left,
                    price=price,
                    ts=ts,
                    fill_uid=str(fill["fill_uid"]),
                    fees=fee_per_unit * qty_left,
                )
            )

    # Leftover open lots → quarantine synthetic open markers (not used in distill).
    for (trader_id, symbol), book in books.items():
        for lot in book.lots:
            closed.append(
                {
                    "position_uid": make_uid(SOURCE, "OPEN", trader_id, symbol, lot.ts, lot.fill_uid),
                    "trader_id": trader_id,
                    "source": SOURCE,
                    "symbol": symbol,
                    "side": lot.side,
                    "entry_ts": lot.ts,
                    "exit_ts": "",
                    "entry_price": lot.price,
                    "exit_price": None,
                    "qty": lot.qty,
                    "pnl_quote": None,
                    "fee_quote": lot.fees,
                    "leverage": None,
                    "strategy_label": "",
                    "exit_ts_source": "",
                    "quality_status": QUALITY_QUARANTINE,
                    "parse_warnings": "OPEN_INVENTORY_LEFTOVER",
                    "import_batch_id": import_batch_id,
                    "raw_ref": lot.fill_uid,
                    "schema_version": SCHEMA_VERSION,
                    "tz_assumption": "UTC0_DECLARED",
                }
            )
    return closed
