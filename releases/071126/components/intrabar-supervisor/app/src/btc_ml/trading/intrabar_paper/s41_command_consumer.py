"""Consume S4.1 command-bus rows into the LIVE1B paper engine (hybrid mode)."""

from __future__ import annotations

import json
import time
import threading
from functools import wraps
from datetime import datetime, timezone
from btc_ml.trading.timeframe_state_adapter import STALE_CLOSED_BAR_SUPERSEDED, closed_bar_superseded
from pathlib import Path
from typing import Any

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths


_TRANSIENT_OPEN_BLOCKS = frozenset(
    {
        "ENTRY_PENDING_WRITER_CONTENTION",
        "ENTRY_PENDING_PUBLICATION",
        "ENTRY_PENDING_ORIGINAL_COMMAND_RECORD",
        "ENTRY_BLOCKED_CURRENT_COMMAND_UNAVAILABLE",
        "ENTRY_BLOCKED_CURRENT_COMMAND_NOT_YET_PUBLISHED",
        "ENTRY_BLOCKED_NO_CAUSAL_BBO",
        "ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY",
        "ENTRY_BLOCKED_ACTIVE_POSITION",
    }
)


_COMMITTED_CLOSE_STATUSES = frozenset(
    {
        "EXITED",
        "DUPLICATE_PREVENTED",
        "CLOSE_NO_POSITION",
        "CLOSE_SIDE_MISMATCH",
        "CLOSE_STALE_FOR_NEWER_POSITION",
    }
)


def close_command_committed(result: dict[str, Any] | None) -> bool:
    """True when a CLOSE may be marked processed.

    No open position is committed, not retried: a leftover LONG-SL CLOSE must
    not flatten the continuation SHORT that opens on the next poll.
    EXIT_PENDING still retries until the same position fills.
    """
    if result is None:
        return True
    status = str(result.get("status") or "").strip()
    if status in _COMMITTED_CLOSE_STATUSES:
        return True
    if status.startswith("EXIT_PENDING"):
        return False
    # Permanent rejects (bad command, ignored) must not spin the cursor.
    return bool(status)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def later_iso(*values: str | None) -> str | None:
    """Return the latest parseable UTC timestamp among *values*."""
    best_text: str | None = None
    best_ts: datetime | None = None
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best_text = text
    return best_text

def _consumer_serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._consumer_lock:
            return method(self, *args, **kwargs)
    return invoke


