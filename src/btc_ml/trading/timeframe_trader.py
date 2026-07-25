"""Independent timeframe trader (S4.1).

Reads only its own timeframe slice of the command bus, applies the shared paper
execution core, and writes only its own book. It never reads or writes another
timeframe's book, and never closes another trader's position.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .command_bus import CommandBus, CommandBusPaths, utc_now
from .paper_trader_engine import PaperTraderEngine
from .timeframe_manager import load_feed
from .trader_book import TraderBook, atomic_write_json, repo_relative

ROOT = Path(__file__).resolve().parents[3]


class TimeframeTrader:
    def __init__(self, *, timeframe: str, book: TraderBook, bus: CommandBus) -> None:
        self.timeframe = str(timeframe).upper()
        if book.timeframe.upper() != self.timeframe:
            raise ValueError(f"book_timeframe_mismatch:{book.timeframe}!={self.timeframe}")
        self.book = book
        self.bus = bus
        self.engine = PaperTraderEngine(book)

    @classmethod
    def production(cls, timeframe: str) -> "TimeframeTrader":
        return cls(
            timeframe=timeframe,
            book=TraderBook.production(timeframe),
            bus=CommandBus(CommandBusPaths.production()),
        )

    @classmethod
    def candidate(cls, timeframe: str) -> "TimeframeTrader":
        return cls(
            timeframe=timeframe,
            book=TraderBook.candidate(timeframe),
            bus=CommandBus(CommandBusPaths.candidate()),
        )

    def pending_commands(self, *, activation_boundary: Any = None) -> list[dict[str, Any]]:
        state = self.book.load_controller_state()
        processed = set(state.get("processed_command_ids") or [])
        return self.bus.pending_for_timeframe(
            self.timeframe,
            processed_command_ids=processed,
            after_evaluation_timestamp=activation_boundary,
        )

    def run_once(
        self,
        *,
        feed: pd.DataFrame | None = None,
        activation_boundary: Any = None,
    ) -> dict[str, Any]:
        market = feed if feed is not None else load_feed()
        now_ts = self._market_clock(market)
        outcomes: list[dict[str, Any]] = []
        for command in self.pending_commands(activation_boundary=activation_boundary):
            if str(command.get("timeframe") or "").upper() != self.timeframe:
                continue
            if self._expired(command, now_ts=now_ts):
                outcomes.append(self.engine.expire_command(command))
                continue
            outcomes.append(self.engine.apply_command(command, feed=market))
        status = self.write_runtime_status(outcomes=outcomes, market=market)
        return {"timeframe": self.timeframe, "outcomes": outcomes, "runtime_status": status}

    @staticmethod
    def _market_clock(market: pd.DataFrame) -> pd.Timestamp | None:
        if market is None or not len(market):
            return None
        column = "bar_close_timestamp" if "bar_close_timestamp" in market.columns else "timestamp"
        if column not in market.columns:
            return None
        stamps = pd.to_datetime(market[column], utc=True, errors="coerce").dropna()
        return None if not len(stamps) else stamps.max()

    @staticmethod
    def _expired(command: dict[str, Any], *, now_ts: pd.Timestamp | None) -> bool:
        if now_ts is None:
            return False
        try:
            evaluated = pd.Timestamp(command.get("evaluation_timestamp"))
        except Exception:
            return False
        if pd.isna(evaluated):
            return False
        evaluated = evaluated.tz_localize("UTC") if evaluated.tzinfo is None else evaluated.tz_convert("UTC")
        try:
            ttl = float(command.get("command_ttl_seconds") or 900.0)
        except Exception:
            ttl = 900.0
        return bool(now_ts > evaluated + pd.Timedelta(seconds=2.0 * ttl))

    def write_runtime_status(
        self,
        *,
        outcomes: list[dict[str, Any]] | None = None,
        market: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        mark_price = None
        if market is not None and len(market) and "close" in market.columns:
            try:
                mark_price = float(market["close"].iloc[-1])
            except Exception:
                mark_price = None
        snapshot = self.engine.snapshot(mark_price=mark_price)
        payload = {
            "generated_at": utc_now(),
            "timeframe": self.timeframe,
            "owner": f"TIMEFRAME_TRADER_{self.timeframe}",
            "book_root": repo_relative(self.book.root),
            "command_bus": repo_relative(self.bus.paths.memory),
            "shared_execution_core": "shared_paper_execution_core_v1",
            "applied_this_cycle": [] if not outcomes else outcomes,
            "mark_price": mark_price,
            **snapshot,
            "paper_only": True,
            "execution_enabled": False,
            "exchange_calls": 0,
        }
        atomic_write_json(self.book.runtime_status, payload)
        return payload
