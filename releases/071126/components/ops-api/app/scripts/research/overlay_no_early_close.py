#!/usr/bin/env python3
"""Counterfactual: no S41 early close. Position rides to first tick SL or TP.

Overlapping reverse entries while the slot stays occupied are dropped.
Not a full manager re-run. Uses the stopped Hybrid tick book + aggTrade.

  PYTHONPATH=src python scripts/research/overlay_no_early_close.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from btc_ml.trading.paper_core import closed_trade_economics  # noqa: E402
from btc_ml.trading.shadow_structural_protection.tick_cache import TickHourCache  # noqa: E402

BOOKS = ROOT / (
    "output/research/living_context_hybrid_tick_partial/"
    "ETLL_HYBRID_TICK_V1_20260915_210947"
)
TICK_REPO = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_full_etll/repo")
OUT = ROOT / "output/research/living_context_hybrid_tick_partial/no_early_close"
MAX_HOLD = pd.Timedelta(days=45)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _bucket(reason: Any) -> str:
    text = str(reason or "").upper()
    if "STOP" in text:
        return "STOP"
    if "TAKE" in text:
        return "TAKE"
    return "EARLY"


def _first_hit(prices: np.ndarray, *, side: str, stop: float, take: float) -> tuple[int, str] | None:
    if not len(prices):
        return None
    if str(side).upper() == "LONG":
        stop_hit = prices <= stop
        take_hit = prices >= take
    else:
        stop_hit = prices >= stop
        take_hit = prices <= take
    both = stop_hit & take_hit
    any_hit = stop_hit | take_hit
    if not any_hit.any():
        return None
    i = int(np.argmax(any_hit))
    if both[i] or stop_hit[i]:
        return i, "STOP_LOSS"
    return i, "TAKE_PROFIT"


def load_book(books: Path) -> pd.DataFrame:
    trades = pd.DataFrame(_read_jsonl(books / "trades.jsonl"))
    opens: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(books / "positions.jsonl"):
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        pid = str(row.get("position_id") or "")
        if pid and pid not in opens:
            opens[pid] = row
    trades["position_id"] = trades["position_id"].astype(str)
    def pick(field: str) -> pd.Series:
        return trades["position_id"].map(lambda p: (opens.get(p) or {}).get(field))

    out = trades.copy()
    out["entry_ts"] = pd.to_datetime(pick("context_occurrence_timestamp"), utc=True, errors="coerce", format="ISO8601")
    out["exit_ts"] = pd.to_datetime(out["context_occurrence_timestamp"], utc=True, errors="coerce", format="ISO8601")
    out["timeframe"] = out["timeframe"].astype(str).str.upper()
    out["side"] = out["side"].astype(str).str.upper()
    out["entry_price"] = pd.to_numeric(pick("entry_price"), errors="coerce")
    out["stop_loss_price"] = pd.to_numeric(pick("stop_loss_price"), errors="coerce")
    out["take_profit_price"] = pd.to_numeric(pick("take_profit_price"), errors="coerce")
    out["quantity"] = pd.to_numeric(pick("quantity"), errors="coerce")
    out["risk_amount_usd"] = pd.to_numeric(pick("risk_amount_usd"), errors="coerce")
    out["net_pnl_usd"] = pd.to_numeric(out["net_pnl_usd"], errors="coerce").fillna(0.0)
    out["bucket"] = out["exit_reason"].map(_bucket)
    need = ["entry_ts", "exit_ts", "entry_price", "stop_loss_price", "take_profit_price", "quantity"]
    out = out.dropna(subset=need).sort_values(["timeframe", "entry_ts"]).reset_index(drop=True)
    return out


def ride_to_barrier(
    ticks: TickHourCache,
    *,
    start: pd.Timestamp,
    side: str,
    stop: float,
    take: float,
    limit: pd.Timestamp,
) -> tuple[pd.Timestamp, float, str] | None:
    hour = start.floor("h")
    last = min(start + MAX_HOLD, limit)
    cursor = start
    chunk = pd.Timedelta(hours=6)
    while cursor < last:
        end = min(cursor + chunk, last)
        ts_ns, prices, _ids = ticks.window(start=cursor, end=end)
        hit = _first_hit(prices, side=side, stop=stop, take=take)
        if hit is not None:
            i, reason = hit
            ts = pd.Timestamp(int(ts_ns[i]), tz="UTC")
            px = float(stop if reason == "STOP_LOSS" else take)
            return ts, px, reason
        cursor = end
    return None


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or not len(frame):
        return {"n": 0}
    net = pd.to_numeric(frame["net_pnl_usd"], errors="coerce").fillna(0.0)
    wins = net[net > 0]
    losses = net[net < 0]
    gp = float(wins.sum())
    gl = float(abs(losses.sum()))
    buckets = frame["bucket"].astype(str).value_counts().to_dict() if "bucket" in frame.columns else {}
    return {
        "n": int(len(frame)),
        "wr": float((net > 0).mean()),
        "pf": (gp / gl) if gl > 0 else None,
        "net": float(net.sum()),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "exits": {str(k): int(v) for k, v in buckets.items()},
    }


def main() -> int:
    base = load_book(BOOKS)
    sample_end = base["exit_ts"].max() + pd.Timedelta(days=1)
    ticks = TickHourCache(repo=TICK_REPO, max_hours=8)
    kept: list[dict[str, Any]] = []
    skipped = 0
    unresolved = 0
    flipped = {"TAKE_PROFIT": 0, "STOP_LOSS": 0}
    early_total = int((base["bucket"] == "EARLY").sum())
    early_done = 0
    started = time.time()
    print(
        json.dumps(
            {
                "overlay": "no_early_close",
                "not_hybrid_replay": True,
                "trades": int(len(base)),
                "early_to_ride": early_total,
            }
        ),
        flush=True,
    )
    for tf, part in base.groupby("timeframe", sort=False):
        occupied: pd.Timestamp | None = None
        for _, row in part.iterrows():
            entry = row["entry_ts"]
            if occupied is not None and entry < occupied:
                skipped += 1
                continue
            if row["bucket"] != "EARLY":
                rec = row.to_dict()
                kept.append(rec)
                occupied = row["exit_ts"]
                continue
            hit = ride_to_barrier(
                ticks,
                start=row["exit_ts"],
                side=str(row["side"]),
                stop=float(row["stop_loss_price"]),
                take=float(row["take_profit_price"]),
                limit=sample_end,
            )
            if hit is None:
                unresolved += 1
                skipped += 1
                occupied = None
                early_done += 1
                continue
            ts, px, reason = hit
            econ = closed_trade_economics(
                side=str(row["side"]),
                entry_price=float(row["entry_price"]),
                exit_price=px,
                position_size_btc=float(row["quantity"]),
                stop_loss_price=float(row["stop_loss_price"]),
                take_profit_price=float(row["take_profit_price"]),
                risk_amount_usd=float(row["risk_amount_usd"] or 1000.0),
                exit_reason=reason,
                exit_execution_source="aggTrade",
            )
            rec = row.to_dict()
            rec["exit_ts"] = ts
            rec["exit_price"] = px
            rec["exit_reason"] = reason
            rec["bucket"] = "STOP" if reason == "STOP_LOSS" else "TAKE"
            rec["net_pnl_usd"] = float(econ["net_pnl_usd"])
            rec["was_early"] = True
            kept.append(rec)
            occupied = ts
            flipped[reason] += 1
            early_done += 1
            if early_done % 25 == 0 or early_done == early_total:
                elapsed = time.time() - started
                print(
                    json.dumps(
                        {
                            "overlay": "no_early_close",
                            "early_done": early_done,
                            "of": early_total,
                            "became_tp": flipped["TAKE_PROFIT"],
                            "became_sl": flipped["STOP_LOSS"],
                            "skipped": skipped,
                            "elapsed_s": round(elapsed, 1),
                        }
                    ),
                    flush=True,
                )

    out = pd.DataFrame(kept)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "trades.parquet", index=False)
    payload = {
        "base": summarize(base),
        "no_early_close": summarize(out),
        "early_became": flipped,
        "skipped_while_occupied": skipped,
        "unresolved_no_barrier": unresolved,
        "note": "Occupancy overlay: early close rides to first SL/TP tick; overlapping entries dropped. Not a full S4.1 re-run.",
        "window": {
            "from": str(base["exit_ts"].min()),
            "to": str(base["exit_ts"].max()),
        },
    }
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
