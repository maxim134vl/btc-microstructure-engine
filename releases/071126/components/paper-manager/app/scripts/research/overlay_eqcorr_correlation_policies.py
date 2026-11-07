#!/usr/bin/env python3
"""Chronological overlay of EQCORR correlation policies on the Hybrid tick book.

Why an overlay instead of the engine
------------------------------------
ShadowEconomicCorrelationEngine.poll_once() processes every new entry before any
close. Replaying a finished 6172-trade book through it therefore opens all 6175
virtual positions before the first one is released, so any policy that caps
concurrent same-direction exposure saturates on its first trade and blocks the
next 2.6 years. Confirmed directly: MAX_1_SAME_DIRECTION executed 2023-12-17
00:30 and 05:45 and then blocked every remaining candidate.

Walking the book as an event stream fixes that without touching the engine, and
the policy rules are imported rather than reimplemented so the two cannot drift.

Semantics
---------
* Events are ordered by market time, EXIT before ENTRY on ties. A manager flip
  closes and reopens within one cycle, so the freed slot must be visible to the
  entry that replaces it.
* A blocked trade earns nothing and occupies no slot, which is what makes the
  counterfactual diverge from reality over time.
* EXECUTE_REDUCED scales both the risk carried in the virtual book and the
  realised PnL by the policy's multiplier.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
sys.path.insert(0, str(ROOT))

from btc_ml.trading.shadow_economic_correlation import POLICY_IDS  # noqa: E402
from btc_ml.trading.shadow_economic_correlation.policies import decide_policy  # noqa: E402
from calibration_split import assign_segment  # noqa: E402

STAGE_ROOT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr"
DEFAULT_EPOCH = "ETLL_HYBRID_TICK_V1_20260905_092610"
REPORTED_SEGMENTS = ("train", "validation")
RISK_UNIT = 1000.0

KEY_ORDER = (
    "BASELINE_ALL_ELIGIBLE",
    "MAX_1_SAME_DIRECTION",
    "MAX_2_SAME_DIRECTION",
    "MAX_3_SAME_DIRECTION",
    "ONE_TACTICAL_ONE_STRUCTURAL",
    "PROGRESSIVE_RISK_REDUCTION",
    "DIRECTION_RISK_CAP_025_BLOCK",
    "DIRECTION_RISK_CAP_050_BLOCK",
    "DIRECTION_RISK_CAP_075_BLOCK",
    "DIRECTION_RISK_CAP_100_BLOCK",
    "DIRECTION_RISK_CAP_025_REDUCE",
    "DIRECTION_RISK_CAP_050_REDUCE",
    "DIRECTION_RISK_CAP_075_REDUCE",
    "DIRECTION_RISK_CAP_100_REDUCE",
    "M15_ONLY",
    "M30_ONLY",
    "H1_ONLY",
    "H4_ONLY",
)


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


def build_trade_table(books: Path) -> pd.DataFrame:
    """One row per closed trade with market entry and exit times.

    trades.jsonl has no usable entry time of its own, so the entry moment comes
    from the position's OPEN record.
    """
    trades = pd.DataFrame(read_jsonl(books / "trades.jsonl"))
    positions = read_jsonl(books / "positions.jsonl")

    entry: dict[str, dict[str, Any]] = {}
    for row in positions:
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        pid = str(row.get("position_id") or "")
        if pid and pid not in entry:
            entry[pid] = row

    trades["position_id"] = trades["position_id"].astype(str)
    trades["net_pnl_usd"] = pd.to_numeric(trades["net_pnl_usd"], errors="coerce").fillna(0.0)
    trades["exit_ts"] = pd.to_datetime(
        trades["context_occurrence_timestamp"], utc=True, errors="coerce", format="ISO8601"
    )
    trades["entry_ts"] = pd.to_datetime(
        trades["position_id"].map(lambda p: (entry.get(p) or {}).get("context_occurrence_timestamp")),
        utc=True,
        errors="coerce",
        format="ISO8601",
    )
    trades["timeframe"] = trades["position_id"].map(
        lambda p: str((entry.get(p) or {}).get("timeframe") or "").upper()
    )
    trades["side"] = trades["position_id"].map(
        lambda p: str((entry.get(p) or {}).get("side") or "").upper()
    )
    trades["risk_usd"] = trades["position_id"].map(
        lambda p: float(
            (entry.get(p) or {}).get("risk_budget_usd")
            or (entry.get(p) or {}).get("risk_amount_usd")
            or RISK_UNIT
        )
    )
    trades["segment"] = assign_segment(trades)

    missing = int(trades["entry_ts"].isna().sum())
    if missing:
        print(f"[warn] {missing} trades without an OPEN record; dropped", file=sys.stderr)
        trades = trades.loc[trades["entry_ts"].notna()].copy()
    # An exit cannot precede its entry; guard rather than silently invert a slot.
    bad = int((trades["exit_ts"] < trades["entry_ts"]).sum())
    if bad:
        print(f"[warn] {bad} trades with exit before entry; dropped", file=sys.stderr)
        trades = trades.loc[trades["exit_ts"] >= trades["entry_ts"]].copy()
    return trades.sort_values("entry_ts").reset_index(drop=True)


def drawdown(pnls: list[tuple[pd.Timestamp, float]], start_equity: float) -> dict[str, Any]:
    """Realised-PnL drawdown, ordered by exit time."""
    if not pnls:
        return {"max_dd_usd": 0.0, "max_dd_pct": 0.0, "max_dd_days": 0.0}
    ordered = sorted(pnls, key=lambda x: x[0])
    equity = start_equity
    peak = start_equity
    peak_ts = ordered[0][0]
    max_dd = 0.0
    max_dd_pct = 0.0
    max_dur = 0.0
    for ts, pnl in ordered:
        equity += pnl
        if equity > peak:
            peak = equity
            peak_ts = ts
            continue
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak * 100 if peak else 0.0
        dur = (ts - peak_ts).total_seconds() / 86400.0
        if dur > max_dur:
            max_dur = dur
    return {
        "max_dd_usd": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "max_dd_days": round(max_dur, 2),
    }


def run_policy(policy_id: str, trades: pd.DataFrame, *, segments: tuple[str, ...]) -> dict[str, Any]:
    events: list[tuple[pd.Timestamp, int, int]] = []
    for i, row in enumerate(trades.itertuples(index=False)):
        # 0 sorts before 1, so an exit frees its slot before same-instant entries.
        events.append((row.exit_ts, 0, i))
        events.append((row.entry_ts, 1, i))
    events.sort(key=lambda e: (e[0], e[1]))

    open_slots: dict[int, dict[str, Any]] = {}
    executed: list[tuple[pd.Timestamp, float]] = []
    blocked_pnl: list[float] = []
    reasons: dict[str, int] = {}
    n_reduced = 0
    peak_same = 0

    for _ts, kind, idx in events:
        if kind == 0:
            open_slots.pop(idx, None)
            continue

        row = trades.iloc[idx]
        candidate = {
            "side": row.side,
            "timeframe": row.timeframe,
            "risk_budget_usd": float(row.risk_usd),
        }
        decision = decide_policy(
            policy_id=policy_id,
            candidate=candidate,
            cluster={},
            policy_open_positions=list(open_slots.values()),
        )
        reasons[decision.reason] = reasons.get(decision.reason, 0) + 1

        in_scope = row.segment in segments
        if decision.action in {"EXECUTE_FULL", "EXECUTE_REDUCED"}:
            mult = float(decision.risk_multiplier)
            if decision.action == "EXECUTE_REDUCED":
                n_reduced += 1
            open_slots[idx] = {
                "side": row.side,
                "timeframe": row.timeframe,
                "risk_amount_usd": float(row.risk_usd) * mult,
            }
            same = sum(1 for p in open_slots.values() if p["side"] == row.side)
            peak_same = max(peak_same, same)
            if in_scope:
                executed.append((row.exit_ts, float(row.net_pnl_usd) * mult))
        elif in_scope:
            blocked_pnl.append(float(row.net_pnl_usd))

    pnls = [p for _t, p in executed]
    s = pd.Series(pnls, dtype=float) if pnls else pd.Series(dtype=float)
    wins = s[s > 0]
    losses = s[s < 0]
    risk_deployed = sum(1 for _ in pnls) * RISK_UNIT
    out: dict[str, Any] = {
        "executed_n": int(len(s)),
        "blocked_n": int(len(blocked_pnl)),
        "reduced_n": n_reduced,
        "block_rate_pct": round(
            len(blocked_pnl) / (len(s) + len(blocked_pnl)) * 100, 2
        )
        if (len(s) + len(blocked_pnl))
        else None,
        "wr_pct": round(float((s > 0).mean()) * 100, 2) if len(s) else None,
        "net_pnl_usd": round(float(s.sum()), 2) if len(s) else 0.0,
        "expectancy_r": round(float(s.sum()) / risk_deployed, 4) if risk_deployed else None,
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3)
        if len(losses) and losses.sum()
        else None,
        "forgone_pnl_usd": round(float(sum(blocked_pnl)), 2),
        "peak_same_direction_open": peak_same,
        "top_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:3]),
    }
    out.update(drawdown(executed, start_equity=100_000.0))
    if out["max_dd_usd"]:
        out["return_over_maxdd"] = round(out["net_pnl_usd"] / out["max_dd_usd"], 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    parser.add_argument("--out-name", default="eqcorr_correlation_overlay.json")
    args = parser.parse_args()

    books = STAGE_ROOT / "paper_repo/data/trading/intrabar_paper" / args.epoch_id / "books"
    trades = build_trade_table(books)
    scope = trades.loc[trades["segment"].isin(REPORTED_SEGMENTS)]

    results = {p: run_policy(p, trades, segments=REPORTED_SEGMENTS) for p in POLICY_IDS}
    base = results["BASELINE_ALL_ELIGIBLE"]
    for entry in results.values():
        entry["pnl_vs_baseline_usd"] = round(
            float(entry["net_pnl_usd"]) - float(base["net_pnl_usd"]), 2
        )

    summary = {
        "stage": "ETLL_EQCORR_CORRELATION_OVERLAY",
        "epoch_id": args.epoch_id,
        "method": "chronological event replay of the immutable Hybrid book; rules imported from policies.decide_policy",
        "book_trades": int(len(trades)),
        "scope_segments": list(REPORTED_SEGMENTS),
        "scope_trades": int(len(scope)),
        "holdout_status": "SEALED — not evaluated",
        "risk_unit_usd": RISK_UNIT,
        "policies": results,
    }
    out_dir = STAGE_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / args.out_name
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    print(f"\nEQCORR correlation overlay — {args.epoch_id}")
    print(f"scope: train+validation, {len(scope)} of {len(trades)} trades   (holdout sealed)\n")
    hdr = (
        f"{'policy':<30}{'exec':>6}{'blk%':>6}{'WR%':>6}{'expR':>7}{'PF':>7}"
        f"{'net_pnl':>12}{'vs_base':>12}{'maxDD':>10}{'DDd':>7}{'pk':>4}"
    )
    print(hdr)
    print("-" * len(hdr))
    for p in KEY_ORDER:
        r = results[p]
        print(
            f"{p:<30}{r['executed_n']:>6}{r['block_rate_pct'] or 0:>6.1f}"
            f"{r['wr_pct'] or 0:>6.1f}{r['expectancy_r'] or 0:>7.3f}"
            f"{r['profit_factor'] or 0:>7.2f}{r['net_pnl_usd']:>12,.0f}"
            f"{r['pnl_vs_baseline_usd']:>12,.0f}{r['max_dd_usd']:>10,.0f}"
            f"{r['max_dd_days']:>7.1f}{r['peak_same_direction_open']:>4}"
        )
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
