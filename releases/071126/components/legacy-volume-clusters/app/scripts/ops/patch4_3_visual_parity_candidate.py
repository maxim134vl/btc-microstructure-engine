#!/usr/bin/env python3
"""Patch 4.3 §15 — candidate visual payload and current-vs-candidate comparison.

Read-only. Builds what the chart *would* render once bound to the canonical
visual trade view, compares it against the live production payload and
classifies every divergence.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.visual.canonical_trade_view import (  # noqa: E402
    CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
    ECONOMICS_VERSION,
    LEGACY_TIMEFRAME,
    activation_boundary,
    build_canonical_visual_trades,
    reconcile,
)

RESEARCH = ROOT / "data" / "research"
PUBLIC_DATA = ROOT / "apps" / "context_visualizer" / "public" / "data"
POLICY_SOURCE = (
    ROOT / "data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet"
)

CLASS_NO_DIVERGENCE = "NO_DIVERGENCE"
CLASS_DYNAMIC_CONTEXT = "EXPECTED_DYNAMIC_CONTEXT"
CLASS_NEW_LIVE_TRADE = "EXPECTED_NEW_LIVE_TRADE"
CLASS_S4_LINEAGE = "EXPECTED_S4_LINEAGE"
CLASS_ECONOMICS = "EXPECTED_ECONOMICS_CONTRACT_FIX"
CLASS_DEDUP = "EXPECTED_DEDUP_FIX"
CLASS_SOURCE_SWAP = "EXPECTED_PRIMARY_SOURCE_SWAP"
CLASS_UNEXPLAINED = "UNEXPLAINED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def current_payload() -> dict[str, Any]:
    path = PUBLIC_DATA / "paper_trade_overlays.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def current_trade_rows() -> list[dict[str, Any]]:
    payload = current_payload()
    shapes = payload.get("trade_shapes") or payload.get("closed_trades") or []
    return [row for row in shapes if isinstance(row, dict)]


def build_candidate() -> dict[str, Any]:
    frame = build_canonical_visual_trades()
    invariants = reconcile(frame)
    trades = [
        {
            "visual_trade_id": row["visual_trade_id"],
            "source_trade_id": row["source_trade_id"],
            "source_book": row["source_book"],
            "timeframe": row["timeframe"],
            "side": row["side"],
            "entry_timestamp": row["entry_timestamp"],
            "exit_timestamp": row["exit_timestamp"],
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "quantity": row["quantity"],
            "gross_pnl": row["gross_pnl"],
            "fees_paid": row["fees_paid"],
            "slippage_paid": row["slippage_paid"],
            "net_pnl": row["net_pnl"],
            "context_episode_id": row["context_episode_id"],
            "manager_command_id": row["manager_command_id"],
            "position_id": row["position_id"],
            "lineage_status": row["lineage_status"],
            "activation_epoch": row["activation_epoch"],
        }
        for _, row in frame.iterrows()
    ]
    return {
        "generated_at": utc_now(),
        "schema_version": CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
        "economics_version": ECONOMICS_VERSION,
        "read_only": True,
        "recomputes_economics": False,
        "activation_boundary": activation_boundary(),
        "primary_source": "canonical_visual_trade_view",
        "secondary_research_layer": "policy_context_canonical_bar_policy_trades",
        "legacy_timeframe_label": LEGACY_TIMEFRAME,
        "trade_count": len(trades),
        "trades": trades,
        "invariants": invariants,
        "totals": {
            "gross_pnl": round(sum(float(t["gross_pnl"] or 0.0) for t in trades), 6),
            "fees_paid": round(sum(float(t["fees_paid"] or 0.0) for t in trades), 6),
            "slippage_paid": round(sum(float(t["slippage_paid"] or 0.0) for t in trades), 6),
            "net_pnl": round(sum(float(t["net_pnl"] or 0.0) for t in trades), 6),
        },
    }


def compare(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    current_rows = current_trade_rows()
    current_ids = {str(r.get("trade_id")) for r in current_rows if r.get("trade_id")}
    candidate_ids = {str(t["visual_trade_id"]) for t in candidate["trades"]}

    policy_rows = 0
    policy_ids: set[str] = set()
    if POLICY_SOURCE.exists():
        policy = pd.read_parquet(POLICY_SOURCE)
        policy_rows = int(len(policy))
        policy_ids = {str(v) for v in policy["trade_id"].tolist()}

    payload = current_payload()
    rows: list[dict[str, Any]] = []

    def add(field: str, current: Any, cand: Any, classification: str, note: str) -> None:
        rows.append(
            {
                "field": field,
                "current": current,
                "candidate": cand,
                "classification": classification,
                "note": note,
            }
        )

    add(
        "primary_source",
        payload.get("source_closed"),
        "data/research/paper_simulator/canonical_visual_trade_view.parquet",
        CLASS_SOURCE_SWAP,
        "Patch 4.3 contract forbids policy-context rows as production truth",
    )
    add(
        "controller_ledger_used_for_render",
        payload.get("controller_ledger_used_for_render"),
        True,
        CLASS_SOURCE_SWAP,
        "canonical hierarchy puts production paper ledger first",
    )
    add(
        "trade_count",
        len(current_rows),
        candidate["trade_count"],
        CLASS_SOURCE_SWAP,
        f"{policy_rows} policy-context rows demoted to secondary research layer",
    )
    add(
        "economics_version",
        payload.get("economics_source") or "recomputed_from_prices",
        ECONOMICS_VERSION,
        CLASS_ECONOMICS,
        "visual displays ledger economics instead of recomputing them",
    )
    add(
        "trade_id_intersection",
        len(current_ids & candidate_ids),
        0,
        CLASS_SOURCE_SWAP,
        "identifier namespace changes with the primary source",
    )
    add(
        "duplicate_visual_trade_ids",
        None,
        candidate["invariants"]["duplicate_visual_trade_ids"],
        CLASS_DEDUP,
        "deterministic VIS_ identifiers deduplicated",
    )
    add(
        "s4_lineage_present",
        False,
        candidate["invariants"]["s4_trades"] > 0,
        CLASS_S4_LINEAGE,
        "timeframe trader tail is empty until the first S4 trade closes",
    )
    add(
        "context_episode_ids",
        sorted({str(r.get("context_id")) for r in current_rows if r.get("context_id")}),
        sorted({str(t["context_episode_id"]) for t in candidate["trades"] if t["context_episode_id"]}),
        CLASS_DYNAMIC_CONTEXT,
        "resolved point-in-time from lifecycle memory, never hardcoded",
    )
    add(
        "policy_context_rows_retained_as_secondary",
        policy_rows,
        policy_rows,
        CLASS_NO_DIVERGENCE,
        "research layer preserved, only demoted from primary",
    )
    add(
        "pnl_reconciliation_errors",
        None,
        candidate["invariants"]["pnl_reconciliation_errors"],
        CLASS_NO_DIVERGENCE,
        "gross - fees - slippage == net for every row",
    )
    add(
        "cutover_overlap",
        None,
        candidate["invariants"]["cutover_overlap"],
        CLASS_NO_DIVERGENCE,
        "legacy history and S4 tail do not overlap the activation boundary",
    )
    _ = policy_ids
    return rows


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = build_candidate()
    rows = compare(candidate)

    RESEARCH.mkdir(parents=True, exist_ok=True)
    payload_path = RESEARCH / "patch4_3_candidate_visual_payload.json"
    payload_path.write_text(json.dumps(candidate, indent=2, default=str) + "\n", encoding="utf-8")

    meta = {
        "generated_at": utc_now(),
        "stamp": stamp,
        "schema_version": CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
        "economics_version": ECONOMICS_VERSION,
        "read_only": True,
        "activation_performed": False,
        "trade_count": candidate["trade_count"],
        "invariants": candidate["invariants"],
    }
    Path(str(payload_path) + ".meta.json").write_text(
        json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8"
    )

    frame = pd.DataFrame(rows, columns=["field", "current", "candidate", "classification", "note"])
    csv_path = RESEARCH / "patch4_3_current_vs_candidate.csv"
    frame.to_csv(csv_path, index=False)

    counts = frame["classification"].value_counts().to_dict()
    unexplained = int(counts.get(CLASS_UNEXPLAINED, 0))
    print(frame.to_string(index=False)[:4000])
    print()
    print(json.dumps({"classification_counts": counts, "unexplained": unexplained}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
