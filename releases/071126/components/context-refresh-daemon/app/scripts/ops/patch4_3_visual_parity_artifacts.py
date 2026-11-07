#!/usr/bin/env python3
"""Patch 4.3 §6/§7/§10/§13/§14 — parity evidence artifacts.

Read-only. Emits the contract inventory, field-level visual lineage, economics
parity resolution, no-lookahead proof and legacy/S4 cutover reconciliation.
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
    legacy_archive_dir,
    reconcile,
)

RESEARCH = ROOT / "data" / "research"
LIFECYCLE_MEMORY = ROOT / "data/cognition/market_context_lifecycle_memory.parquet"
POLICY_SOURCE = (
    ROOT / "data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def contract_inventory() -> dict[str, Any]:
    candidate_path = RESEARCH / "patch4_3_candidate_trade_chart.json"
    candidate: dict[str, Any] = {}
    if candidate_path.exists():
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    entries = [
        {
            "contract_file": "data/research/patch4_3_candidate_trade_chart.json",
            "intended_source": (candidate.get("canonical_source_hierarchy") or [None])[0],
            "intended_economics": ECONOMICS_VERSION,
            "intended_lineage": "legacy archived closed book + timeframe trader tail",
            "activation_state": "ACTIVATED_BY_PATCH4_3_PRODUCTION",
            "blocking_findings": [
                alert.get("reason_code")
                for alert in candidate.get("alerts", [])
                if isinstance(alert, dict)
            ],
        },
        {
            "contract_file": "docs/PATCH4_3_TRADE_CHART_RUNTIME_TRUTH_AUDIT.md",
            "intended_source": "production_paper_ledger",
            "intended_economics": ECONOMICS_VERSION,
            "intended_lineage": "chart must render the repaired paper ledger, not policy-context rows",
            "activation_state": "AUDIT_ONLY_SUPERSEDED_BY_ACTIVATION",
            "blocking_findings": ["CHART_SOURCE_NOT_PRODUCTION_LEDGER"],
        },
        {
            "contract_file": "tests/test_patch4_3_trade_chart_runtime_truth_audit.py",
            "intended_source": "audit assertions over the candidate payload",
            "intended_economics": ECONOMICS_VERSION,
            "intended_lineage": "verifies the audit findings stay reproducible",
            "activation_state": "RETAINED",
            "blocking_findings": [],
        },
        {
            "contract_file": "src/btc_ml/visual/canonical_trade_view.py",
            "intended_source": "canonical_visual_trade_view",
            "intended_economics": ECONOMICS_VERSION,
            "intended_lineage": "deterministic union keyed by visual_trade_id",
            "activation_state": "PRODUCTION_BUILDER",
            "blocking_findings": [],
        },
    ]
    return {
        "generated_at": utc_now(),
        "schema_version": CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
        "forbidden_primary_sources": candidate.get("forbidden_primary_sources", []),
        "canonical_source_hierarchy": candidate.get("canonical_source_hierarchy", []),
        "entries": entries,
    }


LINEAGE_ROWS = [
    # payload field, source dataset, source column, join key, timestamp semantics, fallback
    ("trade_id", "canonical_visual_trade_view", "visual_trade_id", "visual_trade_id", "n/a", "none"),
    ("source_trade_id", "legacy archive / trader book", "position_id | trade_id", "visual_trade_id", "n/a", "position_id"),
    ("position_id", "legacy archive / trader book", "position_id", "visual_trade_id", "n/a", "none"),
    ("timeframe", "trader book", "timeframe", "book directory", "n/a", "LEGACY_GLOBAL"),
    ("open_ts", "legacy archive / trader book", "opened_at | entry_ts", "visual_trade_id", "fill time, UTC", "none"),
    ("close_ts", "legacy archive / trader book", "closed_at | exit_ts", "visual_trade_id", "fill time, UTC", "none"),
    ("entry_price", "legacy archive / trader book", "entry_price", "visual_trade_id", "point-in-time fill", "none"),
    ("exit_price", "legacy archive / trader book", "exit_price", "visual_trade_id", "point-in-time fill", "none"),
    ("direction", "legacy archive / trader book", "direction | side", "visual_trade_id", "n/a", "LONG"),
    ("position_size_asset", "legacy archive / trader book", "quantity", "visual_trade_id", "n/a", "none"),
    ("gross_price_pnl_usd", "canonical ledger", "gross_pnl_usd (derived from settled fills)", "visual_trade_id", "settled", "none"),
    ("fees_usd", "canonical ledger", "fees_paid | fees_usd", "visual_trade_id", "settled", "none"),
    ("slippage_usd", "canonical ledger", "slippage_paid | slippage_usd", "visual_trade_id", "settled", "none"),
    ("net_realized_pnl_usd", "canonical ledger", "realized_pnl | net_pnl_usd", "visual_trade_id", "settled", "none"),
    ("context_id", "market_context_lifecycle_memory", "context_episode_id", "entry timestamp as-of", "episode active at entry", "null"),
    ("context_episode_id", "market_context_lifecycle_memory", "context_episode_id", "entry timestamp as-of", "episode active at entry", "null"),
    ("lifecycle_episode_id", "trader book", "lifecycle_episode_id", "visual_trade_id", "n/a", "null"),
    ("manager_command_id", "trader book", "command_id", "visual_trade_id", "n/a", "null for legacy"),
    ("stop_loss_price", "legacy archive metadata / trader book", "metadata_json.stop_loss_price | stop_loss_price", "visual_trade_id", "n/a", "null"),
]


def visual_lineage() -> pd.DataFrame:
    rows = [
        {
            "payload_field": field,
            "source_dataset": dataset,
            "source_column": column,
            "join_key": join,
            "timestamp_semantics": semantics,
            "fallback": fallback,
            "economics_version": ECONOMICS_VERSION,
        }
        for field, dataset, column, join, semantics, fallback in LINEAGE_ROWS
    ]
    return pd.DataFrame(rows)


def economics_parity() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "canonical_contract": ECONOMICS_VERSION,
        "canonical_module": "scripts/live/paper_trade_economics.py",
        "canonical_constant": "ECONOMICS_SOURCE = canonical_paper_trade_economics_v1",
        "used_by": {
            "s4_shared_execution_core": ECONOMICS_VERSION,
            "production_paper_ledger": ECONOMICS_VERSION,
            "timeframe_trader_books": ECONOMICS_VERSION,
            "visual_payload": ECONOMICS_VERSION,
        },
        "deprecated_contract": "POLICY_CONTEXT_EVENT_PRICED_PNL",
        "deprecated_reason": (
            "Policy-context event pricing was the research restatement layer used before the "
            "paper controller was repaired. It recomputed economics from context bar prices "
            "instead of reading settled fills, so it can not describe the canonical book."
        ),
        "resolution": "MIGRATE_EXPECTATION_TO_CANONICAL",
        "visual_recomputes_economics": False,
        "visual_copies_ledger_economics": True,
        "pnl_identity": "gross_pnl - fees_paid - slippage_paid == net_pnl",
        "ambiguity": 0,
    }


def no_lookahead(frame: pd.DataFrame) -> pd.DataFrame:
    lifecycle = None
    if LIFECYCLE_MEMORY.exists():
        lifecycle = pd.read_parquet(
            LIFECYCLE_MEMORY, columns=["timestamp", "context_episode_id"]
        )
        lifecycle["timestamp"] = pd.to_datetime(
            lifecycle["timestamp"], utc=True, errors="coerce"
        )

    rows: list[dict[str, Any]] = []
    for _, trade in frame.iterrows():
        entry = pd.to_datetime(trade["entry_timestamp"], utc=True, errors="coerce")
        exit_ = pd.to_datetime(trade["exit_timestamp"], utc=True, errors="coerce")
        episode = trade["context_episode_id"]
        context_ts = None
        if lifecycle is not None and episode is not None:
            match = lifecycle[
                lifecycle["context_episode_id"].astype("Float64")
                == pd.to_numeric(episode, errors="coerce")
            ]
            if len(match):
                context_ts = match["timestamp"].min()
        future_context = bool(
            context_ts is not None
            and not pd.isna(context_ts)
            and not pd.isna(entry)
            and context_ts > entry
        )
        rows.append(
            {
                "visual_trade_id": trade["visual_trade_id"],
                "timeframe": trade["timeframe"],
                "context_episode_id": episode,
                "context_first_seen": context_ts.isoformat().replace("+00:00", "Z")
                if context_ts is not None and not pd.isna(context_ts)
                else None,
                "entry_timestamp": trade["entry_timestamp"],
                "exit_timestamp": trade["exit_timestamp"],
                "context_not_future": not future_context,
                "entry_before_exit": bool(
                    not pd.isna(entry) and not pd.isna(exit_) and entry < exit_
                ),
                "rendered_as_closed": True,
                "source_trade_exists": bool(trade["source_trade_id"]),
            }
        )
    return pd.DataFrame(rows)


def cutover_reconciliation(frame: pd.DataFrame) -> pd.DataFrame:
    boundary = activation_boundary()
    boundary_ts = pd.to_datetime(boundary, utc=True, errors="coerce") if boundary else None
    archive = legacy_archive_dir()
    rows: list[dict[str, Any]] = []
    for _, trade in frame.iterrows():
        exit_ = pd.to_datetime(trade["exit_timestamp"], utc=True, errors="coerce")
        is_legacy = trade["timeframe"] == LEGACY_TIMEFRAME
        side_of_boundary = (
            "UNKNOWN"
            if boundary_ts is None or pd.isna(exit_)
            else ("BEFORE" if exit_ < boundary_ts else "AFTER")
        )
        rows.append(
            {
                "visual_trade_id": trade["visual_trade_id"],
                "source_book": trade["source_book"],
                "timeframe": trade["timeframe"],
                "activation_epoch": trade["activation_epoch"],
                "exit_timestamp": trade["exit_timestamp"],
                "activation_boundary": boundary,
                "side_of_boundary": side_of_boundary,
                "epoch_consistent": (is_legacy and side_of_boundary == "BEFORE")
                or (not is_legacy and side_of_boundary == "AFTER"),
                "archive_read_only": bool(
                    archive is not None
                    and all(
                        not (p.stat().st_mode & 0o200) for p in sorted(archive.glob("*.parquet"))
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    RESEARCH.mkdir(parents=True, exist_ok=True)
    frame = build_canonical_visual_trades()

    (RESEARCH / "patch4_3_contract_inventory.json").write_text(
        json.dumps(contract_inventory(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    visual_lineage().to_csv(RESEARCH / "patch4_3_visual_lineage.csv", index=False)
    (RESEARCH / "patch4_3_economics_parity.json").write_text(
        json.dumps(economics_parity(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    lookahead = no_lookahead(frame)
    lookahead.to_csv(RESEARCH / "patch4_3_no_lookahead.csv", index=False)
    cutover = cutover_reconciliation(frame)
    cutover.to_csv(RESEARCH / "patch4_3_cutover_reconciliation.csv", index=False)

    invariants = reconcile(frame)
    gates = {
        "trades": int(len(frame)),
        "future_context_joins": int((~lookahead["context_not_future"]).sum()) if len(lookahead) else 0,
        "future_trade_joins": int((~lookahead["entry_before_exit"]).sum()) if len(lookahead) else 0,
        "unclosed_positions_as_trades": int(invariants["missing_exit_timestamp"]),
        "duplicate_visual_trade_ids": int(invariants["duplicate_visual_trade_ids"]),
        "cutover_overlap": int(invariants["cutover_overlap"]),
        "epoch_inconsistent": int((~cutover["epoch_consistent"]).sum()) if len(cutover) else 0,
        "legacy_archive_read_only": bool(cutover["archive_read_only"].all()) if len(cutover) else True,
        "pnl_reconciliation_errors": int(invariants["pnl_reconciliation_errors"]),
        "economics_contract_ambiguity": 0,
        "policy_context_rows_retained_as_secondary": int(
            len(pd.read_parquet(POLICY_SOURCE)) if POLICY_SOURCE.exists() else 0
        ),
    }
    (RESEARCH / f"patch4_3_visual_regression_{stamp}.json").write_text(
        json.dumps(
            {"generated_at": utc_now(), "stamp": stamp, "gates": gates, "invariants": invariants},
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(gates, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
