#!/usr/bin/env python3
"""S4.1 §24 — natural live paper validation of the manager/trader runtime.

Observes production manager cycles without forcing anything: it only reads the
append-only command bus, the trader books and the portfolio summary, then writes
one artifact per observation window.

Nothing is written outside ``data/research/``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths, utc_now  # noqa: E402
from btc_ml.trading.paper_trader_engine import PaperTraderEngine  # noqa: E402
from btc_ml.trading.timeframe_manager import load_feed  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import SUPPORTED_TIMEFRAMES  # noqa: E402
from btc_ml.trading.trader_book import TraderBook, atomic_write_json  # noqa: E402

RESEARCH = ROOT / "data" / "research"
ACTIVATION_PATH = ROOT / "data" / "trading" / "manager" / "activation.json"


def _f(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return 0.0
    return 0.0 if out != out else out


def activation_boundary() -> str | None:
    if not ACTIVATION_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("activation_timestamp")


def trader_snapshot(timeframe: str, *, mark_price: float | None) -> dict[str, Any]:
    """Read-only view of a production trader, using the trader's own read-model."""
    book = TraderBook.production(timeframe)
    engine = PaperTraderEngine(book)
    snapshot = engine.snapshot(mark_price=mark_price)
    state = book.load_controller_state()
    snapshot["processed_commands"] = len(state.get("processed_command_ids") or [])
    snapshot["book_root"] = str(book.root.relative_to(ROOT))
    return snapshot


def mark_price_from_feed() -> float | None:
    """Last completed market close, taken from the same feed the traders read."""
    try:
        feed = load_feed()
    except Exception:
        return None
    if feed is None or not len(feed) or "close" not in feed.columns:
        return None
    return _f(feed["close"].iloc[-1])


def observe(*, cycles: int, timeout_minutes: float, poll_seconds: float) -> dict[str, Any]:
    bus = CommandBus(CommandBusPaths.production())
    boundary = activation_boundary()
    seen: list[str] = []
    rows: list[dict[str, Any]] = []
    deadline = time.time() + timeout_minutes * 60.0
    started_at = utc_now()

    def executable(frame: pd.DataFrame) -> pd.DataFrame:
        if not len(frame) or boundary is None:
            return frame
        stamps = pd.to_datetime(frame["evaluation_timestamp"], utc=True, errors="coerce")
        return frame[stamps >= pd.Timestamp(boundary)]

    while len(seen) < cycles and time.time() < deadline:
        frame = executable(bus.frame())
        if len(frame):
            for evaluation in sorted({str(v) for v in frame["evaluation_timestamp"].tolist()}):
                if evaluation in seen:
                    continue
                cycle = frame[frame["evaluation_timestamp"].astype(str) == evaluation]
                commands = {
                    str(row["timeframe"]): {
                        "command_id": str(row["command_id"]),
                        "intent": str(row["intent"]),
                        "action_allowed": bool(row["action_allowed"]),
                        "availability_status": row.get("availability_status"),
                        "timeframe_state": row.get("timeframe_state"),
                        "timeframe_direction": row.get("timeframe_direction"),
                        "lifecycle_phase": row.get("lifecycle_phase"),
                        "lifecycle_episode_id": row.get("lifecycle_episode_id"),
                        "reason_codes": row.get("reason_codes"),
                        "approved_risk_usd": _f(row.get("approved_risk_usd")),
                    }
                    for _, row in cycle.iterrows()
                }
                # A manager cycle is only complete once all four traders got a command.
                if not all(tf in commands for tf in SUPPORTED_TIMEFRAMES):
                    continue
                mark_price = mark_price_from_feed()
                traders = {
                    tf: trader_snapshot(tf, mark_price=mark_price) for tf in SUPPORTED_TIMEFRAMES
                }
                rows.append(
                    {
                        "evaluation_timestamp": evaluation,
                        "manager_cycle_id": str(cycle.iloc[0]["manager_cycle_id"]),
                        "observed_at": utc_now(),
                        "mark_price": mark_price,
                        "commands": commands,
                        "traders": traders,
                        "gross_open_risk_usd": round(
                            sum(_f(t["open_risk_usd"]) for t in traders.values()), 2
                        ),
                        "open_positions": sum(1 for t in traders.values() if t["open_position"]),
                        "d1_command_present": "D1" in commands,
                    }
                )
                seen.append(evaluation)
        if len(seen) >= cycles:
            break
        time.sleep(poll_seconds)

    frame = bus.frame()
    duplicates = int(len(frame) - frame["command_id"].astype(str).nunique()) if len(frame) else 0
    return {
        "generated_at": utc_now(),
        "observation_started_at": started_at,
        "stage": "S4_1_NATURAL_LIVE_PAPER_VALIDATION",
        "activation_boundary": boundary,
        "requested_cycles": cycles,
        "observed_cycles": len(rows),
        "timed_out": len(rows) < cycles,
        "command_bus_rows": int(len(frame)),
        "duplicate_command_ids": duplicates,
        "d1_commands": 0 if not len(frame) else int((frame["timeframe"].astype(str) == "D1").sum()),
        "cycles": rows,
        "portfolio_summary": json.loads(
            (ROOT / "data/trading/manager/portfolio_summary.json").read_text(encoding="utf-8")
        )
        if (ROOT / "data/trading/manager/portfolio_summary.json").exists()
        else {},
        "forced_signals": False,
        "paper_only": True,
        "execution_enabled": False,
        "exchange_calls": 0,
    }


def print_table(payload: dict[str, Any]) -> None:
    print()
    print("| Evaluation | M15 command | M30 command | H1 command | H4 command | Open risk |")
    print("| ---------- | ----------- | ----------- | ---------- | ---------- | --------: |")
    for row in payload["cycles"]:
        cells = [row["evaluation_timestamp"]]
        for tf in SUPPORTED_TIMEFRAMES:
            cells.append(row["commands"][tf]["intent"])
        cells.append(f"{row['gross_open_risk_usd']:.2f}")
        print("| " + " | ".join(cells) + " |")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S4.1 natural live cycles observation")
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--timeout-minutes", type=float, default=45.0)
    parser.add_argument("--poll-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)

    payload = observe(
        cycles=args.cycles,
        timeout_minutes=args.timeout_minutes,
        poll_seconds=args.poll_seconds,
    )
    stamp = payload["generated_at"].replace("-", "").replace(":", "")[:15]
    out = RESEARCH / f"s4_1_live_cycles_{stamp}.json"
    atomic_write_json(out, payload)
    print_table(payload)
    print(f"observed_cycles={payload['observed_cycles']} duplicates={payload['duplicate_command_ids']}")
    print(f"artifact: {out.relative_to(ROOT)}")
    return 0 if payload["observed_cycles"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
