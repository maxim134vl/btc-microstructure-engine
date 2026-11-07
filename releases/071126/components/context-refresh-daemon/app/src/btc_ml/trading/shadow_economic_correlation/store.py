"""Append-only JSONL / JSON store confined to the shadow directory."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from btc_ml.runtime.io_cache import IoObserveStats, MtimeJsonlCache

from .paths import assert_shadow_write_path, shadow_root


class ShadowStore:
    INFLIGHT_NAME = "inflight_transaction.json"

    TABLES = (
        "candidate_snapshots",
        "cluster_snapshots",
        "policy_decisions",
        "virtual_positions",
        "virtual_trades",
        "quality_outcomes",
        "candidate_feature_enrichments",
    )

    def __init__(
        self,
        root: Path | None = None,
        *,
        repo: Path | None = None,
        jsonl_cache: MtimeJsonlCache | None = None,
        observe: IoObserveStats | None = None,
    ) -> None:
        self.repo = repo
        self.root = (
            Path(root)
            if root is not None
            else shadow_root(repo)
        )
        assert_shadow_write_path(
            self.root,
            repo=repo,
        )
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._lock = threading.Lock()
        self._lineage: dict[str, Any] = {}
        self.observe = observe or IoObserveStats()
        self.jsonl_cache = jsonl_cache or MtimeJsonlCache(stats=self.observe)

        for name in self.TABLES:
            (
                self.root
                / f"{name}.jsonl"
            ).touch(exist_ok=True)

        for name in (
            "policy_sleeves.json",
            "policy_portfolios.json",
            "checkpoint.json",
            "health.json",
            "policy_manifest.json",
        ):
            path = self.root / name

            if not path.exists():
                path.write_text(
                    "{}\n",
                    encoding="utf-8",
                )

    def set_lineage(
        self,
        lineage: dict[str, Any],
    ) -> None:
        self._lineage = dict(lineage)

    def _jsonl(
        self,
        table: str,
    ) -> Path:
        if table not in self.TABLES:
            raise ValueError(table)

        return assert_shadow_write_path(
            self.root / f"{table}.jsonl",
            repo=self.repo,
        )

    def append(
        self,
        table: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        path = self._jsonl(table)
        payload = dict(row)

        for key, value in self._lineage.items():
            existing = payload.get(key)

            if existing not in (
                None,
                "",
                value,
            ):
                raise RuntimeError(
                    "SHADOW_LINEAGE_CONFLICT:"
                    f"{table}:{key}:"
                    f"{existing}!={value}"
                )

            payload[key] = value

        line = (
            json.dumps(
                payload,
                sort_keys=True,
                default=str,
            )
            + "\n"
        )

        with self._lock:
            with path.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(line)
            self.jsonl_cache.invalidate(path)

        return payload

    def read_all(
        self,
        table: str,
    ) -> list[dict[str, Any]]:
        return self.jsonl_cache.read_jsonl(self._jsonl(table))

    def write_json(
        self,
        name: str,
        payload: dict[str, Any],
    ) -> Path:
        path = assert_shadow_write_path(
            self.root / name,
            repo=self.repo,
        )
        tmp = path.with_name(
            f"{path.name}."
            f"{os.getpid()}."
            f"{time.time_ns()}.tmp"
        )
        data = (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n"
        )

        with self._lock:
            tmp.write_text(
                data,
                encoding="utf-8",
            )
            os.replace(tmp, path)

        return path

    def read_json(
        self,
        name: str,
    ) -> dict[str, Any]:
        path = assert_shadow_write_path(
            self.root / name,
            repo=self.repo,
        )

        if not path.exists():
            return {}

        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except json.JSONDecodeError:
            return {}

        return (
            raw
            if isinstance(raw, dict)
            else {}
        )

    def table_sizes(
        self,
    ) -> dict[str, int]:
        return {
            table: self._jsonl(
                table
            ).stat().st_size
            for table in self.TABLES
        }

    def _inflight_path(
        self,
    ) -> Path:
        return assert_shadow_write_path(
            self.root / self.INFLIGHT_NAME,
            repo=self.repo,
        )

    def read_inflight(
        self,
    ) -> dict[str, Any]:
        path = self._inflight_path()

        if not path.exists():
            return {}

        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            raise RuntimeError(
                "INVALID_INFLIGHT_TRANSACTION:"
                f"{exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise RuntimeError(
                "INVALID_INFLIGHT_TRANSACTION:"
                "NOT_OBJECT"
            )

        required = (
            "kind",
            "key",
            "base_generation",
            "table_sizes",
            "owner_pid",
        )
        missing = [
            name
            for name in required
            if raw.get(name) is None
        ]

        if missing:
            raise RuntimeError(
                "INVALID_INFLIGHT_TRANSACTION:"
                "MISSING:"
                + ",".join(missing)
            )

        return raw

    @staticmethod
    def _pid_is_alive(
        pid: int,
    ) -> bool:
        if int(pid) <= 0:
            return False

        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

        return True

    def begin_transaction(
        self,
        *,
        kind: str,
        key: str,
        base_generation: int,
    ) -> dict[str, Any]:
        marker = {
            "kind": str(kind),
            "key": str(key),
            "base_generation": int(
                base_generation
            ),
            "table_sizes": (
                self.table_sizes()
            ),
            "owner_pid": os.getpid(),
            "started_at_ns": time.time_ns(),
        }

        path = self._inflight_path()
        data = (
            json.dumps(
                marker,
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n"
        )

        with self._lock:
            try:
                descriptor = os.open(
                    path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as exc:
                existing = (
                    self.read_inflight()
                )
                raise RuntimeError(
                    "SHADOW_TRANSACTION_"
                    "ALREADY_ACTIVE:"
                    f"{existing.get('kind')}:"
                    f"{existing.get('key')}:"
                    "pid="
                    f"{existing.get('owner_pid')}"
                ) from exc

            try:
                with os.fdopen(
                    descriptor,
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(
                        handle.fileno()
                    )
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

                path.unlink(
                    missing_ok=True
                )
                raise

        return marker

    def clear_inflight(
        self,
    ) -> None:
        path = self._inflight_path()

        with self._lock:
            path.unlink(
                missing_ok=True
            )

    def rollback_inflight(
        self,
    ) -> dict[str, Any]:
        marker = self.read_inflight()

        if not marker:
            return {
                "status":
                "NO_INFLIGHT_TRANSACTION"
            }

        sizes = marker.get(
            "table_sizes"
        )

        if not isinstance(sizes, dict):
            raise RuntimeError(
                "INVALID_INFLIGHT_TABLE_SIZES"
            )

        with self._lock:
            for table in self.TABLES:
                target = sizes.get(table)

                if target is None:
                    raise RuntimeError(
                        "INFLIGHT_TABLE_SIZE_"
                        f"MISSING:{table}"
                    )

                target_i = int(target)

                if target_i < 0:
                    raise RuntimeError(
                        "INFLIGHT_TABLE_SIZE_"
                        f"INVALID:{table}:"
                        f"{target_i}"
                    )

                path = self._jsonl(table)
                current = path.stat().st_size

                if current < target_i:
                    raise RuntimeError(
                        "INFLIGHT_ROLLBACK_"
                        f"UNDERFLOW:{table}:"
                        f"{current}<{target_i}"
                    )

                with path.open(
                    "r+b"
                ) as handle:
                    handle.truncate(
                        target_i
                    )
                self.jsonl_cache.invalidate(path)

            self._inflight_path().unlink(
                missing_ok=True
            )

        return {
            "status": "ROLLED_BACK",
            "kind": marker.get("kind"),
            "key": marker.get("key"),
        }

    def recover_inflight(
        self,
        *,
        committed_generation: int,
        committed_candidates: set[str],
        committed_closes: set[str],
    ) -> dict[str, Any]:
        marker = self.read_inflight()

        if not marker:
            return {
                "status":
                "NO_INFLIGHT_TRANSACTION"
            }

        kind = str(
            marker.get("kind") or ""
        )
        key = str(
            marker.get("key") or ""
        )
        owner_pid = int(
            marker.get("owner_pid") or 0
        )
        base_generation = int(
            marker.get(
                "base_generation"
            )
            or 0
        )

        committed_keys = (
            committed_candidates
            if kind == "candidate"
            else committed_closes
            if kind == "close"
            else set()
        )

        committed = (
            int(committed_generation)
            > base_generation
            and key in committed_keys
        )

        if committed:
            self.clear_inflight()

            return {
                "status":
                "COMMITTED_MARKER_CLEARED",
                "kind": kind,
                "key": key,
                "owner_pid": owner_pid,
            }

        if self._pid_is_alive(
            owner_pid
        ):
            raise RuntimeError(
                "SHADOW_TRANSACTION_"
                "OWNER_ALIVE:"
                f"{kind}:{key}:"
                f"pid={owner_pid}"
            )

        return self.rollback_inflight()
