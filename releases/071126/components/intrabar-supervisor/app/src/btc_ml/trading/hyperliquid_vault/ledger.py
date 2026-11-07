"""Append-only vault ledger + local per-timeframe position state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.trading.trader_book import atomic_write_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class VaultLedger:
    TABLES = ("commands", "orders", "fills", "positions", "events", "pairs")

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for name in self.TABLES:
            (self.root / f"{name}.jsonl").touch(exist_ok=True)
        self.state_path = self.root / "local_state.json"

    def _path(self, table: str) -> Path:
        if table not in self.TABLES:
            raise ValueError(table)
        return self.root / f"{table}.jsonl"

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload.setdefault("ts", utc_now())
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with self._path(table).open("a", encoding="utf-8") as fh:
            fh.write(line)
        return payload

    def read_all(self, table: str) -> list[dict[str, Any]]:
        path = self._path(table)
        out: list[dict[str, Any]] = []
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"positions": {}, "leverage_set": False, "kill": None}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"positions": {}}
        except json.JSONDecodeError:
            return {"positions": {}, "leverage_set": False, "kill": None}

    def save_state(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.state_path, payload)

    def open_positions(self) -> dict[str, dict[str, Any]]:
        state = self.load_state()
        positions = state.get("positions") or {}
        return {str(tf): dict(row) for tf, row in positions.items() if str(row.get("status") or "") == "OPEN"}
