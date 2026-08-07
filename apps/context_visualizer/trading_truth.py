"""Dashboard/visualizer read adapter for canonical paper-trading truth.

Read-only over:
  - data/trading/timeframe_traders/{M15,M30,H1,H4}/
  - data/cognition/market_context_lifecycle_memory.parquet
  - data/cognition/market_context_lifecycle_episodes.parquet
  - data/runtime/timeframe_manager_latest.json

Does not write trading books. Does not change manager/trader logic.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(os.environ.get("BTC_ML_ROOT", Path(__file__).resolve().parents[2]))
TRADER_BOOKS_ROOT = ROOT / "data" / "trading" / "timeframe_traders"
LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
MANAGER_LATEST = ROOT / "data" / "runtime" / "timeframe_manager_latest.json"
LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
ARBITRATION = ROOT / "data" / "cognition" / "auction_context_arbitration_memory.parquet"

TIMEFRAMES = ("M15", "M30", "H1", "H4")
DIRECTIONAL = {"LONG_CONTEXT", "SHORT_CONTEXT"}
ACTIVE_EPOCH_PATH = ROOT / "data" / "trading" / "paper_epochs" / "active.json"


def _live1b_active() -> bool:
    if not ACTIVE_EPOCH_PATH.exists():
        return False
    try:
        payload = json.loads(ACTIVE_EPOCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return False
    return str(payload.get("rule_contract_version") or "").startswith("INTRABAR_RULES")


def _live1b_books_root() -> Path | None:
    if not _live1b_active():
        return None
    try:
        payload = json.loads(ACTIVE_EPOCH_PATH.read_text(encoding="utf-8"))
        eid = str(payload.get("paper_epoch_id") or "")
    except Exception:
        return None
    if not eid:
        return None
    return ROOT / "data" / "trading" / "intrabar_paper" / eid / "books"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_live1b_open_positions(*, timeframe: str | None = None) -> list[dict[str, Any]]:
    books = _live1b_books_root()
    if books is None:
        return []
    selected = TIMEFRAMES if timeframe in (None, "", "ALL") else (str(timeframe).upper(),)
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(books / "positions.jsonl"):
        pid = str(row.get("position_id") or "")
        if pid:
            latest[pid] = row

    # Context events for lineage fields
    ctx_by_id: dict[str, dict[str, Any]] = {}
    ctx_path = ROOT / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
    for crow in _read_jsonl(ctx_path):
        cid = str(crow.get("context_event_id") or "")
        if cid:
            ctx_by_id[cid] = crow

    # Shared causal mark (LONG→bid, SHORT→ask)
    mark_bid = mark_ask = None
    mark_ts = None
    mark_source = None
    try:
        from btc_ml.trading.intrabar_paper.mark import (  # type: ignore
            mark_price_for_side,
            mark_side_label,
            position_notional_usd,
            risk_reward_ratio,
            unrealized_pnl_usd,
        )
    except Exception:
        mark_price_for_side = None  # type: ignore
        mark_side_label = None  # type: ignore
        position_notional_usd = None  # type: ignore
        risk_reward_ratio = None  # type: ignore
        unrealized_pnl_usd = None  # type: ignore
    try:
        sys.path.insert(0, str(ROOT))
        import ops_dashboard_runtime_truth as ops_truth  # type: ignore

        bbo = ops_truth._latest_book_ticker_bbo()
        if bbo:
            mark_bid = bbo.get("best_bid")
            mark_ask = bbo.get("best_ask")
            mark_ts = bbo.get("mark_timestamp")
            mark_source = bbo.get("mark_source")
    except Exception:
        bbo = None

    try:
        from btc_ml.live.intrabar.partial_bar_state import bar_open_for  # type: ignore
    except Exception:
        bar_open_for = None  # type: ignore

    out: list[dict[str, Any]] = []
    for row in latest.values():
        tf = str(row.get("timeframe") or "").upper()
        if tf not in selected:
            continue
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        side = (_txt(row.get("side")) or "LONG").upper()
        entry_ts = _iso(row.get("opened_at"))
        entry_px = _f(row.get("entry_price"))
        qty = _f(row.get("quantity"))
        stop = _f(row.get("stop_loss_price"))
        take = _f(row.get("take_profit_price"))
        risk = _f(row.get("risk_amount_usd"))
        ctx_id = _txt(row.get("entry_context_event_id"))
        ctx = ctx_by_id.get(ctx_id or "")
        notional = None
        if entry_px is not None and qty is not None and position_notional_usd is not None:
            notional = position_notional_usd(quantity=qty, entry_price=entry_px)
        elif entry_px is not None and qty is not None:
            notional = abs(entry_px * qty)
        rr = None
        if risk_reward_ratio is not None and entry_px is not None:
            rr = risk_reward_ratio(
                side=side,
                entry_price=entry_px,
                stop_loss_price=stop,
                take_profit_price=take,
            )
        mark_px = None
        upnl = None
        mark_side = None
        if (
            mark_price_for_side is not None
            and mark_bid is not None
            and mark_ask is not None
            and entry_px is not None
            and qty is not None
        ):
            mark_px = mark_price_for_side(side=side, best_bid=float(mark_bid), best_ask=float(mark_ask))
            mark_side = mark_side_label(side) if mark_side_label else None
            if unrealized_pnl_usd is not None:
                upnl = unrealized_pnl_usd(
                    side=side, entry_price=entry_px, quantity=qty, mark_price=mark_px
                )
        bar_anchor = None
        if bar_open_for is not None and entry_ts:
            try:
                bar_anchor = bar_open_for(entry_ts, tf).isoformat().replace("+00:00", "Z")
            except Exception:
                bar_anchor = None
        out.append(
            {
                "position_id": _txt(row.get("position_id")),
                "paper_epoch_id": _txt(row.get("paper_epoch_id")),
                "timeframe": tf,
                "status": "OPEN",
                "side": side,
                "entry_timestamp": entry_ts,
                "event_timestamp": entry_ts,
                "entry_fill_timestamp": entry_ts,
                "bar_anchor_time": bar_anchor,
                "entry_price": entry_px,
                "entry_fill_price": entry_px,
                "quantity": qty,
                "position_notional": notional,
                "notional": notional,
                "risk_amount_usd": risk,
                "stop_price": stop,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "risk_reward_ratio": rr,
                "unrealized_pnl": upnl,
                "unrealized_pnl_usd": upnl,
                "mark_price": mark_px,
                "mark_timestamp": mark_ts,
                "mark_side": mark_side,
                "mark_source": mark_source,
                "context_event_id": ctx_id,
                "lifecycle_episode_id": _txt(row.get("lifecycle_episode_id")),
                "episode_key": _txt(row.get("lifecycle_episode_id")),
                "context_started_at": None if ctx is None else _iso(ctx.get("event_timestamp")),
                "context_price": None if ctx is None else _f(ctx.get("context_event_price")),
                "context_price_timestamp": None if ctx is None else _iso(ctx.get("last_trade_timestamp")),
                "exit_timestamp": None,
                "exit_price": None,
                "realized_pnl": None,
                "symbol": "BTCUSDT",
                "command_id": _txt(row.get("entry_command_id")),
                "source_book": f"INTRABAR_PAPER_{tf}",
                "visual_kind": "OPEN_POSITION",
            }
        )
    out.sort(key=lambda r: (r.get("timeframe") or "", r.get("entry_timestamp") or ""))
    return out


def _load_live1b_closed_trades(*, timeframe: str | None = None) -> list[dict[str, Any]]:
    books = _live1b_books_root()
    if books is None:
        return []
    selected = TIMEFRAMES if timeframe in (None, "", "ALL") else (str(timeframe).upper(),)

    # trades.jsonl may contain entry_ts=null. Recover the canonical entry
    # timestamp from the corresponding OPEN position record.
    opened_at_by_position: dict[str, str] = {}
    for position in _read_jsonl(books / "positions.jsonl"):
        position_id = _txt(position.get("position_id"))
        opened_at = _iso(position.get("opened_at"))
        if position_id and opened_at and position_id not in opened_at_by_position:
            opened_at_by_position[position_id] = opened_at

    out: list[dict[str, Any]] = []
    for row in _read_jsonl(books / "trades.jsonl"):
        tf = str(row.get("timeframe") or "").upper()
        if tf not in selected:
            continue
        exit_ts = _iso(row.get("exit_ts"))
        if not exit_ts:
            continue

        position_id = _txt(row.get("position_id"))
        entry_ts = _iso(row.get("entry_ts")) or opened_at_by_position.get(position_id)

        out.append(
            {
                "trade_id": _txt(row.get("trade_id")),
                "position_id": position_id,
                "timeframe": tf,
                "status": "CLOSED",
                "side": (_txt(row.get("side")) or "LONG").upper(),
                "entry_timestamp": entry_ts,
                "entry_fill_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "entry_price": _f(row.get("entry_price")),
                "exit_price": _f(row.get("exit_price")),
                "quantity": _f(row.get("quantity")),
                "notional": None,
                "stop_price": _f(row.get("stop_loss_price")),
                "take_profit_price": _f(row.get("take_profit_price")),
                "realized_pnl": _f(row.get("net_pnl_usd")),
                "symbol": "BTCUSDT",
                "source_book": f"INTRABAR_PAPER_{tf}",
                "visual_kind": "CLOSED_TRADE",
                "paper_epoch_id": _txt(row.get("paper_epoch_id")),
            }
        )
    out.sort(key=lambda r: (r.get("timeframe") or "", r.get("exit_timestamp") or ""))
    return out


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_utc(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        stamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _iso(value: Any) -> str | None:
    stamp = _to_utc(value)
    return None if stamp is None else stamp.isoformat().replace("+00:00", "Z")


def _f(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(out):
        return None
    return out


def _txt(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = _txt(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def book_paths(timeframe: str) -> dict[str, str]:
    root = TRADER_BOOKS_ROOT / timeframe
    return {
        "signals": str(root / "signals.parquet"),
        "orders": str(root / "orders.parquet"),
        "fills": str(root / "fills.parquet"),
        "trades": str(root / "trades.parquet"),
        "positions": str(root / "positions.parquet"),
    }


def load_open_positions(*, timeframe: str | None = None) -> list[dict[str, Any]]:
    """Return OPEN positions from active paper books.

    LIVE1B: legacy closed-bar timeframe_traders books are excluded from the
    active view (archive/void only).
    """
    if _live1b_active():
        return _load_live1b_open_positions(timeframe=timeframe)
    selected = TIMEFRAMES if timeframe in (None, "", "ALL") else (str(timeframe).upper(),)
    rows: list[dict[str, Any]] = []
    for tf in selected:
        if tf not in TIMEFRAMES:
            continue
        path = TRADER_BOOKS_ROOT / tf / "positions.parquet"
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame is None or not len(frame):
            continue
        status = frame.get("status")
        if status is None:
            continue
        open_frame = frame[status.astype(str).str.upper() == "OPEN"]
        for _, raw in open_frame.iterrows():
            meta = _parse_meta(raw.get("metadata_json"))
            episode_key = _txt(meta.get("lifecycle_episode_id")) or _txt(raw.get("lifecycle_episode_id"))
            rows.append(
                {
                    "position_id": _txt(raw.get("position_id")),
                    "timeframe": _txt(raw.get("timeframe")) or tf,
                    "status": "OPEN",
                    "side": (_txt(raw.get("direction")) or _txt(meta.get("side")) or "LONG").upper(),
                    "entry_timestamp": _iso(raw.get("opened_at") or meta.get("fill_timestamp")),
                    "entry_price": _f(raw.get("entry_price") or meta.get("entry_price")),
                    "quantity": _f(raw.get("quantity") or meta.get("quantity_btc")),
                    "notional": _f(raw.get("notional") or meta.get("notional_usd")),
                    "stop_price": _f(meta.get("stop_loss_price")),
                    "take_profit_price": _f(meta.get("take_profit_price")),
                    "unrealized_pnl": _f(raw.get("unrealized_pnl")),
                    "episode_key": episode_key,
                    "exit_timestamp": None,
                    "exit_price": None,
                    "realized_pnl": None,
                    "symbol": _txt(raw.get("symbol")) or "BTCUSDT",
                    "command_id": _txt(raw.get("command_id") or meta.get("command_id")),
                    "source_book": f"TIMEFRAME_TRADER_{tf}",
                    "visual_kind": "OPEN_POSITION",
                }
            )
    rows.sort(key=lambda r: (r.get("timeframe") or "", r.get("entry_timestamp") or ""))
    return rows


def load_closed_trades(*, timeframe: str | None = None) -> list[dict[str, Any]]:
    if _live1b_active():
        return _load_live1b_closed_trades(timeframe=timeframe)
    selected = TIMEFRAMES if timeframe in (None, "", "ALL") else (str(timeframe).upper(),)
    rows: list[dict[str, Any]] = []
    for tf in selected:
        if tf not in TIMEFRAMES:
            continue
        path = TRADER_BOOKS_ROOT / tf / "trades.parquet"
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        for _, raw in frame.iterrows():
            exit_ts = _iso(raw.get("exit_ts"))
            if not exit_ts:
                continue
            rows.append(
                {
                    "trade_id": _txt(raw.get("trade_id")),
                    "timeframe": _txt(raw.get("timeframe")) or tf,
                    "status": "CLOSED",
                    "side": (_txt(raw.get("side")) or "LONG").upper(),
                    "entry_timestamp": _iso(raw.get("entry_ts")),
                    "exit_timestamp": exit_ts,
                    "entry_price": _f(raw.get("entry_price")),
                    "exit_price": _f(raw.get("exit_price")),
                    "quantity": _f(raw.get("quantity")),
                    "notional": _f(raw.get("notional_usd")),
                    "stop_price": _f(raw.get("stop_loss_price")),
                    "take_profit_price": _f(raw.get("take_profit_price")),
                    "realized_pnl": _f(raw.get("net_pnl_usd")),
                    "unrealized_pnl": None,
                    "episode_key": _txt(raw.get("lifecycle_episode_id")),
                    "position_id": _txt(raw.get("position_id")),
                    "command_id": _txt(raw.get("command_id")),
                    "source_book": f"TIMEFRAME_TRADER_{tf}",
                    "visual_kind": "CLOSED_TRADE",
                }
            )
    rows.sort(key=lambda r: (r.get("exit_timestamp") or "", r.get("timeframe") or ""))
    return rows


def collapse_lifecycle_episodes(
    episodes: pd.DataFrame | None = None,
    *,
    latest_evaluation: Any = None,
) -> list[dict[str, Any]]:
    """One continuous visual band per canonical episode_id."""
    if episodes is None:
        if not LIFECYCLE_EPISODES.exists():
            return []
        episodes = pd.read_parquet(LIFECYCLE_EPISODES)
    if episodes is None or not len(episodes):
        return []

    work = episodes.copy()
    work["episode_id"] = pd.to_numeric(work["episode_id"], errors="coerce")
    work = work.dropna(subset=["episode_id"])
    work["start_time"] = work["start_time"].map(_to_utc)
    work["end_time"] = work["end_time"].map(_to_utc)
    work = work.dropna(subset=["start_time"])

    latest = _to_utc(latest_evaluation)
    if latest is None and LIFECYCLE_MEMORY.exists():
        memory = pd.read_parquet(LIFECYCLE_MEMORY)
        if len(memory) and "timestamp" in memory.columns:
            latest = _to_utc(memory["timestamp"].iloc[-1])

    out: list[dict[str, Any]] = []
    for episode_id, group in work.groupby("episode_id", sort=True):
        group = group.sort_values(["start_time", "end_time"])
        start = group["start_time"].min()
        end = group["end_time"].max()
        end_reasons = [str(x) for x in group.get("end_reason", pd.Series(dtype=str)).tolist()]
        is_open = any("latest open" in reason.lower() for reason in end_reasons)
        context = None
        for value in group.get("active_market_context", pd.Series(dtype=str)).tolist():
            text = _txt(value)
            if text in DIRECTIONAL:
                context = text
                break
        if context is None:
            context = _txt(group["active_market_context"].iloc[-1]) or "OBSERVE"
        if is_open and latest is not None and (end is None or end < latest):
            end = latest
        if end is None:
            end = start
        bars = max(1, int(((end - start).total_seconds() // 900) + 1)) if start is not None else 1
        challenged = int(pd.to_numeric(group.get("challenged_bars_count"), errors="coerce").fillna(0).max())
        out.append(
            {
                "episode_id": int(episode_id),
                "episode_key": str(int(episode_id)),
                "context": context,
                "direction": "LONG" if context == "LONG_CONTEXT" else ("SHORT" if context == "SHORT_CONTEXT" else "OBSERVE"),
                "start_time": _iso(start),
                "end_time": _iso(end),
                "start_time_unix": int(pd.Timestamp(start).timestamp()),
                "end_time_unix": int(pd.Timestamp(end).timestamp()),
                "bars_count": bars,
                "duration_minutes": float(bars * 15),
                "dominant_lifecycle_state": _txt(group.get("dominant_lifecycle_state", pd.Series(["UNKNOWN"])).iloc[-1])
                or "UNKNOWN",
                "challenged_bars_count": challenged,
                "challenge_ratio": round(challenged / float(bars), 4) if bars else 0.0,
                "start_reason": _txt(group.get("start_reason", pd.Series(["UNKNOWN"])).iloc[0]) or "UNKNOWN",
                "end_reason": "latest open lifecycle episode" if is_open else (_txt(end_reasons[-1]) or "UNKNOWN"),
                "is_active": bool(is_open),
                "source": "market_context_lifecycle_episodes",
                "visual_source": "canonical_lifecycle_episode_interval",
                "shadow_only": False,
                "plane": "decision_driving",
            }
        )
    out.sort(key=lambda row: (row.get("start_time_unix") or 0, row.get("episode_id") or 0))
    return out


def active_episode_from_memory() -> dict[str, Any] | None:
    if not LIFECYCLE_MEMORY.exists():
        return None
    memory = pd.read_parquet(LIFECYCLE_MEMORY)
    if not len(memory):
        return None
    memory = memory.copy()
    memory["timestamp"] = memory["timestamp"].map(_to_utc)
    memory = memory.dropna(subset=["timestamp"]).sort_values("timestamp")
    tip = memory.iloc[-1]
    episode_id = tip.get("context_episode_id")
    if pd.isna(episode_id):
        return None
    episode_id = int(episode_id)
    active = _txt(tip.get("active_market_context")) or "OBSERVE"
    subset = memory[memory["context_episode_id"] == episode_id]
    start = subset["timestamp"].min() if len(subset) else tip["timestamp"]
    end = tip["timestamp"]
    return {
        "episode_id": episode_id,
        "episode_key": str(episode_id),
        "context": active,
        "direction": "LONG" if active == "LONG_CONTEXT" else ("SHORT" if active == "SHORT_CONTEXT" else "OBSERVE"),
        "start_time": _iso(start),
        "end_time": _iso(end),
        "start_time_unix": int(pd.Timestamp(start).timestamp()),
        "end_time_unix": int(pd.Timestamp(end).timestamp()),
        "lifecycle_state": _txt(tip.get("lifecycle_state")),
        "action_allowed": bool(tip.get("action_allowed")) if tip.get("action_allowed") is not None else False,
        "shadow_only": bool(tip.get("shadow_only")) if tip.get("shadow_only") is not None else True,
        "is_active": active in DIRECTIONAL,
        "source": "market_context_lifecycle_memory",
        "plane": "decision_driving",
    }


def shadow_diagnostics() -> dict[str, Any] | None:
    if not ARBITRATION.exists():
        return None
    try:
        frame = pd.read_parquet(ARBITRATION)
    except Exception:
        return None
    if not len(frame):
        return None
    tip = frame.iloc[-1]
    return {
        "label": "Shadow diagnostics",
        "artifact": "auction_context_arbitration_memory.parquet",
        "timestamp": _iso(tip.get("timestamp")),
        "calibrated_context": _txt(tip.get("calibrated_context")),
        "trading_state": _txt(tip.get("trading_state")),
        "shadow_only": bool(tip.get("shadow_only")) if tip.get("shadow_only") is not None else True,
        "is_active_trading_context": False,
    }


def _tip_from_parquet(path: Path, columns: tuple[str, ...]) -> str | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None
    for column in columns:
        if column in frame.columns:
            series = frame[column].map(_to_utc).dropna()
            if len(series):
                return _iso(series.max())
    return None


def build_trading_truth(*, timeframe: str | None = "ALL") -> dict[str, Any]:
    tf = "ALL" if timeframe in (None, "", "ALL") else str(timeframe).upper()
    open_positions = load_open_positions(timeframe=tf)
    closed_trades = load_closed_trades(timeframe=tf)
    episodes = collapse_lifecycle_episodes()
    active = active_episode_from_memory()
    manager = {}
    if MANAGER_LATEST.exists():
        try:
            manager = json.loads(MANAGER_LATEST.read_text(encoding="utf-8"))
        except Exception:
            manager = {}

    feed_tip = _tip_from_parquet(LIVE_FEED, ("timestamp",))
    life_tip = _tip_from_parquet(LIFECYCLE_MEMORY, ("timestamp",))
    pos_tips = []
    for name in TIMEFRAMES:
        path = TRADER_BOOKS_ROOT / name / "positions.parquet"
        tip = _tip_from_parquet(path, ("opened_at", "closed_at"))
        if tip:
            pos_tips.append(tip)
    trades_tips = []
    for name in TIMEFRAMES:
        tip = _tip_from_parquet(TRADER_BOOKS_ROOT / name / "trades.parquet", ("exit_ts", "entry_ts"))
        if tip:
            trades_tips.append(tip)

    generated = _utc_now_iso()
    life_lag = None
    if feed_tip and life_tip:
        life_lag = abs((_to_utc(feed_tip) - _to_utc(life_tip)).total_seconds())  # type: ignore[operator]

    missing = []
    for name in TIMEFRAMES:
        if not (TRADER_BOOKS_ROOT / name / "positions.parquet").exists():
            missing.append(f"positions:{name}")
    if not LIFECYCLE_MEMORY.exists():
        missing.append("lifecycle_memory")
    if not LIFECYCLE_EPISODES.exists():
        missing.append("lifecycle_episodes")

    return {
        "generated_at": generated,
        "schema_version": "dashboard_trading_truth_v1",
        "timeframe_filter": tf,
        "supported_timeframes": ["ALL", *TIMEFRAMES],
        "canonical_tips": {
            "feed": feed_tip,
            "lifecycle": life_tip,
            "manager_evaluation": _txt(manager.get("evaluation_timestamp")),
            "positions_latest": max(pos_tips) if pos_tips else None,
            "closed_trades_latest": max(trades_tips) if trades_tips else None,
        },
        "active_episode": active,
        "lifecycle_state": None if active is None else active.get("lifecycle_state"),
        "manager_decision": {
            "paper_only": bool(manager.get("paper_only", True)),
            "execution_enabled": bool(manager.get("execution_enabled", False)),
            "evaluation_timestamp": _txt(manager.get("evaluation_timestamp")),
            "commands": {
                key: {
                    "intent": (value or {}).get("intent"),
                    "action_allowed": (value or {}).get("action_allowed"),
                    "reason_codes": (value or {}).get("reason_codes"),
                    "lifecycle_episode_id": (value or {}).get("lifecycle_episode_id"),
                    "timeframe_state": (value or {}).get("timeframe_state"),
                }
                for key, value in (manager.get("commands") or {}).items()
            },
        },
        "open_positions": open_positions,
        "closed_trades": closed_trades,
        "episodes": episodes,
        "timeframes": list(TIMEFRAMES),
        "book_paths": {name: book_paths(name) for name in TIMEFRAMES},
        "shadow_diagnostics": shadow_diagnostics(),
        "banner": {
            "trading_runtime": "LIVE PAPER",
            "real_execution": "DISABLED",
            "pipeline": "HEALTHY",
            "dashboard_data_lag_seconds": life_lag,
            "stale": bool(life_lag is not None and life_lag > 45 * 60),
        },
        "data_quality": {
            "positions_source_fresh": len(open_positions) > 0,
            "episodes_source_fresh": active is not None,
            "trades_source_fresh": True,
            "dashboard_lag_seconds": life_lag,
            "missing_sources": missing,
            "open_position_count": len(open_positions),
            "closed_trade_count": len(closed_trades),
            "active_episode_id": None if active is None else active.get("episode_id"),
        },
        "empty_state": {
            "open_positions_message": (
                f"{len(open_positions)} open paper positions"
                if open_positions
                else ("Trading data unavailable" if missing else "No open paper positions")
            ),
            "closed_trades_message": (
                "No closed trades for selected timeframe"
                if not closed_trades
                else f"{len(closed_trades)} closed trades"
            ),
        },
    }


def open_position_overlay_shapes(positions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Shapes consumable by lifecycle_app open-position rendering."""
    positions = load_open_positions() if positions is None else positions
    shapes: list[dict[str, Any]] = []
    for row in positions:
        entry_ts = row.get("entry_timestamp")
        stamp = _to_utc(entry_ts)
        shapes.append(
            {
                "trade_id": row.get("position_id"),
                "position_id": row.get("position_id"),
                "timeframe": row.get("timeframe"),
                "status": "OPEN",
                "side": row.get("side"),
                "entry_ts": entry_ts,
                "exit_ts": None,
                "entry_price": row.get("entry_price"),
                "exit_price": None,
                "quantity": row.get("quantity"),
                "notional_usd": row.get("notional"),
                "stop_loss_price": row.get("stop_price"),
                "take_profit_price": row.get("take_profit_price"),
                "unrealized_pnl": row.get("unrealized_pnl"),
                "lifecycle_episode_id": row.get("episode_key"),
                "context_episode_id": row.get("episode_key"),
                "source_book": row.get("source_book"),
                "visual_source": "timeframe_trader_open_position",
                "source": "timeframe_trader_books",
                "time_unix": None if stamp is None else int(stamp.timestamp()),
                "stop_take_lines": [
                    line
                    for line in (
                        {
                            "kind": "STOP_LOSS",
                            "price": row.get("stop_price"),
                            "visible": row.get("stop_price") is not None,
                        },
                        {
                            "kind": "TAKE_PROFIT",
                            "price": row.get("take_profit_price"),
                            "visible": row.get("take_profit_price") is not None,
                        },
                    )
                    if line["visible"]
                ],
            }
        )
    return shapes


