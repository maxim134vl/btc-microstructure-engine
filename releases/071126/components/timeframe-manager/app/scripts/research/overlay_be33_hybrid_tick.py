#!/usr/bin/env python3
"""BE33 overlay on the canonical Hybrid tick book (all timeframes).

BE33 takes 1/3 of the position at 1/3 of the distance to target, then moves the
stop on the remaining 2/3 to economic break-even (the exit price at which the
trade nets zero after fees, solved by inverting closed_trade_economics).

Unlike the correlation policies this cannot be decided from entry/exit levels: the
outcome depends on which level the price path touches first, so each trade is
replayed against its exact aggTrade path. The policy never changes which trades
exist, though, so it is a true overlay on the immutable book — no re-simulation.

The existing pilot (run_etll_stp_be33_lived.py) walks ticks one at a time over a
single-month M15 universe. Here the same rules are applied to 6172 trades spanning
2.6 years, so barrier crossings are located with vectorised comparisons and only
the crossing ticks are inspected: at most two searches per trade instead of one
pass per tick.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
sys.path.insert(0, str(ROOT))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics  # noqa: E402
from btc_ml.trading.shadow_structural_protection.be33 import (  # noqa: E402
    partial_trigger_price,
    solve_economic_break_even,
)
from btc_ml.trading.shadow_structural_protection.tick_cache import TickHourCache  # noqa: E402
from calibration_split import assign_segment  # noqa: E402

STAGE_ROOT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr"
DEFAULT_EPOCH = "ETLL_HYBRID_TICK_V1_20260905_092610"
DEFAULT_TICK_REPO = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_full_etll/repo")
REPORTED_SEGMENTS = ("train", "validation")
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


def build_trades(books: Path) -> pd.DataFrame:
    """Closed trades joined to their OPEN position row for entry time and levels."""
    trades = pd.DataFrame(read_jsonl(books / "trades.jsonl"))
    opens: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(books / "positions.jsonl"):
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        pid = str(row.get("position_id") or "")
        if pid and pid not in opens:
            opens[pid] = row

    trades["position_id"] = trades["position_id"].astype(str)

    def pick(field: str) -> pd.Series:
        return trades["position_id"].map(lambda p: (opens.get(p) or {}).get(field))

    trades["entry_ts"] = pd.to_datetime(
        pick("context_occurrence_timestamp"), utc=True, errors="coerce", format="ISO8601"
    )
    trades["exit_ts"] = pd.to_datetime(
        trades["context_occurrence_timestamp"], utc=True, errors="coerce", format="ISO8601"
    )
    trades["timeframe"] = pick("timeframe").astype(str).str.upper()
    trades["side"] = pick("side").astype(str).str.upper()
    for col, field in (
        ("entry_price", "entry_price"),
        ("stop_loss_price", "stop_loss_price"),
        ("take_profit_price", "take_profit_price"),
        ("quantity", "quantity"),
        ("risk_amount_usd", "risk_amount_usd"),
    ):
        trades[col] = pd.to_numeric(pick(field), errors="coerce")
    trades["exit_price"] = pd.to_numeric(trades.get("exit_price"), errors="coerce")
    trades["net_pnl_usd"] = pd.to_numeric(trades.get("net_pnl_usd"), errors="coerce").fillna(0.0)
    trades["segment"] = assign_segment(trades)

    need = ["entry_ts", "exit_ts", "entry_price", "stop_loss_price", "take_profit_price", "quantity"]
    before = len(trades)
    trades = trades.dropna(subset=need)
    trades = trades.loc[trades["exit_ts"] > trades["entry_ts"]]
    dropped = before - len(trades)
    if dropped:
        print(f"[warn] dropped {dropped} trades lacking levels or with non-positive duration")
    return trades.sort_values("entry_ts").reset_index(drop=True)


def _first_hit(prices: np.ndarray, *, side: str, stop: float, trigger: float | None, take: float) -> tuple[int, str] | None:
    """Index and kind of the first tick touching stop / partial trigger / take.

    Precedence at a single tick is stop, then trigger, then take, matching the
    sequential pilot implementation: a tick that spans several levels is resolved
    the same way whichever scan finds it.
    """
    if not len(prices):
        return None
    if side == "LONG":
        m_stop = prices <= stop
        m_take = prices >= take
        m_trig = prices >= trigger if trigger is not None else None
    else:
        m_stop = prices >= stop
        m_take = prices <= take
        m_trig = prices <= trigger if trigger is not None else None

    mask = m_stop | m_take if m_trig is None else (m_stop | m_trig | m_take)
    if not mask.any():
        return None
    i = int(np.argmax(mask))
    if m_stop[i]:
        return i, "STOP"
    if m_trig is not None and m_trig[i]:
        return i, "TRIGGER"
    return i, "TAKE"


def simulate(trade: Any, *, prices: np.ndarray, ts_ns: np.ndarray, cfg: Any) -> dict[str, Any]:
    side = str(trade.side).upper()
    entry = float(trade.entry_price)
    stop = float(trade.stop_loss_price)
    take = float(trade.take_profit_price)
    qty = float(trade.quantity)
    risk = abs(entry - stop) * qty
    if risk <= 0:
        risk = float(trade.risk_amount_usd or RISK_UNIT)
    partial_qty = qty / 3.0
    remain_qty = qty - partial_qty
    trigger = partial_trigger_price(side=side, entry_price=entry, take_price=take)

    can_pnl = float(trade.net_pnl_usd)
    out: dict[str, Any] = {
        "trade_id": getattr(trade, "trade_id", None),
        "position_id": trade.position_id,
        "timeframe": trade.timeframe,
        "side": side,
        "segment": trade.segment,
        "canonical_net_pnl_usd": can_pnl,
        "partial_taken": False,
        "path_ticks": int(len(prices)),
        "evaluated": True,
        "skip_reason": None,
    }
    if not len(prices):
        out.update(
            {
                "evaluated": False,
                "skip_reason": "NO_AGG_PATH",
                "final_exit_reason": "CANONICAL_EXIT_NO_PATH",
                "total_net_pnl_usd": can_pnl,
                "net_difference_vs_canonical_usd": 0.0,
            }
        )
        return out

    hit = _first_hit(prices, side=side, stop=stop, trigger=trigger, take=take)

    def econ(exit_price: float, quantity: float, reason: str) -> float:
        e = closed_trade_economics(
            cfg=cfg,
            side=side,
            entry_price=entry,
            exit_price=exit_price,
            quantity=quantity,
            risk_amount_usd=risk * (quantity / qty),
            exit_reason=reason,
        )
        return float(e["net_pnl_usd"])

    if hit is None:
        out.update(
            {
                "final_exit_reason": "CANONICAL_EXIT_BEFORE_PARTIAL",
                "total_net_pnl_usd": can_pnl,
                "net_difference_vs_canonical_usd": 0.0,
            }
        )
        return out

    idx, kind = hit
    if kind == "STOP":
        total = econ(stop, qty, "SL")
        out.update(
            {
                "final_exit_reason": "SL",
                "final_exit_price": stop,
                "total_net_pnl_usd": total,
                "net_difference_vs_canonical_usd": total - can_pnl,
            }
        )
        return out
    if kind == "TAKE":
        total = econ(take, qty, "TP")
        out.update(
            {
                "final_exit_reason": "TP",
                "final_exit_price": take,
                "total_net_pnl_usd": total,
                "net_difference_vs_canonical_usd": total - can_pnl,
            }
        )
        return out

    # Partial filled: bank 1/3 at the trigger, then trail the rest at economic BE.
    partial_net = econ(trigger, partial_qty, "PARTIAL_TAKE")
    be_price, _ = solve_economic_break_even(
        cfg=cfg,
        side=side,
        entry_price=entry,
        quantity=remain_qty,
        risk_amount_usd=risk * (remain_qty / qty),
    )
    be_price = float(be_price)
    out.update(
        {
            "partial_taken": True,
            "partial_trigger_price": trigger,
            "partial_net_pnl_usd": round(partial_net, 4),
            "economic_break_even_price": be_price,
            "partial_trigger_ts": str(pd.Timestamp(int(ts_ns[idx]), tz="UTC")),
        }
    )

    rest = prices[idx + 1 :]
    hit2 = _first_hit(rest, side=side, stop=be_price, trigger=None, take=take)
    if hit2 is None:
        total = partial_net + econ(float(trade.exit_price or entry), remain_qty, "CANONICAL_EXIT")
        out.update(
            {
                "final_exit_reason": "CANONICAL_EXIT_AFTER_PARTIAL",
                "total_net_pnl_usd": total,
                "net_difference_vs_canonical_usd": total - can_pnl,
            }
        )
        return out

    j, kind2 = hit2
    if kind2 == "STOP":
        total = partial_net + econ(be_price, remain_qty, "SL")
        reason = "BE_STOP"
        price = be_price
    else:
        total = partial_net + econ(take, remain_qty, "TP")
        reason = "TP_AFTER_PARTIAL"
        price = take
    out.update(
        {
            "final_exit_reason": reason,
            "final_exit_price": price,
            "final_exit_ts": str(pd.Timestamp(int(ts_ns[idx + 1 + j]), tz="UTC")),
            "total_net_pnl_usd": total,
            "net_difference_vs_canonical_usd": total - can_pnl,
        }
    )
    return out


def bucket(pnls: list[float]) -> dict[str, Any]:
    if not pnls:
        return {"n": 0}
    s = pd.Series(pnls, dtype=float)
    wins = s[s > 0]
    losses = s[s < 0]
    return {
        "n": int(len(s)),
        "wr_pct": round(float((s > 0).mean()) * 100, 2),
        "net_pnl_usd": round(float(s.sum()), 2),
        "expectancy_r": round(float(s.mean()) / RISK_UNIT, 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3)
        if len(losses) and losses.sum()
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    parser.add_argument("--tick-repo", type=Path, default=DEFAULT_TICK_REPO)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-name", default="be33_overlay_hybrid.json")
    args = parser.parse_args()

    books = STAGE_ROOT / "paper_repo/data/trading/intrabar_paper" / args.epoch_id / "books"
    trades = build_trades(books)
    if args.limit:
        trades = trades.head(int(args.limit)).copy()

    cfg = load_intrabar_paper_config(ROOT / "config" / "intrabar_paper_execution.json", repo_root=ROOT)
    ticks = TickHourCache(repo=args.tick_repo, symbol="BTCUSDT", max_hours=12)

    rows: list[dict[str, Any]] = []
    started = time.time()
    for n, trade in enumerate(trades.itertuples(index=False), start=1):
        ts_ns, prices, _ids = ticks.window(start=trade.entry_ts, end=trade.exit_ts)
        if len(ts_ns):
            # Match the pilot: the canonical exit tick itself is not tradable.
            cut = int(np.searchsorted(ts_ns, int(pd.Timestamp(trade.exit_ts).value), side="left"))
            ts_ns, prices = ts_ns[:cut], prices[:cut]
        rows.append(simulate(trade, prices=prices, ts_ns=ts_ns, cfg=cfg))
        if n % 500 == 0:
            print(
                f"[be33] {n}/{len(trades)} elapsed={time.time() - started:.0f}s "
                f"hours_loaded={ticks.stats()['hour_loads']}",
                flush=True,
            )
    elapsed = time.time() - started

    frame = pd.DataFrame(rows)
    scope = frame.loc[frame["segment"].isin(REPORTED_SEGMENTS)]
    evaluated = scope.loc[scope["evaluated"]]

    summary = {
        "stage": "ETLL_BE33_OVERLAY_HYBRID_TICK",
        "epoch_id": args.epoch_id,
        "method": "exact aggTrade path per trade; BE33 rules from shadow_structural_protection.be33",
        "elapsed_s": round(elapsed, 1),
        "tick_cache": ticks.stats(),
        "trades_total": int(len(frame)),
        "scope_segments": list(REPORTED_SEGMENTS),
        "holdout_status": "SEALED — not evaluated",
        "trades_in_scope": int(len(scope)),
        "evaluated": int(len(evaluated)),
        "no_tick_path": int((~scope["evaluated"]).sum()),
        "partial_taken_n": int(evaluated["partial_taken"].sum()),
        "partial_rate_pct": round(float(evaluated["partial_taken"].mean()) * 100, 2)
        if len(evaluated)
        else None,
        "canonical": bucket(evaluated["canonical_net_pnl_usd"].tolist()),
        "be33": bucket(evaluated["total_net_pnl_usd"].tolist()),
        "net_delta_usd": round(
            float(evaluated["total_net_pnl_usd"].sum() - evaluated["canonical_net_pnl_usd"].sum()), 2
        ),
        "final_exit_reasons": {
            str(k): int(v) for k, v in evaluated["final_exit_reason"].value_counts().items()
        },
        "by_timeframe": {
            tf: {
                "n": int(len(g)),
                "canonical_pnl": round(float(g["canonical_net_pnl_usd"].sum()), 2),
                "be33_pnl": round(float(g["total_net_pnl_usd"].sum()), 2),
                "delta": round(float((g["total_net_pnl_usd"] - g["canonical_net_pnl_usd"]).sum()), 2),
                "partial_rate_pct": round(float(g["partial_taken"].mean()) * 100, 2),
            }
            for tf, g in evaluated.groupby("timeframe")
        },
    }

    out_dir = STAGE_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / args.out_name).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    frame.to_parquet(out_dir / args.out_name.replace(".json", "_trades.parquet"), index=False)

    print(f"\nBE33 overlay — {args.epoch_id}")
    print(f"scope: train+validation, {len(evaluated)} evaluated of {len(scope)}   (holdout sealed)")
    print(f"partial taken: {summary['partial_taken_n']} ({summary['partial_rate_pct']}%)\n")
    c, b = summary["canonical"], summary["be33"]
    print(f"{'variant':<14}{'n':>6}{'WR%':>8}{'expR':>9}{'PF':>8}{'net_pnl':>14}")
    print("-" * 59)
    print(
        f"{'canonical':<14}{c['n']:>6}{c['wr_pct']:>8.1f}{c['expectancy_r']:>9.3f}"
        f"{c['profit_factor'] or 0:>8.2f}{c['net_pnl_usd']:>14,.0f}"
    )
    print(
        f"{'BE33':<14}{b['n']:>6}{b['wr_pct']:>8.1f}{b['expectancy_r']:>9.3f}"
        f"{b['profit_factor'] or 0:>8.2f}{b['net_pnl_usd']:>14,.0f}"
    )
    print(f"\ndelta: {summary['net_delta_usd']:+,.0f} USD")
    print(f"exit reasons: {summary['final_exit_reasons']}")
    print(f"\nwritten: {out_dir / args.out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
