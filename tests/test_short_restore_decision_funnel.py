from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.research.decision_funnel import build_decision_funnel  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_decision_funnel_reports_historical_short_global_disable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data" / "cognition"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "raw_chosen_context": "SHORT_CONTEXT",
                "calibrated_context": "OBSERVE",
                "suppress_reason": "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE",
                "cycle_id": "C1",
            }
        ]
    ).to_parquet(data / "auction_context_arbitration_memory.parquet", index=False)

    out = tmp_path / "out"
    summary = build_decision_funnel(
        repo_root=repo,
        output_dir=out,
        start="2026-07-30T00:00:00Z",
        end="2026-07-31T00:00:00Z",
        epoch="TEST_EPOCH",
        timeframe="M15",
        direction="SHORT",
    )

    funnel = pd.read_csv(out / "decision_funnel.csv")
    calibrated = funnel[funnel["stage"] == "CALIBRATED_CONTEXT"].iloc[0]
    assert int(calibrated["input_count"]) == 1
    assert int(calibrated["passed_count"]) == 0
    assert summary["retired_global_short_disable_count"] == 1

    rejections = pd.read_csv(out / "decision_funnel_rejections.csv")
    assert set(rejections["rejection_reason"]) == {"SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE"}
    assert set(rejections["rejected_stage"]) == {"CALIBRATED_CONTEXT"}


def test_decision_funnel_writes_only_to_output_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data" / "cognition"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "raw_chosen_context": "SHORT_CONTEXT",
                "calibrated_context": "SHORT_CONTEXT",
                "suppress_reason": "",
                "cycle_id": "C2",
            }
        ]
    ).to_parquet(data / "auction_context_arbitration_memory.parquet", index=False)
    before = _snapshot(repo)

    out = tmp_path / "out"
    build_decision_funnel(repo_root=repo, output_dir=out, epoch="TEST_EPOCH", timeframe="M15", direction="SHORT")

    assert _snapshot(repo) == before
    assert sorted(p.name for p in out.iterdir()) == [
        "DECISION_FUNNEL.md",
        "decision_funnel.csv",
        "decision_funnel_rejections.csv",
        "decision_funnel_summary.json",
    ]


def test_decision_funnel_keeps_lifecycle_action_rejection_separate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data" / "cognition"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "raw_chosen_context": "SHORT_CONTEXT",
                "calibrated_context": "SHORT_CONTEXT",
                "suppress_reason": "",
            }
        ]
    ).to_parquet(data / "auction_context_arbitration_memory.parquet", index=False)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "candidate_context": "SHORT_CONTEXT",
                "active_market_context": "OBSERVE",
                "action_allowed": False,
                "block_reason": "ENTRY_BLOCKED_NO_CAUSAL_BBO",
            }
        ]
    ).to_parquet(data / "market_context_lifecycle_memory.parquet", index=False)

    out = tmp_path / "out"
    build_decision_funnel(repo_root=repo, output_dir=out, epoch="TEST_EPOCH", timeframe="M15", direction="SHORT")

    rejections = pd.read_csv(out / "decision_funnel_rejections.csv")
    assert "ENTRY_BLOCKED_NO_CAUSAL_BBO" in set(rejections["rejection_reason"])
    assert "ACTION_ALLOWED" in set(rejections["rejected_stage"])


def test_decision_funnel_distinguishes_manager_and_execution_rejections(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data" / "cognition"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "raw_chosen_context": "SHORT_CONTEXT",
                "calibrated_context": "SHORT_CONTEXT",
                "suppress_reason": "",
            }
        ]
    ).to_parquet(data / "auction_context_arbitration_memory.parquet", index=False)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "candidate_context": "SHORT_CONTEXT",
                "active_market_context": "SHORT_CONTEXT",
                "action_allowed": True,
                "context_start_event": True,
            }
        ]
    ).to_parquet(data / "market_context_lifecycle_memory.parquet", index=False)

    manager_out = tmp_path / "manager_out"
    build_decision_funnel(repo_root=repo, output_dir=manager_out, epoch="TEST_EPOCH", timeframe="M15", direction="SHORT")
    manager_rejections = pd.read_csv(manager_out / "decision_funnel_rejections.csv")
    assert "NO_LIVE1B_ENTRY_INTENT" in set(manager_rejections["rejection_reason"])
    assert "LIVE1B_ENTRY_INTENT" in set(manager_rejections["rejected_stage"])

    _write_jsonl(
        repo / "data" / "trading" / "intrabar_paper" / "TEST_EPOCH" / "books" / "signals.jsonl",
        [{"timestamp": "2026-07-30T12:00:00Z", "timeframe": "M15", "side": "SHORT", "action": "ENTRY"}],
    )
    execution_out = tmp_path / "execution_out"
    build_decision_funnel(repo_root=repo, output_dir=execution_out, epoch="TEST_EPOCH", timeframe="M15", direction="SHORT")
    execution_rejections = pd.read_csv(execution_out / "decision_funnel_rejections.csv")
    assert "NO_LIVE1B_ORDER_CREATED" in set(execution_rejections["rejection_reason"])
    assert "LIVE1B_ORDER_CREATED" in set(execution_rejections["rejected_stage"])
    assert {"decision_id", "source_timestamp", "provider", "epoch"}.issubset(execution_rejections.columns)


def test_decision_funnel_counts_only_opening_position_records(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "data" / "cognition"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "raw_chosen_context": "LONG_CONTEXT",
                "calibrated_context": "LONG_CONTEXT",
                "suppress_reason": "",
            }
        ]
    ).to_parquet(data / "auction_context_arbitration_memory.parquet", index=False)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-30T12:00:00Z",
                "timeframe": "M15",
                "candidate_context": "LONG_CONTEXT",
                "active_market_context": "LONG_CONTEXT",
                "action_allowed": True,
                "context_start_event": True,
            }
        ]
    ).to_parquet(data / "market_context_lifecycle_memory.parquet", index=False)
    books = repo / "data" / "trading" / "intrabar_paper" / "TEST_EPOCH" / "books"
    _write_jsonl(books / "signals.jsonl", [{"timestamp": "2026-07-30T12:00:00Z", "timeframe": "M15", "side": "LONG", "action": "ENTRY"}])
    _write_jsonl(books / "orders.jsonl", [{"timestamp": "2026-07-30T12:00:00Z", "timeframe": "M15", "side": "LONG", "action": "ENTRY", "status": "FILLED"}])
    _write_jsonl(
        books / "positions.jsonl",
        [
            {"opened_at": "2026-07-30T12:00:00Z", "timeframe": "M15", "side": "LONG", "status": "OPEN", "position_id": "p1"},
            {"closed_at": "2026-07-30T13:00:00Z", "timeframe": "M15", "side": "LONG", "status": "CLOSED", "position_id": "p1"},
        ],
    )

    out = tmp_path / "out"
    build_decision_funnel(repo_root=repo, output_dir=out, epoch="TEST_EPOCH", timeframe="M15", direction="LONG")

    funnel = pd.read_csv(out / "decision_funnel.csv")
    opened = funnel[funnel["stage"] == "POSITION_OPENED"].iloc[0]
    assert int(opened["input_count"]) == 1
    assert int(opened["passed_count"]) == 1
