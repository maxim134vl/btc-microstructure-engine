#!/usr/bin/env python3
"""Dry-run one S4.1 manager cycle for the command-relay prototype.

Reuses TimeframeManager policy (context → OPEN/HOLD/CLOSE/NO_ACTION) with
persist=False so production + LIVE1B paths are untouched.

Usage:
  venv/bin/python scripts/research/s41_kinematics_prototype_dry_run.py
  venv/bin/python scripts/research/s41_kinematics_prototype_dry_run.py --evaluation-timestamp 2026-08-10T12:15:00Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.s41_command_relay.contract import (  # noqa: E402
    FORBIDDEN,
    KINEMATICS,
    PROTOTYPE_ID,
    PROTOTYPE_SCHEMA,
    assert_not_production_target,
)
from btc_ml.trading.timeframe_manager import TimeframeManager, load_feed  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import load_sources  # noqa: E402
from btc_ml.trading.trader_book import TraderBook  # noqa: E402


def _latest_evaluation_timestamp() -> str | None:
    path = ROOT / "data" / "runtime" / "multi_timeframe_availability_latest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("latest_evaluation_timestamp")


def build_ephemeral_manager() -> TimeframeManager:
    """Manager with empty in-memory-like books via candidate paths, persist=False later."""
    # Candidate paths are research-only; we still never persist in this dry-run.
    bus = CommandBus(CommandBusPaths.candidate())
    assert_not_production_target(bus.paths.memory)
    books = {
        tf: TraderBook.candidate(tf)
        for tf in ("M15", "M30", "H1", "H4")
    }
    return TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{PROTOTYPE_ID} dry-run (no writes)")
    parser.add_argument(
        "--evaluation-timestamp",
        type=str,
        default=None,
        help="UTC evaluation timestamp (default: MTF availability latest)",
    )
    args = parser.parse_args(argv)

    evaluation = args.evaluation_timestamp or _latest_evaluation_timestamp()
    if evaluation is None:
        print(json.dumps({"error": "NO_EVALUATION_TIMESTAMP", "prototype": PROTOTYPE_ID}))
        return 2

    manager = build_ephemeral_manager()
    cycle = manager.run_cycle(
        evaluation_timestamp=evaluation,
        sources=load_sources(),
        feed=load_feed(),
        activation_boundary=None,
        persist=False,
    )

    commands_out: list[dict[str, Any]] = []
    for cmd in cycle["commands"]:
        commands_out.append(
            {
                "timeframe": cmd.get("timeframe"),
                "intent": cmd.get("intent"),
                "timeframe_direction": cmd.get("timeframe_direction"),
                "lifecycle_phase": cmd.get("lifecycle_phase"),
                "lifecycle_episode_id": cmd.get("lifecycle_episode_id"),
                "availability_status": cmd.get("availability_status"),
                "action_allowed": cmd.get("action_allowed"),
                "reason_codes": cmd.get("reason_codes"),
                "approved_risk_usd": cmd.get("approved_risk_usd"),
                "command_id": cmd.get("command_id"),
            }
        )

    payload = {
        "prototype_id": PROTOTYPE_ID,
        "schema": PROTOTYPE_SCHEMA,
        "mode": "DRY_RUN",
        "kinematics": KINEMATICS,
        "forbidden": list(FORBIDDEN),
        "persist": False,
        "evaluation_timestamp": str(cycle["evaluation_timestamp"]),
        "manager_cycle_id": cycle["manager_cycle_id"],
        "commands": commands_out,
        "note": (
            "Reuses S4.1 TimeframeManager intent policy; does not write command bus "
            "or trader books. LIVE1B untouched. See docs/design/S41_COMMAND_RELAY_PROTOTYPE.md"
        ),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
