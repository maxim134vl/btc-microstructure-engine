"""Runtime dataset ownership and metadata (Patch 1).

Operational metadata only. Must not participate in trading decisions,
auction/context classification, action_allowed, sizing, or execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

METADATA_VERSION = "runtime_dataset_metadata_v1"
REGISTRY_VERSION = "runtime_dataset_ownership_v1"
DEFAULT_REGISTRY_REL = "config/runtime_dataset_ownership.json"
DEFAULT_STATUS_REL = "data/runtime/runtime_dataset_status.json"

SEMANTIC_TYPES = frozenset(
    {
        "MARKET_FEED",
        "PER_BAR_STATE",
        "EVENT_LOG",
        "STATE_SNAPSHOT",
        "EPISODE_MEMORY",
        "DECISION_LOG",
        "PAPER_SIGNAL_LOG",
        "PAPER_ORDER_LOG",
        "PAPER_TRADE_LEDGER",
        "READ_MODEL",
    }
)

OPERATIONAL_STATUSES = frozenset(
    {
        "ACTIVE",
        "ACTIVE_STALE",
        "BROKEN",
        "EVENT_SPARSE_BY_DESIGN",
        "INACTIVE_DEPRECATED",
        "RESEARCH_ONLY",
        "PHANTOM",
        "UNKNOWN",
    }
)

HEALTH_STATES = frozenset(
    {
        "FRESH",
        "PIPELINE_PENDING",
        "STALE",
        "BROKEN",
        "EVENT_SPARSE_BY_DESIGN",
        "INACTIVE_DEPRECATED",
        "RESEARCH_ONLY",
        "PHANTOM",
        "MISSING_EXPECTED",
        "DEAD_WRITER",
        "UNKNOWN",
        "UNKNOWN_METADATA",
        "HEALTHY_WITH_UNSUPPORTED_TIMEFRAME",
        "DEGRADED",
    }
)

REQUIRED_DATASET_FIELDS = (
    "dataset_id",
    "logical_state",
    "dataset_path",
    "authority_plane",
    "authority_role",
    "canonical_writer",
    "writer_entrypoint",
    "semantic_type",
    "write_mode",
    "expected_cadence_seconds",
    "source_timestamp_field",
    "evaluated_timestamp_field",
    "event_sparse",
    "event_sparse_inheritance_mode",
    "maximum_inheritance_age_seconds",
    "freshness_budget_seconds",
    "atomic_write_required",
    "builder_version_source",
    "allowed_consumers",
    "operational_status",
    "legacy_names",
    "notes",
)


class DatasetOwnershipError(ValueError):
    """Invalid ownership registry."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_ts(value: Any) -> datetime | None:
    """Normalize timestamps for metadata comparison only (never mutates parquet)."""
    if value is None:
        return None
    try:
        import pandas as pd

        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts).to_pydatetime()
    except Exception:
        return None


