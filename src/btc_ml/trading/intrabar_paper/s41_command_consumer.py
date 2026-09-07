"""Consume S4.1 command-bus rows into the LIVE1B paper engine (hybrid mode)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths


_TRANSIENT_OPEN_BLOCKS = frozenset(
    {
        "ENTRY_BLOCKED_NO_CAUSAL_BBO",
        "ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY",
    }
)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class S41CommandConsumer:
    """Apply OPEN_*/CLOSE from the append-only command bus into LIVE1B books."""

    def __init__(
        self,
        engine: Any,
        *,
        checkpoint_path: Path,
        consume_after: str | None,
        bus: CommandBus | None = None,
    ) -> None:
        self.engine = engine
        self.checkpoint_path = Path(checkpoint_path)
        self.consume_after = consume_after
        self.bus = bus or CommandBus(CommandBusPaths.production())
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                ids = payload.get("processed_command_ids") or []
                return {
                    "processed_command_ids": [str(x) for x in ids if str(x).strip()],
                    "consume_after": payload.get("consume_after") or self.consume_after,
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
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        ids = list(dict.fromkeys(self._state.get("processed_command_ids") or []))
        # Bound growth: keep last 5000 ids
        if len(ids) > 5000:
            ids = ids[-5000:]
        payload = {
            "processed_command_ids": ids,
            "consume_after": self._state.get("consume_after") or self.consume_after,
            "updated_at": _utc_iso(),
            "schema_version": "s41_live1b_command_cursor_v1",
        }
        tmp = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.checkpoint_path)
        self._state = payload

    def _mark(self, command_id: str) -> None:
        ids = list(self._state.get("processed_command_ids") or [])
        if command_id not in ids:
            ids.append(command_id)
        self._state["processed_command_ids"] = ids

    def poll(self) -> list[dict[str, Any]]:
        processed = {str(x) for x in (self._state.get("processed_command_ids") or [])}
        after = self._state.get("consume_after") or self.consume_after
        actions: list[dict[str, Any]] = []
        for tf in self.engine.cfg.timeframes:
            pending = self.bus.pending_for_timeframe(
                tf,
                processed_command_ids=processed,
                after_evaluation_timestamp=after,
            )
            for command in pending:
                command_id = str(command.get("command_id") or "").strip()
                if not command_id:
                    continue
                intent = str(command.get("intent") or "").upper()
                allowed = bool(command.get("action_allowed"))
                result: dict[str, Any] | None = None
                if intent in {"OPEN_LONG", "OPEN_SHORT"} and allowed:
                    if not self.engine.execution_market_ready_for_entry():
                        continue
                    local_bbo, _reason, _age, _domain = self.engine.bbo.resolve_live_local_entry_bbo(
                        max_age_ms=self.engine.cfg.max_bbo_age_ms,
                    )
                    if local_bbo is None:
                        continue
                    result = self.engine.apply_s41_manager_command(command)
                    if str((result or {}).get("status") or "") in _TRANSIENT_OPEN_BLOCKS:
                        continue
                elif intent == "CLOSE" and allowed:
                    result = self.engine.apply_s41_manager_command(command)
                else:
                    result = {
                        "status": "IGNORED",
                        "intent": intent,
                        "command_id": command_id,
                        "timeframe": tf,
                    }
                if result is not None:
                    actions.append(result)
                self._mark(command_id)
                processed.add(command_id)
                self._save()
        return actions
