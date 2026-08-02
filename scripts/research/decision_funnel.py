#!/usr/bin/env python3
"""Read-only decision funnel for canonical context-to-paper execution diagnostics."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

DEFAULT_EPOCH = "PER_TF_EQUITY_1PCT_V1_20260729_181431"
DEFAULT_PROVIDER = "LIVE1A_CANONICAL_INTRABAR_CONTEXT"
DIRECTIONAL_CONTEXTS = {"LONG_CONTEXT", "SHORT_CONTEXT"}
STAGES = (
    "RAW_DIRECTIONAL_CONTEXT",
    "ARBITRATION_CHOSEN_CONTEXT",
    "CALIBRATED_CONTEXT",
    "LIFECYCLE_CANDIDATE",
    "LIFECYCLE_ACTIVE_CONTEXT",
    "ACTION_ALLOWED",
    "CONTEXT_START_EVENT",
    "LIVE1B_ENTRY_INTENT",
    "LIVE1B_ORDER_CREATED",
    "POSITION_OPENED",
)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_context(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    if text in {"LONG", "BUY", "OPEN_LONG", "INTENT_OPEN_LONG"}:
        return "LONG_CONTEXT"
    if text in {"SHORT", "SELL", "OPEN_SHORT", "INTENT_OPEN_SHORT"}:
        return "SHORT_CONTEXT"
    if text in DIRECTIONAL_CONTEXTS:
        return text
    return text


def normalize_direction(value: Any) -> str:
    context = normalize_context(value)
    if context == "LONG_CONTEXT":
        return "LONG"
    if context == "SHORT_CONTEXT":
        return "SHORT"
    return ""


def context_for_direction(direction: str) -> str | None:
    direction = direction.strip().upper()
    if direction == "LONG":
        return "LONG_CONTEXT"
    if direction == "SHORT":
        return "SHORT_CONTEXT"
    return None


def parse_ts(value: Any) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts


def timestamp_value(row: dict[str, Any]) -> Any:
    for key in (
        "timestamp",
        "event_ts",
        "created_at",
        "cycle_ts",
        "decision_ts",
        "entry_ts",
        "opened_at",
        "ts",
    ):
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "nan", "NaT"}:
            return value
    return None


def in_window(value: Any, start: pd.Timestamp | None, end: pd.Timestamp | None) -> bool:
    ts = parse_ts(value)
    if ts is None:
        return True
    if start is not None and ts < start:
        return False
    if end is not None and ts > end:
        return False
    return True


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def records_from_frame(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return df.to_dict(orient="records")


def filter_records(
    records: Iterable[dict[str, Any]],
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    timeframe: str | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    tf = (timeframe or "").strip().upper()
    for row in records:
        if not in_window(timestamp_value(row), start, end):
            continue
        row_tf = str(row.get("timeframe") or row.get("tf") or "").strip().upper()
        effective_tf = row_tf or "M15"
        if tf and effective_tf != tf:
            continue
        selected.append(row)
    return selected


def row_matches_context(row: dict[str, Any], fields: tuple[str, ...], context: str) -> bool:
    return any(normalize_context(row.get(field)) == context for field in fields)


def action_allowed(row: dict[str, Any], context: str) -> bool:
    if str(row.get("action_allowed") or "").strip().lower() == "true":
        return True
    if row.get("action_allowed") is True:
        return True
    side = normalize_direction(context)
    action = str(row.get("paper_action_candidate") or row.get("paper_policy_action") or "").upper()
    intended = normalize_direction(row.get("intended_side") or row.get("trade_side") or row.get("side"))
    return intended == side and ("INTENT_OPEN" in action or "OPEN" in action)


def stage_row(
    stage: str,
    *,
    timeframe: str,
    direction: str,
    input_count: int,
    passed_count: int,
    rejection_reasons: Iterable[str],
) -> dict[str, Any]:
    rejected_count = max(int(input_count) - int(passed_count), 0)
    counter = Counter(reason for reason in rejection_reasons if reason)
    reason, count = (counter.most_common(1)[0] if counter else ("", 0))
    rate = (float(passed_count) / float(input_count)) if input_count else 0.0
    return {
        "stage": stage,
        "timeframe": timeframe,
        "direction": direction,
        "input_count": int(input_count),
        "passed_count": int(passed_count),
        "rejected_count": int(rejected_count),
        "pass_rate": rate,
        "dominant_rejection_reason": reason,
        "dominant_rejection_count": int(count),
    }


def count_signals(rows: list[dict[str, Any]], context: str) -> int:
    side = normalize_direction(context)
    count = 0
    for row in rows:
        row_side = normalize_direction(row.get("side") or row.get("direction") or row.get("intended_side"))
        action = str(row.get("action") or row.get("signal_type") or row.get("paper_action") or "").upper()
        if row_side == side and ("ENTRY" in action or "OPEN" in action or action == ""):
            count += 1
    return count


def count_orders(rows: list[dict[str, Any]], context: str) -> int:
    side = normalize_direction(context)
    count = 0
    for row in rows:
        row_side = normalize_direction(row.get("side") or row.get("direction") or row.get("trade_side"))
        order_status = str(row.get("status") or row.get("order_status") or "").upper()
        order_type = str(row.get("order_type") or row.get("type") or row.get("action") or "").upper()
        if row_side == side and ("ENTRY" in order_type or "OPEN" in order_type or order_type == ""):
            if order_status not in {"REJECTED", "CANCELLED", "CANCELED"}:
                count += 1
    return count


def count_positions(rows: list[dict[str, Any]], context: str) -> int:
    side = normalize_direction(context)
    count = 0
    for row in rows:
        row_side = normalize_direction(row.get("side") or row.get("direction") or row.get("trade_side"))
        status = str(row.get("status") or row.get("position_status") or "").upper()
        is_opening_record = bool(
            row.get("opened_at")
            or row.get("entry_command_id")
            or row.get("entry_fill_id")
            or row.get("entry_context_event_id")
            or status == "OPEN"
        )
        if row_side == side and is_opening_record and status not in {"REJECTED", "CANCELLED", "CANCELED"}:
            count += 1
    return count


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def make_rejection(
    *,
    row: dict[str, Any] | None,
    timeframe: str,
    direction: str,
    source_stage: str,
    rejected_stage: str,
    rejection_reason: str,
    epoch: str,
    raw_context: str = "",
    calibrated_context: str = "",
    provider: str = DEFAULT_PROVIDER,
) -> dict[str, Any]:
    row = row or {}
    source_timestamp = timestamp_value(row)
    decision_id = row.get("decision_id") or row.get("cycle_id") or row.get("event_id") or source_timestamp or ""
    return {
        "decision_id": decision_id,
        "source_timestamp": source_timestamp,
        "timestamp": source_timestamp,
        "timeframe": timeframe,
        "direction": direction,
        "source_stage": source_stage,
        "rejected_stage": rejected_stage,
        "rejection_reason": rejection_reason,
        "provider": provider,
        "epoch": epoch,
        "raw_context": raw_context or normalize_context(row.get("raw_chosen_context") or row.get("candidate_context") or row.get("active_market_context")),
        "calibrated_context": calibrated_context or normalize_context(row.get("calibrated_context") or row.get("active_market_context")),
        "cycle_id": row.get("cycle_id", ""),
    }


def build_decision_funnel(
    *,
    repo_root: Path,
    output_dir: Path,
    start: str | None = None,
    end: str | None = None,
    epoch: str = DEFAULT_EPOCH,
    timeframe: str = "M15",
    direction: str = "SHORT",
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    output_dir = Path(output_dir)
    start_ts = parse_ts(start) if start else None
    end_ts = parse_ts(end) if end else None
    direction = direction.strip().upper()
    context = context_for_direction(direction)
    if context is None:
        raise ValueError(f"unsupported direction: {direction}")

    arbitration = filter_records(
        records_from_frame(read_parquet(repo_root / "data" / "cognition" / "auction_context_arbitration_memory.parquet")),
        start=start_ts,
        end=end_ts,
        timeframe=timeframe,
    )
    lifecycle = filter_records(
        records_from_frame(read_parquet(repo_root / "data" / "cognition" / "market_context_lifecycle_memory.parquet")),
        start=start_ts,
        end=end_ts,
        timeframe=timeframe,
    )
    context_events = filter_records(
        read_jsonl(repo_root / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"),
        start=start_ts,
        end=end_ts,
        timeframe=timeframe,
    )
    books = repo_root / "data" / "trading" / "intrabar_paper" / epoch / "books"
    signals = filter_records(read_jsonl(books / "signals.jsonl"), start=start_ts, end=end_ts, timeframe=timeframe)
    orders = filter_records(read_jsonl(books / "orders.jsonl"), start=start_ts, end=end_ts, timeframe=timeframe)
    positions = filter_records(read_jsonl(books / "positions.jsonl"), start=start_ts, end=end_ts, timeframe=timeframe)

    raw_rows = [r for r in arbitration if row_matches_context(r, ("raw_chosen_context", "raw_context"), context)]
    chosen_rows = [r for r in arbitration if row_matches_context(r, ("raw_chosen_context", "chosen_context"), context)]
    calibrated_rows = [r for r in arbitration if row_matches_context(r, ("calibrated_context", "chosen_context"), context)]
    lifecycle_candidate = [r for r in lifecycle if row_matches_context(r, ("candidate_context",), context)]
    lifecycle_active = [r for r in lifecycle if row_matches_context(r, ("active_market_context",), context)]
    allowed_rows = [r for r in lifecycle if action_allowed(r, context)]
    start_rows = [
        r
        for r in lifecycle
        if row_matches_context(r, ("candidate_context", "active_market_context"), context)
        and (r.get("context_start_event") is True or str(r.get("context_start_event") or "").lower() == "true")
    ]
    start_rows.extend(
        r
        for r in context_events
        if row_matches_context(r, ("context", "new_context", "active_market_context", "candidate_context"), context)
        and str(r.get("event_type") or r.get("type") or "").upper() in {"CONTEXT_START", "CONTEXT_FLIP", "START"}
    )
    signal_count = count_signals(signals, context)
    order_count = count_orders(orders, context)
    position_count = count_positions(positions, context)

    rejections: list[dict[str, Any]] = []
    for row in raw_rows:
        calibrated = normalize_context(row.get("calibrated_context") or row.get("chosen_context"))
        if calibrated != context:
            rejections.append(
                make_rejection(
                    row=row,
                    timeframe=timeframe,
                    direction=direction,
                    source_stage="ARBITRATION_CHOSEN_CONTEXT",
                    rejected_stage="CALIBRATED_CONTEXT",
                    rejection_reason=row.get("suppress_reason") or "CALIBRATED_CONTEXT_MISMATCH",
                    epoch=epoch,
                    raw_context=normalize_context(row.get("raw_chosen_context") or row.get("raw_context")),
                    calibrated_context=calibrated,
                )
            )
    for row in lifecycle_candidate:
        if not action_allowed(row, context):
            rejections.append(
                make_rejection(
                    row=row,
                    timeframe=timeframe,
                    direction=direction,
                    source_stage="LIFECYCLE_CANDIDATE",
                    rejected_stage="ACTION_ALLOWED",
                    rejection_reason=row.get("block_reason")
                    or row.get("no_trade_reason")
                    or row.get("transition_block_reason")
                    or "ACTION_NOT_ALLOWED",
                    epoch=epoch,
                    raw_context=normalize_context(row.get("candidate_context")),
                    calibrated_context=normalize_context(row.get("active_market_context")),
                )
            )

    def add_aggregate_loss(source_stage: str, rejected_stage: str, loss_count: int, reason: str) -> None:
        for idx in range(max(int(loss_count), 0)):
            rejections.append(
                make_rejection(
                    row={"decision_id": f"AGGREGATE_{rejected_stage}_{idx + 1}"},
                    timeframe=timeframe,
                    direction=direction,
                    source_stage=source_stage,
                    rejected_stage=rejected_stage,
                    rejection_reason=reason,
                    epoch=epoch,
                    raw_context=context,
                    calibrated_context=context,
                )
            )

    add_aggregate_loss("CALIBRATED_CONTEXT", "LIFECYCLE_CANDIDATE", len(calibrated_rows) - len(lifecycle_candidate), "LIFECYCLE_CANDIDATE_NOT_MATERIALIZED")
    add_aggregate_loss("LIFECYCLE_CANDIDATE", "LIFECYCLE_ACTIVE_CONTEXT", len(lifecycle_candidate) - len(lifecycle_active), "LIFECYCLE_ACTIVE_CONTEXT_NOT_REACHED")
    add_aggregate_loss("ACTION_ALLOWED", "CONTEXT_START_EVENT", len(allowed_rows) - len(start_rows), "NO_CONTEXT_START_EVENT")
    add_aggregate_loss("CONTEXT_START_EVENT", "LIVE1B_ENTRY_INTENT", len(start_rows) - signal_count, "NO_LIVE1B_ENTRY_INTENT")
    add_aggregate_loss("LIVE1B_ENTRY_INTENT", "LIVE1B_ORDER_CREATED", signal_count - order_count, "NO_LIVE1B_ORDER_CREATED")
    add_aggregate_loss("LIVE1B_ORDER_CREATED", "POSITION_OPENED", order_count - position_count, "NO_POSITION_OPENED")

    rejection_by_stage: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for row in rejections:
        rejection_by_stage.setdefault(str(row["rejected_stage"]), []).append(str(row["rejection_reason"]))

    counts = {
        "RAW_DIRECTIONAL_CONTEXT": (len(arbitration), len(raw_rows)),
        "ARBITRATION_CHOSEN_CONTEXT": (len(raw_rows), len(chosen_rows)),
        "CALIBRATED_CONTEXT": (len(chosen_rows), len(calibrated_rows)),
        "LIFECYCLE_CANDIDATE": (len(calibrated_rows), len(lifecycle_candidate)),
        "LIFECYCLE_ACTIVE_CONTEXT": (len(lifecycle_candidate), len(lifecycle_active)),
        "ACTION_ALLOWED": (len(lifecycle_candidate), len(allowed_rows)),
        "CONTEXT_START_EVENT": (len(allowed_rows), len(start_rows)),
        "LIVE1B_ENTRY_INTENT": (len(start_rows), signal_count),
        "LIVE1B_ORDER_CREATED": (signal_count, order_count),
        "POSITION_OPENED": (order_count, position_count),
    }
    summary_rows = [
        stage_row(
            stage,
            timeframe=timeframe,
            direction=direction,
            input_count=counts[stage][0],
            passed_count=counts[stage][1],
            rejection_reasons=rejection_by_stage.get(stage, []),
        )
        for stage in STAGES
    ]

    summary = {
        "repo_root": str(repo_root),
        "epoch": epoch,
        "timeframe": timeframe,
        "direction": direction,
        "start": start or "",
        "end": end or "",
        "stage_count": len(STAGES),
        "rejection_count": len(rejections),
        "retired_global_short_disable_count": sum(
            1 for r in rejections if r.get("rejection_reason") == "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE"
        ),
        "outputs": {
            "decision_funnel_csv": str(output_dir / "decision_funnel.csv"),
            "decision_funnel_rejections_csv": str(output_dir / "decision_funnel_rejections.csv"),
            "decision_funnel_summary_json": str(output_dir / "decision_funnel_summary.json"),
            "decision_funnel_md": str(output_dir / "DECISION_FUNNEL.md"),
        },
    }

    write_csv(
        output_dir / "decision_funnel.csv",
        summary_rows,
        [
            "stage",
            "timeframe",
            "direction",
            "input_count",
            "passed_count",
            "rejected_count",
            "pass_rate",
            "dominant_rejection_reason",
            "dominant_rejection_count",
        ],
    )
    write_csv(
        output_dir / "decision_funnel_rejections.csv",
        rejections,
        [
            "decision_id",
            "source_timestamp",
            "timestamp",
            "timeframe",
            "direction",
            "source_stage",
            "rejected_stage",
            "rejection_reason",
            "provider",
            "epoch",
            "raw_context",
            "calibrated_context",
            "cycle_id",
        ],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "decision_funnel_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    md_lines = [
        "# Decision Funnel",
        "",
        f"repo_root: `{repo_root}`",
        f"epoch: `{epoch}`",
        f"timeframe: `{timeframe}`",
        f"direction: `{direction}`",
        f"window: `{start or ''}` -> `{end or ''}`",
        "",
        "| stage | input | passed | rejected | pass_rate | dominant_rejection |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary_rows:
        md_lines.append(
            "| {stage} | {input_count} | {passed_count} | {rejected_count} | {pass_rate:.4f} | {reason} |".format(
                reason=row.get("dominant_rejection_reason") or "",
                **row,
            )
        )
    (output_dir / "DECISION_FUNNEL.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(repo_root_from_script()))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--epoch", default=DEFAULT_EPOCH)
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--direction", choices=("LONG", "SHORT"), default="SHORT")
    args = parser.parse_args(argv)
    build_decision_funnel(
        repo_root=Path(args.repo_root),
        output_dir=Path(args.output_dir),
        start=args.start,
        end=args.end,
        epoch=args.epoch,
        timeframe=args.timeframe,
        direction=args.direction,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
