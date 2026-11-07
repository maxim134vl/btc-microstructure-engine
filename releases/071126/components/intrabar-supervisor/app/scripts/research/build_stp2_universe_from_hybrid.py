#!/usr/bin/env python3
"""Emit an STP2 pilot universe file from the canonical Hybrid tick book.

run_etll_stp2_filter_pilot.py consumes a universe JSON that was originally built
for a single-month M15 slice. The Hybrid book is the same shape of data — closed
trades with entry/exit levels — just 6172 trades across four timeframes and 2.6
years, so it only needs reshaping, not re-simulation.

Entry time, levels and quantity live on the position's OPEN record rather than on
the trade row, and both are read from the market-time staging (the raw book stamps
wall-clock time, which would send the pilot's causal lookback to the wrong dates).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from calibration_split import assign_segment  # noqa: E402

STAGE_ROOT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr"
DEFAULT_EPOCH = "ETLL_HYBRID_TICK_V1_20260905_092610"
RISK_UNIT = 1000.0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    parser.add_argument("--segments", default="train,validation")
    parser.add_argument("--out", type=Path, default=STAGE_ROOT / "stp2" / "hybrid_trade_universe.json")
    args = parser.parse_args()

    books = STAGE_ROOT / "paper_repo/data/trading/intrabar_paper" / args.epoch_id / "books"
    trades = pd.DataFrame(read_jsonl(books / "trades.jsonl"))
    opens: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(books / "positions.jsonl"):
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        pid = str(row.get("position_id") or "")
        if pid and pid not in opens:
            opens[pid] = row

    trades["position_id"] = trades["position_id"].astype(str)
    trades["segment"] = assign_segment(trades)
    want = {s.strip() for s in args.segments.split(",") if s.strip()}
    keep = trades.loc[trades["segment"].isin(want)]

    out_rows: list[dict[str, Any]] = []
    skipped = 0
    for row in keep.to_dict("records"):
        pos = opens.get(str(row.get("position_id")))
        if not pos:
            skipped += 1
            continue
        entry_ts = pos.get("context_occurrence_timestamp")
        exit_ts = row.get("context_occurrence_timestamp")
        try:
            entry = float(pos.get("entry_price"))
            stop = float(pos.get("stop_loss_price"))
            take = float(pos.get("take_profit_price"))
            qty = float(pos.get("quantity"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not entry_ts or not exit_ts or qty <= 0:
            skipped += 1
            continue
        net = float(row.get("net_pnl_usd") or 0.0)
        risk = abs(entry - stop) * qty
        out_rows.append(
            {
                "trade_id": row.get("trade_id"),
                "position_id": row.get("position_id"),
                "timeframe": str(pos.get("timeframe") or "").upper(),
                "side": str(pos.get("side") or "").upper(),
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_price": entry,
                "exit_price": float(row.get("exit_price") or entry),
                "stop_loss_price": stop,
                "take_profit_price": take,
                "quantity": qty,
                "net_pnl_usd": net,
                "r_multiple": net / risk if risk > 0 else net / RISK_UNIT,
                "exit_reason": row.get("exit_reason"),
                "fees_usd": float(row.get("fees_usd") or 0.0),
                "slippage_usd": float(row.get("slippage_usd") or 0.0),
                "risk_amount_usd": float(pos.get("risk_amount_usd") or RISK_UNIT),
                "segment": row.get("segment"),
            }
        )

    out_rows.sort(key=lambda r: str(r["entry_ts"]))
    stamps = [r["entry_ts"] for r in out_rows]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": "STP2_HYBRID_UNIVERSE",
        "status": "UNIVERSE_READY",
        "shadow": "STRUCTURAL_STOP_TAKE_FILTER",
        "source": {
            "paper_epoch_id": args.epoch_id,
            "books": str(books),
            "note": "market-time staged Hybrid tick book (S4.1 manager + LIVE1B intrabar)",
        },
        "segments_included": sorted(want),
        "holdout_status": "SEALED — excluded from this universe",
        "window_stats": {
            "entry_first": stamps[0] if stamps else None,
            "entry_last": stamps[-1] if stamps else None,
            "n_trades": len(out_rows),
            "skipped_without_open_record": skipped,
        },
        "by_timeframe": {
            tf: sum(1 for r in out_rows if r["timeframe"] == tf) for tf in ("M15", "M30", "H1", "H4")
        },
        "trades": out_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    print(f"universe: {len(out_rows)} trades  (skipped {skipped})")
    print(f"  span: {payload['window_stats']['entry_first']} -> {payload['window_stats']['entry_last']}")
    print(f"  by tf: {payload['by_timeframe']}")
    print(f"  written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
