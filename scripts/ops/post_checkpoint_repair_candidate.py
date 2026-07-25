"""Candidate validation for the post-checkpoint runtime repair.

Builds candidate artifacts and checks the acceptance gates without touching any
production dataset or starting any daemon. Production inputs are opened
read-only; every write goes to data/research/post_checkpoint_*.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("/Users/fontecrypto/btc-ml")
RESEARCH = ROOT / "data/research"
PRODUCTION_CONTEXT_LOG = ROOT / "data/live/context_decision_log.parquet"

CONTEXT_CANDIDATE = RESEARCH / "post_checkpoint_context_candidate.parquet"
VIEW_CANDIDATE = RESEARCH / "post_checkpoint_visual_view_candidate.parquet"
PAYLOAD_CANDIDATE = RESEARCH / "post_checkpoint_visual_payload_candidate.json"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------- context
def context_candidate() -> dict:
    logger = _load("append_context_decision_log", "scripts/live/append_context_decision_log.py")

    before_hash = sha256(PRODUCTION_CONTEXT_LOG)
    existing = pd.read_parquet(PRODUCTION_CONTEXT_LOG)
    existing_schema = pq.read_schema(PRODUCTION_CONTEXT_LOG)
    prefix_before = existing.copy(deep=True)

    # Worst case for the defect: a non-null context_entered_at arriving as an ISO
    # string with no microseconds, appended onto a timestamp[us, tz=UTC] column.
    row = {col: None for col in existing.columns}
    row["candle_timestamp"] = "2099-01-01T00:00:00Z"
    row["context_entered_at"] = "2026-07-25T09:15:00Z"
    row["record_origin"] = "CANDIDATE_VALIDATION"

    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    degraded = str(combined["context_entered_at"].dtype) == "object"
    combined = logger.normalize_canonical_timestamp_columns(combined)
    combined.to_parquet(CONTEXT_CANDIDATE, index=False)

    candidate = pd.read_parquet(CONTEXT_CANDIDATE)
    candidate_schema = pq.read_schema(CONTEXT_CANDIDATE)

    prefix_after = candidate.iloc[: len(prefix_before)]
    prefix_changed = not prefix_before["context_entered_at"].equals(
        prefix_after["context_entered_at"]
    )
    for column in ("candle_timestamp", "decision_payload_hash"):
        if column in prefix_before.columns:
            prefix_changed = prefix_changed or not prefix_before[column].equals(
                prefix_after[column]
            )

    duplicates = 0
    if "candle_timestamp" in candidate.columns:
        duplicates = int(candidate["candle_timestamp"].dropna().duplicated().sum())

    return {
        "production_untouched": sha256(PRODUCTION_CONTEXT_LOG) == before_hash,
        "concat_degraded_to_object_before_normalize": degraded,
        "context_schema_match": existing_schema.names == candidate_schema.names,
        "context_entered_at_type": str(candidate_schema.field("context_entered_at").type),
        "context_entered_at_type_preserved": str(
            candidate_schema.field("context_entered_at").type
        )
        == str(existing_schema.field("context_entered_at").type),
        "context_prefix_changed": bool(prefix_changed),
        "context_duplicate_rows": duplicates,
        "rows_before": int(len(existing)),
        "rows_after": int(len(candidate)),
        "appended_value_readable": str(candidate["context_entered_at"].iloc[-1]),
    }


# ---------------------------------------------------------------------- visual
def visual_candidate() -> dict:
    from btc_ml.visual.canonical_trade_view import (  # noqa: PLC0415
        build_canonical_visual_trades,
        reconcile,
        utc_series,
    )

    refresher = _load(
        "run_market_context_visual_refresher",
        "scripts/live/run_market_context_visual_refresher.py",
    )

    frame = build_canonical_visual_trades()
    frame.to_parquet(VIEW_CANDIDATE, index=False)
    invariants = reconcile(frame)

    entry = utc_series(frame["entry_timestamp"])
    exit_ = utc_series(frame["exit_timestamp"])
    parse_errors = int(entry.isna().sum() + exit_.isna().sum())

    s4 = frame[frame["timeframe"] != "LEGACY_GLOBAL"]
    misclassified = int(utc_series(s4["exit_timestamp"]).isna().sum()) if len(s4) else 0

    layer = refresher.build_normalized_trade_render_layer(utc_now(), None)
    overlays = refresher.build_overlays_from_trade_render_layer(layer)
    PAYLOAD_CANDIDATE.write_text(
        json.dumps({"render_layer": layer, "overlays": overlays}, indent=2, default=str)
    )

    closed = overlays.get("closed_trades") or []
    rendered_timeframes = sorted({str(t.get("timeframe")) for t in closed if isinstance(t, dict)})

    return {
        "view_rows": int(len(frame)),
        "mixed_timestamp_parse_errors": parse_errors,
        "closed_S4_trades_misclassified": misclassified,
        "unclosed_positions_as_trades": int(invariants["missing_exit_timestamp"]),
        "future_context_joins": int(invariants["s4_rows_before_boundary"])
        + int(invariants["legacy_rows_after_boundary"]),
        "future_trade_joins": int(invariants["inverted_timestamps"]),
        "pnl_reconciliation_errors": int(invariants["pnl_reconciliation_errors"]),
        "duplicate_visual_trade_ids": int(invariants["duplicate_visual_trade_ids"]),
        "payload_closed_trade_count": len(closed),
        "payload_timeframes_rendered": rendered_timeframes,
        "s4_rows": int(len(s4)),
    }


def main() -> int:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    context = context_candidate()
    visual = visual_candidate()

    gates = {
        "context_schema_match": context["context_schema_match"]
        and context["context_entered_at_type_preserved"],
        "context_prefix_changed": context["context_prefix_changed"],
        "context_duplicate_rows": context["context_duplicate_rows"],
        "mixed_timestamp_parse_errors": visual["mixed_timestamp_parse_errors"],
        "closed_S4_trades_misclassified": visual["closed_S4_trades_misclassified"],
        "unclosed_positions_as_trades": visual["unclosed_positions_as_trades"],
        "future_context_joins": visual["future_context_joins"],
        "future_trade_joins": visual["future_trade_joins"],
        "pnl_reconciliation_errors": visual["pnl_reconciliation_errors"],
        "duplicate_visual_trade_ids": visual["duplicate_visual_trade_ids"],
    }
    passed = (
        gates["context_schema_match"] is True
        and gates["context_prefix_changed"] is False
        and all(
            gates[k] == 0
            for k in (
                "context_duplicate_rows",
                "mixed_timestamp_parse_errors",
                "closed_S4_trades_misclassified",
                "unclosed_positions_as_trades",
                "future_context_joins",
                "future_trade_joins",
                "pnl_reconciliation_errors",
                "duplicate_visual_trade_ids",
            )
        )
        and context["production_untouched"]
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": utc_now(),
        "stamp": stamp,
        "context": context,
        "visual": visual,
        "gates": gates,
        "all_gates_passed": passed,
    }
    (RESEARCH / f"post_checkpoint_candidate_gates_{stamp}.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
