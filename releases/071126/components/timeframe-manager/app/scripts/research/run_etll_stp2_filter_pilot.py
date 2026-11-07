#!/usr/bin/env python3
"""ETLL STP2 filter-pass pilot on lived M15 trades + exact aggTrade tick pack.

Observe-only. Unit of analysis = lived trade_id.
Does not mutate live trading / live STP stores.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
# parquet_utils sits at the repo root and is imported as a top-level module by the
# cognition chain that intrabar_paper.config pulls in.
sys.path.insert(0, str(ROOT))

from btc_ml.trading.shadow_structural_protection import DEFAULT_TICK_SIZE  # noqa: E402
from btc_ml.trading.shadow_structural_protection.catalog import (  # noqa: E402
    build_candidate_catalog,
    select_usable_zone,
)
from btc_ml.trading.shadow_structural_protection.coverage import policy_family  # noqa: E402
from btc_ml.trading.shadow_structural_protection.engine import reaction_is_proven  # noqa: E402
from btc_ml.trading.shadow_structural_protection.policies import (  # noqa: E402
    POLICY_SPECS,
    geometry_valid,
    structural_stop_price,
    structural_take_price,
)
from btc_ml.trading.shadow_structural_protection.timeutil import parse_ts  # noqa: E402
from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades  # noqa: E402

DEFAULT_UNIVERSE = (
    ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/pilot_trade_universe.json"
)
DEFAULT_TICK_REPO = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/stp2_pilot/tick_pack_202606/repo"
)
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot"
DEFAULT_MANIFEST = DEFAULT_OUT / "tick_pack_manifest.json"

# Preferred live-aligned sleeves only (one policy per family). Full matrix is too heavy for pilot.
PREFERRED_POLICY_IDS = (
    "BASELINE_CANONICAL",
    (
        "STRUCTURAL_SL_CANONICAL_TP__ALL_CANONICAL_SIGNIFICANT__POC_VALUE_AREA_70"
        "__MAX_ONE_TICK_OR_SPREAD__REACTION_100_ZONE_WIDTH__ZONE_AGE_4_BARS"
    ),
    (
        "CANONICAL_SL_STRUCTURAL_TP__ALL_CANONICAL_SIGNIFICANT__POC_VALUE_AREA_70"
        "__TARGET_POC__REACTION_100_ZONE_WIDTH__ZONE_AGE_4_BARS"
    ),
    (
        "STRUCTURAL_SL_STRUCTURAL_TP_NO_GATE__ALL_CANONICAL_SIGNIFICANT__POC_VALUE_AREA_70"
        "__MAX_ONE_TICK_OR_SPREAD__TARGET_POC__REACTION_100_ZONE_WIDTH__ZONE_AGE_4_BARS"
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _side_sign(side: str) -> float:
    return 1.0 if str(side).upper() == "LONG" else -1.0


def _pnl_usd(
    *,
    side: str,
    entry: float,
    exit_price: float,
    qty: float,
    fees_usd: float,
) -> float:
    return _side_sign(side) * (float(exit_price) - float(entry)) * float(qty) - float(fees_usd)


def _r_multiple(*, side: str, entry: float, exit_price: float, stop: float) -> float | None:
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return None
    return _side_sign(side) * (float(exit_price) - float(entry)) / risk


def _fees_for_exit(
    *,
    fees_canonical: float,
    entry: float,
    exit_canonical: float,
    exit_structural: float,
    qty: float,
) -> float:
    """Scale lived round-trip fees by exit notional ratio (same fee rate)."""
    denom = abs(float(entry) * float(qty)) + abs(float(exit_canonical) * float(qty))
    if denom <= 0:
        return float(fees_canonical)
    rate = float(fees_canonical) / denom
    return rate * (abs(float(entry) * float(qty)) + abs(float(exit_structural) * float(qty)))


def _first_agg_hit(
    *,
    side: str,
    stop: float,
    take: float,
    path: pd.DataFrame,
) -> tuple[float, str, str] | None:
    if path is None or path.empty:
        return None
    side_u = str(side).upper()
    # Row-wise this was ~30% of a pass. The scan only needs the first index where
    # either barrier is touched, with stop winning a tick that spans both — which
    # is exactly what the sequential form did by testing stop first.
    prices = path["price"].to_numpy(dtype="float64", copy=False)
    if side_u == "LONG":
        hit_stop = prices <= stop
        hit_take = prices >= take
    else:
        hit_stop = prices >= stop
        hit_take = prices <= take
    mask = hit_stop | hit_take
    if not mask.any():
        return None
    i = int(np.argmax(mask))
    ts = pd.DatetimeIndex(path["_ts"])[i]
    ts_s = ts.isoformat().replace("+00:00", "Z") if hasattr(ts, "isoformat") else str(ts)
    return float(prices[i]), ("STOP_LOSS" if hit_stop[i] else "TAKE_PROFIT"), ts_s


def _preferred_specs() -> list[Any]:
    by_id = {p.policy_id: p for p in POLICY_SPECS}
    missing = [pid for pid in PREFERRED_POLICY_IDS if pid not in by_id]
    if missing:
        raise RuntimeError(f"preferred policy ids missing from POLICY_SPECS: {missing}")
    return [by_id[pid] for pid in PREFERRED_POLICY_IDS]


def _decide_levels(
    *,
    spec: Any,
    side: str,
    entry: float,
    canonical_stop: float,
    canonical_take: float,
    zones: list[dict[str, Any]],
    decision_ts: datetime,
    timeframe: str,
    causal_history_ok: bool,
) -> dict[str, Any]:
    family = policy_family(spec.policy_id)
    out: dict[str, Any] = {
        "policy_id": spec.policy_id,
        "policy_family": family,
        "action": None,
        "skip_reason": None,
        "structural_sl_price": None,
        "structural_tp_price": None,
        "protective_usable": False,
        "target_usable": False,
        "zones_detected": len(zones),
    }
    if spec.kind != "BASELINE" and not causal_history_ok:
        out["action"] = "SKIP_INSUFFICIENT_CAUSAL_HISTORY"
        out["skip_reason"] = "INSUFFICIENT_CAUSAL_HISTORY"
        return out

    if spec.kind == "BASELINE":
        out["action"] = "EXECUTE_STRUCTURAL"
        out["structural_sl_price"] = float(canonical_stop)
        out["structural_tp_price"] = float(canonical_take)
        return out

    needs_prot = spec.kind in {"STRUCTURAL_SL_STRUCTURAL_TP", "STRUCTURAL_SL_CANONICAL_TP"}
    needs_targ = spec.kind in {"STRUCTURAL_SL_STRUCTURAL_TP", "CANONICAL_SL_STRUCTURAL_TP"}
    react_id = str(spec.reaction_threshold_id or "REACTION_100_ZONE_WIDTH")
    age_id = str(spec.zone_age_policy or "ZONE_AGE_4_BARS")
    stop = float(canonical_stop)
    take = float(canonical_take)

    if needs_prot:
        prot, prot_react, prot_usable = select_usable_zone(
            zones=zones,
            role="PROTECTIVE",
            side=side,
            entry=entry,
            volume_class_policy=str(spec.volume_class_policy),
            zone_method=str(spec.zone_method),
            reaction_threshold_id=react_id,
            zone_age_policy=age_id,
            decision_ts=decision_ts,
            timeframe=timeframe,
        )
        out["protective_usable"] = bool(prot_usable and reaction_is_proven(prot_react))
        if prot is None:
            out["action"] = "SKIP_NO_PROTECTIVE_ZONE"
            out["skip_reason"] = "SKIP_NO_PROTECTIVE_ZONE"
            return out
        if not out["protective_usable"]:
            out["action"] = "SKIP_NO_REACTION_PROOF"
            out["skip_reason"] = f"PROTECTIVE_{prot_react.get('status')}"
            return out
        stop = structural_stop_price(
            side=side,
            zone=prot,
            buffer_policy=str(spec.buffer_policy),
            tick_size=DEFAULT_TICK_SIZE,
            executable_spread=None,
        )

    if needs_targ:
        targ, targ_react, targ_usable = select_usable_zone(
            zones=zones,
            role="TARGET",
            side=side,
            entry=entry,
            volume_class_policy=str(spec.volume_class_policy),
            zone_method=str(spec.zone_method),
            reaction_threshold_id=react_id,
            zone_age_policy=age_id,
            decision_ts=decision_ts,
            timeframe=timeframe,
        )
        out["target_usable"] = bool(targ_usable and reaction_is_proven(targ_react))
        if targ is None:
            out["action"] = "SKIP_NO_TARGET_ZONE"
            out["skip_reason"] = "SKIP_NO_TARGET_ZONE"
            return out
        if not out["target_usable"]:
            out["action"] = "SKIP_NO_REACTION_PROOF"
            out["skip_reason"] = f"TARGET_{targ_react.get('status')}"
            return out
        take = structural_take_price(side=side, zone=targ, take_policy=str(spec.take_policy))

    ok_geo, geo_reason = geometry_valid(side=side, entry=entry, stop=stop, take=take)
    if not ok_geo:
        out["action"] = str(geo_reason)
        out["skip_reason"] = str(geo_reason)
        return out

    out["action"] = "EXECUTE_STRUCTURAL"
    out["structural_sl_price"] = float(stop)
    out["structural_tp_price"] = float(take)
    return out


def _simulate_row(
    *,
    trade: dict[str, Any],
    decision: dict[str, Any],
    path: pd.DataFrame,
) -> dict[str, Any]:
    side = trade["side"]
    entry = float(trade["entry_price"])
    qty = float(trade["quantity"])
    fees_c = float(trade.get("fees_usd") or 0.0)
    can_exit = float(trade["exit_price"])
    can_ts = str(trade["exit_ts"])
    can_reason = str(trade.get("exit_reason") or "CANONICAL_EXIT")
    can_pnl = float(trade["net_pnl_usd"])
    can_r = trade.get("r_multiple")
    can_stop = float(trade["stop_loss_price"])

    row: dict[str, Any] = {
        "trade_id": trade["trade_id"],
        "position_id": trade.get("position_id"),
        "timeframe": trade.get("timeframe", "M15"),
        "side": side,
        "entry_ts": trade["entry_ts"],
        "entry_price": entry,
        "quantity": qty,
        "policy_id": decision["policy_id"],
        "policy_family": decision["policy_family"],
        "fidelity": "EXACT_AGG_TRADE",
        "canonical_exit_ts": can_ts,
        "canonical_exit_price": can_exit,
        "canonical_exit_reason": can_reason,
        "canonical_net_pnl_usd": can_pnl,
        "canonical_r_multiple": can_r,
        "structural_sl_price": decision.get("structural_sl_price"),
        "structural_tp_price": decision.get("structural_tp_price"),
        "zones_detected": decision.get("zones_detected"),
        "protective_usable": decision.get("protective_usable"),
        "target_usable": decision.get("target_usable"),
        "lookahead_violation": False,
        "action": decision.get("action"),
        "skip_reason": decision.get("skip_reason"),
        "evaluated": decision.get("evaluated", False),
        "age_eligible_significant_count": decision.get("age_eligible_significant_count"),
        "causal_history_ok": decision.get("causal_history_ok"),
    }

    if decision.get("action") != "EXECUTE_STRUCTURAL":
        row.update(
            {
                "structural_exit_ts": can_ts,
                "structural_exit_price": can_exit,
                "structural_exit_reason": "CANONICAL_EXIT_NO_STRUCTURAL_LEVELS",
                "structural_net_pnl_usd": can_pnl,
                "structural_r_multiple": can_r,
                "delta_net_pnl_usd": 0.0,
                "delta_r_multiple": 0.0,
            }
        )
        return row

    # BASELINE sleeve mirrors lived exit exactly (filter overlay identity).
    if decision.get("policy_family") == "BASELINE":
        row.update(
            {
                "structural_exit_ts": can_ts,
                "structural_exit_price": can_exit,
                "structural_exit_reason": "BASELINE_CANONICAL_EXIT",
                "structural_net_pnl_usd": can_pnl,
                "structural_r_multiple": can_r,
                "delta_net_pnl_usd": 0.0,
                "delta_r_multiple": 0.0,
            }
        )
        return row

    stop = float(decision["structural_sl_price"])
    take = float(decision["structural_tp_price"])
    hit = _first_agg_hit(side=side, stop=stop, take=take, path=path)
    if hit is None:
        exit_px, exit_reason, exit_ts = can_exit, "CANONICAL_EXIT_NO_STRUCTURAL_HIT", can_ts
    else:
        exit_px, exit_reason, exit_ts = hit[0], hit[1], hit[2]
        # Lookahead: structural exit after canonical exit is invalid for this overlay.
        if parse_ts(exit_ts) and parse_ts(can_ts) and parse_ts(exit_ts) > parse_ts(can_ts):
            row["lookahead_violation"] = True
            exit_px, exit_reason, exit_ts = can_exit, "CANONICAL_EXIT_LOOKAHEAD_GUARD", can_ts

    fees = _fees_for_exit(
        fees_canonical=fees_c,
        entry=entry,
        exit_canonical=can_exit,
        exit_structural=exit_px,
        qty=qty,
    )
    st_pnl = _pnl_usd(side=side, entry=entry, exit_price=exit_px, qty=qty, fees_usd=fees)
    st_r = _r_multiple(side=side, entry=entry, exit_price=exit_px, stop=stop)
    can_r_f = float(can_r) if can_r is not None else None
    row.update(
        {
            "structural_exit_ts": exit_ts,
            "structural_exit_price": exit_px,
            "structural_exit_reason": exit_reason,
            "structural_net_pnl_usd": st_pnl,
            "structural_r_multiple": st_r,
            "delta_net_pnl_usd": st_pnl - can_pnl,
            "delta_r_multiple": (None if st_r is None or can_r_f is None else st_r - can_r_f),
            # risk reference for R uses structural stop when available else canonical
            "risk_stop_used": stop if stop else can_stop,
        }
    )
    return row


def evaluate_trade(
    *,
    trade: dict[str, Any],
    repo: Path,
    specs: list[Any],
    trade_cache: dict | None,
) -> list[dict[str, Any]]:
    decision_ts = parse_ts(trade["entry_ts"])
    exit_ts = parse_ts(trade["exit_ts"])
    if decision_ts is None or exit_ts is None:
        return [
            {
                "trade_id": trade["trade_id"],
                "evaluated": False,
                "skip_reason": "BAD_TIMESTAMPS",
                "fidelity": "EXACT_AGG_TRADE",
                "policy_id": spec.policy_id,
                "policy_family": policy_family(spec.policy_id),
                "lookahead_violation": False,
                "canonical_net_pnl_usd": trade.get("net_pnl_usd"),
                "delta_net_pnl_usd": 0.0,
            }
            for spec in specs
        ]

    catalog = build_candidate_catalog(
        repo=repo,
        timeframe=str(trade.get("timeframe") or "M15"),
        side=str(trade["side"]),
        decision_ts=decision_ts,
        entry=float(trade["entry_price"]),
        trade_cache=trade_cache,
    )
    lookback = catalog.get("lookback_coverage") or {}
    causal_ok = bool(lookback.get("coverage_ok"))
    zones = catalog.get("zones") or []
    age_elig = catalog.get("age_eligible_significant_count")
    evaluated = True
    base_skip = None
    if not causal_ok:
        base_skip = "INSUFFICIENT_CAUSAL_HISTORY"
        # Still mark evaluated for Gate A only when catalog ran; insufficient history counts as skip.
        evaluated = False

    # Path for hit detection: entry → canonical exit (inclusive).
    path = load_agg_trades(repo=repo, start=decision_ts, end=exit_ts)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        decision = _decide_levels(
            spec=spec,
            side=str(trade["side"]),
            entry=float(trade["entry_price"]),
            canonical_stop=float(trade["stop_loss_price"]),
            canonical_take=float(trade["take_profit_price"]),
            zones=zones,
            decision_ts=decision_ts,
            timeframe=str(trade.get("timeframe") or "M15"),
            causal_history_ok=causal_ok,
        )
        decision["evaluated"] = evaluated if spec.kind == "BASELINE" or causal_ok else False
        decision["age_eligible_significant_count"] = age_elig
        decision["causal_history_ok"] = causal_ok
        if base_skip and spec.kind != "BASELINE" and decision.get("action") != "EXECUTE_STRUCTURAL":
            decision["skip_reason"] = decision.get("skip_reason") or base_skip
        row = _simulate_row(trade=trade, decision=decision, path=path)
        rows.append(row)
    return rows


def _summarize(
    rows: list[dict[str, Any]],
    *,
    n_lived: int,
    tick_coverage_pct: float,
    runtime_s: float,
    smoke: bool,
) -> dict[str, Any]:
    # Gate metrics on unique trade_id using preferred FULL family if present else any
    by_trade: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_trade.setdefault(str(r["trade_id"]), []).append(r)

    evaluated_ids = {
        tid
        for tid, rs in by_trade.items()
        if any(bool(r.get("evaluated")) or r.get("causal_history_ok") for r in rs)
        or any(r.get("policy_family") == "BASELINE" and r.get("action") == "EXECUTE_STRUCTURAL" for r in rs)
    }
    # Prefer: trade evaluable if catalog causal ok on any non-baseline attempt or baseline always
    evaluated_ids = set()
    skipped_ids = set()
    skip_reason_counts: dict[str, int] = {}
    for tid, rs in by_trade.items():
        non_base = [r for r in rs if r.get("policy_family") != "BASELINE"]
        causal_ok = any(r.get("causal_history_ok") for r in rs)
        if causal_ok or any(r.get("evaluated") for r in rs):
            evaluated_ids.add(tid)
        else:
            skipped_ids.add(tid)
            reason = next((r.get("skip_reason") for r in non_base if r.get("skip_reason")), "UNKNOWN")
            skip_reason_counts[str(reason)] = skip_reason_counts.get(str(reason), 0) + 1

    def _family_block(family: str) -> dict[str, Any]:
        fr = [r for r in rows if r.get("policy_family") == family]
        exec_rows = [r for r in fr if r.get("action") == "EXECUTE_STRUCTURAL"]
        usable_sl = sum(1 for r in fr if r.get("protective_usable"))
        usable_tp = sum(1 for r in fr if r.get("target_usable"))
        usable_both = sum(1 for r in fr if r.get("protective_usable") and r.get("target_usable"))
        deltas = [float(r.get("delta_net_pnl_usd") or 0.0) for r in exec_rows]
        can_wins = sum(1 for r in fr if float(r.get("canonical_net_pnl_usd") or 0) > 0)
        st_wins = sum(1 for r in fr if float(r.get("structural_net_pnl_usd") or 0) > 0)
        n = max(len(fr), 1)
        return {
            "n_rows": len(fr),
            "n_execute": len(exec_rows),
            "usable_structural_sl_pct": round(100.0 * usable_sl / n, 4),
            "usable_structural_tp_pct": round(100.0 * usable_tp / n, 4),
            "usable_both_pct": round(100.0 * usable_both / n, 4),
            "delta_net_pnl_usd_sum": round(sum(deltas), 6),
            "delta_net_pnl_usd_median": round(statistics.median(deltas), 6) if deltas else 0.0,
            "canonical_wr": round(can_wins / n, 6),
            "structural_wr": round(st_wins / n, 6),
            "skip_reason_counts": _count([r.get("skip_reason") for r in fr if r.get("action") != "EXECUTE_STRUCTURAL"]),
            "exit_reason_counts": _count([r.get("structural_exit_reason") for r in exec_rows]),
        }

    # Overall usable rates on structural families only
    struct_rows = [r for r in rows if r.get("policy_family") != "BASELINE"]
    n_struct = max(len(struct_rows), 1)
    lookahead_n = sum(1 for r in rows if r.get("lookahead_violation"))

    gate_a = {
        "tick_coverage_hours_pct_ok": tick_coverage_pct >= 99.0,
        "evaluable_pct": round(100.0 * len(evaluated_ids) / max(n_lived, 1), 4),
        "evaluable_pct_ok": (100.0 * len(evaluated_ids) / max(n_lived, 1)) >= 90.0,
        "lookahead_violation_count": lookahead_n,
        "lookahead_ok": lookahead_n == 0,
    }
    gate_a["pass"] = all(
        [
            gate_a["tick_coverage_hours_pct_ok"],
            gate_a["evaluable_pct_ok"],
            gate_a["lookahead_ok"],
        ]
    )

    exec_all = [r for r in struct_rows if r.get("action") == "EXECUTE_STRUCTURAL"]
    deltas_all = [float(r.get("delta_net_pnl_usd") or 0.0) for r in exec_all]
    summary = {
        "generated_at": _utc_now(),
        "stage": "STP2_PILOT_P4" if not smoke else "STP2_PILOT_P3_SMOKE",
        "status": "STP2_PILOT_DONE",
        "shadow": "STRUCTURAL_STOP_TAKE_FILTER",
        "pilot_month": "2026-06",
        "n_lived_trades_in_window": n_lived,
        "n_evaluated": len(evaluated_ids),
        "n_skipped": len(skipped_ids),
        "skip_reason_counts": skip_reason_counts,
        "usable_structural_sl_pct": round(
            100.0 * sum(1 for r in struct_rows if r.get("protective_usable")) / n_struct, 4
        ),
        "usable_structural_tp_pct": round(
            100.0 * sum(1 for r in struct_rows if r.get("target_usable")) / n_struct, 4
        ),
        "usable_both_pct": round(
            100.0
            * sum(1 for r in struct_rows if r.get("protective_usable") and r.get("target_usable"))
            / n_struct,
            4,
        ),
        "delta_net_pnl_usd_sum": round(sum(deltas_all), 6),
        "delta_net_pnl_usd_median": round(statistics.median(deltas_all), 6) if deltas_all else 0.0,
        "canonical_wr": round(
            sum(1 for r in struct_rows if float(r.get("canonical_net_pnl_usd") or 0) > 0) / n_struct, 6
        ),
        "structural_wr": round(
            sum(1 for r in struct_rows if float(r.get("structural_net_pnl_usd") or 0) > 0) / n_struct, 6
        ),
        "by_policy_family": {
            fam: _family_block(fam)
            for fam in ("BASELINE", "STRUCTURAL_SL_ONLY", "STRUCTURAL_TP_ONLY", "FULL_STRUCTURAL")
        },
        "external_trades_used": False,
        "fidelity": "EXACT_AGG_TRADE",
        "approximation_used": False,
        "tick_coverage_hours_pct": tick_coverage_pct,
        "lookahead_violation_count": lookahead_n,
        "runtime_seconds": round(runtime_s, 3),
        "preferred_policy_ids": list(PREFERRED_POLICY_IDS),
        "gate_a": gate_a,
        "gate_b_note_ru": (
            "Интерпретировать delta PnL / WR только если gate_a.pass=true; "
            "семьи не смешивать — смотреть by_policy_family."
        ),
        "gate_verdict": "GO_REVIEW_GATE_B" if gate_a["pass"] else "NO_GO_FIX_GATE_A",
    }
    return summary


def _count(values: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        k = str(v or "NONE")
        out[k] = out.get(k, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--tick-repo", type=Path, default=DEFAULT_TICK_REPO)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=None, help="First N trades (smoke)")
    parser.add_argument("--trade-id", action="append", default=None)
    args = parser.parse_args()

    t0 = time.time()
    universe = json.loads(args.universe.read_text(encoding="utf-8"))
    trades = list(universe.get("trades") or [])
    if args.trade_id:
        want = set(args.trade_id)
        trades = [t for t in trades if t.get("trade_id") in want]
    if args.limit is not None:
        trades = trades[: max(0, int(args.limit))]

    tick_coverage = 100.0
    if args.manifest.exists():
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        tick_coverage = float(man.get("hour_coverage_pct") or 0.0)

    specs = _preferred_specs()
    repo = args.tick_repo
    if not (repo / "data/raw_market_events_v2/agg_trade").exists():
        raise SystemExit(f"tick repo missing agg_trade partitions: {repo}")

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    trade_cache: dict = {}
    errors: list[dict[str, Any]] = []
    for i, trade in enumerate(trades, start=1):
        tid = trade.get("trade_id")
        print(f"[{i}/{len(trades)}] {tid} {trade.get('entry_ts')}", flush=True)
        try:
            rows = evaluate_trade(trade=trade, repo=repo, specs=specs, trade_cache=trade_cache)
            all_rows.extend(rows)
            if i <= 5:
                (samples_dir / f"{tid}.json").write_text(
                    json.dumps({"trade": trade, "rows": rows}, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            err = {"trade_id": tid, "error": str(exc), "traceback": traceback.format_exc()}
            errors.append(err)
            print(f"  ERROR {exc}", flush=True)
        # Bound cache growth: keep only last few lookback windows.
        if len(trade_cache) > 4:
            for k in list(trade_cache.keys())[:-2]:
                del trade_cache[k]

    runtime = time.time() - t0
    smoke = args.limit is not None and int(args.limit) < 97
    summary = _summarize(
        all_rows,
        n_lived=len(trades),
        tick_coverage_pct=tick_coverage,
        runtime_s=runtime,
        smoke=smoke,
    )
    summary["errors"] = errors
    summary["n_rows"] = len(all_rows)

    tag = "smoke" if smoke else "202606"
    per_trade_path = out_dir / f"stp2_pilot_{tag}_per_trade.parquet"
    summary_path = out_dir / f"stp2_pilot_{tag}_summary.json"
    if all_rows:
        pd.DataFrame(all_rows).to_parquet(per_trade_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Stable name expected by plan for full pilot
    if not smoke:
        (out_dir / "stp2_pilot_202606_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if all_rows:
            pd.DataFrame(all_rows).to_parquet(out_dir / "stp2_pilot_202606_per_trade.parquet", index=False)

    print(json.dumps({k: summary[k] for k in (
        "status", "n_lived_trades_in_window", "n_evaluated", "n_skipped",
        "gate_a", "gate_verdict", "usable_structural_sl_pct", "usable_structural_tp_pct",
        "delta_net_pnl_usd_sum", "runtime_seconds",
    )}, indent=2), flush=True)
    print(f"wrote {summary_path}", flush=True)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
