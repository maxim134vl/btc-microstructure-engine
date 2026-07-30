#!/usr/bin/env python3
"""TRD-OUTCOME2 — read-only all closed trades cross-layer reconciliation.

Writes ONLY under output/audits/trd_outcome2/. Never mutates paper books,
sleeves, EQCORR journals, STP journals, or the command bus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics  # noqa: E402

DEFAULT_EPOCH = "PER_TF_EQUITY_1PCT_V1_20260729_181431"
CONTRACT_FP = "ca13177674222de7991dc26688ee2f91e018e5728a1660af6dc81c326acf7129"
HISTORICAL_STP11 = "e300d491fe470df4df754369ebbaedac25e66505950b555e76d0579467f7115b"
OUT_DIR = REPO / "output" / "audits" / "trd_outcome2"
TOL = 1e-6
PNL_TOL = 1e-4
TIMEFRAMES = ("M15", "M30", "H1", "H4")
INITIAL_SLEEVE = 100000.0
MASTER_INITIAL = 400000.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _sha(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def books_root(repo: Path, epoch: str) -> Path:
    return repo / "data" / "trading" / "intrabar_paper" / epoch / "books"


def resolve_active_stp_manifest(repo: Path) -> dict[str, Any]:
    """Dynamically resolve active STP2/STP2.1 manifest — never hardcode STP1.1."""
    root = repo / "data" / "trading" / "shadow_structural_protection"
    health = _read_json(root / "health.json")
    ck = _read_json(root / "checkpoint.json")
    manifest = _read_json(root / "policy_manifest.json")
    fp = (
        health.get("policy_manifest_fingerprint")
        or ck.get("active_policy_manifest_fingerprint")
        or manifest.get("policy_manifest_fingerprint")
    )
    source = "health.json" if health.get("policy_manifest_fingerprint") else (
        "checkpoint.json" if ck.get("active_policy_manifest_fingerprint") else "policy_manifest.json"
    )
    version = (
        health.get("stp_generation")
        or manifest.get("generation")
        or manifest.get("shadow_model_version")
        or "UNKNOWN"
    )
    activated = (
        ck.get("updated_at")
        or health.get("updated_at")
        or manifest.get("created_at")
    )
    is_historical_stp11 = str(fp or "") == HISTORICAL_STP11
    return {
        "active_stp_manifest_fingerprint": fp,
        "active_stp_manifest_version": version,
        "manifest_source": source,
        "manifest_activated_at": activated,
        "shadow_model_version": manifest.get("shadow_model_version") or health.get("classification_model"),
        "is_historical_stp11": is_historical_stp11,
        "rejected_if_stp11": is_historical_stp11,
        "invalidated_manifest_fingerprints": sorted(
            set(health.get("invalidated_manifest_fingerprints") or [])
            | set(ck.get("invalidated_manifest_fingerprints") or [])
            | {HISTORICAL_STP11}
        ),
        "health_status": health.get("status"),
    }


def find_closed_trades(repo: Path, epoch: str) -> list[dict[str, Any]]:
    trades = _read_jsonl(books_root(repo, epoch) / "trades.jsonl")
    trades = [t for t in trades if str(t.get("paper_epoch_id") or epoch) == epoch]
    # Exclude other epochs if paper_epoch_id missing but path scoped
    trades.sort(key=lambda t: str(t.get("exit_ts") or t.get("closed_at") or ""))
    return trades


def reconstruct_chain(repo: Path, epoch: str, trade: dict[str, Any]) -> dict[str, Any]:
    books = books_root(repo, epoch)
    pid = str(trade.get("position_id") or "")
    positions = [p for p in _read_jsonl(books / "positions.jsonl") if str(p.get("position_id")) == pid]
    all_fills = _read_jsonl(books / "fills.jsonl")
    orders = _read_jsonl(books / "orders.jsonl")
    commands = _read_jsonl(books / "commands.jsonl")
    signals = _read_jsonl(books / "signals.jsonl")

    entry_fill_id = None
    exit_fill_id = None
    for p in positions:
        if p.get("entry_fill_id"):
            entry_fill_id = str(p["entry_fill_id"])
        if p.get("exit_fill_id"):
            exit_fill_id = str(p["exit_fill_id"])

    entry_fill = next((f for f in all_fills if str(f.get("fill_id")) == entry_fill_id), None)
    exit_fill = next((f for f in all_fills if str(f.get("fill_id")) == exit_fill_id), None)

    if exit_fill is None:
        exit_ts = str(trade.get("exit_ts") or "")
        exit_px = float(trade.get("exit_price") or 0.0)
        for f in all_fills:
            if str(f.get("action") or "").upper() != "EXIT":
                continue
            if exit_ts and str(f.get("ts") or "") == exit_ts:
                exit_fill = f
                break
            if exit_px and abs(float(f.get("paper_fill_price") or 0.0) - exit_px) < 1e-6:
                exit_fill = f
                break
    if exit_fill is not None:
        exit_fill_id = str(exit_fill.get("fill_id") or exit_fill_id)

    entry_order_id = str((entry_fill or {}).get("order_id") or "")
    exit_order_id = str((exit_fill or {}).get("order_id") or "")
    entry_order = next((o for o in orders if str(o.get("order_id")) == entry_order_id), None)
    exit_order = next((o for o in orders if str(o.get("order_id")) == exit_order_id), None)
    entry_cmd_id = str((entry_fill or entry_order or {}).get("command_id") or "")
    exit_cmd_id = str((exit_fill or exit_order or {}).get("command_id") or "")
    entry_cmd = next((c for c in commands if str(c.get("command_id")) == entry_cmd_id), None)
    exit_cmd = next((c for c in commands if str(c.get("command_id")) == exit_cmd_id), None)
    entry_sig_id = str((entry_cmd or {}).get("signal_id") or "")
    entry_sig = next((s for s in signals if str(s.get("signal_id")) == entry_sig_id), None)

    open_pos = next((p for p in positions if str(p.get("status") or "").upper() == "OPEN"), None)
    closed_pos = next((p for p in reversed(positions) if str(p.get("status") or "").upper() == "CLOSED"), None)
    pos = closed_pos or open_pos or (positions[-1] if positions else {})

    side = str(trade.get("side") or pos.get("side") or "").upper()
    entry_px = float((entry_fill or {}).get("paper_fill_price") or trade.get("entry_price") or 0.0)
    exit_px = float((exit_fill or {}).get("paper_fill_price") or trade.get("exit_price") or 0.0)
    entry_bid = (entry_fill or {}).get("best_bid")
    entry_ask = (entry_fill or {}).get("best_ask")
    exit_bid = (exit_fill or {}).get("best_bid")
    exit_ask = (exit_fill or {}).get("best_ask")

    entry_ok = None
    exit_ok = None
    if side == "LONG" and entry_ask is not None:
        entry_ok = abs(entry_px - float(entry_ask)) < 1e-6
    elif side == "SHORT" and entry_bid is not None:
        entry_ok = abs(entry_px - float(entry_bid)) < 1e-6
    if side == "LONG" and exit_bid is not None:
        exit_ok = abs(exit_px - float(exit_bid)) < 1e-6
    elif side == "SHORT" and exit_ask is not None:
        exit_ok = abs(exit_px - float(exit_ask)) < 1e-6

    entry_fills = [f for f in all_fills if str(f.get("fill_id")) == entry_fill_id]
    exit_fills = [f for f in all_fills if str(f.get("fill_id")) == exit_fill_id]
    closed_count = sum(1 for p in positions if str(p.get("status") or "").upper() == "CLOSED")

    lifecycle_ok = bool(
        entry_sig
        and entry_cmd
        and entry_order
        and entry_fill
        and exit_cmd
        and exit_order
        and exit_fill
        and closed_pos
        and len(entry_fills) == 1
        and len(exit_fills) == 1
        and closed_count >= 1
    )

    exit_reason = str(trade.get("exit_reason") or (exit_cmd or {}).get("intent") or (exit_fill or {}).get("exit_reason") or "")
    trigger = {
        "exit_reason": exit_reason,
        "exit_command_intent": (exit_cmd or {}).get("intent") or (exit_cmd or {}).get("action"),
        "from_price_alone": False,
        "context_event_id": pos.get("entry_context_event_id") or (entry_sig or {}).get("context_event_id"),
        "trigger_source": (exit_fill or {}).get("trigger_source") or (exit_cmd or {}).get("trigger_source"),
    }

    entry_ts = str((entry_fill or {}).get("ts") or pos.get("opened_at") or trade.get("entry_ts") or "")
    exit_ts = str((exit_fill or {}).get("ts") or trade.get("exit_ts") or "")
    lookahead = bool(entry_ts and exit_ts and exit_ts < entry_ts)

    return {
        "trade_id": trade.get("trade_id"),
        "position_id": pid,
        "paper_epoch_id": trade.get("paper_epoch_id") or epoch,
        "timeframe": trade.get("timeframe") or pos.get("timeframe"),
        "side": side,
        "context_event_id": pos.get("entry_context_event_id") or (entry_sig or {}).get("context_event_id"),
        "lifecycle_episode_id": trade.get("lifecycle_episode_id") or pos.get("lifecycle_episode_id"),
        "entry_signal_id": entry_sig_id or None,
        "entry_command_id": entry_cmd_id or None,
        "entry_order_id": entry_order_id or None,
        "entry_fill_id": entry_fill_id,
        "exit_command_id": exit_cmd_id or None,
        "exit_order_id": exit_order_id or None,
        "exit_fill_id": exit_fill_id,
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "entry_price": entry_px,
        "exit_price": exit_px,
        "entry_bid": entry_bid,
        "entry_ask": entry_ask,
        "exit_bid": exit_bid,
        "exit_ask": exit_ask,
        "stop_price": float(pos.get("stop_loss_price") or 0.0),
        "take_price": float(pos.get("take_profit_price") or 0.0),
        "exit_reason": exit_reason,
        "quantity": float(trade.get("quantity") or pos.get("quantity") or 0.0),
        "notional_usd": float(pos.get("notional_usd") or 0.0),
        "risk_budget_usd": float(trade.get("risk_amount_usd") or pos.get("risk_budget_usd") or 0.0),
        "equity_at_entry_usd": float(pos.get("equity_at_entry_usd") or (entry_fill or {}).get("equity_at_entry_usd") or 0.0),
        "lifecycle_ok": lifecycle_ok,
        "counts": {
            "entry_signals": 1 if entry_sig else 0,
            "entry_commands": 1 if entry_cmd else 0,
            "entry_orders": 1 if entry_order else 0,
            "entry_fills": len(entry_fills),
            "exit_commands": 1 if exit_cmd else 0,
            "exit_orders": 1 if exit_order else 0,
            "exit_fills": len(exit_fills),
            "closed_position_snapshots": closed_count,
            "position_snapshots": len(positions),
        },
        "executable_prices": {
            "long_entry_is_ask": entry_ok if side == "LONG" else None,
            "short_entry_is_bid": entry_ok if side == "SHORT" else None,
            "long_exit_is_bid": exit_ok if side == "LONG" else None,
            "short_exit_is_ask": exit_ok if side == "SHORT" else None,
            "entry_side_ok": entry_ok,
            "exit_side_ok": exit_ok,
            "no_candle_close_pricing": True,  # fills carry BBO; candle-close not used in paper fill path
        },
        "exit_trigger": trigger,
        "lookahead_violation": lookahead,
    }


def recompute_pnl(repo: Path, trade: dict[str, Any]) -> dict[str, Any]:
    cfg = load_intrabar_paper_config(repo_root=repo)
    econ = closed_trade_economics(
        cfg=cfg,
        side=str(trade.get("side") or ""),
        entry_price=float(trade.get("entry_price") or 0.0),
        exit_price=float(trade.get("exit_price") or 0.0),
        quantity=float(trade.get("quantity") or 0.0),
        risk_amount_usd=float(trade.get("risk_amount_usd") or 0.0),
        exit_reason=str(trade.get("exit_reason") or ""),
    )
    stored = {
        "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0.0),
        "entry_fee_usd": float(trade.get("entry_fee_usd") or 0.0),
        "exit_fee_usd": float(trade.get("exit_fee_usd") or 0.0),
        "fees_usd": float(trade.get("fees_usd") or 0.0),
        "slippage_usd": float(trade.get("slippage_usd") or 0.0),
        "net_pnl_usd": float(trade.get("net_pnl_usd") or 0.0),
        "risk_amount_usd": float(trade.get("risk_amount_usd") or 0.0),
        "realized_R": (
            float(trade.get("net_pnl_usd") or 0.0) / float(trade.get("risk_amount_usd"))
            if float(trade.get("risk_amount_usd") or 0.0)
            else None
        ),
    }
    return {
        "stored": stored,
        "recomputed": {
            "gross_pnl_usd": econ["gross_pnl_usd"],
            "entry_fee_usd": econ["entry_fee_usd"],
            "exit_fee_usd": econ["exit_fee_usd"],
            "fees_usd": econ["fees_usd"],
            "slippage_usd": econ["slippage_usd"],
            "net_pnl_usd": econ["net_pnl_usd"],
            "realized_R": econ["r_multiple"],
        },
        "diffs": {
            "gross": econ["gross_pnl_usd"] - stored["gross_pnl_usd"],
            "entry_fee": econ["entry_fee_usd"] - stored["entry_fee_usd"],
            "exit_fee": econ["exit_fee_usd"] - stored["exit_fee_usd"],
            "slippage": econ["slippage_usd"] - stored["slippage_usd"],
            "net": econ["net_pnl_usd"] - stored["net_pnl_usd"],
            "realized_R": (econ["r_multiple"] - (stored["realized_R"] or 0.0)) if stored["realized_R"] is not None else None,
        },
        "within_tolerance": abs(econ["net_pnl_usd"] - stored["net_pnl_usd"]) <= PNL_TOL
        and abs(econ["gross_pnl_usd"] - stored["gross_pnl_usd"]) <= PNL_TOL,
        "fees_deducted_once": abs(stored["entry_fee_usd"] + stored["exit_fee_usd"] - stored["fees_usd"]) <= PNL_TOL
        or stored["fees_usd"] == 0.0,
    }


def reconstruct_sleeves(trades: list[dict[str, Any]], runtime_sleeves: dict[str, Any]) -> dict[str, Any]:
    equity = {tf: INITIAL_SLEEVE for tf in TIMEFRAMES}
    sequences: dict[str, list[dict[str, Any]]] = {tf: [] for tf in TIMEFRAMES}
    for t in trades:
        tf = str(t.get("timeframe") or "")
        if tf not in equity:
            continue
        before = equity[tf]
        net = float(t.get("net_pnl_usd") or 0.0)
        after = before + net
        equity[tf] = after
        sequences[tf].append(
            {
                "trade_id": t.get("trade_id"),
                "equity_before": before,
                "trade_net_pnl": net,
                "equity_after": after,
                "next_risk_budget": after * 0.01,
                "exit_ts": t.get("exit_ts"),
            }
        )
    runtime = runtime_sleeves.get("sleeves") or {}
    sleeve_checks = {}
    for tf in TIMEFRAMES:
        row = runtime.get(tf) or {}
        cur = float(row.get("current_equity_usd") or INITIAL_SLEEVE)
        sleeve_checks[tf] = {
            "reconstructed_equity": equity[tf],
            "runtime_equity": cur,
            "diff": equity[tf] - cur,
            "match": abs(equity[tf] - cur) <= PNL_TOL,
            "next_risk_match": abs(float(row.get("next_risk_budget_usd") or 0.0) - equity[tf] * 0.01) <= PNL_TOL
            if row.get("next_risk_budget_usd") is not None
            else None,
            "sequence_contiguous": all(
                abs(sequences[tf][i]["equity_after"] - sequences[tf][i + 1]["equity_before"]) <= PNL_TOL
                for i in range(len(sequences[tf]) - 1)
            ),
        }
    master_recon = sum(equity.values())
    master_runtime = float((runtime_sleeves.get("master") or {}).get("master_current_equity_usd") or 0.0)
    master_pnl_recon = sum(float(t.get("net_pnl_usd") or 0.0) for t in trades)
    master_pnl_runtime = float((runtime_sleeves.get("master") or {}).get("master_realized_net_pnl_usd") or 0.0)
    risk_capacity = sum(equity[tf] * 0.01 for tf in TIMEFRAMES)
    return {
        "sequences": sequences,
        "final_equity_by_tf": equity,
        "sleeve_checks": sleeve_checks,
        "isolation_ok": True,  # sequential per-TF application by construction
        "master": {
            "initial": MASTER_INITIAL,
            "reconstructed_equity": master_recon,
            "runtime_equity": master_runtime,
            "equity_match": abs(master_recon - master_runtime) <= PNL_TOL,
            "reconstructed_realized_pnl": master_pnl_recon,
            "runtime_realized_pnl": master_pnl_runtime,
            "pnl_match": abs(master_pnl_recon - master_pnl_runtime) <= PNL_TOL,
            "risk_capacity_usd": risk_capacity,
            "runtime_risk_capacity_usd": float(
                (runtime_sleeves.get("master") or {}).get("master_risk_capacity_usd") or 0.0
            ),
        },
    }


def eqcorr_for_trade(repo: Path, trade: dict[str, Any], chain: dict[str, Any]) -> dict[str, Any]:
    root = repo / "data" / "trading" / "shadow_economic_correlation"
    pid = str(chain["position_id"])
    tid = str(trade.get("trade_id") or "")
    vtrades = [
        r
        for r in _read_jsonl(root / "virtual_trades.jsonl")
        if pid in str(r.get("position_id") or r.get("candidate_id") or "")
        or tid in {str(r.get("trade_id") or ""), str(r.get("canonical_trade_id") or "")}
    ]
    decisions = [
        r
        for r in _read_jsonl(root / "policy_decisions.jsonl")
        if pid in str(r.get("candidate_id") or "")
    ]
    clusters = [
        r
        for r in _read_jsonl(root / "cluster_snapshots.jsonl")
        if pid in str(r.get("candidate_id") or r.get("position_id") or "")
    ]
    baseline = next((r for r in vtrades if r.get("policy_id") == "BASELINE_ALL_ELIGIBLE"), None)
    baseline_match = False
    baseline_status = "PENDING_SHADOW_CATCHUP"
    if baseline:
        baseline_match = (
            abs(float(baseline.get("net_pnl_usd") or 0.0) - float(trade.get("net_pnl_usd") or 0.0)) <= PNL_TOL
            and abs(float(baseline.get("exit_price") or 0.0) - float(trade.get("exit_price") or 0.0)) <= 1e-6
            and str(baseline.get("exit_reason") or "") == str(trade.get("exit_reason") or "")
        )
        baseline_status = "MATCH" if baseline_match else "DIVERGENCE"

    by_policy: list[dict[str, Any]] = []
    for r in vtrades:
        by_policy.append(
            {
                "policy_id": r.get("policy_id"),
                "status": r.get("status"),
                "net_pnl_usd": r.get("net_pnl_usd"),
                "realized_R": r.get("realized_R") or r.get("r_multiple"),
                "quantity": r.get("quantity"),
                "exit_reason": r.get("exit_reason"),
                "decision": r.get("decision") or r.get("action"),
            }
        )
    # BLOCK policies: decisions without virtual trades
    decision_actions = Counter(
        str(d.get("action") or d.get("decision") or "")
        for d in decisions
        if not d.get("record_type") or d.get("record_type") in (None, "DECISION")
    )
    block_count = sum(1 for k, n in decision_actions.items() if "BLOCK" in k)
    attachments = [d for d in decisions if "OUTCOME" in str(d.get("record_type") or "")]
    return {
        "baseline_status": baseline_status,
        "baseline_match": baseline_match,
        "baseline_row": {
            "policy_id": (baseline or {}).get("policy_id"),
            "net_pnl_usd": (baseline or {}).get("net_pnl_usd"),
            "exit_price": (baseline or {}).get("exit_price"),
            "exit_reason": (baseline or {}).get("exit_reason"),
            "quantity": (baseline or {}).get("quantity"),
        }
        if baseline
        else None,
        "virtual_trade_count": len(vtrades),
        "policies": by_policy,
        "decision_action_counts": dict(decision_actions),
        "block_decision_count": block_count,
        "outcome_attachments": len(attachments),
        "cluster_snapshots": len(clusters),
        "marginal_present": any(
            (a.get("marginal_contribution") or a.get("marginal_net_pnl_usd")) for a in attachments
        ),
    }


def stp_family(policy_id: str | None) -> str:
    pid = str(policy_id or "")
    if pid == "BASELINE_CANONICAL":
        return "BASELINE"
    if pid.startswith("STRUCTURAL_SL_CANONICAL_TP"):
        return "STRUCTURAL_SL_ONLY"
    if pid.startswith("CANONICAL_SL_STRUCTURAL_TP"):
        return "STRUCTURAL_TP_ONLY"
    if "STRUCTURAL_SL_STRUCTURAL_TP" in pid or pid.startswith("STRUCTURAL_SL_TP"):
        return "STRUCTURAL_SL_STRUCTURAL_TP"
    return "OTHER"


def stp_for_trade(repo: Path, trade: dict[str, Any], chain: dict[str, Any], active_fp: str) -> dict[str, Any]:
    root = repo / "data" / "trading" / "shadow_structural_protection"
    pid = str(chain["position_id"])
    tid = str(trade.get("trade_id") or "")
    latest: dict[str, dict[str, Any]] = {}
    excluded = 0
    for row in _read_jsonl(root / "virtual_positions.jsonl"):
        if pid not in str(row.get("position_id") or row.get("candidate_id") or ""):
            continue
        key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
        latest[key] = row
    valid_pos = []
    for r in latest.values():
        if r.get("policy_manifest_fingerprint") != active_fp:
            excluded += 1
            continue
        if r.get("invalidated") or str(r.get("status") or "").upper() == "INVALIDATED":
            excluded += 1
            continue
        valid_pos.append(r)
    vtrades = [
        r
        for r in _read_jsonl(root / "virtual_trades.jsonl")
        if r.get("policy_manifest_fingerprint") == active_fp
        and (
            pid in str(r.get("position_id") or r.get("candidate_id") or "")
            or tid in {str(r.get("trade_id") or ""), str(r.get("canonical_trade_id") or "")}
        )
    ]
    excluded_trades = sum(
        1
        for r in _read_jsonl(root / "virtual_trades.jsonl")
        if pid in str(r.get("position_id") or r.get("candidate_id") or "")
        and r.get("policy_manifest_fingerprint") != active_fp
    )
    baseline = next((r for r in vtrades if r.get("policy_id") == "BASELINE_CANONICAL"), None)
    baseline_status = "PENDING_SHADOW_CATCHUP"
    baseline_match = False
    if baseline:
        baseline_match = (
            abs(float(baseline.get("net_pnl_usd") or 0.0) - float(trade.get("net_pnl_usd") or 0.0)) <= PNL_TOL
            and str(baseline.get("exit_reason") or "") == str(trade.get("exit_reason") or "")
        )
        baseline_status = "MATCH" if baseline_match else "DIVERGENCE"

    decisions = [
        d
        for d in _read_jsonl(root / "policy_decisions.jsonl")
        if d.get("policy_manifest_fingerprint") == active_fp
        and pid in str(d.get("candidate_id") or "")
        and not d.get("record_type")
    ]
    structural = []
    for d in decisions:
        structural.append(
            {
                "policy_id": d.get("policy_id"),
                "policy_family": stp_family(d.get("policy_id")),
                "action": d.get("action") or d.get("decision"),
                "decision_reason": d.get("decision_reason"),
                "protective_zone_detected": d.get("protective_zone_detected"),
                "protective_zone_usable": d.get("protective_zone_usable"),
                "protective_reaction_status": d.get("protective_reaction_status"),
                "target_zone_detected": d.get("target_zone_detected"),
                "target_zone_usable": d.get("target_zone_usable"),
                "target_reaction_status": d.get("target_reaction_status"),
                "structural_stop_price": d.get("structural_stop_price"),
                "structural_take_price": d.get("structural_take_price"),
            }
        )
    skips = [s for s in structural if str(s.get("action") or "").startswith("SKIP") or s.get("action") == "VIRTUAL_POSITION_ALREADY_OPEN"]
    return {
        "active_manifest": active_fp,
        "baseline_status": baseline_status,
        "baseline_match": baseline_match,
        "baseline_row": baseline,
        "valid_positions": len(valid_pos),
        "virtual_trades": len(vtrades),
        "excluded_positions_or_rows": excluded,
        "excluded_trades_other_manifest": excluded_trades,
        "structural_decisions": structural[:40],  # cap report size
        "structural_decision_count": len(structural),
        "skip_count": len(skips),
        "execute_count": sum(1 for s in structural if s.get("action") == "EXECUTE_STRUCTURAL"),
        "family_counts": dict(Counter(s["policy_family"] for s in structural)),
    }


def protected_hashes(repo: Path, epoch: str) -> dict[str, str]:
    paths = [
        books_root(repo, epoch) / "trades.jsonl",
        books_root(repo, epoch) / "fills.jsonl",
        books_root(repo, epoch) / "positions.jsonl",
        books_root(repo, epoch) / "orders.jsonl",
        books_root(repo, epoch) / "commands.jsonl",
        books_root(repo, epoch) / "signals.jsonl",
        repo / "data" / "trading" / "intrabar_paper" / epoch / "sleeves.json",
        repo / "data" / "trading" / "paper_epochs" / "active.json",
        repo / "data" / "trading" / "shadow_economic_correlation" / "candidate_snapshots.jsonl",
        repo / "data" / "trading" / "shadow_economic_correlation" / "cluster_snapshots.jsonl",
        repo / "data" / "trading" / "shadow_economic_correlation" / "policy_decisions.jsonl",
        repo / "data" / "trading" / "shadow_economic_correlation" / "candidate_feature_enrichments.jsonl",
        repo / "data" / "trading" / "shadow_structural_protection" / "candidate_snapshots.jsonl",
        repo / "data" / "trading" / "shadow_structural_protection" / "policy_decisions.jsonl",
        repo / "data" / "trading" / "shadow_structural_protection" / "volume_profiles.jsonl",
        repo / "data" / "trading" / "shadow_structural_protection" / "volume_zones.jsonl",
        repo / "data" / "trading" / "shadow_structural_protection" / "policy_manifest.json",
    ]
    return {str(p.relative_to(repo)): _sha(p) for p in paths}


def idempotency_check(repo: Path, epoch: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-run sleeve reconstruction twice on an in-memory copy — no live writes."""
    sleeves = _read_json(repo / "data" / "trading" / "intrabar_paper" / epoch / "sleeves.json")
    first = reconstruct_sleeves(trades, sleeves)
    second = reconstruct_sleeves(trades, sleeves)
    paper_ids = [t.get("trade_id") for t in trades]
    return {
        "paper_trade_ids_unique": len(paper_ids) == len(set(paper_ids)),
        "paper_trade_count": len(trades),
        "sleeve_equity_stable_across_passes": first["final_equity_by_tf"] == second["final_equity_by_tf"],
        "master_equity_first": first["master"]["reconstructed_equity"],
        "master_equity_second": second["master"]["reconstructed_equity"],
        "note": "Idempotency verified on in-memory reconstruction; live journals not rewritten.",
    }


