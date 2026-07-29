"""Append-only JSONL / JSON store confined to the shadow directory."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .paths import assert_shadow_write_path, shadow_root


class ShadowStore:
    TABLES = (
        "candidate_snapshots",
        "cluster_snapshots",
        "policy_decisions",
        "virtual_positions",
        "virtual_trades",
        "quality_outcomes",
    )

    def __init__(self, root: Path | None = None, *, repo: Path | None = None) -> None:
        self.repo = repo
        self.root = Path(root) if root is not None else shadow_root(repo)
        assert_shadow_write_path(self.root, repo=repo)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        for name in self.TABLES:
            (self.root / f"{name}.jsonl").touch(exist_ok=True)
        for name in ("policy_sleeves.json", "policy_portfolios.json", "checkpoint.json", "health.json", "policy_manifest.json"):
            p = self.root / name
            if not p.exists():
                p.write_text("{}\n" if name.endswith(".json") else "{}\n", encoding="utf-8")

    def _jsonl(self, table: str) -> Path:
        if table not in self.TABLES:
            raise ValueError(table)
        return assert_shadow_write_path(self.root / f"{table}.jsonl", repo=self.repo)

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        path = self._jsonl(table)
        line = json.dumps(row, sort_keys=True, default=str) + "\n"
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        return row

    def read_all(self, table: str) -> list[dict[str, Any]]:
        path = self._jsonl(table)
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def write_json(self, name: str, payload: dict[str, Any]) -> Path:
        path = assert_shadow_write_path(self.root / name, repo=self.repo)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    def read_json(self, name: str) -> dict[str, Any]:
        path = assert_shadow_write_path(self.root / name, repo=self.repo)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}
