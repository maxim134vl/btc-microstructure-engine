"""Deterministic timeframe manager (S4.1).

The manager is a pure command dispatcher. It never executes orders, never
writes paper fills/trades, never touches cognition/context/decision datasets,
and never merges directions across timeframes: each timeframe receives its own
explainable command every cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .command_bus import COMMAND_SCHEMA_VERSION, VALID_INTENTS, CommandBus, CommandBusPaths, utc_now
from .paper_core import compute_stop_take, evaluate_exit_preview, make_id, safe_float
from .paper_trader_engine import PaperTraderEngine
from .portfolio_risk import PortfolioRiskCoordinator
from .timeframe_state_adapter import (
    SUPPORTED_TIMEFRAMES,
    UNSUPPORTED_TIMEFRAMES,
    TimeframeSources,
    load_sources,
    resolve_all_states,
)
from .trader_book import TraderBook, repo_relative

ROOT = Path(__file__).resolve().parents[3]
LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"

ASSET = "BTCUSDT"
TIMEFRAME_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


def _command_key(*, asset: str, timeframe: str, evaluation_timestamp: Any, episode: Any, intent: str) -> str:
    return make_id(
        "TF_CMD",
        asset,
        timeframe,
        evaluation_timestamp,
        episode if episode is not None else "NO_EPISODE",
        intent,
    )


def _market_observation(feed: pd.DataFrame, *, at_or_before: Any) -> dict[str, Any] | None:
    """Last bar already complete at the evaluation instant (bar_close <= ts)."""
    if feed is None or not len(feed):
        return None
    column = "bar_close_timestamp" if "bar_close_timestamp" in feed.columns else "timestamp"
    if column not in feed.columns:
        return None
    boundary = pd.Timestamp(at_or_before)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    stamps = pd.to_datetime(feed[column], utc=True, errors="coerce")
    mask = stamps <= boundary
    if not bool(mask.any()):
        return None
    idx = stamps[mask].sort_values().index[-1]
    row = feed.loc[idx]
    return {
        "timestamp": stamps.loc[idx].isoformat().replace("+00:00", "Z"),
        "close": safe_float(row.get("close")),
        "high": safe_float(row.get("high")),
        "low": safe_float(row.get("low")),
    }


FEED_BAR_SECONDS = 900


def with_bar_close(feed: pd.DataFrame, *, bar_seconds: int = FEED_BAR_SECONDS) -> pd.DataFrame:
    """Feed timestamps are bar-open labels; derive the completed-bar clock."""
    if feed is None or not len(feed) or "timestamp" not in feed.columns:
        return feed
    out = feed.copy()
    opens = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out["bar_open_timestamp"] = opens
    out["bar_close_timestamp"] = opens + pd.Timedelta(seconds=bar_seconds)
    return out


def load_feed(path: Path | None = None) -> pd.DataFrame:
    target = path or LIVE_FEED
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    if not target.exists():
        return empty
    try:
        return with_bar_close(pd.read_parquet(target))
    except Exception:
        return empty


class TimeframeManager:
    def __init__(
        self,
        *,
        bus: CommandBus,
        books: dict[str, TraderBook],
        risk: PortfolioRiskCoordinator,
        asset: str = ASSET,
        timeframes: tuple[str, ...] = SUPPORTED_TIMEFRAMES,
    ) -> None:
        self.bus = bus
        self.books = books
        self.risk = risk
        self.asset = asset
        self.timeframes = timeframes

    @classmethod
    def production(cls) -> "TimeframeManager":
        return cls(
            bus=CommandBus(CommandBusPaths.production()),
            books={tf: TraderBook.production(tf) for tf in SUPPORTED_TIMEFRAMES},
            risk=PortfolioRiskCoordinator.load(),
        )

    @classmethod
    def candidate(cls) -> "TimeframeManager":
        return cls(
            bus=CommandBus(CommandBusPaths.candidate()),
            books={tf: TraderBook.candidate(tf) for tf in SUPPORTED_TIMEFRAMES},
            risk=PortfolioRiskCoordinator.load(),
        )

    # --- read-only trader views ---------------------------------------------
    def trader_views(self, *, mark_price: float | None = None) -> dict[str, dict[str, Any]]:
        return {tf: PaperTraderEngine(book).snapshot(mark_price=mark_price) for tf, book in self.books.items()}

    # --- cycle ---------------------------------------------------------------
    def run_cycle(
        self,
        *,
        evaluation_timestamp: Any,
        sources: TimeframeSources | None = None,
        feed: pd.DataFrame | None = None,
        activation_boundary: Any = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        src = sources or load_sources()
        market_feed = feed if feed is not None else load_feed()
        states = resolve_all_states(evaluation_timestamp=evaluation_timestamp, sources=src, timeframes=self.timeframes)
        manager_cycle_id = make_id("TF_MGR_CYCLE", self.asset, evaluation_timestamp, ",".join(self.timeframes))

        mark = _market_observation(market_feed, at_or_before=evaluation_timestamp)
        mark_price = (mark or {}).get("close")
        views = self.trader_views(mark_price=mark_price)
        open_risk = {tf: float(view.get("open_risk_usd") or 0.0) for tf, view in views.items()}
        open_positions = {tf: (1 if view.get("open_position") else 0) for tf, view in views.items()}

        state = self.bus.load_manager_state()
        tf_state = dict(state.get("timeframes") or {})
        cross_metadata = {
            tf: {
                "direction": states[tf].get("timeframe_direction"),
                "availability": states[tf].get("availability_status"),
                "lifecycle_phase": states[tf].get("lifecycle_phase"),
            }
            for tf in self.timeframes
        }

        reserved_risk = dict(open_risk)
        commands: list[dict[str, Any]] = []
        for tf in self.timeframes:
            command = self._build_command(
                timeframe=tf,
                state=states[tf],
                view=views[tf],
                manager_cycle_id=manager_cycle_id,
                evaluation_timestamp=evaluation_timestamp,
                feed=market_feed,
                reserved_risk=reserved_risk,
                open_positions=open_positions,
                per_tf_state=tf_state.setdefault(tf, {}),
                cross_metadata=cross_metadata,
                activation_boundary=activation_boundary,
            )
            approved = float(safe_float(command.get("approved_risk_usd")) or 0.0)
            if command.get("intent") in {"OPEN_LONG", "OPEN_SHORT"} and approved > 0:
                reserved_risk[tf] = reserved_risk.get(tf, 0.0) + approved
            commands.append(command)

        for tf in UNSUPPORTED_TIMEFRAMES:
            tf_state.pop(tf, None)

        append_result = {"appended": 0, "duplicates_rejected": 0, "duplicate_command_ids": [], "total_rows": 0}
        if persist:
            append_result = self.bus.append(commands)

        portfolio = self.portfolio_summary(
            manager_cycle_id=manager_cycle_id,
            views=views,
            mark_price=mark_price,
            evaluation_timestamp=evaluation_timestamp,
        )
        snapshot = {
            "generated_at": utc_now(),
            "manager_cycle_id": manager_cycle_id,
            "evaluation_timestamp": str(evaluation_timestamp),
            "schema_version": COMMAND_SCHEMA_VERSION,
            "asset": self.asset,
            "supported_timeframes": list(self.timeframes),
            "unsupported_timeframes": list(UNSUPPORTED_TIMEFRAMES),
            "commands": {
                cmd["timeframe"]: {
                    "command_id": cmd["command_id"],
                    "intent": cmd["intent"],
                    "action_allowed": cmd["action_allowed"],
                    "reason_codes": cmd["reason_codes"],
                    "timeframe_state": cmd["timeframe_state"],
                    "timeframe_direction": cmd["timeframe_direction"],
                    "availability_status": cmd["availability_status"],
                    "lifecycle_episode_id": cmd["lifecycle_episode_id"],
                    "approved_risk_usd": cmd["approved_risk_usd"],
                }
                for cmd in commands
            },
            "portfolio": portfolio,
            "command_bus": {
                "memory_path": repo_relative(self.bus.paths.memory),
                **append_result,
            },
            "manager_writes_cognition": False,
            "manager_writes_paper_ledger": False,
            "directional_netting": False,
            "paper_only": True,
            "execution_enabled": False,
            "exchange_calls": 0,
        }
        if persist:
            self.bus.write_latest_snapshot(snapshot)
            self.bus.write_portfolio_summary(portfolio)
            state.update(
                {
                    "cycles": int(state.get("cycles") or 0) + 1,
                    "last_manager_cycle_id": manager_cycle_id,
                    "last_evaluation_timestamp": str(evaluation_timestamp),
                    "timeframes": tf_state,
                    "updated_at": utc_now(),
                }
            )
            self.bus.save_manager_state(state)

        return {
            "manager_cycle_id": manager_cycle_id,
            "evaluation_timestamp": str(evaluation_timestamp),
            "commands": commands,
            "states": states,
            "portfolio": portfolio,
            "append_result": append_result,
            "snapshot": snapshot,
        }

    # --- per-timeframe decision ---------------------------------------------
    def _build_command(
        self,
        *,
        timeframe: str,
        state: dict[str, Any],
        view: dict[str, Any],
        manager_cycle_id: str,
        evaluation_timestamp: Any,
        feed: pd.DataFrame,
        reserved_risk: dict[str, float],
        open_positions: dict[str, int],
        per_tf_state: dict[str, Any],
        cross_metadata: dict[str, Any],
        activation_boundary: Any = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        intent = "NO_ACTION"
        exit_reason = None
        requested_risk = 0.0
        approved_risk = 0.0
        stop_reference = None
        invalidation_reference = state.get("invalidation_reason")
        risk_view = self.risk.evaluate(
            timeframe=timeframe,
            requested_risk_usd=self.risk.trader_budget(timeframe),
            open_risk_by_timeframe=reserved_risk,
            open_positions_by_timeframe=open_positions,
        )
        portfolio_open_risk = risk_view.portfolio_open_risk_usd

        open_position = view.get("open_position")
        bar_close = state.get("source_bar_close")

        if activation_boundary is not None and bar_close is not None:
            boundary = pd.Timestamp(activation_boundary)
            boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
            evaluated = pd.Timestamp(evaluation_timestamp)
            evaluated = evaluated.tz_localize("UTC") if evaluated.tzinfo is None else evaluated.tz_convert("UTC")
            if evaluated < boundary:
                reasons.append("BEFORE_ACTIVATION_BOUNDARY")

        if open_position:
            observation = _market_observation(feed, at_or_before=evaluation_timestamp)
            meta = self._position_meta(timeframe)
            if observation is None or observation.get("close") is None:
                intent = "HOLD"
                reasons.append("NO_MARKET_OBSERVATION_HOLD")
            else:
                side = str(open_position.get("direction") or "").upper()
                entry = float(safe_float(open_position.get("entry_price")) or 0.0)
                quantity = float(safe_float(open_position.get("quantity")) or 0.0)
                stop = safe_float(meta.get("stop_loss_price"))
                take = safe_float(meta.get("take_profit_price"))
                if stop is None or take is None:
                    stop, take = compute_stop_take(side, entry)
                stop_reference = stop
                preview = evaluate_exit_preview(
                    side=side,
                    entry_price=entry,
                    quantity=quantity,
                    stop_loss_price=float(stop),
                    take_profit_price=float(take),
                    entry_fee_usd=float(safe_float(meta.get("entry_fee_usd")) or 0.0),
                    current_price=float(observation["close"]),
                    latest_high=float(observation.get("high") or observation["close"]),
                    latest_low=float(observation.get("low") or observation["close"]),
                    latest_context=str(state.get("timeframe_state") or ""),
                    latest_lifecycle_state=str(state.get("lifecycle_phase") or ""),
                )
                if preview.get("is_close"):
                    intent = "CLOSE"
                    exit_reason = str(preview.get("exit_preview_reason") or "CONTEXT_EXIT")
                    reasons.append(str(preview.get("exit_preview_action")))
                else:
                    intent = "HOLD"
                    reasons.append(str(preview.get("exit_preview_reason") or "HOLD"))
        elif not state.get("actionable"):
            intent = "NO_ACTION"
            reasons.append(str(state.get("no_action_reason") or "NOT_ACTIONABLE"))
        elif "BEFORE_ACTIVATION_BOUNDARY" in reasons:
            intent = "NO_ACTION"
        else:
            episode = state.get("lifecycle_episode_id")
            # Re-running the same evaluation must reproduce the same command, so the
            # entry recorded by this very evaluation does not block itself.
            already_entered = (
                episode is not None
                and per_tf_state.get("last_entry_episode_id") == episode
                and per_tf_state.get("last_entry_evaluation_timestamp")
                != str(state.get("evaluation_timestamp") or evaluation_timestamp)
            )
            if already_entered:
                intent = "NO_ACTION"
                reasons.append("EPISODE_ALREADY_TRADED")
            else:
                direction = str(state.get("timeframe_direction") or "").upper()
                candidate_intent = "OPEN_LONG" if direction == "LONG" else "OPEN_SHORT"
                requested_risk = self.risk.trader_budget(timeframe)
                decision = self.risk.evaluate(
                    timeframe=timeframe,
                    requested_risk_usd=requested_risk,
                    open_risk_by_timeframe=reserved_risk,
                    open_positions_by_timeframe=open_positions,
                )
                portfolio_open_risk = decision.portfolio_open_risk_usd
                if decision.approved:
                    intent = candidate_intent
                    approved_risk = decision.approved_risk_usd
                    reasons.append(f"TIMEFRAME_DIRECTIONAL_ENTRY:{direction}")
                    per_tf_state["last_entry_episode_id"] = episode
                    per_tf_state["last_entry_evaluation_timestamp"] = str(
                        state.get("evaluation_timestamp") or evaluation_timestamp
                    )
                    observation = _market_observation(feed, at_or_before=evaluation_timestamp)
                    if observation and observation.get("close"):
                        stop_reference = compute_stop_take(
                            "LONG" if candidate_intent == "OPEN_LONG" else "SHORT",
                            float(observation["close"]),
                        )[0]
                else:
                    intent = "NO_ACTION"
                    reasons.append(str(decision.reason))

        action_allowed = intent in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}
        if not reasons:
            reasons.append(intent)
        if intent not in VALID_INTENTS:
            raise ValueError(f"invalid_intent:{intent}")

        episode = state.get("lifecycle_episode_id")
        command_id = _command_key(
            asset=self.asset,
            timeframe=timeframe,
            evaluation_timestamp=state.get("evaluation_timestamp") or str(evaluation_timestamp),
            episode=episode,
            intent=intent,
        )
        return {
            "command_id": command_id,
            "manager_cycle_id": manager_cycle_id,
            "schema_version": COMMAND_SCHEMA_VERSION,
            "asset": self.asset,
            "timeframe": timeframe,
            "evaluation_timestamp": state.get("evaluation_timestamp") or str(evaluation_timestamp),
            "source_bar_open": state.get("source_bar_open"),
            "source_bar_close": bar_close,
            "source_state_timestamp": state.get("source_state_timestamp"),
            "source_event_timestamp": state.get("source_event_timestamp"),
            "timeframe_state": state.get("timeframe_state"),
            "timeframe_direction": state.get("timeframe_direction"),
            "availability_status": state.get("availability_status"),
            "lifecycle_episode_id": episode,
            "lifecycle_phase": state.get("lifecycle_phase"),
            "intent": intent,
            "action_allowed": action_allowed,
            "reason_codes": json.dumps(reasons),
            "exit_reason": exit_reason,
            "confidence": state.get("confidence"),
            "alignment_score": state.get("alignment_score"),
            "persistence_score": state.get("persistence_score"),
            "structural_rank": state.get("structural_rank"),
            "location_bias": state.get("location_bias"),
            "requested_risk_usd": requested_risk,
            "approved_risk_usd": approved_risk,
            "portfolio_open_risk_usd": portfolio_open_risk,
            "stop_reference": stop_reference,
            "invalidation_reference": invalidation_reference,
            "command_ttl_seconds": TIMEFRAME_SECONDS.get(timeframe, 900),
            "cross_timeframe_metadata": json.dumps(cross_metadata),
            "created_at": utc_now(),
            "source_lineage": json.dumps(state.get("source_lineage") or {}),
            "paper_only": True,
            "execution_enabled": False,
        }

    def _position_meta(self, timeframe: str) -> dict[str, Any]:
        position = self.books[timeframe].open_position()
        if not position:
            return {}
        meta = position.get("metadata_json")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return meta if isinstance(meta, dict) else {}

    # --- read-only aggregation ----------------------------------------------
    def portfolio_summary(
        self,
        *,
        manager_cycle_id: str,
        views: dict[str, dict[str, Any]] | None = None,
        mark_price: float | None = None,
        evaluation_timestamp: Any = None,
    ) -> dict[str, Any]:
        views = views or self.trader_views(mark_price=mark_price)
        gross_long = 0.0
        gross_short = 0.0
        gross_risk = 0.0
        realized = 0.0
        unrealized = 0.0
        fees = 0.0
        slippage = 0.0
        open_positions = 0
        for tf, view in views.items():
            realized += float(view.get("realized_pnl_usd") or 0.0)
            unrealized += float(view.get("unrealized_pnl_usd") or 0.0)
            fees += float(view.get("fees_paid_usd") or 0.0)
            slippage += float(view.get("slippage_paid_usd") or 0.0)
            gross_risk += abs(float(view.get("open_risk_usd") or 0.0))
            position = view.get("open_position")
            if not position:
                continue
            open_positions += 1
            notional = float(position.get("quantity") or 0.0) * float(position.get("entry_price") or 0.0)
            if str(position.get("direction")).upper() == "LONG":
                gross_long += notional
            else:
                gross_short += notional
        return {
            "generated_at": utc_now(),
            "manager_cycle_id": manager_cycle_id,
            "evaluation_timestamp": None if evaluation_timestamp is None else str(evaluation_timestamp),
            "read_model_only": True,
            "netting_forbidden": True,
            "net_notional_is_reporting_only": True,
            "traders": views,
            "open_positions": open_positions,
            "gross_long_notional": gross_long,
            "gross_short_notional": gross_short,
            "net_notional": gross_long - gross_short,
            "gross_open_risk_usd": gross_risk,
            "available_risk_usd": max(0.0, self.risk.portfolio_max_risk_usd - gross_risk),
            "portfolio_max_risk_usd": self.risk.portfolio_max_risk_usd,
            "per_trader_max_risk_usd": self.risk.per_trader_max_risk_usd,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "fees_paid": fees,
            "slippage_paid": slippage,
            "mark_price": mark_price,
            "paper_only": True,
            "execution_enabled": False,
        }