class S41CommandConsumer:
    """Apply OPEN_*/CLOSE from the append-only command bus into LIVE1B books."""

    def __init__(
        self,
        engine: Any,
        *,
        checkpoint_path: Path,
        consume_after: str | None,
        bus: CommandBus | None = None,
        paper_trend_integration: Any = None,
    ) -> None:
        # Optional, explicitly bound PAPER reader; absent preserves production deny.
        inherited = getattr(engine, '_paper_trend_integration', None)
        self.paper_trend_integration = paper_trend_integration or inherited
        if paper_trend_integration is not None:
            from btc_ml.trend.context_trend_integration import ContextTrendIntegration
            if type(paper_trend_integration) is not ContextTrendIntegration:
                raise ValueError('PAPER_NATIVE_TREND_INTEGRATION_REQUIRED')
            if inherited is not None and inherited is not paper_trend_integration:
                raise ValueError('PAPER_TREND_ATTACHMENT_CONFLICT')
            engine._paper_trend_integration = paper_trend_integration
        self._consumer_lock = threading.RLock()
        self.engine = engine
        self.checkpoint_path = Path(checkpoint_path)
        self.consume_after = consume_after
        self.bus = bus or CommandBus(CommandBusPaths.production())
        self.engine._s41_bus=self.bus
        self._state = self._load()
        self.quarantine_path = self.checkpoint_path.with_name("s41_recovery_open_barrier.json")
        try:
            self._quarantine = json.loads(self.quarantine_path.read_text())
            if (self._quarantine.get("schema_version") != "s41_recovery_open_barrier_v1"
                    or self._quarantine.get("paper_epoch_id") != self.engine.epoch.paper_epoch_id
                    or not self._quarantine.get("cutoff")):
                raise ValueError("invalid recovery barrier")
        except FileNotFoundError:
            self._quarantine = {}


    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                ids = payload.get("processed_command_ids") or []
                return {
                    "processed_command_ids": [str(x) for x in ids if str(x).strip()],
                    "consume_after": later_iso(payload.get("consume_after"), self.consume_after) or self.consume_after,
                    "updated_at": payload.get("updated_at"),
                }
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "processed_command_ids": [],
            "consume_after": self.consume_after,
            "updated_at": None,
        }

    def _save(self) -> None:
        # Actual cursor mutations are only the durable ACK owner's responsibility.
        from .unified_financial_authority import check_locked
        with self.engine.books.exclusive():
            check_locked(self.engine.books.root.parent,self.engine.epoch.paper_epoch_id)
            self._state=self._load()

    def _mark(self, command_id: str) -> None:
        ids = list(self._state.get("processed_command_ids") or [])
        if command_id not in ids:
            ids.append(command_id)
        self._state["processed_command_ids"] = ids

    def _record_close_result(self, command: dict[str, Any], result: dict[str, Any]) -> None:
        # Terminal CLOSE outcomes belong to execution diagnostics, not fills.
        import os
        path = self.checkpoint_path.with_name("s41_close_results.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        command_id = str(command["command_id"])
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if json.loads(line).get("command_id") == command_id:
                        return
        record = {"command_id": command_id, "timeframe": command.get("timeframe"),
                  "result": result, "recorded_at": _utc_iso(), "schema_version": "s41_close_result_v1"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _record_open_rejection(self, command_id: str, timeframe: str, reason: str) -> None:
        import os
        path = self.checkpoint_path.with_name("s41_command_rejections.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    old = json.loads(line)
                    if old.get("command_id") == command_id and old.get("reason") == reason:
                        return
        record = {"command_id": command_id, "timeframe": timeframe,
                  "reason": reason, "rejected_at": _utc_iso(),
                  "schema_version": "s41_command_rejection_v1"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @_consumer_serialized
    def quarantine_recovery_backlog(self) -> dict[str, Any]:
        """Fence historical OPEN only. CLOSE remains on the original path.

        The durable cutoff also blocks an old decision appended after this
        snapshot. It is never inferred from a cursor or advanced by skipping
        market data. The coordinator must call this before admitting entries.
        """
        from .quarantine_barrier import quarantine
        return quarantine(self)

    def _open_block_reason(self, command: dict[str, Any]) -> str | None:
        """Enforce existing command TTL/identity; never replay gap-period entries."""
        from datetime import datetime, timezone
        import math
        import pandas as pd

        from .quarantine_barrier import read_current
        self._quarantine=read_current(self.engine.books)
        if self._quarantine:
            if self._quarantine.get("status") != "COMPLETED":
                return "ENTRY_BLOCKED_RECOVERY_BARRIER_INCOMPLETE"
            command_stamp = pd.to_datetime(command.get("evaluation_timestamp"), utc=True, errors="coerce")
            cutoff = pd.to_datetime(self._quarantine.get("cutoff"), utc=True, errors="coerce")
            if pd.isna(cutoff):
                raise RuntimeError("RECOVERY_BARRIER_INVALID_CUTOFF")
            if not pd.isna(command_stamp) and command_stamp <= cutoff:
                return "ENTRY_BLOCKED_RECOVERY_BARRIER"
        market = getattr(self.engine, "execution_market", None)
        state = getattr(market, "state", None)
        if bool(getattr(state, "unresolved_gap", False)):
            return "ENTRY_BLOCKED_RECOVERY_COMMAND"
        stamp = pd.to_datetime(command.get("evaluation_timestamp"), utc=True, errors="coerce")
        try:
            ttl = float(command.get("command_ttl_seconds"))
        except (TypeError, ValueError):
            return "ENTRY_BLOCKED_INVALID_COMMAND_TTL"
        if pd.isna(stamp) or not math.isfinite(ttl) or ttl <= 0:
            return "ENTRY_BLOCKED_INVALID_COMMAND_TTL"
        age = (pd.Timestamp(datetime.now(timezone.utc)) - stamp).total_seconds()
        if age < 0:
            return "ENTRY_BLOCKED_COMMAND_NOT_YET_AVAILABLE"
        if age > ttl:
            return "ENTRY_BLOCKED_EXPIRED_COMMAND"
        try:
            latest = json.loads(self.bus.paths.latest.read_text(encoding="utf-8"))
            current = latest["commands"][str(command.get("timeframe") or "").upper()]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return "ENTRY_BLOCKED_CURRENT_COMMAND_UNAVAILABLE"
        published_at = pd.to_datetime(latest.get("evaluation_timestamp"), utc=True, errors="coerce")
        if pd.isna(published_at) or published_at < stamp:
            return "ENTRY_BLOCKED_CURRENT_COMMAND_NOT_YET_PUBLISHED"
        if (str(current.get("command_id")) != str(command.get("command_id"))
                or current.get("intent") != command.get("intent")
                or not current.get("action_allowed")):
            return "ENTRY_BLOCKED_SUPERSEDED_COMMAND"
        episode = command.get("lifecycle_episode_id")
        if str(current.get("lifecycle_episode_id")) != str(episode):
            return "ENTRY_BLOCKED_COMMAND_EPISODE_MISMATCH"
        decision_id = command.get("decision_id")
        if decision_id is not None and not pd.isna(decision_id):
            if str(current.get("decision_id")) != str(decision_id):
                return "ENTRY_BLOCKED_COMMAND_DECISION_MISMATCH"
        if getattr(self.engine, "fresh_live_contract_required", False):
            from ..sleeve_risk_contract import validate
            reason = validate(command, self.engine.epoch.paper_epoch_id,
                self.engine.sleeves.get(str(command.get("timeframe", "")).upper()).risk_pct_per_trade)
            if reason:
                return reason
        from btc_ml.trend.entry_kill_switch import EntryOnlyKillSwitch
        if getattr(self, '_paper_reconcile_error', None):
            return 'ENTRY_BLOCKED_PAPER_RECONCILIATION_' + self._paper_reconcile_error
        if self.paper_trend_integration is not None:
            try:
                permission = self.paper_trend_integration.paper_permission(str(command['timeframe']), datetime.now(timezone.utc).isoformat())
                if Path(permission['financial_root']).resolve() != self.engine.epoch_root.resolve():
                    return 'ENTRY_BLOCKED_PAPER_FINANCIAL_ROOT_MISMATCH'
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                return 'ENTRY_BLOCKED_PAPER_' + str(exc)
        return EntryOnlyKillSwitch(paper_integration=self.paper_trend_integration).command_admission_reason(command)

    def _reconcile_paper(self) -> None:
        # Missing Trend evidence must block new entries, never protective exits.
        self._paper_reconcile_error = None
        if self.paper_trend_integration is None:
            return
        try:
            self.paper_trend_integration.reconcile_paper_execution(self.engine, self.bus.frame().to_dict('records'))
        except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
            self._paper_reconcile_error = str(exc)
            import logging
            logging.getLogger(__name__).error('PAPER R2 reconciliation unavailable; OPEN blocked: %s', exc)

    @_consumer_serialized
    def poll(self, *, now: str | None = None) -> list[dict[str, Any]]:
        self._reconcile_paper()
        processed = {str(x) for x in (self._state.get("processed_command_ids") or [])}
        after = self._state.get("consume_after") or self.consume_after
        actions: list[dict[str, Any]] = []
        dirty = False
        clock = now or _utc_iso()
        for tf in self.engine.cfg.timeframes:
            pending = self.bus.pending_for_timeframe(
                tf,
                processed_command_ids=processed,
                after_evaluation_timestamp=after,
            )
            pending.sort(key=lambda c: (0 if str(c.get("intent") or "").upper() == "CLOSE" else 1,
                                        str(c.get("command_id") or "")))
            for command in pending:
                command_id = str(command.get("command_id") or "").strip()
                if not command_id:
                    continue
                from .unified_financial_authority import already_processed
                if already_processed(self,command):
                    processed.add(command_id)
                    continue
                intent = str(command.get("intent") or "").upper()
                allowed = bool(command.get("action_allowed"))
                result: dict[str, Any] | None = None
                if intent in {"OPEN_LONG", "OPEN_SHORT"} and allowed:
                    block_reason = self._open_block_reason(command)
                    if block_reason is None and closed_bar_superseded(
                        timeframe=str(command.get("timeframe") or tf),
                        source_bar_close=command.get("source_bar_close"), now=clock,
                    ):
                        block_reason = f"ENTRY_BLOCKED_{STALE_CLOSED_BAR_SUPERSEDED}"
                    if block_reason in {"ENTRY_BLOCKED_CURRENT_COMMAND_UNAVAILABLE",
                                         "ENTRY_BLOCKED_CURRENT_COMMAND_NOT_YET_PUBLISHED"}:
                        continue  # Atomic bus/snapshot publication may still be in flight.
                    if block_reason:
                        self._record_open_rejection(command_id, tf, block_reason)
                        actions.append({"status": block_reason, "command_id": command_id,
                                        "timeframe": tf, "intent": intent})
                        from .unified_financial_authority import confirm_consumer
                        confirm_consumer(self,command,{"status":block_reason,"command_id":command_id,"timeframe":tf},completion_source="S41_ORIGINAL_PREFLIGHT_REJECTION")
                        processed.add(command_id)
                        dirty = True
                        continue
                    if not self.engine.execution_market_ready_for_entry():
                        continue
                    local_bbo, _reason, _age, _domain = self.engine.bbo.resolve_live_local_entry_bbo(
                        max_age_ms=self.engine.cfg.max_bbo_age_ms,
                    )
                    if local_bbo is None:
                        continue
                    if self.paper_trend_integration is not None:
                        try:
                            self.paper_trend_integration.reserve_paper_command(command)
                        except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
                            # Failed CAS/reservation leaves this OPEN unexecuted.
                            # Other timeframes' protective exits still proceed.
                            actions.append({'status':'ENTRY_BLOCKED_PAPER_RESERVATION',
                                'reason':str(exc),'command_id':command_id,'timeframe':tf})
                            continue
                    result = self.engine.apply_s41_manager_command(command)
                    if str((result or {}).get("status") or "") in _TRANSIENT_OPEN_BLOCKS:
                        continue
                elif intent == "CLOSE" and allowed:
                    result = self.engine.apply_s41_manager_command(command)
                    if not close_command_committed(result):
                        if result is not None:
                            actions.append(result)
                        continue
                    if result is not None:
                        self._record_close_result(command, result)
                else:
                    result = {
                        "status": "IGNORED",
                        "intent": intent,
                        "command_id": command_id,
                        "timeframe": tf,
                    }
                self._reconcile_paper()
                if result is not None:
                    actions.append(result)
                from .unified_financial_authority import confirm_consumer
                confirm_consumer(self,command,result)
                processed.add(command_id)
                dirty = True
                self._save()
        if dirty:
            self._save()
        return actions
