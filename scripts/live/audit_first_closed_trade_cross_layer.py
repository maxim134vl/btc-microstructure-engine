#!/usr/bin/env python3
"""TRD-OUTCOME1 — read-only first closed trade cross-layer reconciliation.

Writes ONLY under output/audits/trd_outcome1/. Never mutates paper books,
sleeves, EQCORR journals, STP journals, or the command bus.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
EPOCH = "PER_TF_EQUITY_1PCT_V1_20260729_181431"
CONTRACT_FP = "ca13177674222de7991dc26688ee2f91e018e5728a1660af6dc81c326acf7129"
STP_MANIFEST = "e300d491fe470df4df754369ebbaedac25e66505950b555e76d0579467f7115b"
OUT_DIR = REPO / "output" / "audits" / "trd_outcome1"
TOL = 1e-6


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _books_root() -> Path:
    return REPO / "data" / "trading" / "intrabar_paper" / EPOCH / "books"


def find_first_closed_trade() -> dict[str, Any] | None:
    trades = _read_jsonl(_books_root() / "trades.jsonl")
    trades = [t for t in trades if str(t.get("paper_epoch_id") or EPOCH) == EPOCH]
    if not trades:
        return None
    trades.sort(key=lambda t: str(t.get("exit_ts") or t.get("closed_at") or ""))
    return trades[0]


def reconstruct_chain(trade: dict[str, Any]) -> dict[str, Any]:
    books = _books_root()
    pid = str(trade.get("position_id") or "")
    positions = [p for p in _read_jsonl(books / "positions.jsonl") if str(p.get("position_id")) == pid]
    fills = [f for f in _read_jsonl(books / "fills.jsonl") if str(f.get("position_id") or "") == pid or str(f.get("fill_id") or "") in {str(p.get("entry_fill_id") or "") for p in positions} | {str(p.get("exit_fill_id") or "") for p in positions}]
    # Prefer fill linkage via entry_fill_id on position snapshots
    entry_fill_id = None
    exit_fill_id = None
    for p in positions:
        if p.get("entry_fill_id"):
            entry_fill_id = str(p["entry_fill_id"])
        if p.get("exit_fill_id"):
            exit_fill_id = str(p["exit_fill_id"])
    all_fills = _read_jsonl(books / "fills.jsonl")
    entry_fill = next((f for f in all_fills if str(f.get("fill_id")) == entry_fill_id), None)
    exit_fill = next((f for f in all_fills if str(f.get("fill_id")) == exit_fill_id), None)
    if entry_fill is None:
        entry_fill = next((f for f in all_fills if str(f.get("action") or "").upper() == "ENTRY" and str(f.get("fill_id") or "") == entry_fill_id), None)
    orders = _read_jsonl(books / "orders.jsonl")
    commands = _read_jsonl(books / "commands.jsonl")
    signals = _read_jsonl(books / "signals.jsonl")

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
    pos = open_pos or closed_pos or (positions[-1] if positions else {})

    # Exit fills may omit position_id; match by exit timestamp + price.
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
        exit_order_id = str(exit_fill.get("order_id") or exit_order_id)
        exit_cmd_id = str(exit_fill.get("command_id") or exit_cmd_id)
        exit_order = next((o for o in orders if str(o.get("order_id")) == exit_order_id), exit_order)
        exit_cmd = next((c for c in commands if str(c.get("command_id")) == exit_cmd_id), exit_cmd)

    return {
        "trade_id": trade.get("trade_id"),
        "position_id": pid,
        "timeframe": trade.get("timeframe") or pos.get("timeframe"),
        "side": trade.get("side") or pos.get("side"),
        "context_event_id": pos.get("entry_context_event_id") or (entry_sig or {}).get("context_event_id"),
        "episode_id": trade.get("lifecycle_episode_id") or pos.get("lifecycle_episode_id"),
        "entry_signal_id": entry_sig_id or None,
        "entry_command_id": entry_cmd_id or None,
        "entry_order_id": entry_order_id or None,
        "entry_fill_id": entry_fill_id,
        "exit_command_id": exit_cmd_id or None,
        "exit_order_id": exit_order_id or None,
        "exit_fill_id": exit_fill_id,
        "entry_timestamp": (entry_fill or {}).get("ts") or pos.get("opened_at") or trade.get("entry_ts"),
        "entry_executable_price": float((entry_fill or {}).get("paper_fill_price") or trade.get("entry_price") or 0.0),
        "stop_price": float(pos.get("stop_loss_price") or 0.0),
        "take_price": float(pos.get("take_profit_price") or 0.0),
        "exit_timestamp": trade.get("exit_ts"),
        "exit_executable_price": float(trade.get("exit_price") or 0.0),
        "exit_reason": trade.get("exit_reason"),
        "quantity": float(trade.get("quantity") or pos.get("quantity") or 0.0),
        "notional": float(pos.get("notional_usd") or 0.0),
        "risk_budget_usd": float(trade.get("risk_amount_usd") or pos.get("risk_budget_usd") or 0.0),
        "equity_at_entry_usd": float(pos.get("equity_at_entry_usd") or (entry_fill or {}).get("equity_at_entry_usd") or 0.0),
        "chain": {
            "entry_fill_present": entry_fill is not None,
            "exit_fill_present": exit_fill is not None,
            "closed_position_present": closed_pos is not None,
            "position_snapshots": len(positions),
            "entry_best_bid": (entry_fill or {}).get("best_bid"),
            "entry_best_ask": (entry_fill or {}).get("best_ask"),
            "exit_best_bid": (exit_fill or {}).get("best_bid"),
            "exit_best_ask": (exit_fill or {}).get("best_ask"),
            "long_entry_is_ask": (
                abs(float((entry_fill or {}).get("paper_fill_price") or 0.0) - float((entry_fill or {}).get("best_ask") or -1.0))
                < 1e-6
                if entry_fill and entry_fill.get("best_ask") is not None
                else None
            ),
            "long_exit_is_bid": (
                abs(float((exit_fill or {}).get("paper_fill_price") or trade.get("exit_price") or 0.0) - float((exit_fill or {}).get("best_bid") or -1.0))
                < 1e-6
                if exit_fill and exit_fill.get("best_bid") is not None
                else None
            ),
        },
    }


def recompute_pnl(trade: dict[str, Any]) -> dict[str, Any]:
    stored = {
        "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0.0),
        "entry_fee_usd": float(trade.get("entry_fee_usd") or 0.0),
        "exit_fee_usd": float(trade.get("exit_fee_usd") or 0.0),
        "fees_usd": float(trade.get("fees_usd") or 0.0),
        "slippage_usd": float(trade.get("slippage_usd") or 0.0),
        "net_pnl_usd": float(trade.get("net_pnl_usd") or 0.0),
        "risk_amount_usd": float(trade.get("risk_amount_usd") or 0.0),
    }
    fees_sum = stored["entry_fee_usd"] + stored["exit_fee_usd"]
    fees_ok = abs(fees_sum - stored["fees_usd"]) <= TOL or stored["fees_usd"] == 0.0
    recomputed_net = stored["gross_pnl_usd"] - stored["fees_usd"] - stored["slippage_usd"]
    # Prefer explicit fee components when fees_usd aggregates them
    if abs(fees_sum - stored["fees_usd"]) <= TOL:
        recomputed_net = stored["gross_pnl_usd"] - fees_sum - stored["slippage_usd"]
    realized_r = (
        stored["net_pnl_usd"] / stored["risk_amount_usd"] if stored["risk_amount_usd"] else None
    )
    return {
        "stored": stored,
        "recomputed_net_pnl_usd": recomputed_net,
        "net_diff": recomputed_net - stored["net_pnl_usd"],
        "fees_components_sum_ok": fees_ok,
        "realized_R": realized_r,
        "within_tolerance": abs(recomputed_net - stored["net_pnl_usd"]) <= max(TOL, 1e-4),
    }


def sleeve_snapshot(tf: str, net_pnl: float) -> dict[str, Any]:
    path = REPO / "data" / "trading" / "intrabar_paper" / EPOCH / "sleeves.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sleeves = raw.get("sleeves") or raw
    # Support both nested and flat layouts
    if isinstance(sleeves, dict) and tf in sleeves:
        cur = sleeves[tf]
    else:
        cur = (raw.get("timeframes") or {}).get(tf) or {}
    out = {"timeframe": tf, "sleeve_row": cur, "all_timeframes": {}}
    for k in ("M15", "M30", "H1", "H4"):
        row = sleeves.get(k) if isinstance(sleeves, dict) else {}
        if isinstance(row, dict):
            out["all_timeframes"][k] = {
                "initial_equity_usd": row.get("initial_equity_usd"),
                "current_equity_usd": row.get("current_equity_usd"),
                "cumulative_realized_net_pnl_usd": row.get("cumulative_realized_net_pnl_usd"),
                "next_risk_budget_usd": row.get("next_risk_budget_usd"),
                "closed_trades_count": row.get("closed_trades_count"),
            }
    # Reconstruct expected after-close for TF if we know initial + cumulative
    row = out["all_timeframes"].get(tf) or {}
    init_eq = float(row.get("initial_equity_usd") or 100000.0)
    cum = float(row.get("cumulative_realized_net_pnl_usd") or 0.0)
    cur_eq = float(row.get("current_equity_usd") or (init_eq + cum))
    out["checks"] = {
        "equity_matches_initial_plus_cumulative": abs(cur_eq - (init_eq + cum)) <= 1e-4,
        "next_risk_is_1pct": abs(float(row.get("next_risk_budget_usd") or 0.0) - cur_eq * 0.01) <= 1e-4
        if row.get("next_risk_budget_usd") is not None
        else None,
        "trade_net_pnl_usd": net_pnl,
    }
    return out


def eqcorr_reconcile(trade: dict[str, Any], chain: dict[str, Any]) -> dict[str, Any]:
    root = REPO / "data" / "trading" / "shadow_economic_correlation"
    pid = str(chain["position_id"])
    tid = str(trade.get("trade_id") or "")
    cand_suffix = pid
    vtrades = [r for r in _read_jsonl(root / "virtual_trades.jsonl") if pid in str(r.get("position_id") or r.get("candidate_id") or "") or tid == str(r.get("trade_id") or r.get("canonical_trade_id") or "")]
    decisions = [r for r in _read_jsonl(root / "policy_decisions.jsonl") if cand_suffix in str(r.get("candidate_id") or "")]
    outcomes = [r for r in _read_jsonl(root / "quality_outcomes.jsonl") if cand_suffix in str(r.get("candidate_id") or "") or tid == str(r.get("trade_id") or "")]
    baseline_names = ("BASELINE_ALL_ELIGIBLE", "BASELINE", "BASELINE_CANONICAL")
    baseline_trades = [r for r in vtrades if str(r.get("policy_id") or "") in baseline_names or "BASELINE" in str(r.get("policy_id") or "")]
    # Prefer exact BASELINE_ALL_ELIGIBLE
    baseline = next((r for r in vtrades if r.get("policy_id") == "BASELINE_ALL_ELIGIBLE"), None)
    if baseline is None and baseline_trades:
        baseline = baseline_trades[0]
    attachments = [d for d in decisions if d.get("record_type") == "OUTCOME_ATTACHMENT"]
    policy_actions = Counter(
        str(d.get("action") or d.get("original_action") or d.get("decision") or "")
        for d in decisions
        if not d.get("record_type") or d.get("record_type") == "DECISION"
    )
    # immutable decision hashes (decision rows without outcome attachment bodies)
    decision_core = [d for d in decisions if d.get("record_type") in (None, "DECISION") or "OUTCOME" not in str(d.get("record_type") or "")]
    return {
        "baseline_row": baseline,
        "baseline_match": bool(
            baseline
            and abs(float(baseline.get("net_pnl_usd") or 0.0) - float(trade.get("net_pnl_usd") or 0.0)) <= 1e-4
            and str(baseline.get("exit_reason") or "") == str(trade.get("exit_reason") or "")
            and abs(float(baseline.get("exit_price") or 0.0) - float(trade.get("exit_price") or 0.0)) <= 1e-6
        ),
        "virtual_trade_count": len(vtrades),
        "policy_action_counts": dict(policy_actions),
        "outcome_attachments": len(attachments),
        "quality_outcomes": len(outcomes),
        "marginal_sample": (attachments[-1].get("marginal_contribution") if attachments else None),
        "decision_core_count": len(decision_core),
    }


def stp_reconcile(trade: dict[str, Any], chain: dict[str, Any]) -> dict[str, Any]:
    root = REPO / "data" / "trading" / "shadow_structural_protection"
    health = json.loads((root / "health.json").read_text()) if (root / "health.json").exists() else {}
    mfp = str(health.get("policy_manifest_fingerprint") or STP_MANIFEST)
    pid = str(chain["position_id"])
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(root / "virtual_positions.jsonl"):
        if pid not in str(row.get("position_id") or row.get("candidate_id") or ""):
            continue
        key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
        latest[key] = row
    valid = [
        r
        for r in latest.values()
        if r.get("policy_manifest_fingerprint") == mfp
        and not r.get("invalidated")
        and str(r.get("status") or "").upper() != "INVALIDATED"
    ]
    invalidated = [
        r
        for r in latest.values()
        if r.get("invalidated") or str(r.get("status") or "").upper() == "INVALIDATED"
    ]
    vtrades = [
        r
        for r in _read_jsonl(root / "virtual_trades.jsonl")
        if pid in str(r.get("position_id") or r.get("candidate_id") or "")
        and r.get("policy_manifest_fingerprint") == mfp
    ]
    baseline = next((r for r in vtrades if r.get("policy_id") == "BASELINE_CANONICAL"), None)
    if baseline is None:
        baseline_pos = next((r for r in valid if r.get("policy_id") == "BASELINE_CANONICAL"), None)
    else:
        baseline_pos = None
    decisions = [
        d
        for d in _read_jsonl(root / "policy_decisions.jsonl")
        if d.get("policy_manifest_fingerprint") == mfp
        and pid in str(d.get("candidate_id") or "")
        and not d.get("record_type")
    ]
    return {
        "active_manifest": mfp,
        "expected_manifest": STP_MANIFEST,
        "manifest_match": mfp == STP_MANIFEST,
        "valid_positions": [
            {"policy_id": r.get("policy_id"), "status": r.get("status"), "research_valid": r.get("research_valid")}
            for r in valid
        ],
        "invalidated_count": len(invalidated),
        "virtual_trades_current_manifest": len(vtrades),
        "baseline_trade": baseline,
        "baseline_position_if_open": baseline_pos,
        "baseline_match": bool(
            baseline
            and abs(float(baseline.get("net_pnl_usd") or 0.0) - float(trade.get("net_pnl_usd") or 0.0)) <= 1e-4
            and str(baseline.get("exit_reason") or "") == str(trade.get("exit_reason") or "")
        ),
        "decision_actions": dict(Counter(str(d.get("action")) for d in decisions)),
        "health": {
            "status": health.get("status"),
            "protective_zone_usable_count": health.get("protective_zone_usable_count"),
            "target_zone_usable_count": health.get("target_zone_usable_count"),
            "economic_execute_count": health.get("economic_execute_count"),
            "virtual_trades_closed": health.get("virtual_trades_closed"),
            "lookahead_violation_count": health.get("lookahead_violation_count"),
            "write_boundary_violation_count": health.get("write_boundary_violation_count"),
        },
    }


def build_report() -> dict[str, Any]:
    active = json.loads((REPO / "data/trading/paper_epochs/active.json").read_text())
    trade = find_first_closed_trade()
    if trade is None:
        return {
            "status": "TRD_OUTCOME1_READY_AWAITING_FIRST_CLOSE",
            "generated_at": _utc(),
            "active_epoch": active.get("paper_epoch_id"),
            "trading_contract_fingerprint": active.get("trading_contract_fingerprint"),
            "first_closed_trade": None,
        }
    chain = reconstruct_chain(trade)
    pnl = recompute_pnl(trade)
    sleeves = sleeve_snapshot(str(chain.get("timeframe") or "M15"), float(trade.get("net_pnl_usd") or 0.0))
    eqcorr = eqcorr_reconcile(trade, chain)
    stp = stp_reconcile(trade, chain)

    status = "TRD_OUTCOME1_FIRST_CLOSE_RECONCILED"
    blockers: list[str] = []
    if active.get("paper_epoch_id") != EPOCH:
        blockers.append("ACTIVE_EPOCH_MISMATCH")
    if not pnl["within_tolerance"]:
        blockers.append("TRD_OUTCOME1_PAPER_RECONCILIATION_FAILURE")
    if not eqcorr.get("baseline_match"):
        blockers.append("TRD_OUTCOME1_EQCORR_BASELINE_DIVERGENCE")
    if not stp.get("baseline_match") and not stp.get("virtual_trades_current_manifest"):
        # baseline still open / close not attached yet — soft warn via status detail
        blockers.append("TRD_OUTCOME1_STP_BASELINE_DIVERGENCE")
    if blockers:
        status = blockers[0]

    return {
        "status": status,
        "blockers": blockers,
        "generated_at": _utc(),
        "active_epoch": active.get("paper_epoch_id"),
        "trading_contract_fingerprint": active.get("trading_contract_fingerprint"),
        "expected_contract_fingerprint": CONTRACT_FP,
        "first_closed_trade": trade,
        "identity": chain,
        "pnl": pnl,
        "sleeves": sleeves,
        "eqcorr": eqcorr,
        "stp": stp,
        "runtime_hashes": {
            "active.json": _sha(REPO / "data/trading/paper_epochs/active.json"),
            "sleeves.json": _sha(REPO / "data/trading/intrabar_paper" / EPOCH / "sleeves.json"),
            "trades.jsonl": _sha(_books_root() / "trades.jsonl"),
            "positions.jsonl": _sha(_books_root() / "positions.jsonl"),
        },
    }


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    jp = OUT_DIR / f"trd_outcome1_{stamp}.json"
    mp = OUT_DIR / f"trd_outcome1_{stamp}.md"
    jp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    ident = report.get("identity") or {}
    trade = report.get("first_closed_trade") or {}
    lines = [
        f"# TRD-OUTCOME1 {report.get('status')}",
        "",
        f"generated_at: {report.get('generated_at')}",
        f"active_epoch: {report.get('active_epoch')}",
        f"trade_id: {trade.get('trade_id')}",
        f"position_id: {ident.get('position_id')}",
        f"timeframe/side: {ident.get('timeframe')}/{ident.get('side')}",
        f"exit_reason: {ident.get('exit_reason')}",
        f"net_pnl: {(report.get('pnl') or {}).get('stored', {}).get('net_pnl_usd')}",
        f"eqcorr_baseline_match: {(report.get('eqcorr') or {}).get('baseline_match')}",
        f"stp_baseline_match: {(report.get('stp') or {}).get('baseline_match')}",
        f"blockers: {report.get('blockers')}",
        "",
    ]
    mp.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "latest.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return jp, mp


def main() -> int:
    report = build_report()
    jp, mp = write_report(report)
    print(json.dumps({"status": report["status"], "json": str(jp), "md": str(mp), "blockers": report.get("blockers")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
