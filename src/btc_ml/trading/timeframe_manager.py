"""Deterministic timeframe manager (S4.1).

The manager is a pure command dispatcher. It never executes orders, never
writes paper fills/trades, and never merges directions across timeframes:
each timeframe receives its own explainable command every cycle.

Identity-only read: exact lookup against ``context_decision_log`` attaches
immutable ``decision_id`` (and related additive identity fields) onto new
command rows. Trading policy / intent / risk logic is unchanged. No separate
manager-evaluation live artifact is written.
"""

from __future__ import annotations

import hashlib
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
CONTEXT_DECISION_LOG = ROOT / "data" / "live" / "context_decision_log.parquet"

ASSET = "BTCUSDT"
TIMEFRAME_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
_SOURCE_TF_TO_MANAGER = {"15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4"}


def _canonical_episode_id(*, namespace: str, original: str, timeframe: str | None) -> str:
    """Deterministic bridge id — does not replace original episode keys."""
    payload = "|".join(["episode", namespace, original, timeframe if timeframe else "NONE"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _ts_key(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


LINEAGE_EXACT_UNIQUE_MATCH = "EXACT_UNIQUE_MATCH"
LINEAGE_NO_EXACT_DECISION_MATCH = "NO_EXACT_DECISION_MATCH"
LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH = "AMBIGUOUS_EXACT_DECISION_MATCH"


def _empty_identity(*, status: str) -> dict[str, Any]:
    return {
        "decision_id": None,
        "context_id": None,
        "source_decision_timestamp": None,
        "lineage_lookup_status": status,
    }


def _index_put(
    index: dict[tuple[pd.Timestamp, str], dict[str, Any]],
    key: tuple[pd.Timestamp, str],
    identity: dict[str, Any],
) -> None:
    """Insert identity; mark key ambiguous if distinct decision_ids collide."""
    existing = index.get(key)
    if existing is None:
        index[key] = identity
        return
    if existing.get("lineage_lookup_status") == LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH:
        return
    if existing.get("decision_id") == identity.get("decision_id"):
        return
    # Fail-closed marker — never keep first/last winner
    index[key] = {
        "decision_id": None,
        "context_id": None,
        "source_decision_timestamp": None,
        "lineage_lookup_status": LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH,
        "ambiguous_decision_ids": sorted(
            {
                str(existing.get("decision_id")),
                str(identity.get("decision_id")),
            }
        ),
    }


def load_decision_identity_index(
    path: Path | None = None,
) -> dict[str, dict[tuple[pd.Timestamp, str], dict[str, Any]]]:
    """Exact-key indexes separated by bar-open vs bar-close.

    Open keys use ``candle_timestamp``; close keys use ``candle_close_time_utc``.
    Mixing both into one map creates false collisions (prev close == next open).
    Never invents ``decision_id``. Missing / unreadable log → empty indexes.
    """
    empty: dict[str, dict[tuple[pd.Timestamp, str], dict[str, Any]]] = {"open": {}, "close": {}}
    target = path or CONTEXT_DECISION_LOG
    if not target.exists():
        return empty
    try:
        frame = pd.read_parquet(target)
    except Exception:
        return empty
    if frame is None or not len(frame) or "decision_id" not in frame.columns:
        return empty
    for _, row in frame.iterrows():
        manager_tf = _SOURCE_TF_TO_MANAGER.get(str(row.get("source_timeframe") or "").strip())
        if not manager_tf:
            continue
        decision_id = row.get("decision_id")
        if decision_id is None or (isinstance(decision_id, float) and pd.isna(decision_id)):
            continue
        decision_text = str(decision_id).strip()
        if not decision_text:
            continue
        context_raw = row.get("context_episode_id")
        lifecycle_raw = row.get("lifecycle_episode_id")
        context_id = None if context_raw is None or pd.isna(context_raw) else str(context_raw).strip() or None
        lifecycle_id = None if lifecycle_raw is None or pd.isna(lifecycle_raw) else str(lifecycle_raw).strip() or None
        identity = {
            "decision_id": decision_text,
            "context_id": context_id,
            "lifecycle_episode_id_from_decision": lifecycle_id,
            "source_decision_timestamp": row.get("candle_timestamp") or row.get("candle_close_time_utc"),
            "lineage_lookup_status": LINEAGE_EXACT_UNIQUE_MATCH,
        }
        open_ts = _ts_key(row.get("candle_timestamp"))
        if open_ts is not None:
            _index_put(empty["open"], (open_ts, manager_tf), identity)
        close_ts = _ts_key(row.get("candle_close_time_utc"))
        if close_ts is not None:
            _index_put(empty["close"], (close_ts, manager_tf), identity)
    return empty


def resolve_decision_identity(
    *,
    timeframe: str,
    source_bar_open: Any,
    source_bar_close: Any,
    evaluation_timestamp: Any,
    index: dict[str, dict[tuple[pd.Timestamp, str], dict[str, Any]]] | dict[tuple[pd.Timestamp, str], dict[str, Any]] | None,
) -> dict[str, Any]:
    """Exact join only — no first/last pick, no fuzzy window, no synthetic decision_id.

    Status contract:
      EXACT_UNIQUE_MATCH | NO_EXACT_DECISION_MATCH | AMBIGUOUS_EXACT_DECISION_MATCH
    """
    if not index:
        return _empty_identity(status=LINEAGE_NO_EXACT_DECISION_MATCH)

    # Backward-compatible: flat dict treated as open-index only (tests / callers).
    if "open" in index and "close" in index and isinstance(index.get("open"), dict):
        open_index = index["open"]
        close_index = index["close"]
    else:
        open_index = index  # type: ignore[assignment]
        close_index = {}

    tf = str(timeframe).upper()
    # Ordered probes: first exact unique hit wins. Ambiguity on a probed key
    # fails closed immediately — never pick first/last among colliding IDs.
    probes: list[tuple[Any, dict[tuple[pd.Timestamp, str], dict[str, Any]]]] = [
        (source_bar_open, open_index),
        (source_bar_close, close_index),
        (evaluation_timestamp, open_index),
        (evaluation_timestamp, close_index),
    ]
    for value, table in probes:
        key_ts = _ts_key(value)
        if key_ts is None:
            continue
        hit = table.get((key_ts, tf))
        if hit is None:
            continue
        if hit.get("lineage_lookup_status") == LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH:
            return _empty_identity(status=LINEAGE_AMBIGUOUS_EXACT_DECISION_MATCH)
        if hit.get("decision_id"):
            return {
                "decision_id": hit.get("decision_id"),
                "context_id": hit.get("context_id"),
                "source_decision_timestamp": hit.get("source_decision_timestamp") or value,
                "lineage_lookup_status": LINEAGE_EXACT_UNIQUE_MATCH,
            }
    return _empty_identity(status=LINEAGE_NO_EXACT_DECISION_MATCH)


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
        if self._use_live1b_position_views():
            from .live1b_position_views import live1b_trader_views

            return live1b_trader_views(
                timeframes=self.timeframes,
                mark_price=mark_price,
            )
        return {tf: PaperTraderEngine(book).snapshot(mark_price=mark_price) for tf, book in self.books.items()}

    @staticmethod
    def _use_live1b_position_views() -> bool:
        """Hybrid: S4.1 manager reads LIVE1B epoch books for open/risk."""
        activation = ROOT / "data" / "trading" / "manager" / "activation.json"
        try:
            payload = json.loads(activation.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        hybrid = payload.get("hybrid") if isinstance(payload.get("hybrid"), dict) else {}
        if str(hybrid.get("position_source") or "").lower() in {
            "live1b",
            "live1b_epoch_books",
            "live1b_intrabar_paper",
        }:
            return True
        return str(payload.get("execution_owner") or "").upper() in {
            "LIVE1B_INTRABAR_PAPER",
            "LIVE1B",
        }

    # --- cycle ---------------------------------------------------------------
    def run_cycle(
        self,
        *,
        evaluation_timestamp: Any,
        sources: TimeframeSources | None = None,
        feed: pd.DataFrame | None = None,
        activation_boundary: Any = None,
        persist: bool = True,
        decision_log_path: Path | None = None,
        decision_index: dict[str, dict[tuple[pd.Timestamp, str], dict[str, Any]]]
        | dict[tuple[pd.Timestamp, str], dict[str, Any]]
        | None = None,
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
        # Identity lookup is read-only. Callers may pass an empty index to isolate
        # fixtures from the live decision log without changing trading policy.
        resolved_decision_index = (
            decision_index if decision_index is not None else load_decision_identity_index(decision_log_path)
        )
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
                decision_index=resolved_decision_index,
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
                    "decision_id": cmd.get("decision_id"),
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
        decision_index: dict[str, dict[tuple[pd.Timestamp, str], dict[str, Any]]]
        | dict[tuple[pd.Timestamp, str], dict[str, Any]]
        | None = None,
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
                meta = self._position_meta(timeframe)
                stop = safe_float(open_position.get("stop_loss_price"))
                take = safe_float(open_position.get("take_profit_price"))
                if stop is None:
                    stop = safe_float(meta.get("stop_loss_price"))
                if take is None:
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
                    entry_fee_usd=float(
                        safe_float(open_position.get("entry_fee_usd"))
                        or safe_float(meta.get("entry_fee_usd"))
                        or 0.0
                    ),
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
        # Additive identity passthrough — never invent decision_id; never alias command_id.
        identity = resolve_decision_identity(
            timeframe=timeframe,
            source_bar_open=state.get("source_bar_open"),
            source_bar_close=bar_close,
            evaluation_timestamp=state.get("evaluation_timestamp") or evaluation_timestamp,
            index=decision_index,
        )
        decision_id = identity.get("decision_id")
        lineage_lookup_status = identity.get("lineage_lookup_status") or LINEAGE_NO_EXACT_DECISION_MATCH
        timeframe_episode_id = str(episode).strip() if episode is not None and str(episode).strip() else None
        canonical_episode_id = None
        if timeframe_episode_id:
            canonical_episode_id = _canonical_episode_id(
                namespace="timeframe",
                original=timeframe_episode_id,
                timeframe=timeframe,
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
            "context_origin_price": state.get("context_origin_price"),
            "context_started_at": state.get("context_started_at"),
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
            "decision_id": decision_id,
            "context_id": identity.get("context_id"),
            "canonical_episode_id": canonical_episode_id,
            "timeframe_episode_id": timeframe_episode_id,
            "source_decision_timestamp": identity.get("source_decision_timestamp")
            or state.get("source_bar_open")
            or state.get("evaluation_timestamp")
            or evaluation_timestamp,
            "lineage_lookup_status": lineage_lookup_status,
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
