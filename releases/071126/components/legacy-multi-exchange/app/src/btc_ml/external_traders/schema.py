"""Canonical schemas for external trader imports."""

from __future__ import annotations

SCHEMA_VERSION = "external_trades_v1"

FILL_COLUMNS: tuple[str, ...] = (
    "fill_uid",
    "trader_id",
    "source",
    "symbol",
    "action",  # BUY / SELL (exchange fill action)
    "fill_ts",
    "price",
    "qty",
    "pnl_quote",
    "fee_quote",
    "order_id",
    "is_funding",
    "quality_status",
    "parse_warnings",
    "import_batch_id",
    "raw_ref",
    "schema_version",
    "tz_assumption",
)

POSITION_COLUMNS: tuple[str, ...] = (
    "position_uid",
    "trader_id",
    "source",
    "symbol",
    "side",  # LONG / SHORT
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "qty",
    "pnl_quote",
    "fee_quote",
    "leverage",
    "strategy_label",
    "exit_ts_source",
    "quality_status",
    "parse_warnings",
    "import_batch_id",
    "raw_ref",
    "schema_version",
    "tz_assumption",
)

QUALITY_OK = "OK"
QUALITY_QUARANTINE = "QUARANTINE"
QUALITY_REJECTED = "REJECTED"
