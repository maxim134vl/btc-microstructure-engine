"""Current Context + Trade Toxicity orchestrator (MODEL-4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.registry import read_active_runtime
from btc_ml.model_assurance.toxic_box.common import (
    atomic_write_json,
    load_json,
    read_jsonl,
    utc_now_iso,
)
from btc_ml.model_assurance.toxic_box.context_toxicity import evaluate_context_toxicity
from btc_ml.model_assurance.toxic_box.trade_toxicity import evaluate_trade_toxicity
from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "toxic_box"
    return {
        "config": root / "config" / "model_assurance_current_toxicity.json",
        "context_events": base / "contexts" / "events" / "context_toxic_events.jsonl",
        "context_summary": base / "contexts" / "snapshots" / "latest_summary.json",
        "trade_events": base / "trades" / "events" / "trade_toxic_events.jsonl",
        "trade_summary": base / "trades" / "snapshots" / "latest_summary.json",
        "current_summary": base / "current" / "snapshots" / "latest_summary.json",
        "checkpoint": base / "current" / "runtime" / "checkpoint.json",
        "health": base / "current" / "runtime" / "health.json",
        "bv_predictions": root
        / "data"
        / "model_assurance"
        / "behavioral_validation"
        / "events"
        / "context_predictions.jsonl",
        "bv_outcomes": root
        / "data"
        / "model_assurance"
        / "behavioral_validation"
        / "outcomes"
        / "context_outcomes.jsonl",
        "econ_evals": root
        / "data"
        / "model_assurance"
        / "economic_validation"
        / "trades"
        / "trade_evaluations.jsonl",
        "books_root": root / "data" / "trading" / "intrabar_paper",
    }


def load_config(repo_root: Path | None = None) -> dict[str, Any]:
    return json.loads(paths(repo_root)["config"].read_text(encoding="utf-8"))


def _branch_summary(events: list[dict[str, Any]], *, branch: str) -> dict[str, Any]:
    rows = [e for e in events if e.get("branch") == branch]
    return {
        "events": len(rows),
        "candidates": sum(1 for e in rows if e.get("status") == "CANDIDATE"),
        "confirmed": sum(1 for e in rows if e.get("status") == "CONFIRMED"),
        "counts_by_subtype": _count(rows, "subtype"),
        "counts_by_severity": _count(rows, "severity"),
    }


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "")
        out[k] = out.get(k, 0) + 1
    return out


def build_current_summary(
    *,
    active: dict[str, Any],
    context_stats: dict[str, Any],
    trade_stats: dict[str, Any],
) -> dict[str, Any]:
    ctx_events = context_stats.get("events") or []
    trd_events = trade_stats.get("events") or []
    all_events = list(ctx_events) + list(trd_events)
    not_eval: dict[str, int] = {}
    for src in (context_stats.get("not_evaluable_checks") or {}, trade_stats.get("not_evaluable_checks") or {}):
        for k, v in src.items():
            not_eval[k] = not_eval.get(k, 0) + int(v)

    preds_seen = int(context_stats.get("predictions_seen") or 0)
    preds_eval = int(context_stats.get("predictions_evaluable") or 0)
    trades_seen = int(trade_stats.get("trades_seen") or 0)
    trades_eval = int(trade_stats.get("trades_evaluable") or 0)

    confirmed_critical = any(
        e.get("status") == "CONFIRMED" and e.get("severity") == "CRITICAL" for e in all_events
    )
    confirmed_warning = any(
        e.get("status") == "CONFIRMED" and e.get("severity") == "WARNING" for e in all_events
    )
    any_candidate = any(e.get("status") == "CANDIDATE" for e in all_events)

    if preds_eval == 0 and trades_eval == 0:
        status = "NO_ELIGIBLE_EVENTS_YET"
    elif confirmed_critical:
        status = "CURRENT_CRITICAL"
    elif confirmed_warning:
        status = "CURRENT_WARNING"
    elif any_candidate:
        status = "CURRENT_WATCH"
    else:
        status = "CURRENT_CLEAR"

    return {
        "status": status,
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "registry_record_id": active.get("registry_record_id"),
        "context_predictions_seen": preds_seen,
        "context_predictions_evaluable": preds_eval,
        "context_toxic_candidates": int(context_stats.get("toxic_candidates") or 0),
        "context_confirmed_events": int(context_stats.get("confirmed_events") or 0),
        "trades_seen": trades_seen,
        "trades_evaluable": trades_eval,
        "trade_toxic_candidates": int(trade_stats.get("toxic_candidates") or 0),
        "trade_confirmed_events": int(trade_stats.get("confirmed_events") or 0),
        "counts_by_branch": {
            "CONTEXT": len(ctx_events),
            "TRADE": len(trd_events),
        },
        "counts_by_subtype": _count(all_events, "subtype"),
        "counts_by_severity": _count(all_events, "severity"),
        "not_evaluable_checks": not_eval,
        "last_context_event_at": context_stats.get("last_context_event_at"),
        "last_trade_event_at": trade_stats.get("last_trade_event_at"),
        "updated_at": utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    config = load_config(root)
    active = read_active_runtime(repo_root=root)
    if not active:
        summary = {
            "status": "NO_ELIGIBLE_EVENTS_YET",
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "context_predictions_seen": 0,
            "context_predictions_evaluable": 0,
            "trades_seen": 0,
            "trades_evaluable": 0,
            "updated_at": utc_now_iso(),
        }
        atomic_write_json(p["current_summary"], summary)
        atomic_write_json(
            p["health"],
            {"status": summary["status"], "alive": True, "runtime_impact": "NON_BLOCKING", "updated_at": utc_now_iso()},
        )
        return summary

    existing_ctx = {str(e.get("toxic_event_id")) for e in read_jsonl(p["context_events"])}
    existing_trd = {str(e.get("toxic_event_id")) for e in read_jsonl(p["trade_events"])}

    predictions = read_jsonl(p["bv_predictions"])
    outcomes = read_jsonl(p["bv_outcomes"])
    context_stats = evaluate_context_toxicity(
        active=active,
        predictions=predictions,
        outcomes=outcomes,
        config=config,
        events_path=p["context_events"],
        existing_ids=existing_ctx,
    )
    atomic_write_json(
        p["context_summary"],
        {
            "status": "OK",
            "runtime_impact": "NON_BLOCKING",
            **{k: v for k, v in context_stats.items() if k != "events"},
            "updated_at": utc_now_iso(),
        },
    )

    paper_epoch_id = str(active.get("paper_epoch_id") or "")
    books = EpochBooks(p["books_root"] / paper_epoch_id / "books", paper_epoch_id=paper_epoch_id)
    econ = read_jsonl(p["econ_evals"])
    exec_cfg = load_intrabar_paper_config(repo_root=root)
    trade_stats = evaluate_trade_toxicity(
        active=active,
        books=books,
        economic_evaluations=econ,
        config=config,
        max_bbo_age_ms=float(exec_cfg.max_bbo_age_ms),
        events_path=p["trade_events"],
        existing_ids=existing_trd,
    )
    atomic_write_json(
        p["trade_summary"],
        {
            "status": "OK",
            "runtime_impact": "NON_BLOCKING",
            **{k: v for k, v in trade_stats.items() if k != "events"},
            "updated_at": utc_now_iso(),
        },
    )

    # Refresh event lists after writes
    context_stats["events"] = [e for e in read_jsonl(p["context_events"]) if e.get("branch") == "CONTEXT"]
    trade_stats["events"] = [e for e in read_jsonl(p["trade_events"]) if e.get("branch") == "TRADE"]
    # Recompute candidate/confirmed from full files
    context_stats["toxic_candidates"] = sum(1 for e in context_stats["events"] if e.get("status") == "CANDIDATE")
    context_stats["confirmed_events"] = sum(1 for e in context_stats["events"] if e.get("status") == "CONFIRMED")
    trade_stats["toxic_candidates"] = sum(1 for e in trade_stats["events"] if e.get("status") == "CANDIDATE")
    trade_stats["confirmed_events"] = sum(1 for e in trade_stats["events"] if e.get("status") == "CONFIRMED")

    summary = build_current_summary(active=active, context_stats=context_stats, trade_stats=trade_stats)
    atomic_write_json(p["current_summary"], summary)
    atomic_write_json(
        p["checkpoint"],
        {
            "paper_epoch_id": paper_epoch_id,
            "context_event_count": len(context_stats["events"]),
            "trade_event_count": len(trade_stats["events"]),
            "updated_at": utc_now_iso(),
        },
    )
    atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "pid": os.getpid(),
            "paper_epoch_id": paper_epoch_id,
            "context_predictions_evaluable": summary["context_predictions_evaluable"],
            "trades_evaluable": summary["trades_evaluable"],
            "paper_only": active.get("paper_only", True),
            "real_execution": active.get("real_execution", False),
            "updated_at": utc_now_iso(),
        },
    )
    return summary
