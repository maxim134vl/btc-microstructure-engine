#!/usr/bin/env python3
"""Fast offline stats replay of the current S4.1 paper contract on available history.

Isolated research only:
  - writes under data/research/s4_1_* candidate paths
  - never touches production manager bus / LIVE1B epoch books
  - forces manager views onto candidate books (ignores hybrid LIVE1B position_source)
  - buffers command-bus parquet writes so full history finishes in minutes, not hours

Question answered: if the current manager+paper economics traded every actionable
command on the available MTF history, what would the closed-trade stats look like?
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import threading  # noqa: E402

from btc_ml.trading.command_bus import (  # noqa: E402
    COMMAND_COLUMNS,
    CommandBus,
    CommandBusPaths,
)
from btc_ml.trading.paper_core import core_fingerprint  # noqa: E402
from btc_ml.trading.paper_trader_engine import (  # noqa: E402
    PaperTraderEngine,
    resolve_point_in_time_fill,
)
from btc_ml.trading.s41_live1b_fill import Live1bStyleFill  # noqa: E402
import btc_ml.trading.paper_trader_engine as paper_trader_engine  # noqa: E402
from btc_ml.trading.timeframe_manager import (  # noqa: E402
    SUPPORTED_TIMEFRAMES,
    TimeframeManager,
    load_feed,
)
from btc_ml.trading.timeframe_state_adapter import load_sources  # noqa: E402
from btc_ml.trading.timeframe_trader import TimeframeTrader  # noqa: E402
from btc_ml.trading.trader_book import (  # noqa: E402
    TraderBook,
    atomic_write_json as disk_write_json,
    atomic_write_parquet as disk_write_parquet,
    read_parquet as disk_read_parquet,
)
import btc_ml.trading.trader_book as trader_book_mod  # noqa: E402
from btc_ml.trading import proofs  # noqa: E402

# Historical fills must use completed-bar close after the command tip — NOT live BBO.
# Production PaperTraderEngine was switched to LIVE1B-style BBO; that makes offline
# history look like instant churn at today's price. Research-only override below.
_FILL_CTX = threading.local()
_ORIG_APPLY = PaperTraderEngine.apply_command
_PARQUET_MEM: dict[str, pd.DataFrame] = {}
_JSON_MEM: dict[str, Any] = {}


def _historical_live1b_style_fill(*, side: str, action: str) -> Live1bStyleFill:
    feed = getattr(_FILL_CTX, "feed", None)
    after = getattr(_FILL_CTX, "after", None)
    if feed is None or after is None:
        return Live1bStyleFill(
            available=False,
            price=None,
            timestamp=None,
            best_bid=None,
            best_ask=None,
            book_update_id=None,
            bbo_receive_timestamp=None,
            bbo_age_ms=None,
            reason="NO_HISTORICAL_FILL_CONTEXT",
            source="historical_completed_bar_close",
        )
    obs = resolve_point_in_time_fill(feed, after_timestamp=after)
    price = obs.price
    return Live1bStyleFill(
        available=bool(obs.available),
        price=price,
        timestamp=obs.timestamp,
        best_bid=price,
        best_ask=price,
        book_update_id=None,
        bbo_receive_timestamp=obs.timestamp,
        bbo_age_ms=0.0,
        reason=obs.reason,
        source="historical_completed_bar_close",
    )


def _apply_command_historical(self: PaperTraderEngine, command: dict[str, Any], *, feed: pd.DataFrame) -> dict[str, Any]:
    _FILL_CTX.feed = feed
    _FILL_CTX.after = command.get("evaluation_timestamp")
    try:
        return _ORIG_APPLY(self, command, feed=feed)
    finally:
        _FILL_CTX.feed = None
        _FILL_CTX.after = None


def _mem_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    _PARQUET_MEM[str(path)] = frame.copy()


def _mem_read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    key = str(path)
    if key in _PARQUET_MEM:
        frame = _PARQUET_MEM[key].copy()
        for col in columns:
            if col not in frame.columns:
                frame[col] = None
        return frame
    return disk_read_parquet(path, columns)


def _mem_write_json(path: Path, payload: Any) -> None:
    _JSON_MEM[str(path)] = payload


def flush_memory_ledgers() -> None:
    for key, frame in list(_PARQUET_MEM.items()):
        disk_write_parquet(Path(key), frame)
    for key, payload in list(_JSON_MEM.items()):
        disk_write_json(Path(key), payload)


def install_historical_fill_patch() -> None:
    paper_trader_engine.resolve_live1b_style_fill = _historical_live1b_style_fill  # type: ignore[assignment]
    PaperTraderEngine.apply_command = _apply_command_historical  # type: ignore[method-assign]
    # Keep candidate trader ledgers in RAM; flush once at the end.
    trader_book_mod.atomic_write_parquet = _mem_write_parquet  # type: ignore[assignment]
    trader_book_mod.read_parquet = _mem_read_parquet  # type: ignore[assignment]
    trader_book_mod.atomic_write_json = _mem_write_json  # type: ignore[assignment]
    paper_trader_engine.atomic_write_parquet = _mem_write_parquet  # type: ignore[attr-defined]

    import btc_ml.trading.command_bus as command_bus_mod

    command_bus_mod.atomic_write_parquet = _mem_write_parquet  # type: ignore[assignment]
    command_bus_mod.atomic_write_json = _mem_write_json  # type: ignore[assignment]
    command_bus_mod.read_parquet = _mem_read_parquet  # type: ignore[assignment]

    _orig_load_state = TraderBook.load_controller_state

    def _mem_load_controller_state(self: TraderBook) -> dict[str, Any]:
        key = str(self.controller_state)
        if key in _JSON_MEM:
            payload = _JSON_MEM[key]
            return dict(payload) if isinstance(payload, dict) else {}
        return _orig_load_state(self)

    TraderBook.load_controller_state = _mem_load_controller_state  # type: ignore[method-assign]

RESEARCH = ROOT / "data" / "research"
AVAILABILITY_MEMORY = ROOT / "data" / "cognition" / "multi_timeframe_availability_memory.parquet"
SUMMARY_PATH = RESEARCH / "s41_full_history_stats_summary.json"
TRADES_PATH = RESEARCH / "s41_full_history_stats_trades.parquet"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BufferedCommandBus(CommandBus):
    """Same contract as CommandBus, but append() stays in memory until flush()."""

    def __init__(self, paths: CommandBusPaths) -> None:
        super().__init__(paths)
        self._buffer = self.frame().copy() if self.paths.memory.exists() else pd.DataFrame(columns=COMMAND_COLUMNS)
        self._known = set(self._buffer["command_id"].astype(str).tolist()) if len(self._buffer) else set()
        self._dirty = False

    def frame(self) -> pd.DataFrame:
        return self._buffer.copy()

    def existing_command_ids(self) -> set[str]:
        return set(self._known)

    def append(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        fresh: list[dict[str, Any]] = []
        duplicates: list[str] = []
        for command in commands:
            command_id = str(command.get("command_id"))
            if command_id in self._known:
                duplicates.append(command_id)
                continue
            self._known.add(command_id)
            fresh.append({col: command.get(col) for col in COMMAND_COLUMNS})
        if fresh:
            new_frame = pd.DataFrame(fresh, columns=COMMAND_COLUMNS)
            self._buffer = (
                pd.concat([self._buffer, new_frame], ignore_index=True)
                if len(self._buffer)
                else new_frame
            )
            self._dirty = True
        return {
            "appended": len(fresh),
            "duplicates_rejected": len(duplicates),
            "duplicate_command_ids": duplicates,
            "total_rows": int(len(self._buffer)),
        }

    def flush(self) -> None:
        if not self._dirty:
            return
        atomic_write_parquet = disk_write_parquet
        atomic_write_parquet(self.paths.memory, self._buffer[COMMAND_COLUMNS] if len(self._buffer) else pd.DataFrame(columns=COMMAND_COLUMNS))
        self._dirty = False


def reset_candidate_state() -> list[str]:
    _PARQUET_MEM.clear()
    _JSON_MEM.clear()
    removed: list[str] = []
    paths = CommandBusPaths.candidate()
    for path in (paths.memory, paths.latest, paths.manager_state, paths.portfolio_summary):
        for target in (path, path.with_suffix(path.suffix + ".meta.json")):
            if target.exists():
                target.unlink()
                removed.append(str(target.relative_to(ROOT)))
    for tf in SUPPORTED_TIMEFRAMES:
        book = TraderBook.candidate(tf)
        if book.root.exists():
            shutil.rmtree(book.root)
            removed.append(str(book.root.relative_to(ROOT)))
    return removed


def evaluation_timestamps(*, limit: int | None) -> list[pd.Timestamp]:
    frame = pd.read_parquet(AVAILABILITY_MEMORY, columns=["evaluation_timestamp", "timeframe"])
    m15 = frame[frame["timeframe"].astype(str).str.upper() == "M15"]
    stamps = pd.to_datetime(m15["evaluation_timestamp"], utc=True, errors="coerce").dropna()
    ordered = sorted(set(stamps.tolist()))
    return ordered if not limit else ordered[-limit:]


def _usd(values: list[float]) -> float:
    return float(sum(v for v in values if math.isfinite(v)))


def collect_closed_trades() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for tf in SUPPORTED_TIMEFRAMES:
        book = TraderBook.candidate(tf)
        trades = book.trades_frame()
        if not len(trades):
            continue
        for _, row in trades.iterrows():
            record = row.to_dict()
            record["timeframe"] = tf
            rows.append(record)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def summarize_trades(trades: pd.DataFrame, *, cycles: int, window: dict[str, Any], started_at: str, elapsed_s: float) -> dict[str, Any]:
    if not len(trades):
        return {
            "generated_at": _now(),
            "started_at": started_at,
            "elapsed_seconds": elapsed_s,
            "stage": "S41_FULL_HISTORY_STATS",
            "cycles": cycles,
            "window": window,
            "closed_trades": 0,
            "note": "no closed trades in candidate books",
            "paper_only": True,
            "live_paths_touched": False,
        }

    net = pd.to_numeric(trades.get("net_pnl_usd"), errors="coerce").fillna(0.0)
    gross = pd.to_numeric(trades.get("gross_pnl_usd"), errors="coerce").fillna(0.0)
    fees = pd.to_numeric(trades.get("fees_usd"), errors="coerce").fillna(0.0)
    slip = pd.to_numeric(trades.get("slippage_usd"), errors="coerce").fillna(0.0)
    wins = net[net > 0]
    losses = net[net < 0]
    by_tf: dict[str, Any] = {}
    for tf, part in trades.groupby(trades["timeframe"].astype(str).str.upper()):
        n = pd.to_numeric(part.get("net_pnl_usd"), errors="coerce").fillna(0.0)
        by_tf[str(tf)] = {
            "closed_trades": int(len(part)),
            "net_pnl_usd": float(n.sum()),
            "wins": int((n > 0).sum()),
            "losses": int((n < 0).sum()),
            "win_rate": float((n > 0).mean()) if len(part) else None,
        }

    intent_side = trades.get("side")
    side_counts = intent_side.astype(str).str.upper().value_counts().to_dict() if intent_side is not None else {}

    return {
        "generated_at": _now(),
        "started_at": started_at,
        "elapsed_seconds": elapsed_s,
        "stage": "S41_FULL_HISTORY_STATS",
        "contract": {
            "manager": "TimeframeManager.candidate",
            "execution_core": core_fingerprint(),
            "books": "data/research/s4_1_candidate_timeframe_traders",
            "command_bus": "data/research/s4_1_candidate_manager_commands.parquet",
            "hybrid_position_source_forced_off": True,
            "fill_model": "historical_completed_bar_close_after_command",
            "note": "Current S4.1 manager intents + shared paper economics; PIT bar fills (not live BBO)",
        },
        "cycles": cycles,
        "window": window,
        "closed_trades": int(len(trades)),
        "side_counts": side_counts,
        "net_pnl_usd": float(net.sum()),
        "gross_pnl_usd": float(gross.sum()),
        "fees_usd": float(fees.sum()),
        "slippage_usd": float(slip.sum()),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "breakeven": int((net == 0).sum()),
        "win_rate": float(len(wins) / len(trades)) if len(trades) else None,
        "average_win_usd": float(wins.mean()) if len(wins) else None,
        "average_loss_usd": float(losses.mean()) if len(losses) else None,
        "best_trade_usd": float(net.max()) if len(net) else None,
        "worst_trade_usd": float(net.min()) if len(net) else None,
        "profit_factor": (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) and float(abs(losses.sum())) > 0
            else (None if len(losses) else float("inf") if len(wins) else None)
        ),
        "by_timeframe": by_tf,
        "artifacts": {
            "summary": str(SUMMARY_PATH.relative_to(ROOT)),
            "trades": str(TRADES_PATH.relative_to(ROOT)),
            "command_bus": "data/research/s4_1_candidate_manager_commands.parquet",
        },
        "paper_only": True,
        "live_paths_touched": False,
        "exchange_calls": 0,
    }


def run(*, limit: int | None, flush_every: int) -> dict[str, Any]:
    started = time.time()
    started_at = _now()
    removed = reset_candidate_state()

    # Critical: do not let hybrid LIVE1B books contaminate historical risk/open views.
    TimeframeManager._use_live1b_position_views = staticmethod(lambda: False)  # type: ignore[method-assign]
    # Critical: fills from historical completed bars, not live BBO / wall-clock.
    install_historical_fill_patch()

    bus = BufferedCommandBus(CommandBusPaths.candidate())
    manager = TimeframeManager.candidate()
    manager.bus = bus
    traders = {tf: TimeframeTrader.candidate(tf) for tf in SUPPORTED_TIMEFRAMES}
    for trader in traders.values():
        trader.bus = bus

    feed = load_feed()
    sources = load_sources()
    stamps = evaluation_timestamps(limit=limit)

    for index, evaluation in enumerate(stamps):
        visible = proofs.visible_feed(feed, evaluation)
        if not len(visible):
            continue
        manager.run_cycle(
            evaluation_timestamp=evaluation,
            sources=sources,
            feed=visible,
            persist=True,
        )
        for trader in traders.values():
            trader.run_once(feed=visible)
        if flush_every > 0 and (index + 1) % flush_every == 0:
            bus.flush()
            if (index + 1) % max(flush_every * 5, 100) == 0:
                print(
                    json.dumps(
                        {
                            "progress_cycle": index + 1,
                            "of": len(stamps),
                            "evaluation_timestamp": str(evaluation),
                            "commands": int(len(bus._buffer)),
                        }
                    ),
                    flush=True,
                )

    bus.flush()
    flush_memory_ledgers()
    trades = collect_closed_trades()
    if len(trades):
        trades.to_parquet(TRADES_PATH, index=False)
    elif TRADES_PATH.exists():
        TRADES_PATH.unlink()

    commands = bus.frame()
    intent_counts = (
        commands.groupby(["timeframe", "intent"]).size().unstack(fill_value=0).to_dict()
        if len(commands)
        else {}
    )
    open_counts = (
        commands[commands["intent"].astype(str).str.upper().isin(["OPEN_LONG", "OPEN_SHORT"])]
        .groupby("timeframe")
        .size()
        .to_dict()
        if len(commands)
        else {}
    )

    summary = summarize_trades(
        trades,
        cycles=len(stamps),
        window={
            "first_evaluation_timestamp": str(stamps[0]) if stamps else None,
            "last_evaluation_timestamp": str(stamps[-1]) if stamps else None,
        },
        started_at=started_at,
        elapsed_s=time.time() - started,
    )
    summary["reset_removed"] = removed
    summary["command_bus"] = {
        "rows": int(len(commands)),
        "open_commands_by_timeframe": {str(k): int(v) for k, v in open_counts.items()},
        "intent_counts_by_timeframe": intent_counts,
        "duplicate_commands": int(len(commands) - commands["command_id"].astype(str).nunique()) if len(commands) else 0,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only last N M15 evaluation instants")
    parser.add_argument("--flush-every", type=int, default=50, help="flush buffered command bus every N cycles")
    args = parser.parse_args(argv)
    RESEARCH.mkdir(parents=True, exist_ok=True)
    summary = run(limit=args.limit, flush_every=args.flush_every)
    print(
        json.dumps(
            {
                "closed_trades": summary.get("closed_trades"),
                "net_pnl_usd": summary.get("net_pnl_usd"),
                "win_rate": summary.get("win_rate"),
                "cycles": summary.get("cycles"),
                "window": summary.get("window"),
                "open_commands_by_timeframe": summary.get("command_bus", {}).get("open_commands_by_timeframe"),
                "by_timeframe": summary.get("by_timeframe"),
                "elapsed_seconds": summary.get("elapsed_seconds"),
                "summary": str(SUMMARY_PATH.relative_to(ROOT)),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
