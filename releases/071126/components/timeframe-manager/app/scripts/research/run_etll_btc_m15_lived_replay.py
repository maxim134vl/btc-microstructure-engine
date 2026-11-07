#!/usr/bin/env python3
"""ETLL lived replay: current S4.1 manager+trader on BTC M15 market pack.

Isolated under the pack directory. Does not touch live cognition or production books.
Fills use historical completed-bar close (not live BBO).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

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
import btc_ml.trading.paper_trader_engine as paper_trader_engine  # noqa: E402
from btc_ml.trading.s41_live1b_fill import Live1bStyleFill  # noqa: E402
from btc_ml.trading.timeframe_manager import (  # noqa: E402
    TimeframeManager,
    load_feed,
    with_bar_close,
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
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading import proofs  # noqa: E402
import btc_ml.trading.timeframe_state_adapter as state_adapter  # noqa: E402

DEFAULT_PACK_M15 = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_PACK = DEFAULT_PACK_M15


def default_pack_dir(timeframe: str) -> Path:
    tf = str(timeframe or "M15").upper()
    if tf == "M15":
        return DEFAULT_PACK_M15
    return ROOT / f"data/research/external_traders/market_pack_btc_{tf.lower()}"


def feed_filename(timeframe: str) -> str:
    return f"feed_{str(timeframe).lower()}.parquet"

_FILL_CTX = threading.local()
_ORIG_APPLY = PaperTraderEngine.apply_command
_PARQUET_MEM: dict[str, pd.DataFrame] = {}
_JSON_MEM: dict[str, Any] = {}
_PROCESSED_IDS: dict[str, set[str]] = {}
_MANAGER_STATE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    # Store without copy — callers rebuild frames; copying every apply is O(n²).
    _PARQUET_MEM[str(path)] = frame


def _mem_read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    key = str(path)
    if key in _PARQUET_MEM:
        frame = _PARQUET_MEM[key]
        missing = [col for col in columns if col not in frame.columns]
        if missing:
            frame = frame.copy()
            for col in missing:
                frame[col] = None
        return frame
    if Path(path).exists():
        return disk_read_parquet(path, columns)
    return pd.DataFrame(columns=columns)


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
    trader_book_mod.atomic_write_parquet = _mem_write_parquet  # type: ignore[assignment]
    trader_book_mod.read_parquet = _mem_read_parquet  # type: ignore[assignment]
    trader_book_mod.atomic_write_json = _mem_write_json  # type: ignore[assignment]
    paper_trader_engine.atomic_write_parquet = _mem_write_parquet  # type: ignore[attr-defined]

    import btc_ml.trading.command_bus as command_bus_mod
    import btc_ml.trading.timeframe_trader as timeframe_trader_mod

    command_bus_mod.atomic_write_parquet = _mem_write_parquet  # type: ignore[assignment]
    command_bus_mod.atomic_write_json = _mem_write_json  # type: ignore[assignment]
    command_bus_mod.read_parquet = _mem_read_parquet  # type: ignore[assignment]
    # timeframe_trader imported atomic_write_json by name — patch that binding too.
    timeframe_trader_mod.atomic_write_json = _mem_write_json  # type: ignore[assignment]

    _orig_load_state = TraderBook.load_controller_state

    def _mem_load_controller_state(self: TraderBook) -> dict[str, Any]:
        key = str(self.controller_state)
        if key in _JSON_MEM:
            payload = _JSON_MEM[key]
            return dict(payload) if isinstance(payload, dict) else {}
        return _orig_load_state(self)

    TraderBook.load_controller_state = _mem_load_controller_state  # type: ignore[method-assign]

    # Production cursor keeps only last 500 ids — on a full pack that re-queues
    # older commands every cycle (O(n²)). Keep a full in-memory set for replay.
    def _processed_key(book: TraderBook) -> str:
        return str(book.controller_state)

    def _already_applied_fast(self: PaperTraderEngine, command_id: str) -> bool:
        return command_id in _PROCESSED_IDS.get(_processed_key(self.book), set())

    def _record_cursor_full(self: PaperTraderEngine, command: dict[str, Any], outcome: dict[str, Any]) -> None:
        if outcome.get("result") == paper_trader_engine.RESULT_ALREADY_APPLIED:
            return
        key = _processed_key(self.book)
        processed = _PROCESSED_IDS.setdefault(key, set())
        command_id = str(command.get("command_id") or "")
        if (
            command_id
            and command_id not in processed
            and outcome.get("result") not in paper_trader_engine.NON_CONSUMING_RESULTS
        ):
            processed.add(command_id)
        open_position = self.book.open_position()
        state = self.book.load_controller_state()
        state.update(
            {
                "timeframe": self.timeframe,
                # Full id set lives in _PROCESSED_IDS; avoid O(n) list materialization.
                "processed_command_ids": [],
                "processed_command_count": len(processed),
                "last_command_id": command_id,
                "last_command_evaluation_timestamp": command.get("evaluation_timestamp"),
                "cursor_evaluation_timestamp": command.get("evaluation_timestamp"),
                "last_result": outcome.get("result"),
                "last_reason": outcome.get("reason"),
                "open_position_id": (open_position or {}).get("position_id"),
                "cycles": int(state.get("cycles") or 0) + 1,
                "updated_at": paper_trader_engine._utc_now(),
                "paper_only": True,
                "execution_enabled": False,
                "shared_core": "shared_paper_execution_core_v1",
            }
        )
        self.book.save_controller_state(state)

    def _pending_commands_fast(
        self: TimeframeTrader, *, activation_boundary: Any = None
    ) -> list[dict[str, Any]]:
        processed = _PROCESSED_IDS.get(_processed_key(self.book), set())
        return self.bus.pending_for_timeframe(
            self.timeframe,
            processed_command_ids=processed,
            after_evaluation_timestamp=activation_boundary,
        )

    PaperTraderEngine.already_applied = _already_applied_fast  # type: ignore[method-assign]
    PaperTraderEngine._record_cursor = _record_cursor_full  # type: ignore[method-assign]
    TimeframeTrader.pending_commands = _pending_commands_fast  # type: ignore[method-assign]

    # runtime_status with applied_this_cycle is unused for ETLL artifacts and
    # becomes multi-MB JSON once pending drifts — skip per-cycle writes.
    def _skip_runtime_status(
        self: TimeframeTrader,
        *,
        outcomes: list[dict[str, Any]] | None = None,
        market: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        return {
            "generated_at": _now(),
            "timeframe": self.timeframe,
            "skipped_for_lived_replay": True,
            "applied_this_cycle_count": 0 if not outcomes else len(outcomes),
        }

    TimeframeTrader.write_runtime_status = _skip_runtime_status  # type: ignore[method-assign]

    # Manager latest/portfolio JSON every bar are not ETLL outputs — drop them.
    # Manager state MUST stay in memory (episode / per-TF cursor semantics).
    def _noop_json_write(self: CommandBus, payload: dict[str, Any]) -> None:
        return None

    def _load_manager_state_mem(self: CommandBus) -> dict[str, Any]:
        key = str(self.paths.manager_state)
        if key in _MANAGER_STATE:
            payload = _MANAGER_STATE[key]
            return dict(payload) if isinstance(payload, dict) else {"cycles": 0, "timeframes": {}}
        return {"cycles": 0, "timeframes": {}, "last_manager_cycle_id": None}

    def _save_manager_state_mem(self: CommandBus, payload: dict[str, Any]) -> None:
        _MANAGER_STATE[str(self.paths.manager_state)] = dict(payload) if isinstance(payload, dict) else {}

    CommandBus.write_latest_snapshot = _noop_json_write  # type: ignore[method-assign]
    CommandBus.write_portfolio_summary = _noop_json_write  # type: ignore[method-assign]
    CommandBus.load_manager_state = _load_manager_state_mem  # type: ignore[method-assign]
    CommandBus.save_manager_state = _save_manager_state_mem  # type: ignore[method-assign]


class BufferedCommandBus(CommandBus):
    def __init__(self, paths: CommandBusPaths) -> None:
        super().__init__(paths)
        if self.paths.memory.exists():
            existing = disk_read_parquet(self.paths.memory, list(COMMAND_COLUMNS))
            self._rows: list[dict[str, Any]] = existing.to_dict(orient="records") if len(existing) else []
        else:
            self._rows = []
        self._known = {str(r.get("command_id")) for r in self._rows}
        self._dirty = False
        self._frame_cache: pd.DataFrame | None = None
        # Per-TF chronological dict rows + scan cursors for O(new) pending lookups.
        self._by_tf: dict[str, list[dict[str, Any]]] = {}
        self._tf_scan_from: dict[str, int] = {}
        for record in self._rows:
            tf = str(record.get("timeframe") or "").upper()
            self._by_tf.setdefault(tf, []).append(record)

    def frame(self) -> pd.DataFrame:
        if self._frame_cache is None:
            self._frame_cache = (
                pd.DataFrame(self._rows, columns=COMMAND_COLUMNS)
                if self._rows
                else pd.DataFrame(columns=COMMAND_COLUMNS)
            )
        return self._frame_cache.copy()

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
            row = {col: command.get(col) for col in COMMAND_COLUMNS}
            fresh.append(row)
            self._rows.append(row)
            tf = str(row.get("timeframe") or "").upper()
            self._by_tf.setdefault(tf, []).append(row)
        if fresh:
            self._dirty = True
            self._frame_cache = None
        return {
            "appended": len(fresh),
            "duplicates_rejected": len(duplicates),
            "duplicate_command_ids": duplicates,
            "total_rows": int(len(self._rows)),
        }

    def pending_for_timeframe(
        self,
        timeframe: str,
        *,
        processed_command_ids: set[str],
        after_evaluation_timestamp: Any = None,
    ) -> list[dict[str, Any]]:
        tf = str(timeframe).upper()
        rows = self._by_tf.get(tf) or []
        if not rows:
            return []
        boundary = None
        if after_evaluation_timestamp is not None:
            boundary = pd.Timestamp(after_evaluation_timestamp)
            boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
        start = int(self._tf_scan_from.get(tf, 0))
        while start < len(rows) and str(rows[start].get("command_id")) in processed_command_ids:
            start += 1
        self._tf_scan_from[tf] = start
        out: list[dict[str, Any]] = []
        for index in range(start, len(rows)):
            record = rows[index]
            command_id = str(record.get("command_id"))
            if command_id in processed_command_ids:
                continue
            if boundary is not None:
                try:
                    stamp = pd.Timestamp(record.get("evaluation_timestamp"))
                    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                except Exception:
                    continue
                if stamp < boundary:
                    continue
            out.append(record)
        return out

    def flush(self) -> None:
        if not self._dirty:
            return
        frame = (
            pd.DataFrame(self._rows, columns=COMMAND_COLUMNS)
            if self._rows
            else pd.DataFrame(columns=COMMAND_COLUMNS)
        )
        self._frame_cache = frame
        disk_write_parquet(self.paths.memory, frame)
        self._dirty = False


def pack_paths(out_dir: Path, timeframes: tuple[str, ...]) -> tuple[CommandBusPaths, dict[str, TraderBook]]:
    bus_paths = CommandBusPaths(
        memory=out_dir / "manager_commands.parquet",
        latest=out_dir / "manager_latest.json",
        manager_state=out_dir / "manager_state.json",
        portfolio_summary=out_dir / "portfolio_summary.json",
    )
    books = {tf: TraderBook(timeframe=tf, root=out_dir / "books" / tf) for tf in timeframes}
    return bus_paths, books


def evaluation_timestamps(
    availability_path: Path,
    *,
    timeframe: str,
    limit: int | None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> list[pd.Timestamp]:
    frame = pd.read_parquet(availability_path)
    tf = str(timeframe).upper()
    scoped = frame[frame["timeframe"].astype(str).str.upper() == tf]
    stamps = pd.to_datetime(scoped["evaluation_timestamp"], utc=True, errors="coerce").dropna()
    ordered = sorted(set(stamps.tolist()))
    if from_ts:
        lo = pd.Timestamp(from_ts)
        ordered = [s for s in ordered if s >= lo]
    if to_ts:
        hi = pd.Timestamp(to_ts)
        ordered = [s for s in ordered if s < hi]
    return ordered if not limit else ordered[: int(limit)]


def collect_closed_trades(books: dict[str, TraderBook]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for tf, book in books.items():
        trades = book.trades_frame()
        if not len(trades):
            continue
        for _, row in trades.iterrows():
            record = row.to_dict()
            record["timeframe"] = tf
            rows.append(record)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(path)


def summarize(
    trades: pd.DataFrame,
    commands: pd.DataFrame,
    *,
    timeframe: str,
    cycles: int,
    window: dict[str, Any],
    started_at: str,
    elapsed_s: float,
    pack_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    tf = str(timeframe).upper()
    net = pd.to_numeric(trades.get("net_pnl_usd"), errors="coerce").fillna(0.0) if len(trades) else pd.Series(dtype=float)
    wins = net[net > 0]
    losses = net[net < 0]
    intent_counts = (
        commands.groupby(["timeframe", "intent"]).size().unstack(fill_value=0).to_dict()
        if len(commands)
        else {}
    )
    return {
        "generated_at": _now(),
        "started_at": started_at,
        "elapsed_seconds": round(elapsed_s, 3),
        "stage": f"ETLL_BTC_{tf}_LIVED_REPLAY",
        "contract": {
            "manager": f"TimeframeManager(timeframes={tf})",
            "execution_core": core_fingerprint(),
            "books": _rel(out_dir / "books"),
            "fill_model": "historical_completed_bar_close_after_command",
            "pack_dir": str(pack_dir),
            "hybrid_position_source_forced_off": True,
            "live_paths_touched": False,
        },
        "cycles": cycles,
        "window": window,
        "closed_trades": int(len(trades)),
        "commands": int(len(commands)),
        "intent_counts": intent_counts,
        "net_pnl_usd": float(net.sum()) if len(net) else 0.0,
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "breakeven": int((net == 0).sum()) if len(net) else 0,
        "win_rate": float(len(wins) / len(trades)) if len(trades) else None,
        "average_win_usd": float(wins.mean()) if len(wins) else None,
        "average_loss_usd": float(losses.mean()) if len(losses) else None,
        "best_trade_usd": float(net.max()) if len(net) else None,
        "worst_trade_usd": float(net.min()) if len(net) else None,
        "profit_factor": (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) and float(abs(losses.sum())) > 0
            else (None if len(losses) else (float("inf") if len(wins) else None))
        ),
        "artifacts": {
            "summary": _rel(out_dir / "lived_replay_summary.json"),
            "trades": _rel(out_dir / "lived_trades.parquet"),
            "commands": _rel(out_dir / "manager_commands.parquet"),
        },
        "paper_only": True,
        "status": "LIVED_REPLAY_DONE",
    }


def prepare_fast_sources(sources, *, timeframe: str):
    """Pre-index availability + lifecycle for O(log n) causal lookups."""
    tf = str(timeframe).upper()
    avail = sources.availability.copy()
    avail = avail[avail["timeframe"].astype(str).str.upper() == tf].copy()
    avail["_eval_ts"] = pd.to_datetime(avail["evaluation_timestamp"], utc=True, errors="coerce")
    avail = avail.dropna(subset=["_eval_ts"]).sort_values("_eval_ts").reset_index(drop=True)
    sources.availability = avail

    life = sources.lifecycle.copy()
    if "timeframe" in life.columns:
        stamps_tf = life["timeframe"].astype(str).str.upper()
        life = life[stamps_tf == tf].copy()
    elif tf != "M15":
        life = life.iloc[0:0].copy()
    life["_life_ts"] = pd.to_datetime(life["timestamp"], utc=True, errors="coerce")
    life = life.dropna(subset=["_life_ts"]).sort_values("_life_ts").reset_index(drop=True)
    sources.lifecycle = life

    avail_ts = avail["_eval_ts"].to_numpy(dtype="datetime64[ns]")
    life_ts = life["_life_ts"].to_numpy(dtype="datetime64[ns]")
    pack_tf = tf
    state_adapter_resolve_orig = state_adapter.resolve_timeframe_state

    def _fast_availability_row(availability, *, timeframe, evaluation_ts):
        if str(timeframe).upper() != pack_tf:
            return None
        boundary = pd.Timestamp(evaluation_ts)
        if boundary.tzinfo is None:
            boundary = boundary.tz_localize("UTC")
        else:
            boundary = boundary.tz_convert("UTC")
        idx = int(avail_ts.searchsorted(boundary.to_datetime64(), side="right")) - 1
        if idx < 0:
            return None
        return availability.iloc[idx].to_dict()

    def _life_row_at_or_before(bar_close: pd.Timestamp) -> dict[str, Any] | None:
        idx = int(life_ts.searchsorted(bar_close.to_datetime64(), side="right")) - 1
        if idx < 0:
            return None
        return life.iloc[idx].to_dict()

    def _resolve_fast(**kwargs):
        req_tf = str(kwargs.get("timeframe") or "").upper()
        evaluation_ts = state_adapter._ts(kwargs.get("evaluation_timestamp"))
        src = kwargs["sources"]
        if (
            req_tf != pack_tf
            or evaluation_ts is None
            or bool(kwargs.get("allow_provisional"))
            or str(kwargs.get("evaluation_mode") or "").upper() == "PROVISIONAL_INTRABAR"
        ):
            # Keep original path for non-pack cases.
            return state_adapter_resolve_orig(**kwargs)

        base: dict[str, Any] = {
            "timeframe": req_tf,
            "evaluation_timestamp": state_adapter._iso(evaluation_ts),
            "resolved_at": state_adapter._utc_now(),
            "source_bar_open": None,
            "source_bar_close": None,
            "source_state_timestamp": None,
            "source_event_timestamp": None,
            "is_new_event": None,
            "availability_status": "UNKNOWN",
            "availability_reason": None,
            "writer_state": None,
            "timeframe_state": "UNKNOWN",
            "timeframe_direction": state_adapter.DIRECTION_FLAT,
            "direction_reason": None,
            "lifecycle_episode_id": None,
            "lifecycle_phase": None,
            "lifecycle_row_timestamp": None,
            "actionable": False,
            "no_action_reason": None,
            "confidence": None,
            "alignment_score": None,
            "persistence_score": None,
            "structural_rank": None,
            "location_bias": None,
            "is_closed": True,
            "evaluation_mode": "CLOSED_BAR",
            "causal_cutoff_timestamp": None,
            "causal_cutoff_monotonic_ns": kwargs.get("causal_cutoff_monotonic_ns"),
            "model_version": kwargs.get("model_version"),
            "source_lineage": {
                "availability": "pack",
                "lifecycle": "pack",
                "lifecycle_source": "parquet",
            },
        }
        row = _fast_availability_row(src.availability, timeframe=req_tf, evaluation_ts=evaluation_ts)
        if row is None:
            base["availability_status"] = "DATASET_MISSING"
            base["no_action_reason"] = "NO_AVAILABILITY_ROW_AT_OR_BEFORE_EVALUATION"
            return base
        status = str(row.get("availability_status") or "UNKNOWN").upper()
        bar_close = state_adapter._ts(row.get("source_bar_close"))
        base.update(
            {
                "availability_status": status,
                "availability_reason": row.get("availability_reason"),
                "is_new_event": bool(row.get("is_new_event"))
                if row.get("is_new_event") is not None
                else None,
                "writer_state": row.get("writer_state"),
                "source_bar_open": state_adapter._iso(row.get("source_bar_open")),
                "source_bar_close": state_adapter._iso(bar_close),
                "source_state_timestamp": state_adapter._iso(row.get("source_state_timestamp")),
                "source_event_timestamp": state_adapter._iso(row.get("source_event_timestamp")),
            }
        )
        if status in state_adapter.NO_ACTION_AVAILABILITY:
            base["no_action_reason"] = status
            base["timeframe_state"] = status
            return base
        if status not in state_adapter.OPERATIONAL_AVAILABILITY:
            base["no_action_reason"] = f"UNKNOWN_AVAILABILITY_STATUS:{status}"
            return base
        if bar_close is None:
            base["no_action_reason"] = "MISSING_SOURCE_BAR_CLOSE"
            return base
        if bar_close > evaluation_ts:
            base["no_action_reason"] = "UNCLOSED_BAR_REJECTED"
            base["timeframe_state"] = "WAITING_FOR_BAR_CLOSE"
            return base

        life_row = _life_row_at_or_before(bar_close)
        if life_row is None:
            base["no_action_reason"] = "NO_LIFECYCLE_ROW_AT_OR_BEFORE_BAR_CLOSE"
            return base
        direction, direction_reason = state_adapter._lifecycle_direction(life_row)
        phase = str(life_row.get("lifecycle_state") or "UNKNOWN").upper()
        episode = state_adapter._episode_id_for_timeframe(tf, life_row.get("context_episode_id"))
        base.update(
            {
                "timeframe_state": str(life_row.get("active_market_context") or "UNKNOWN").upper(),
                "timeframe_direction": direction,
                "direction_reason": direction_reason,
                "lifecycle_episode_id": episode,
                "lifecycle_phase": phase,
                "lifecycle_row_timestamp": state_adapter._iso(
                    life_row.get("_life_ts") or life_row.get("timestamp")
                ),
                "context_started_at": state_adapter._iso(life_row.get("active_context_started_at")),
                "invalidation_reason": life_row.get("invalidation_reason"),
                "context_origin_price": None
                if life_row.get("context_origin_price") is None
                else float(life_row.get("context_origin_price") or 0.0) or None,
                "actionable": direction
                in {state_adapter.DIRECTION_LONG, state_adapter.DIRECTION_SHORT}
                and phase == "ACTIVE",
            }
        )
        if not base["actionable"] and base["no_action_reason"] is None:
            if direction == state_adapter.DIRECTION_FLAT:
                base["no_action_reason"] = "NON_DIRECTIONAL_TIMEFRAME_STATE"
            elif phase in state_adapter.TERMINAL_LIFECYCLE_PHASES:
                base["no_action_reason"] = f"TERMINAL_LIFECYCLE_PHASE:{phase}"
            else:
                base["no_action_reason"] = f"LIFECYCLE_PHASE_NOT_ACTIONABLE:{phase}"
        return base

    state_adapter._availability_row = _fast_availability_row  # type: ignore[assignment]
    state_adapter.resolve_timeframe_state = _resolve_fast  # type: ignore[assignment]
    return sources


def run(
    *,
    pack_dir: Path,
    timeframe: str = "M15",
    limit: int | None,
    flush_every: int,
    out_dir: Path | None = None,
    anti_saw: bool = True,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> dict[str, Any]:
    tf = str(timeframe).upper()
    timeframes = (tf,)
    started = time.time()
    started_at = _now()
    out_dir = Path(out_dir) if out_dir is not None else (pack_dir / "lived_replay")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for t in timeframes:
        (out_dir / "books" / t).mkdir(parents=True, exist_ok=True)

    _PARQUET_MEM.clear()
    _JSON_MEM.clear()
    _PROCESSED_IDS.clear()
    _MANAGER_STATE.clear()
    install_historical_fill_patch()
    TimeframeManager._use_live1b_position_views = staticmethod(lambda: False)  # type: ignore[method-assign]
    import btc_ml.trading.timeframe_manager as tm_mod

    tm_mod.ANTI_SAW_ENABLED = False

    feed_path = pack_dir / feed_filename(tf)
    availability_path = pack_dir / "context" / "multi_timeframe_availability_memory.parquet"
    lifecycle_path = pack_dir / "context" / "market_context_lifecycle_memory.parquet"
    for required in (feed_path, availability_path, lifecycle_path):
        if not required.exists():
            raise FileNotFoundError(required)

    bus_paths, books = pack_paths(out_dir, timeframes)
    bus = BufferedCommandBus(bus_paths)
    manager = TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
        timeframes=timeframes,
    )
    traders = {
        t: TimeframeTrader(timeframe=t, book=books[t], bus=bus) for t in timeframes
    }

    feed = with_bar_close(load_feed(feed_path))
    sources = load_sources(
        availability_path=availability_path,
        lifecycle_path=lifecycle_path,
    )
    sources = prepare_fast_sources(sources, timeframe=tf)
    stamps = evaluation_timestamps(
        availability_path, timeframe=tf, limit=limit, from_ts=from_ts, to_ts=to_ts
    )
    if not stamps:
        raise RuntimeError("no evaluation timestamps in pack availability")

    window = {
        "first_evaluation": stamps[0].isoformat().replace("+00:00", "Z"),
        "last_evaluation": stamps[-1].isoformat().replace("+00:00", "Z"),
        "evaluations": len(stamps),
        "limit": limit,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "anti_saw_enabled": False,
        "out_dir": str(out_dir),
    }

    # Avoid reloading live context_decision_log every cycle (O(history) iterrows).
    empty_decision_index: dict[str, dict] = {"open": {}, "close": {}}
    # Causal feed views via searchsorted (avoid O(n²) boolean filters).
    feed = feed.sort_values("bar_close_timestamp").reset_index(drop=True)
    bar_closes = pd.to_datetime(feed["bar_close_timestamp"], utc=True).to_numpy(dtype="datetime64[ns]")

    for index, evaluation in enumerate(stamps):
        boundary = pd.Timestamp(evaluation)
        if boundary.tzinfo is None:
            boundary = boundary.tz_localize("UTC")
        else:
            boundary = boundary.tz_convert("UTC")
        cut = int(bar_closes.searchsorted(boundary.to_datetime64(), side="right"))
        if cut <= 0:
            continue
        # Command TTL is ~2 M15 bars; keep a short causal tail instead of O(n) full history.
        visible = feed.iloc[max(0, cut - 16) : cut]
        manager.run_cycle(
            evaluation_timestamp=evaluation,
            sources=sources,
            feed=visible,
            persist=True,
            decision_index=empty_decision_index,
        )
        for trader in traders.values():
            trader.run_once(feed=visible)
        if flush_every > 0 and (index + 1) % flush_every == 0:
            bus.flush()
            elapsed = time.time() - started
            done = index + 1
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (len(stamps) - done) / rate if rate > 0 else None
            print(
                json.dumps(
                    {
                        "progress_cycle": done,
                        "of": len(stamps),
                        "evaluation_timestamp": str(evaluation),
                        "commands": int(len(bus._rows)),
                        "elapsed_s": round(elapsed, 1),
                        "bars_per_s": round(rate, 1),
                        "eta_s": None if eta is None else round(eta, 1),
                    }
                ),
                flush=True,
            )

    bus.flush()
    flush_memory_ledgers()
    trades = collect_closed_trades(books)
    if len(trades):
        trades.to_parquet(out_dir / "lived_trades.parquet", index=False)
    commands = bus.frame()
    if len(commands):
        disk_write_parquet(bus_paths.memory, commands[COMMAND_COLUMNS])

    summary = summarize(
        trades,
        commands,
        timeframe=tf,
        cycles=len(stamps),
        window=window,
        started_at=started_at,
        elapsed_s=time.time() - started,
        pack_dir=pack_dir,
        out_dir=out_dir,
    )
    (out_dir / "lived_replay_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Update pack manifest
    manifest_path = pack_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        manifest["status"] = "LIVED_REPLAY_DONE"
        manifest["lived_replay"] = {
            "dir": str(out_dir),
            "closed_trades": summary["closed_trades"],
            "net_pnl_usd": summary["net_pnl_usd"],
            "elapsed_seconds": summary["elapsed_seconds"],
            "generated_at": summary["generated_at"],
        }
        manifest["next_step_ru"] = (
            "Lived replay готов. Дальше — сравнение наших сделок с чужими BTC "
            "и отбор good/bad → Toxic Box."
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", type=str, default="M15", help="Single TF replay: M15, M30, H1, H4")
    parser.add_argument("--pack-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="First N evaluation bars (smoke)")
    parser.add_argument("--flush-every", type=int, default=500)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output dir (default: pack_dir/lived_replay). Does not touch other snapshots.",
    )
    parser.add_argument(
        "--anti-saw",
        choices=("on", "off"),
        default="off",
        help="Ignored. Bar-count anti-saw is archived; this flag is a no-op.",
    )
    parser.add_argument("--from", dest="from_ts", default=None, help="Inclusive evaluation start ISO")
    parser.add_argument("--to", dest="to_ts", default=None, help="Exclusive evaluation end ISO")
    args = parser.parse_args()
    tf = str(args.timeframe).upper()
    pack_dir = args.pack_dir or default_pack_dir(tf)
    summary = run(
        pack_dir=pack_dir,
        timeframe=tf,
        limit=args.limit,
        flush_every=args.flush_every,
        out_dir=args.out_dir,
        anti_saw=(args.anti_saw == "on"),
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
