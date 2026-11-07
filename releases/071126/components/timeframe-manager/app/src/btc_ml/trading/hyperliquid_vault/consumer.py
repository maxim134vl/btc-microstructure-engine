"""Consume S4.1 command-bus rows into the Hyperliquid vault executor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths

from .executor import VaultExecutor
from .ledger import utc_now


class VaultCommandConsumer:
    def __init__(
        self,
        executor: VaultExecutor,
        *,
        checkpoint_path: Path,
        consume_after: str | None,
        bus: CommandBus | None = None,
    ) -> None:
        self.executor = executor
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
        return {"processed_command_ids": [], "consume_after": self.consume_after, "updated_at": None}

    def _save(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        ids = list(dict.fromkeys(self._state.get("processed_command_ids") or []))
        if len(ids) > 5000:
            ids = ids[-5000:]
        payload = {
            "processed_command_ids": ids,
            "consume_after": self._state.get("consume_after") or self.consume_after,
            "updated_at": utc_now(),
            "schema_version": "s41_hl_vault_command_cursor_v1",
        }
        tmp = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.checkpoint_path)
        self._state = payload

    def poll(self) -> list[dict[str, Any]]:
        processed = {str(x) for x in (self._state.get("processed_command_ids") or [])}
        after = self._state.get("consume_after") or self.consume_after
        actions: list[dict[str, Any]] = []
        dirty = False
        for tf in self.executor.cfg.timeframes:
            pending = self.bus.pending_for_timeframe(
                tf,
                processed_command_ids=processed,
                after_evaluation_timestamp=after,
            )
            for command in pending:
                command_id = str(command.get("command_id") or "").strip()
                if not command_id:
                    continue
                result = self.executor.apply_command(command)
                actions.append(result)
                if str((result or {}).get("status") or "") in {"EXCHANGE_ERROR"}:
                    continue
                self._state.setdefault("processed_command_ids", []).append(command_id)
                processed.add(command_id)
                dirty = True
        if dirty:
            self._save()
        return actions