def write_trading_truth_artifacts(output_dir: Path, *, timeframe: str = "ALL") -> dict[str, Any]:
    """Write dashboard JSON artifacts under output_dir (candidate or public/data)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    truth = build_trading_truth(timeframe=timeframe)
    episodes = truth["episodes"]
    open_positions = truth["open_positions"]
    shapes = open_position_overlay_shapes(open_positions)

    try:
        from active_epoch_trade_filter import active_paper_epoch_id, live1b_paper_active  # type: ignore
    except Exception:
        live1b_paper_active = lambda: False  # type: ignore
        active_paper_epoch_id = lambda: None  # type: ignore

    epoch_id = active_paper_epoch_id() if live1b_paper_active() else None
    truth["active_paper_epoch_id"] = epoch_id
    truth["legacy_excluded"] = bool(live1b_paper_active())
    truth["trade_overlay_source"] = (
        "LIVE1B_INTRABAR_PAPER_EPOCH" if live1b_paper_active() else "TIMEFRAME_TRADER_BOOKS"
    )
    truth["trade_marker_count"] = len(open_positions) + len(truth.get("closed_trades") or []) * 2
    truth["open_position_overlay_count"] = len(open_positions)
    truth["closed_trade_overlay_count"] = len(truth.get("closed_trades") or [])

    (output_dir / "trading_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "open_positions.json").write_text(
        json.dumps(
            {
                "generated_at_utc": truth["generated_at"],
                "source": (
                    f"data/trading/intrabar_paper/{epoch_id}/books"
                    if live1b_paper_active()
                    else "data/trading/timeframe_traders"
                ),
                "active_paper_epoch_id": epoch_id,
                "legacy_excluded": bool(live1b_paper_active()),
                "open_positions": open_positions,
                "overlay_shapes": shapes,
                "count": len(open_positions),
                "open_position_overlay_count": len(open_positions),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "lifecycle_context_episodes.json").write_text(
        json.dumps(episodes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return truth


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build dashboard trading-truth JSON (read-only books).")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "data" / "candidate" / "architecture_recovery" / "obs2a_dashboard_truth_candidate"),
    )
    parser.add_argument("--timeframe", default="ALL")
    args = parser.parse_args()
    payload = write_trading_truth_artifacts(Path(args.output_dir), timeframe=args.timeframe)
    print(
        json.dumps(
            {
                "output_dir": args.output_dir,
                "open_positions": payload["data_quality"]["open_position_count"],
                "active_episode_id": payload["data_quality"]["active_episode_id"],
                "episodes": len(payload["episodes"]),
            },
            indent=2,
        )
    )
