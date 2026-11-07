"""Build canonical external fills + positions from known Downloads sources."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from btc_ml.external_traders.importers.bybit_positions import iter_bybit_positions
from btc_ml.external_traders.importers.filtered_rounded import iter_filtered_rounded_positions
from btc_ml.external_traders.importers.okx_bill import iter_okx_bill_fills
from btc_ml.external_traders.reconstruct_okx import reconstruct_okx_positions
from btc_ml.external_traders.schema import FILL_COLUMNS, POSITION_COLUMNS, SCHEMA_VERSION


def _utc_batch_id() -> str:
    return datetime.now(timezone.utc).strftime("batch_%Y%m%dT%H%M%SZ")


def _as_frame(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(columns))
    frame = pd.DataFrame(list(rows))
    for col in columns:
        if col not in frame.columns:
            frame[col] = None
    return frame.loc[:, list(columns)]


def _summary(positions: pd.DataFrame, fills: pd.DataFrame) -> dict[str, Any]:
    def bucket(frame: pd.DataFrame, cols: list[str]) -> dict[str, int]:
        if frame.empty:
            return {}
        grouped = frame.groupby(cols, dropna=False).size()
        return {str(k): int(v) for k, v in grouped.items()}

    btc = positions[positions["symbol"] == "BTCUSDT"] if not positions.empty else positions
    return {
        "schema_version": SCHEMA_VERSION,
        "fills_rows": int(len(fills)),
        "positions_rows": int(len(positions)),
        "positions_by_source_quality": bucket(positions, ["source", "quality_status"]),
        "positions_btc_by_source_quality": bucket(btc, ["source", "quality_status"]),
        "positions_by_trader_top": dict(
            list(
                positions.groupby("trader_id").size().sort_values(ascending=False).head(20).items()
            )
        )
        if not positions.empty
        else {},
        "fills_funding_rows": int(fills["is_funding"].sum()) if not fills.empty else 0,
        "fills_trade_rows": int((~fills["is_funding"]).sum()) if not fills.empty else 0,
    }


def build_canonical_external_trades(
    *,
    bybit_path: Path | None,
    filtered_path: Path | None,
    okx_paths: Sequence[Path],
    output_dir: Path,
    import_batch_id: str | None = None,
) -> dict[str, Any]:
    batch_id = import_batch_id or _utc_batch_id()
    output_dir.mkdir(parents=True, exist_ok=True)

    position_rows: list[dict[str, Any]] = []
    fill_rows: list[dict[str, Any]] = []

    if bybit_path is not None and bybit_path.exists():
        position_rows.extend(iter_bybit_positions(bybit_path, import_batch_id=batch_id))

    if filtered_path is not None and filtered_path.exists():
        position_rows.extend(iter_filtered_rounded_positions(filtered_path, import_batch_id=batch_id))

    for okx_path in okx_paths:
        if okx_path.exists():
            fill_rows.extend(iter_okx_bill_fills(okx_path, import_batch_id=batch_id))

    if fill_rows:
        position_rows.extend(
            reconstruct_okx_positions(fill_rows, import_batch_id=batch_id)
        )

    fills = _as_frame(fill_rows, FILL_COLUMNS)
    positions = _as_frame(position_rows, POSITION_COLUMNS)

    # Stable sort for deterministic artifacts.
    if not fills.empty:
        fills = fills.sort_values(["trader_id", "symbol", "fill_ts", "fill_uid"]).reset_index(drop=True)
    if not positions.empty:
        positions = positions.sort_values(
            ["source", "trader_id", "symbol", "entry_ts", "exit_ts", "position_uid"]
        ).reset_index(drop=True)

    fills_path = output_dir / "canonical_external_fills.parquet"
    positions_path = output_dir / "canonical_external_positions.parquet"
    # Also CSV for quick eyeballing of small slices.
    positions_btc_csv = output_dir / "canonical_external_positions_btcusdt.csv"

    fills.to_parquet(fills_path, index=False)
    positions.to_parquet(positions_path, index=False)
    btc = positions[positions["symbol"] == "BTCUSDT"] if not positions.empty else positions
    btc.to_csv(positions_btc_csv, index=False)

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "import_batch_id": batch_id,
        "inputs": {
            "bybit_path": str(bybit_path) if bybit_path else None,
            "filtered_path": str(filtered_path) if filtered_path else None,
            "okx_paths": [str(p) for p in okx_paths],
        },
        "outputs": {
            "fills": str(fills_path),
            "positions": str(positions_path),
            "positions_btcusdt_csv": str(positions_btc_csv),
        },
        "summary": _summary(positions, fills),
    }
    report_path = output_dir / "canonical_external_trades_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["outputs"]["report"] = str(report_path)
    return report
