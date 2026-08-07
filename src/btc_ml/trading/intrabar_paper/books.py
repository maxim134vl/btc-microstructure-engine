"""JSONL books for LIVE1B epoch-isolated paper trading."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .performance_eligibility import is_void_position_row


class EpochBooks:
    """Append-only JSONL books stamped with paper_epoch_id."""

    TABLES = (
        "signals",
        "commands",
        "orders",
        "fills",
        "trades",
        "positions",
        "equity_snapshots",
        "metrics",
        "blocked",
    )

    def __init__(self, root: Path, *, paper_epoch_id: str) -> None:
        self.root = Path(root)
        self.paper_epoch_id = paper_epoch_id
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        for name in self.TABLES:
            (self.root / f"{name}.jsonl").touch(exist_ok=True)

    def _path(self, table: str) -> Path:
        if table not in self.TABLES:
            raise ValueError(table)
        return self.root / f"{table}.jsonl"

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["paper_epoch_id"] = self.paper_epoch_id
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with self._lock:
            with self._path(table).open("a", encoding="utf-8") as fh:
                fh.write(line)
        return payload

    def read_all(self, table: str) -> list[dict[str, Any]]:
        path = self._path(table)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def latest_positions(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.read_all("positions"):
            pid = str(row.get("position_id") or "")
            if pid:
                latest[pid] = row
        return latest

    def open_positions(self) -> list[dict[str, Any]]:
        """Latest status per position_id; return only still-OPEN."""
        return [
            row
            for row in self.latest_positions().values()
            if str(row.get("status") or "").upper() == "OPEN" and not is_void_position_row(row)
        ]

    def closed_trades(self) -> list[dict[str, Any]]:
        from .performance_eligibility import counts_toward_strategy_performance

        return [row for row in self.read_all("trades") if counts_toward_strategy_performance(row)]

    def count(self, table: str) -> int:
        return len(self.read_all(table))