def ts_to_iso(value: Any) -> str | None:
    dt = normalize_ts(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_hash_from_columns(columns: list[str]) -> str:
    payload = json.dumps(list(columns), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def meta_path_for(dataset_path: Path) -> Path:
    return Path(str(dataset_path) + ".meta.json")


def load_dataset_ownership_registry(
    path: str | Path | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    reg_path = Path(path) if path else root / DEFAULT_REGISTRY_REL
    if not reg_path.is_absolute():
        reg_path = root / reg_path
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    validate_dataset_ownership_registry(payload)
    return payload


def validate_dataset_ownership_registry(registry: dict[str, Any]) -> None:
    if not isinstance(registry, dict):
        raise DatasetOwnershipError("registry must be an object")
    datasets = registry.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise DatasetOwnershipError("registry.datasets must be a non-empty list")

    ids: set[str] = set()
    path_owners: dict[str, str] = {}
    logical_paths: dict[str, list[str]] = {}

    for row in datasets:
        if not isinstance(row, dict):
            raise DatasetOwnershipError("dataset entry must be an object")
        for field in REQUIRED_DATASET_FIELDS:
            if field not in row:
                raise DatasetOwnershipError(f"missing field {field} on dataset entry")

        dataset_id = str(row["dataset_id"])
        if dataset_id in ids:
            raise DatasetOwnershipError(f"duplicate dataset_id: {dataset_id}")
        ids.add(dataset_id)

        path = str(row["dataset_path"])
        writer = str(row["canonical_writer"])
        if path in path_owners and path_owners[path] != writer:
            raise DatasetOwnershipError(
                f"two authoritative writers for {path}: {path_owners[path]} vs {writer}"
            )
        path_owners[path] = writer

        logical = str(row["logical_state"])
        logical_paths.setdefault(logical, []).append(path)

        semantic = str(row["semantic_type"])
        if semantic not in SEMANTIC_TYPES:
            raise DatasetOwnershipError(f"invalid semantic_type {semantic} for {dataset_id}")

        status = str(row["operational_status"])
        if status not in OPERATIONAL_STATUSES:
            raise DatasetOwnershipError(f"invalid operational_status {status} for {dataset_id}")

        if status in {"ACTIVE", "ACTIVE_STALE", "BROKEN", "EVENT_SPARSE_BY_DESIGN"}:
            if not writer or writer in {"NONE", "unknown"}:
                raise DatasetOwnershipError(f"ACTIVE-like dataset {dataset_id} missing writer")
            if row.get("freshness_budget_seconds") is None:
                raise DatasetOwnershipError(
                    f"ACTIVE-like dataset {dataset_id} missing freshness_budget_seconds"
                )
            if not row.get("source_timestamp_field") or not row.get("evaluated_timestamp_field"):
                raise DatasetOwnershipError(
                    f"ACTIVE-like dataset {dataset_id} missing timestamp fields"
                )
            role = str(row.get("authority_role") or "")
            if role in {"", "NONE"} and status != "PHANTOM":
                # allow READ_MODEL derived roles
                if str(row.get("authority_plane")) not in {
                    "decision_logger",
                    "visual_read_model",
                }:
                    raise DatasetOwnershipError(
                        f"active trading/context dataset {dataset_id} has authority_role NONE"
                    )

        if bool(row.get("event_sparse")) or semantic == "EVENT_LOG":
            if not row.get("event_sparse_inheritance_mode"):
                raise DatasetOwnershipError(
                    f"EVENT_LOG/event_sparse {dataset_id} missing inheritance mode"
                )
            if row.get("maximum_inheritance_age_seconds") is None:
                raise DatasetOwnershipError(
                    f"event-sparse {dataset_id} missing maximum_inheritance_age_seconds"
                )

        for consumer in row.get("allowed_consumers") or []:
            c = str(consumer)
            # production consumers must not treat research paths as canonical inputs
            if c.startswith("data/research/") and "paper_simulator/paper_" not in path:
                raise DatasetOwnershipError(
                    f"production consumer path {c} not allowed for {dataset_id}"
                )

    for logical, paths in logical_paths.items():
        unique = sorted(set(paths))
        if len(unique) > 1:
            # allow explicit multi-path only when marked
            marked = [
                d
                for d in datasets
                if d.get("logical_state") == logical and d.get("allow_duplicate_logical_paths")
            ]
            if not marked:
                raise DatasetOwnershipError(
                    f"logical_state {logical} maps to multiple paths without allow flag: {unique}"
                )


def _probe_parquet(path: Path, source_field: str, evaluated_field: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "row_count": None,
        "column_count": None,
        "schema_hash": None,
        "first_timestamp": None,
        "latest_timestamp": None,
        "source_market_timestamp": None,
        "evaluated_timestamp": None,
        "columns": [],
        "error": None,
    }
    if not path.exists():
        out["error"] = "missing"
        return out
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    cols = [str(c) for c in frame.columns]
    out["row_count"] = int(len(frame))
    out["column_count"] = int(len(cols))
    out["columns"] = cols
    out["schema_hash"] = schema_hash_from_columns(cols)

    def series_tip(field: str) -> tuple[Any, Any]:
        if field not in frame.columns or frame.empty:
            return None, None
        series = pd.to_datetime(frame[field], utc=True, errors="coerce")
        if not series.notna().any():
            return None, None
        return series.min(), series.max()

    first, latest = series_tip(source_field)
    out["first_timestamp"] = ts_to_iso(first)
    out["latest_timestamp"] = ts_to_iso(latest)
    out["source_market_timestamp"] = ts_to_iso(latest)
    if evaluated_field and evaluated_field in frame.columns:
        _, eval_latest = series_tip(evaluated_field)
        out["evaluated_timestamp"] = ts_to_iso(eval_latest)
    else:
        out["evaluated_timestamp"] = out["source_market_timestamp"]
    return out


def _probe_json_read_model(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "row_count": None,
        "column_count": None,
        "schema_hash": None,
        "first_timestamp": None,
        "latest_timestamp": None,
        "source_market_timestamp": None,
        "evaluated_timestamp": None,
        "columns": [],
        "error": None,
    }
    if not path.exists():
        out["error"] = "missing"
        return out
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    keys = sorted(payload.keys()) if isinstance(payload, dict) else ["_list"]
    out["column_count"] = len(keys)
    out["columns"] = keys
    out["schema_hash"] = schema_hash_from_columns(keys)
    tip = None
    if isinstance(payload, dict):
        for key in (
            "latest_evaluation_timestamp",
            "timestamp",
            "generated_at",
            "as_of",
            "latest_timestamp",
        ):
            if key in payload:
                tip = ts_to_iso(payload[key])
                if tip:
                    break
    mtime = (
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    out["source_market_timestamp"] = tip
    out["latest_timestamp"] = tip
    out["evaluated_timestamp"] = tip or mtime
    out["row_count"] = 1 if isinstance(payload, dict) else (
        len(payload) if isinstance(payload, list) else None
    )
    return out


def build_dataset_metadata(
    dataset_row: dict[str, Any],
    *,
    root: Path | None = None,
    writer_pid: int | None = None,
    writer_interpreter: str | None = None,
    writer_process_started_at: str | None = None,
    builder_version: str | None = None,
    last_write_status: str = "BOOTSTRAP",
    metadata_origin: str = "BOOTSTRAP_READ_ONLY",
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    rel = str(dataset_row["dataset_path"])
    path = root / rel if not Path(rel).is_absolute() else Path(rel)
    if path.suffix == ".json":
        probe = _probe_json_read_model(path)
    else:
        probe = _probe_parquet(
            path,
            str(dataset_row.get("source_timestamp_field") or "timestamp"),
            str(dataset_row.get("evaluated_timestamp_field") or "timestamp"),
        )
    mtime = None
    if path.exists():
        mtime = (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    meta = {
        "dataset_id": dataset_row["dataset_id"],
        "dataset_path": rel,
        "authority_plane": dataset_row["authority_plane"],
        "authority_role": dataset_row["authority_role"],
        "canonical_writer": dataset_row["canonical_writer"],
        "writer_entrypoint": dataset_row["writer_entrypoint"],
        "writer_pid": writer_pid,
        "writer_interpreter": writer_interpreter,
        "writer_process_started_at": writer_process_started_at,
        "builder_version": builder_version or dataset_row.get("builder_version_source"),
        "write_mode": dataset_row["write_mode"],
        "last_write_status": last_write_status,
        "source_market_timestamp": probe.get("source_market_timestamp"),
        "evaluated_timestamp": probe.get("evaluated_timestamp"),
        "file_mtime": mtime,
        "row_count": probe.get("row_count"),
        "column_count": probe.get("column_count"),
        "schema_hash": probe.get("schema_hash"),
        "file_sha256": file_sha256(path) if path.exists() else None,
        "first_timestamp": probe.get("first_timestamp"),
        "latest_timestamp": probe.get("latest_timestamp"),
        "written_at": utc_now_iso(),
        "metadata_version": METADATA_VERSION,
        "metadata_origin": metadata_origin,
        "error_code": error_code or probe.get("error"),
        "error_message": error_message,
        "operational_status": dataset_row.get("operational_status"),
        "semantic_type": dataset_row.get("semantic_type"),
        "event_sparse": bool(dataset_row.get("event_sparse")),
        "legacy_names": dataset_row.get("legacy_names") or [],
        "notes": dataset_row.get("notes") or "",
    }
    src = normalize_ts(meta["source_market_timestamp"])
    eva = normalize_ts(meta["evaluated_timestamp"])
    if src and eva and src > eva:
        meta["error_code"] = meta.get("error_code") or "SOURCE_AFTER_EVALUATED"
        meta["error_message"] = (
            meta.get("error_message")
            or "source_market_timestamp > evaluated_timestamp (metadata warning only)"
        )
    return meta


def write_dataset_metadata_atomic(
    metadata: dict[str, Any],
    *,
    root: Path | None = None,
    dataset_path: str | Path | None = None,
) -> Path:
    """Atomic metadata write. Never mutates the parquet payload."""
    root = root or repo_root()
    rel = str(dataset_path or metadata["dataset_path"])
    target = meta_path_for(root / rel if not Path(rel).is_absolute() else Path(rel))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    return target


def read_dataset_metadata(
    dataset_path: str | Path,
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    root = root or repo_root()
    path = Path(dataset_path)
    if not path.is_absolute():
        path = root / path
    meta = meta_path_for(path)
    if not meta.exists():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def emit_dataset_metadata_safe(
    dataset_row: dict[str, Any],
    *,
    root: Path | None = None,
    metadata_origin: str = "LIVE_WRITER",
    last_write_status: str = "OK",
    builder_version: str | None = None,
    writer_pid: int | None = None,
) -> dict[str, Any]:
    """Best-effort metadata emission after a successful dataset write.

    Failures never raise into the trading/writer path.
    """
    root = root or repo_root()
    try:
        meta = build_dataset_metadata(
            dataset_row,
            root=root,
            writer_pid=writer_pid if writer_pid is not None else os.getpid(),
            writer_interpreter=sys_executable(),
            builder_version=builder_version,
            last_write_status=last_write_status,
            metadata_origin=metadata_origin,
        )
        write_dataset_metadata_atomic(meta, root=root)
        return {"ok": True, "metadata": meta}
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"UNKNOWN_METADATA for {dataset_row.get('dataset_id')}: {type(exc).__name__}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return {
            "ok": False,
            "health_override": "UNKNOWN_METADATA",
            "error": f"{type(exc).__name__}: {exc}",
            "dataset_id": dataset_row.get("dataset_id"),
        }


def sys_executable() -> str:
    import sys

    return sys.executable


def writer_process_state(
    *,
    pid: int | None = None,
    pid_file: Path | None = None,
    match_token: str | None = None,
) -> dict[str, Any]:
    resolved_pid = pid
    if resolved_pid is None and pid_file and pid_file.exists():
        try:
            resolved_pid = int(pid_file.read_text().strip())
        except Exception:
            resolved_pid = None
    alive = False
    command = None
    if resolved_pid is not None:
        try:
            out = subprocess.check_output(
                ["ps", "-p", str(resolved_pid), "-o", "command="],
                text=True,
            ).strip()
            if out:
                alive = True
                command = out
                if match_token and match_token not in out:
                    alive = False
        except Exception:
            alive = False
    return {
        "pid": resolved_pid,
        "alive": alive,
        "state": "ALIVE" if alive else "DEAD",
        "command": command,
    }


def classify_dataset_health(
    dataset_row: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    market_feed_tip: str | None = None,
    now: datetime | None = None,
    writer_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Operational health only — never maps to BALANCE/NEUTRAL/OBSERVE."""
    now = now or datetime.now(timezone.utc)
    status = str(dataset_row.get("operational_status") or "UNKNOWN")
    reason_parts: list[str] = []

    if status == "INACTIVE_DEPRECATED":
        return {"health": "INACTIVE_DEPRECATED", "reason": "registry operational_status", "age_seconds": None}
    if status == "RESEARCH_ONLY":
        return {"health": "RESEARCH_ONLY", "reason": "registry operational_status", "age_seconds": None}
    if status == "PHANTOM":
        return {"health": "PHANTOM", "reason": "registry operational_status", "age_seconds": None}

    rel = str(dataset_row["dataset_path"])
    path = repo_root() / rel
    if not path.exists() and status in {
        "ACTIVE",
        "ACTIVE_STALE",
        "BROKEN",
        "EVENT_SPARSE_BY_DESIGN",
    }:
        return {
            "health": "MISSING_EXPECTED",
            "reason": "active dataset file missing",
            "age_seconds": None,
        }

    # mtime alone must never imply FRESH.
    # If metadata sidecar is provided, trust only its source/evaluated tips (no silent mtime fallback).
    source_tip = None
    evaluated_tip = None
    if metadata is not None:
        if metadata.get("error_code") and metadata.get("metadata_origin") == "FAILED":
            return {
                "health": "UNKNOWN_METADATA",
                "reason": str(metadata.get("error_message") or metadata.get("error_code")),
                "age_seconds": None,
            }
        source_tip = metadata.get("source_market_timestamp") or metadata.get("latest_timestamp")
        evaluated_tip = metadata.get("evaluated_timestamp")
    else:
        if path.suffix == ".json":
            probe = _probe_json_read_model(path)
        else:
            probe = _probe_parquet(
                path,
                str(dataset_row.get("source_timestamp_field") or "timestamp"),
                str(dataset_row.get("evaluated_timestamp_field") or "timestamp"),
            )
        source_tip = probe.get("source_market_timestamp")
        evaluated_tip = probe.get("evaluated_timestamp")
        if probe.get("error") == "missing":
            return {
                "health": "MISSING_EXPECTED",
                "reason": "file missing",
                "age_seconds": None,
            }

    src_dt = normalize_ts(source_tip)
    age_seconds = None if src_dt is None else (now - src_dt).total_seconds()

    if dataset_row.get("force_health"):
        return {
            "health": str(dataset_row["force_health"]),
            "reason": dataset_row.get("force_health_reason") or "registry force_health",
            "age_seconds": age_seconds,
            "source_market_timestamp": source_tip,
            "evaluated_timestamp": evaluated_tip,
        }

    if dataset_row.get("availability_health_policy") == "ALLOW_UNSUPPORTED_TIMEFRAME":
        latest_path = repo_root() / "data/runtime/multi_timeframe_availability_latest.json"
        overall = None
        d1_status = None
        if latest_path.exists():
            try:
                latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
                overall = latest_payload.get("overall_health")
                d1_status = (
                    (latest_payload.get("timeframes") or {}).get("D1") or {}
                ).get("availability_status")
                source_tip = (
                    latest_payload.get("latest_evaluation_timestamp") or source_tip
                )
                evaluated_tip = source_tip
                src_dt = normalize_ts(source_tip)
                age_seconds = None if src_dt is None else (now - src_dt).total_seconds()
            except Exception as exc:  # noqa: BLE001
                return {
                    "health": "UNKNOWN_METADATA",
                    "reason": f"mtf availability latest unreadable: {exc}",
                    "age_seconds": age_seconds,
                }
        if overall in HEALTH_STATES:
            return {
                "health": str(overall),
                "reason": (
                    f"D1={d1_status or 'n/a'}; unsupported timeframe does not break dataset"
                ),
                "age_seconds": age_seconds,
                "source_market_timestamp": source_tip,
                "evaluated_timestamp": evaluated_tip,
            }

    if writer_state and writer_state.get("state") == "DEAD" and dataset_row.get(
        "require_live_writer"
    ):
        return {
            "health": "DEAD_WRITER",
            "reason": "canonical writer process is DEAD",
            "age_seconds": age_seconds,
            "source_market_timestamp": source_tip,
            "evaluated_timestamp": evaluated_tip,
        }

    event_sparse = bool(dataset_row.get("event_sparse")) or dataset_row.get("semantic_type") == "EVENT_LOG"
    max_age = dataset_row.get("maximum_inheritance_age_seconds")
    budget = dataset_row.get("freshness_budget_seconds")

    upstream_lag = None
    feed_dt = normalize_ts(market_feed_tip)
    if feed_dt and src_dt:
        upstream_lag = (feed_dt - src_dt).total_seconds()

    if event_sparse:
        if age_seconds is None:
            health = "UNKNOWN"
            reason_parts.append("missing source tip")
        elif max_age is not None and age_seconds > float(max_age):
            health = "STALE"
            reason_parts.append(
                f"inherited event age {age_seconds:.0f}s exceeds max {max_age}s"
            )
        else:
            health = "EVENT_SPARSE_BY_DESIGN"
            reason_parts.append("event log within maximum inheritance age")
        return {
            "health": health,
            "reason": "; ".join(reason_parts),
            "age_seconds": age_seconds,
            "upstream_lag_seconds": upstream_lag,
            "source_market_timestamp": source_tip,
            "evaluated_timestamp": evaluated_tip,
        }

    if status == "BROKEN" or dataset_row.get("force_broken"):
        return {
            "health": "BROKEN",
            "reason": dataset_row.get("notes") or "registry BROKEN",
            "age_seconds": age_seconds,
            "upstream_lag_seconds": upstream_lag,
            "source_market_timestamp": source_tip,
            "evaluated_timestamp": evaluated_tip,
        }

    if age_seconds is None:
        return {
            "health": "UNKNOWN",
            "reason": "no source_market_timestamp (mtime ignored for freshness)",
            "age_seconds": None,
            "upstream_lag_seconds": upstream_lag,
        }

    # Prefer lag vs market feed when available for dense layers
    compare = upstream_lag if upstream_lag is not None else age_seconds
    if compare is None:
        health = "UNKNOWN"
    elif budget is not None and compare <= float(budget):
        if compare <= min(float(budget), 900.0):
            health = "FRESH"
        else:
            health = "PIPELINE_PENDING"
    elif budget is not None and compare <= float(budget) * 4:
        health = "STALE"
    elif compare > 24 * 3600:
        health = "BROKEN"
    else:
        health = "STALE"

    if status == "ACTIVE_STALE" and health == "FRESH":
        # registry acknowledges plane lag expectation; keep STALE if lag remains
        if upstream_lag is not None and budget is not None and upstream_lag > float(budget):
            health = "STALE"
            reason_parts.append("ACTIVE_STALE plane lag vs feed")

    if metadata is None:
        # missing sidecar must not imply FRESH
        if health == "FRESH":
            health = "UNKNOWN"
            reason_parts.append("missing metadata sidecar; not FRESH")
        else:
            reason_parts.append("missing metadata sidecar")

    if not reason_parts:
        reason_parts.append(f"compare_seconds={compare:.0f} budget={budget}")

    return {
        "health": health,
        "reason": "; ".join(reason_parts),
        "age_seconds": age_seconds,
        "upstream_lag_seconds": upstream_lag,
        "source_market_timestamp": source_tip,
        "evaluated_timestamp": evaluated_tip,
    }


def build_runtime_status_snapshot(
    registry: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    registry = registry or load_dataset_ownership_registry(root=root)
    now = now or datetime.now(timezone.utc)

    # market feed tip
    feed_row = next(
        (d for d in registry["datasets"] if d["dataset_id"] == "live_market_feed"),
        None,
    )
    market_feed_tip = None
    if feed_row:
        probe = _probe_parquet(
            root / feed_row["dataset_path"],
            feed_row["source_timestamp_field"],
            feed_row["evaluated_timestamp_field"],
        )
        market_feed_tip = probe.get("source_market_timestamp")

    paper_pid = root / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
    writers = {
        "canonical_pipeline_loop": writer_process_state(match_token="run.py"),
        "live_market_feed_writer": writer_process_state(match_token="live_binance_feed_v2.py"),
        "visual_refresher": writer_process_state(
            match_token="run_market_context_visual_refresher.py"
        ),
        "paper_controller": writer_process_state(
            pid_file=paper_pid,
            match_token="bounded_paper_trading_controller",
        ),
    }
    # refine pipeline pid via ps scan
    try:
        ps = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
        for line in ps.splitlines():
            line = line.strip()
            if not line:
                continue
            pid_s, _, cmd = line.partition(" ")
            cmd = cmd.strip()
            if cmd.endswith("run.py") or " run.py" in f" {cmd}" and "pytest" not in cmd:
                if "run.py" in cmd and "Cursor" not in cmd:
                    writers["canonical_pipeline_loop"] = {
                        "pid": int(pid_s),
                        "alive": True,
                        "state": "ALIVE",
                        "command": cmd[:220],
                    }
            if "live_binance_feed_v2.py" in cmd:
                writers["live_market_feed_writer"] = {
                    "pid": int(pid_s),
                    "alive": True,
                    "state": "ALIVE",
                    "command": cmd[:220],
                }
            if "run_market_context_visual_refresher.py" in cmd:
                writers["visual_refresher"] = {
                    "pid": int(pid_s),
                    "alive": True,
                    "state": "ALIVE",
                    "command": cmd[:220],
                }
            if "bounded_paper_trading_controller" in cmd:
                writers["paper_controller"] = {
                    "pid": int(pid_s),
                    "alive": True,
                    "state": "ALIVE",
                    "command": cmd[:220],
                }
    except Exception:
        pass

    datasets_out = []
    counts = {
        "fresh_count": 0,
        "stale_count": 0,
        "broken_count": 0,
        "dead_writer_count": 0,
        "event_sparse_count": 0,
        "deprecated_count": 0,
        "phantom_count": 0,
        "unknown_count": 0,
        "pipeline_pending_count": 0,
        "missing_count": 0,
        "healthy_with_unsupported_count": 0,
        "degraded_count": 0,
    }

    for row in sorted(registry["datasets"], key=lambda r: r["dataset_id"]):
        meta = read_dataset_metadata(row["dataset_path"], root=root)
        wstate = None
        writer = row["canonical_writer"]
        if writer in writers:
            wstate = writers[writer]
        elif writer == "paper_controller":
            wstate = writers.get("paper_controller")
        health = classify_dataset_health(
            row,
            metadata=meta,
            market_feed_tip=market_feed_tip,
            now=now,
            writer_state=wstate,
        )
        h = health["health"]
        if h == "FRESH":
            counts["fresh_count"] += 1
        elif h == "STALE":
            counts["stale_count"] += 1
        elif h == "BROKEN":
            counts["broken_count"] += 1
        elif h == "DEAD_WRITER":
            counts["dead_writer_count"] += 1
        elif h == "EVENT_SPARSE_BY_DESIGN":
            counts["event_sparse_count"] += 1
        elif h == "INACTIVE_DEPRECATED":
            counts["deprecated_count"] += 1
        elif h == "PHANTOM":
            counts["phantom_count"] += 1
        elif h == "PIPELINE_PENDING":
            counts["pipeline_pending_count"] += 1
        elif h == "MISSING_EXPECTED":
            counts["missing_count"] += 1
        elif h == "HEALTHY_WITH_UNSUPPORTED_TIMEFRAME":
            counts["healthy_with_unsupported_count"] += 1
        elif h == "DEGRADED":
            counts["degraded_count"] += 1
        else:
            counts["unknown_count"] += 1

        datasets_out.append(
            {
                "dataset_id": row["dataset_id"],
                "logical_state": row["logical_state"],
                "dataset_path": row["dataset_path"],
                "authority_plane": row["authority_plane"],
                "authority_role": row["authority_role"],
                "semantic_type": row["semantic_type"],
                "operational_status": row["operational_status"],
                "health": h,
                "source_market_timestamp": health.get("source_market_timestamp"),
                "evaluated_timestamp": health.get("evaluated_timestamp"),
                "age_seconds": health.get("age_seconds"),
                "upstream_lag_seconds": health.get("upstream_lag_seconds"),
                "writer_state": (wstate or {}).get("state"),
                "writer_pid": (wstate or {}).get("pid"),
                "row_count": None if meta is None else meta.get("row_count"),
                "schema_hash": None if meta is None else meta.get("schema_hash"),
                "file_sha256": None if meta is None else meta.get("file_sha256"),
                "metadata_origin": None if meta is None else meta.get("metadata_origin"),
                "reason": health.get("reason"),
            }
        )

    planes = registry.get("planes") or []
    engine_parity = registry.get("engine_parity") or {}

    return {
        "generated_at": ts_to_iso(now) or utc_now_iso(),
        "registry_version": registry.get("registry_version", REGISTRY_VERSION),
        "metadata_version": METADATA_VERSION,
        "market_feed_tip": market_feed_tip,
        "flags_frozen": registry.get("flags_frozen")
        or {
            "BTC_ML_CONTINUATION_PROGRESSION": "0",
            "PRICE_GATE": "OFF",
            "execution": "disabled",
        },
        "datasets": datasets_out,
        "planes": planes,
        "writers": writers,
        "engine_parity": engine_parity,
        "summary": counts,
        "read_model_only": True,
        "trading_use_forbidden": True,
    }


def write_runtime_status_snapshot(
    snapshot: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
    path: str | Path | None = None,
) -> Path:
    root = root or repo_root()
    snapshot = snapshot or build_runtime_status_snapshot(root=root)
    out = Path(path) if path else root / DEFAULT_STATUS_REL
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=out.name + ".", suffix=".tmp", dir=str(out.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, out)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    return out


def registry_row_by_path(
    registry: dict[str, Any], dataset_path: str
) -> dict[str, Any] | None:
    for row in registry.get("datasets") or []:
        if row.get("dataset_path") == dataset_path:
            return row
    return None


def emit_metadata_for_path(
    dataset_path: str,
    *,
    root: Path | None = None,
    metadata_origin: str = "LIVE_WRITER",
    last_write_status: str = "OK",
) -> dict[str, Any]:
    """Helper for writers: look up registry row and emit sidecar safely."""
    root = root or repo_root()
    try:
        registry = load_dataset_ownership_registry(root=root)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"ownership registry load failed: {exc}", RuntimeWarning, stacklevel=2)
        return {"ok": False, "error": str(exc)}
    row = registry_row_by_path(registry, dataset_path)
    if row is None:
        return {"ok": False, "error": f"dataset_path not in registry: {dataset_path}"}
    return emit_dataset_metadata_safe(
        row,
        root=root,
        metadata_origin=metadata_origin,
        last_write_status=last_write_status,
    )