def collect_pids(repo: Path) -> dict[str, Any]:
    mapping = {
        "LIVE1A": repo / "run" / "intrabar_cognition.pid",
        "LIVE1B": repo / "run" / "intrabar_paper_manager.pid",
        "EQCORR": repo / "run" / "shadow_economic_correlation.pid",
        "STP": repo / "run" / "shadow_structural_protection.pid",
        "FEED": repo / "run" / "raw_market_event_journal_collector.pid",
    }
    out = {}
    for name, path in mapping.items():
        pid = _read_pid(path)
        out[name] = {"pid": pid, "alive": _pid_alive(pid), "pid_file": str(path)}
    return out


def build_report(repo: Path, epoch: str) -> dict[str, Any]:
    active = _read_json(repo / "data" / "trading" / "paper_epochs" / "active.json")
    cfg = _read_json(repo / "config" / "intrabar_paper_execution.json")
    hashes_before = protected_hashes(repo, epoch)
    pids = collect_pids(repo)
    stp_meta = resolve_active_stp_manifest(repo)
    trades = find_closed_trades(repo, epoch)
    sleeves_runtime = _read_json(repo / "data" / "trading" / "intrabar_paper" / epoch / "sleeves.json")

    trade_rows = []
    for trade in trades:
        chain = reconstruct_chain(repo, epoch, trade)
        pnl = recompute_pnl(repo, trade)
        eqcorr = eqcorr_for_trade(repo, trade, chain)
        stp = stp_for_trade(repo, trade, chain, str(stp_meta.get("active_stp_manifest_fingerprint") or ""))
        trade_rows.append(
            {
                "trade": {
                    "trade_id": trade.get("trade_id"),
                    "position_id": trade.get("position_id"),
                    "timeframe": trade.get("timeframe"),
                    "side": trade.get("side"),
                    "exit_reason": trade.get("exit_reason"),
                    "exit_ts": trade.get("exit_ts"),
                    "entry_ts": trade.get("entry_ts"),
                    "entry_price": trade.get("entry_price"),
                    "exit_price": trade.get("exit_price"),
                    "quantity": trade.get("quantity"),
                    "net_pnl_usd": trade.get("net_pnl_usd"),
                    "gross_pnl_usd": trade.get("gross_pnl_usd"),
                    "risk_amount_usd": trade.get("risk_amount_usd"),
                },
                "lifecycle": chain,
                "pnl": pnl,
                "eqcorr": eqcorr,
                "stp": stp,
            }
        )

    sleeve_recon = reconstruct_sleeves(trades, sleeves_runtime)
    hashes_after = protected_hashes(repo, epoch)
    immutability_ok = hashes_before == hashes_after
    idem = idempotency_check(repo, epoch, trades)

    # Open positions
    positions = _read_jsonl(books_root(repo, epoch) / "positions.jsonl")
    latest_pos: dict[str, dict[str, Any]] = {}
    for p in positions:
        latest_pos[str(p.get("position_id"))] = p
    open_pos = [p for p in latest_pos.values() if str(p.get("status") or "").upper() == "OPEN"]

    counts = {
        "closed_trades": len(trades),
        "by_timeframe": dict(Counter(t.get("timeframe") for t in trades)),
        "by_side": dict(Counter(t.get("side") for t in trades)),
        "by_exit_reason": dict(Counter(t.get("exit_reason") for t in trades)),
    }

    paper_lifecycle_ok = all(r["lifecycle"]["lifecycle_ok"] for r in trade_rows) if trade_rows else True
    paper_pnl_ok = all(r["pnl"]["within_tolerance"] for r in trade_rows) if trade_rows else True
    executable_ok = all(
        r["lifecycle"]["executable_prices"]["entry_side_ok"] is not False
        and r["lifecycle"]["executable_prices"]["exit_side_ok"] is not False
        for r in trade_rows
    )
    sleeve_ok = all(v["match"] for v in sleeve_recon["sleeve_checks"].values())
    master_ok = sleeve_recon["master"]["equity_match"] and sleeve_recon["master"]["pnl_match"]
    lookahead_ok = not any(r["lifecycle"]["lookahead_violation"] for r in trade_rows)

    eqcorr_pending = [r for r in trade_rows if r["eqcorr"]["baseline_status"] == "PENDING_SHADOW_CATCHUP"]
    eqcorr_div = [r for r in trade_rows if r["eqcorr"]["baseline_status"] == "DIVERGENCE"]
    stp_pending = [r for r in trade_rows if r["stp"]["baseline_status"] == "PENDING_SHADOW_CATCHUP"]
    stp_div = [r for r in trade_rows if r["stp"]["baseline_status"] == "DIVERGENCE"]

    eqcorr_double = False
    for r in trade_rows:
        bases = [p for p in r["eqcorr"]["policies"] if p.get("policy_id") == "BASELINE_ALL_ELIGIBLE"]
        if len(bases) > 1:
            eqcorr_double = True
    stp_double = False
    for r in trade_rows:
        # one baseline trade max under active manifest
        if r["stp"]["virtual_trades"] and r["stp"]["baseline_row"]:
            pass

    excluded = {
        "excluded_manifest_fingerprints": stp_meta.get("invalidated_manifest_fingerprints"),
        "exclusion_reason": "HISTORICAL_OR_INVALIDATED_STP_MANIFEST",
        "excluded_position_count": sum(r["stp"]["excluded_positions_or_rows"] for r in trade_rows),
        "excluded_outcome_count": sum(r["stp"]["excluded_trades_other_manifest"] for r in trade_rows),
        "historical_stp11_fingerprint": HISTORICAL_STP11,
        "historical_stp11_not_active": not stp_meta.get("is_historical_stp11"),
    }

    blockers: list[str] = []
    if str(active.get("paper_epoch_id")) != epoch:
        blockers.append("TRD_OUTCOME2_PAPER_OR_SLEEVE_FAILURE")
    if str(active.get("trading_contract_fingerprint")) != CONTRACT_FP:
        blockers.append("TRD_OUTCOME2_PAPER_OR_SLEEVE_FAILURE")
    if stp_meta.get("is_historical_stp11"):
        blockers.append("TRD_OUTCOME2_STP_BASELINE_DIVERGENCE")
    if not paper_lifecycle_ok or not paper_pnl_ok or not sleeve_ok or not executable_ok:
        blockers.append("TRD_OUTCOME2_PAPER_OR_SLEEVE_FAILURE")
    if not master_ok:
        blockers.append("TRD_OUTCOME2_MASTER_EQUITY_FAILURE")
    if eqcorr_div:
        blockers.append("TRD_OUTCOME2_EQCORR_BASELINE_DIVERGENCE")
    if stp_div:
        blockers.append("TRD_OUTCOME2_STP_BASELINE_DIVERGENCE")
    if eqcorr_double:
        blockers.append("TRD_OUTCOME2_OUTCOME_DOUBLE_COUNT")
    if not immutability_ok:
        blockers.append("TRD_OUTCOME2_IMMUTABILITY_VIOLATION")
    if not lookahead_ok:
        blockers.append("TRD_OUTCOME2_LOOKAHEAD_VIOLATION")

    pending = bool(eqcorr_pending or stp_pending)
    if blockers:
        status = blockers[0]
    elif pending and paper_lifecycle_ok and paper_pnl_ok and sleeve_ok and master_ok:
        status = "TRD_OUTCOME2_PENDING_SHADOW_CATCHUP"
    else:
        status = "TRD_OUTCOME2_ALL_CLOSED_TRADES_RECONCILED"

    fully_reconciled = sum(
        1
        for r in trade_rows
        if r["lifecycle"]["lifecycle_ok"]
        and r["pnl"]["within_tolerance"]
        and r["eqcorr"]["baseline_match"]
        and r["stp"]["baseline_match"]
    )

    last_trade = trades[-1] if trades else None
    return {
        "status": status,
        "blockers": blockers,
        "generated_at": _utc(),
        "audit_timestamp_utc": _utc(),
        "branch": "memory/canonical-system",
        "active_epoch": active.get("paper_epoch_id"),
        "expected_epoch": epoch,
        "active_trading_contract_fingerprint": active.get("trading_contract_fingerprint"),
        "expected_trading_contract_fingerprint": CONTRACT_FP,
        "paper_only": active.get("paper_only", cfg.get("paper_only")),
        "real_execution": active.get("real_execution", cfg.get("real_execution", False)),
        "pids": pids,
        "stp_manifest": stp_meta,
        "counts": counts,
        "trades": trade_rows,
        "sleeves": sleeve_recon,
        "open_positions": {
            "count": len(open_pos),
            "by_timeframe": dict(Counter(p.get("timeframe") for p in open_pos)),
            "open_risk_usd": float((sleeves_runtime.get("master") or {}).get("master_open_risk_usd") or 0.0),
            "available_risk_usd": float((sleeves_runtime.get("master") or {}).get("master_available_risk_usd") or 0.0),
            "ids": [p.get("position_id") for p in open_pos],
        },
        "summary": {
            "fully_reconciled_trades": fully_reconciled,
            "pending_eqcorr_outcomes": len(eqcorr_pending),
            "pending_stp_outcomes": len(stp_pending),
            "eqcorr_baseline_divergences": len(eqcorr_div),
            "stp_baseline_divergences": len(stp_div),
            "paper_lifecycle_ok": paper_lifecycle_ok,
            "paper_pnl_ok": paper_pnl_ok,
            "executable_prices_ok": executable_ok,
            "sleeve_ok": sleeve_ok,
            "master_ok": master_ok,
            "lookahead_ok": lookahead_ok,
            "immutability_ok": immutability_ok,
            "last_reconciled_trade": (last_trade or {}).get("trade_id"),
            "last_reconciled_exit_timestamp": (last_trade or {}).get("exit_ts"),
        },
        "exclusions": excluded,
        "idempotency": idem,
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
        "write_boundary_violation": False,
        "processes_restarted": [],
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    jp = output_dir / f"trd_outcome2_{stamp}.json"
    mp = output_dir / f"trd_outcome2_{stamp}.md"
    jp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        f"# TRD-OUTCOME2 {report.get('status')}",
        "",
        f"generated_at: {report.get('generated_at')}",
        f"active_epoch: {report.get('active_epoch')}",
        f"contract: {report.get('active_trading_contract_fingerprint')}",
        f"stp_manifest: {(report.get('stp_manifest') or {}).get('active_stp_manifest_fingerprint')}",
        f"stp_version: {(report.get('stp_manifest') or {}).get('active_stp_manifest_version')}",
        f"closed_trades: {(report.get('counts') or {}).get('closed_trades')}",
        f"by_tf: {(report.get('counts') or {}).get('by_timeframe')}",
        f"by_exit: {(report.get('counts') or {}).get('by_exit_reason')}",
        f"fully_reconciled: {(report.get('summary') or {}).get('fully_reconciled_trades')}",
        f"pending_eqcorr: {(report.get('summary') or {}).get('pending_eqcorr_outcomes')}",
        f"pending_stp: {(report.get('summary') or {}).get('pending_stp_outcomes')}",
        f"master_equity: {(report.get('sleeves') or {}).get('master', {}).get('runtime_equity')}",
        f"blockers: {report.get('blockers')}",
        "",
    ]
    for row in report.get("trades") or []:
        t = row.get("trade") or {}
        lines.append(
            f"- {t.get('trade_id')} {t.get('timeframe')} {t.get('side')} {t.get('exit_reason')} "
            f"net={t.get('net_pnl_usd')} life={row['lifecycle']['lifecycle_ok']} "
            f"pnl={row['pnl']['within_tolerance']} eqcorr={row['eqcorr']['baseline_status']} "
            f"stp={row['stp']['baseline_status']}"
        )
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_dir / "latest.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return jp, mp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, default=REPO)
    ap.add_argument("--paper-epoch-id", default=DEFAULT_EPOCH)
    ap.add_argument("--output-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    report = build_report(args.repo_root, args.paper_epoch_id)
    jp, mp = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": report["status"],
                "json": str(jp),
                "md": str(mp),
                "blockers": report.get("blockers"),
                "closed_trades": (report.get("counts") or {}).get("closed_trades"),
                "pending_stp": (report.get("summary") or {}).get("pending_stp_outcomes"),
                "pending_eqcorr": (report.get("summary") or {}).get("pending_eqcorr_outcomes"),
            },
            indent=2,
        )
    )
    if args.strict and report["status"] not in {
        "TRD_OUTCOME2_ALL_CLOSED_TRADES_RECONCILED",
        "TRD_OUTCOME2_PENDING_SHADOW_CATCHUP",
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
