"""JSONL books for LIVE1B epoch-isolated paper trading."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from typing import Iterator
import json
import threading
from .execution_commit import CURRENT, EXCLUSIVE_ROOT, ExecutionCommit
import os
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
        from .unified_financial_authority import preconstructor
        preconstructor(self.root.parent,paper_epoch_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._exclusive_lock = threading.RLock()
        self._exclusive_depth = 0
        self._exclusive_owner = None
        for name in self.TABLES:
            path = self.root / f"{name}.jsonl"
            if not path.exists():
                if (self.root.parent / "execution_commits_v1/head.json").exists():
                    raise RuntimeError("COMMITTED_BOOK_MISSING")
                path.touch(exist_ok=False)
        self.commit = ExecutionCommit(self)
        with self.exclusive():
            from .unified_financial_authority import initialize_or_validate
            initialize_or_validate(self)

    @contextmanager
    def exclusive(self, *, blocking: bool = True) -> Iterator[None]:
        """Cross-process lock so two paper managers cannot enter the same TF."""
        with self._exclusive_lock:
            if self._exclusive_depth:
                if not self.owns_exclusive():
                    raise RuntimeError("FINANCIAL_EX_OWNER_CONFLICT")
                self._exclusive_depth += 1
                try: yield
                finally: self._exclusive_depth -= 1
                return
            lock_path = self.root / ".writer.lock"
            with lock_path.open("a+") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                from .financial_authority_runtime import activate
                activate(self.root.parent)
                self._exclusive_depth = 1
                self._exclusive_owner = threading.get_ident()
                ownership_token=EXCLUSIVE_ROOT.set((self.root.parent.resolve(),os.getpid(),threading.get_ident()))
                try: yield
                finally:
                    EXCLUSIVE_ROOT.reset(ownership_token)
                    self._exclusive_depth = 0
                    self._exclusive_owner = None
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def owns_exclusive(self):
        return (self._exclusive_depth > 0
                and self._exclusive_owner == threading.get_ident()
                and EXCLUSIVE_ROOT.get() == (self.root.parent.resolve(), os.getpid(), threading.get_ident()))

    def _path(self, table: str) -> Path:
        if table not in self.TABLES:
            raise ValueError(table)
        return self.root / f"{table}.jsonl"

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["paper_epoch_id"] = self.paper_epoch_id
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        active = CURRENT.get()
        if active is not None and active.books is self:
            if not self.owns_exclusive():
                raise RuntimeError("FINANCIAL_WRITER_REQUIRES_EX")
            self._path(table)
            active.rows.setdefault(table, []).append(line)
            return payload
        raise RuntimeError("FINANCIAL_BOOK_REQUIRES_COMMIT")

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
        active = CURRENT.get()
        if active is not None and active.books is self:
            out.extend(json.loads(line) for line in active.rows.get(table, []))
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
        from .performance_eligibility import counts_toward_strategy_performance, filter_superseded_trades

        rows = filter_superseded_trades(self.read_all("trades"))
        return [row for row in rows if counts_toward_strategy_performance(row)]

    def count(self, table: str) -> int:
        return len(self.read_all(table))
