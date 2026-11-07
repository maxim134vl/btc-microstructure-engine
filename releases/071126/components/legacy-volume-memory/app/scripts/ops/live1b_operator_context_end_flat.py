#!/usr/bin/env python3
"""Close LIVE1B open positions via durable CONTEXT_END (current paper rules).

Appends operator CONTEXT_END events matching each active position's
lifecycle_episode_id so the running IntrabarPaperEngine exits by contract
(CONTEXT_END → _exit_position). Does not invent ledger rows by hand.

  venv/bin/python scripts/ops/live1b_operator_context_end_flat.py
  venv/bin/python scripts/ops/live1b_operator_context_end_flat.py --wait-seconds 90
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import importlib.util


def _load_journal_mod():
    path = ROOT / "src" / "btc_ml" / "live" / "intrabar" / "context_event_journal.py"
    spec = importlib.util.spec_from_file_location("context_event_journal_cutover", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_journal_mod = _load_journal_mod()
ContextEventJournal = _journal_mod.ContextEventJournal

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.epoch import load_active_epoch  # noqa: E402


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_health() -> dict[str, Any]:
    path = ROOT / "data" / "runtime" / "intrabar_paper_health.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _active_from_health(health: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = health.get("active_positions_by_timeframe") or {}
    return {str(tf).upper(): dict(val) for tf, val in raw.items() if val}


def _latest_open_row(books_root: Path, timeframe: str) -> dict[str, Any] | None:
    path = books_root / "positions.jsonl"
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if str(row.get("timeframe") or "").upper() != timeframe:
            continue
        last = row
    if last is None:
        return None
    if str(last.get("status") or "").upper() != "OPEN" or last.get("closed_at"):
        return None
    return last


def _max_journal_mono(journal_path: Path) -> int:
    mono = 0
    if not journal_path.exists():
        return mono
    with journal_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                mono = max(mono, int(ev.get("event_monotonic_ns") or 0))
            except (TypeError, ValueError):
                continue
    return mono


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_intrabar_paper_config(repo_root=ROOT)
    epoch = load_active_epoch(cfg.epochs_root)
    if epoch is None or epoch.epoch_status != "ACTIVE":
        print(json.dumps({"error": "no_active_epoch"}))
        return 2

    health = _load_health()
    active = _active_from_health(health)
    if not active:
        print(json.dumps({"status": "ALREADY_FLAT", "active": {}}, indent=2))
        return 0

    books_root = cfg.books_root / epoch.paper_epoch_id / "books"
    journal_root = ROOT / "data" / "cognition" / "intrabar_context_events"
    journal = ContextEventJournal(journal_root)
    bbo = (health.get("current_bbo") or {}) if isinstance(health.get("current_bbo"), dict) else {}
    bid = bbo.get("best_bid")
    ask = bbo.get("best_ask")
    mid = None
    if bid is not None and ask is not None:
        mid = (float(bid) + float(ask)) / 2.0
    mono_base = max(_max_journal_mono(journal.path), int(time.time_ns()))

    planned: list[dict[str, Any]] = []
    for i, (tf, pos_h) in enumerate(sorted(active.items())):
        row = _latest_open_row(books_root, tf)
        if row is None:
            planned.append({"timeframe": tf, "error": "NO_OPEN_BOOK_ROW", "health": pos_h})
            continue
        side = str(pos_h.get("side") or row.get("side") or "LONG").upper()
        prev = "LONG_CONTEXT" if side == "LONG" else "SHORT_CONTEXT"
        episode = str(row.get("lifecycle_episode_id") or "")
        mono = mono_base + 10_000 + i
        now = _utc_iso()
        price = mid if mid is not None else float(pos_h.get("entry_price") or row.get("entry_price") or 0.0)
        event = journal.build_event(
            timeframe=tf,
            event_type="CONTEXT_END",
            previous_context=prev,
            new_context="OBSERVE",
            event_timestamp=now,
            event_monotonic_ns=mono,
            context_event_price=str(price),
            last_trade_id=None,
            last_trade_timestamp=None,
            best_bid=bid,
            best_ask=ask,
            book_update_id=bbo.get("book_update_id"),
            bbo_receive_monotonic_ns=mono,
            bbo_age_ms=0.0,
            connection_session_id=str(uuid.uuid4()),
            reconnect_generation=1,
            causal_cutoff_timestamp=now,
            causal_cutoff_monotonic_ns=mono,
            model_version="operator_cutover_context_end_v1",
            lifecycle_episode_id=episode,
            evidence={
                "operator_action": "CUTOVER_FLAT",
                "reason": "REPLACE_LIVE1B_WITH_S41_INDEPENDENT_TF",
                "position_id": row.get("position_id"),
                "side": side,
            },
            provider_id="OPERATOR_CUTOVER",
            epoch_id=epoch.paper_epoch_id,
            source_bar_timestamp=now,
            decision_available_at=now,
            context_origin_timestamp=row.get("opened_at") or now,
            execution_not_before=now,
            direction=side,
            evaluation_mode="OPERATOR_CONTEXT_END",
            extra_metadata={"paper_action_candidate": "EXIT", "intended_side": "FLAT"},
        )
        # Ensure exit side matching for engine._event_side / END branch.
        event["direction"] = side
        event["new_context"] = "OBSERVE"
        event["previous_context"] = prev
        planned.append(
            {
                "timeframe": tf,
                "position_id": row.get("position_id"),
                "lifecycle_episode_id": episode,
                "side": side,
                "context_event_id": event.get("context_event_id"),
                "event": event,
            }
        )

    result: dict[str, Any] = {
        "status": "DRY_RUN" if args.dry_run else "SUBMITTED",
        "paper_epoch_id": epoch.paper_epoch_id,
        "active_before": active,
        "planned": [
            {k: v for k, v in item.items() if k != "event"} for item in planned
        ],
    }
    if args.dry_run:
        print(json.dumps(result, indent=2, default=str))
        return 0

    written = []
    for item in planned:
        if "error" in item:
            continue
        ok = journal.append(item["event"])
        written.append(
            {
                "timeframe": item["timeframe"],
                "appended": ok,
                "context_event_id": item["context_event_id"],
                "lifecycle_episode_id": item["lifecycle_episode_id"],
            }
        )
    result["written"] = written

    deadline = time.time() + float(args.wait_seconds)
    flat = False
    last_active: dict[str, Any] = active
    while time.time() < deadline:
        time.sleep(float(args.poll_seconds))
        try:
            health = _load_health()
        except Exception as exc:  # noqa: BLE001
            result["wait_error"] = str(exc)
            break
        last_active = _active_from_health(health)
        if not last_active:
            flat = True
            break

    result["active_after"] = last_active
    result["flat"] = flat
    result["status"] = "FLAT" if flat else "WAITING_TIMEOUT"
    print(json.dumps(result, indent=2, default=str))
    return 0 if flat else 3


if __name__ == "__main__":
    raise SystemExit(main())
