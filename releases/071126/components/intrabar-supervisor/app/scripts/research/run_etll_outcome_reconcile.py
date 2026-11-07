#!/usr/bin/env python3
"""ETLL-native cross-layer outcome reconciliation for lived M15 books + shadow pilots.

Does NOT use live TRD-OUTCOME2 contract (no EQCORR / live CONTRACT_FP / BBO required).
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
DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/etll_outcome_reconcile"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_june_trades(pack: Path, *, from_ts: str, to_ts: str) -> pd.DataFrame:
    path = pack / "lived_replay" / "lived_trades.parquet"
    df = pd.read_parquet(path)
    entry = pd.to_datetime(df["entry_ts"], utc=True)
    lo = pd.Timestamp(from_ts)
    hi = pd.Timestamp(to_ts)
    return df[(entry >= lo) & (entry < hi)].copy()


def _lifecycle_ok(books_root: Path, trade: dict[str, Any]) -> dict[str, Any]:
    tf = str(trade.get("timeframe") or "M15")
    root = books_root / tf
    position_id = str(trade.get("position_id") or "")
    trade_id = str(trade.get("trade_id") or "")
    out = {
        "trade_id": trade_id,
        "position_id": position_id,
        "has_position": False,
        "has_trade_row": False,
        "has_entry_fill": False,
        "has_exit_fill": False,
        "pnl_match": False,
        "lifecycle_ok": False,
        "pnl_delta": None,
    }
    if not root.exists():
        return out
    try:
        positions = pd.read_parquet(root / "positions.parquet")
        trades = pd.read_parquet(root / "trades.parquet")
        fills = pd.read_parquet(root / "fills.parquet")
    except Exception as exc:
        out["error"] = str(exc)
        return out
    out["has_position"] = bool((positions.get("position_id") == position_id).any()) if "position_id" in positions else False
    tr = trades[trades.get("trade_id") == trade_id] if "trade_id" in trades else trades.iloc[0:0]
    out["has_trade_row"] = len(tr) > 0
    if len(tr) > 0 and "net_pnl_usd" in tr.columns:
        book_pnl = float(tr.iloc[0]["net_pnl_usd"])
        lived_pnl = float(trade.get("net_pnl_usd") or 0)
        out["pnl_delta"] = book_pnl - lived_pnl
        out["pnl_match"] = abs(out["pnl_delta"]) < 1e-4
    if "position_id" in fills.columns:
        pf = fills[fills["position_id"] == position_id]
        sides = set(str(x).upper() for x in pf.get("side", pd.Series(dtype=str)).tolist()) if len(pf) else set()
        # entry/exit inferred by fill count / reasons when present
        out["has_entry_fill"] = len(pf) >= 1
        out["has_exit_fill"] = len(pf) >= 2
    out["lifecycle_ok"] = bool(
        out["has_position"] and out["has_trade_row"] and out["has_entry_fill"] and out["has_exit_fill"] and out["pnl_match"]
    )
    return out


def _join_shadow(trade_id: str, paths: dict[str, Path]) -> dict[str, Any]:
    joined: dict[str, Any] = {}
    for name, path in paths.items():
        if not path.exists():
            joined[name] = {"present": False}
            continue
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
            if "trade_id" not in df.columns:
                joined[name] = {"present": True, "join": "NO_TRADE_ID_COLUMN"}
                continue
            hit = df[df["trade_id"] == trade_id]
            joined[name] = {
                "present": True,
                "rows": int(len(hit)),
                "sample": hit.iloc[0].to_dict() if len(hit) else None,
            }
        else:
            joined[name] = {"present": True, "path": str(path)}
    return joined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--from", dest="from_ts", default="2026-06-01T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-01T00:00:00Z")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--stp2-per-trade",
        type=Path,
        default=ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/stp2_pilot_202606_per_trade.parquet",
    )
    parser.add_argument(
        "--be33-per-trade",
        type=Path,
        default=ROOT / "output/audits/etll_lived_replay_20260825/stp_be33_pilot/stp_be33_pilot_202606_per_trade.parquet",
    )
    parser.add_argument(
        "--auction-summary",
        type=Path,
        default=DEFAULT_PACK / "lived_replay/shadow_lab/reports/shadow_auction_summary.json",
    )
    args = parser.parse_args()

    trades = _load_june_trades(args.pack_dir, from_ts=args.from_ts, to_ts=args.to_ts)
    books = args.pack_dir / "lived_replay" / "books"
    rows: list[dict[str, Any]] = []
    for _, tr in trades.iterrows():
        trade = tr.to_dict()
        life = _lifecycle_ok(books, trade)
        shadows = _join_shadow(
            str(trade.get("trade_id")),
            {
                "stp2": args.stp2_per_trade,
                "be33": args.be33_per_trade,
            },
        )
        life["shadows"] = {
            k: {"present": v.get("present"), "rows": v.get("rows")} for k, v in shadows.items()
        }
        # Attach compact shadow deltas when available
        if shadows.get("stp2", {}).get("sample"):
            s = shadows["stp2"]["sample"]
            # prefer FULL_STRUCTURAL row if multiple — sample is first match; reload filtered below
            life["stp2_delta_net_pnl_usd"] = s.get("delta_net_pnl_usd")
            life["stp2_action"] = s.get("action")
        if shadows.get("be33", {}).get("sample"):
            s = shadows["be33"]["sample"]
            life["be33_delta_net_pnl_usd"] = s.get("net_difference_vs_canonical_usd")
            life["be33_final_exit_reason"] = s.get("final_exit_reason")
        rows.append(life)

    # Prefer FULL_STRUCTURAL join for stp2 deltas
    if args.stp2_per_trade.exists():
        stp = pd.read_parquet(args.stp2_per_trade)
        if "policy_family" in stp.columns:
            full = stp[stp["policy_family"] == "FULL_STRUCTURAL"]
            by_id = {str(r.trade_id): r for r in full.itertuples()}
            for life in rows:
                r = by_id.get(str(life["trade_id"]))
                if r is not None:
                    life["stp2_delta_net_pnl_usd"] = getattr(r, "delta_net_pnl_usd", None)
                    life["stp2_action"] = getattr(r, "action", None)

    n = len(rows)
    lifecycle_ok = sum(1 for r in rows if r.get("lifecycle_ok"))
    pnl_ok = sum(1 for r in rows if r.get("pnl_match"))
    auction = None
    if args.auction_summary.exists():
        auction = json.loads(args.auction_summary.read_text(encoding="utf-8"))

    summary = {
        "generated_at": _utc_now(),
        "stage": "ETLL_OUTCOME_RECONCILE_PILOT",
        "status": "ETLL_OUTCOME_RECONCILE_DONE",
        "window": {"from": args.from_ts, "to": args.to_ts},
        "n_lived_trades": n,
        "lifecycle_ok_count": lifecycle_ok,
        "lifecycle_ok_pct": round(100.0 * lifecycle_ok / max(n, 1), 4),
        "pnl_match_count": pnl_ok,
        "pnl_match_pct": round(100.0 * pnl_ok / max(n, 1), 4),
        "stp2_join_rows": sum(1 for r in rows if r.get("shadows", {}).get("stp2", {}).get("rows")),
        "be33_join_rows": sum(1 for r in rows if r.get("shadows", {}).get("be33", {}).get("rows")),
        "auction_summary_present": auction is not None,
        "auction_status": None if auction is None else auction.get("status"),
        "external_trades_used": False,
        "eqcorr_required": False,
        "fidelity_note": "ETLL parquet books + optional shadow pilot joins; not live TRD-OUTCOME2",
        "gate_verdict": "GO" if lifecycle_ok / max(n, 1) >= 0.95 and pnl_ok / max(n, 1) >= 0.95 else "REVIEW",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        # drop nested for parquet
        flat = []
        for r in rows:
            flat.append({k: v for k, v in r.items() if k != "shadows"})
        pd.DataFrame(flat).to_parquet(args.out_dir / "etll_outcome_reconcile_per_trade.parquet", index=False)
    (args.out_dir / "etll_outcome_reconcile_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
