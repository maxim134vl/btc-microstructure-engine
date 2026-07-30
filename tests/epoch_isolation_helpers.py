"""Isolated temporary epoch registry for trading-contract tests.

Tests must never read or mutate runtime:
  data/trading/paper_epochs/active.json
  data/trading/intrabar_paper/**
  live sleeves / books
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from btc_ml.trading.intrabar_paper.trading_contract import CANONICAL_SOURCE_EPOCH

WORKSPACE = Path(__file__).resolve().parents[1]


RUNTIME_HASH_PATHS = (
    "data/trading/paper_epochs/active.json",
    f"data/trading/paper_epochs/{CANONICAL_SOURCE_EPOCH}.json",
    "data/trading/paper_epochs/PER_TF_EQUITY_1PCT_V1_20260729_181431.json",
    "data/trading/paper_epochs/PER_TF_EQUITY_1PCT_V1_20260729_181431.trading_contract.json",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/sleeves.json",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/signals.jsonl",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/commands.jsonl",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/orders.jsonl",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/fills.jsonl",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/positions.jsonl",
    "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260729_181431/books/trades.jsonl",
)


def runtime_file_hashes(repo: Path | None = None) -> dict[str, str]:
    root = repo or WORKSPACE
    out: dict[str, str] = {}
    for rel in RUNTIME_HASH_PATHS:
        path = root / rel
        if not path.exists():
            out[rel] = "MISSING"
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def make_isolated_contract_repo(
    tmp_path: Path,
    *,
    stamp: str = "ISO",
    activate_source: bool = True,
    initial_equity_usd: float | None = None,
) -> Path:
    """Build a self-contained temp repo with explicit source epoch + active pointer."""
    repo = tmp_path / f"isolated_repo_{stamp}"
    (repo / "config").mkdir(parents=True)
    raw = json.loads((WORKSPACE / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    if initial_equity_usd is not None:
        raw["initial_equity_usd"] = float(initial_equity_usd)
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )

    for rel in (
        "data/cognition/intrabar_context_events",
        "data/trading/intrabar_paper",
        "data/trading/paper_epochs",
    ):
        (repo / rel).mkdir(parents=True)

    src_epoch = WORKSPACE / "data" / "trading" / "paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json"
    if not src_epoch.exists():
        raise FileNotFoundError(f"canonical source epoch missing for fixture copy: {src_epoch}")
    epoch_payload = json.loads(src_epoch.read_text(encoding="utf-8"))
    if initial_equity_usd is not None:
        epoch_payload["initial_equity_usd"] = float(initial_equity_usd)
    dst_epoch = repo / "data" / "trading" / "paper_epochs" / f"{CANONICAL_SOURCE_EPOCH}.json"
    dst_epoch.write_text(json.dumps(epoch_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    books = repo / "data" / "trading" / "intrabar_paper" / CANONICAL_SOURCE_EPOCH / "books"
    books.mkdir(parents=True)
    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "positions",
        "trades",
        "blocked",
        "metrics",
        "equity_snapshots",
    ):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")

    if activate_source:
        active = {
            "paper_epoch_id": CANONICAL_SOURCE_EPOCH,
            "epoch_status": "ACTIVE",
            "created_at": epoch_payload.get("created_at"),
            "activated_at": epoch_payload.get("activated_at") or epoch_payload.get("created_at"),
            "closed_at": None,
            "initial_equity_usd": float(epoch_payload.get("initial_equity_usd") or 100000.0),
            "rule_contract_version": epoch_payload.get("rule_contract_version") or "INTRABAR_RULES_V1",
            "trading_contract_fingerprint": epoch_payload.get("trading_contract_fingerprint"),
            "parent_trading_contract_fingerprint": epoch_payload.get(
                "parent_trading_contract_fingerprint"
            ),
        }
        # Keep only known PaperEpoch fields for load_active_epoch compatibility.
        active_epoch = {
            "paper_epoch_id": active["paper_epoch_id"],
            "epoch_status": "ACTIVE",
            "created_at": str(active["created_at"] or "2026-07-28T11:06:36Z"),
            "activated_at": str(active["activated_at"] or "2026-07-28T11:06:36Z"),
            "closed_at": None,
            "initial_equity_usd": float(active["initial_equity_usd"]),
            "rule_contract_version": str(active["rule_contract_version"]),
            "void_reason": None,
            "failed_reason": None,
            "activated_at_monotonic_ns": None,
        }
        (repo / "data" / "trading" / "paper_epochs" / "active.json").write_text(
            json.dumps(active_epoch, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return repo


def assert_no_runtime_touch(before: dict[str, str], after: dict[str, str]) -> None:
    if before != after:
        diverged = {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
        raise AssertionError(f"EPOCH_TEST_RUNTIME_ISOLATION_FAILURE: {diverged}")
