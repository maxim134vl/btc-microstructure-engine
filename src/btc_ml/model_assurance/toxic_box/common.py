"""Shared helpers for current Toxic Box branches (MODEL-4)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(canonical_json(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def toxic_event_id(*, registry_record_id: str, subject_id: str, subtype: str) -> str:
    return "TOX4_" + sha256_text(
        canonical_json(
            {
                "registry_record_id": registry_record_id,
                "subject_id": subject_id,
                "subtype": subtype,
            }
        )
    )[:32]


def base_event(
    *,
    branch: str,
    subtype: str,
    severity: str,
    status: str,
    active: dict[str, Any],
    subject_event_at: str | None,
    timeframe: str | None = None,
    direction: str | None = None,
    context_event_id: str | None = None,
    lifecycle_episode_id: str | None = None,
    prediction_id: str | None = None,
    outcome_id: str | None = None,
    trade_id: str | None = None,
    position_id: str | None = None,
    order_id: str | None = None,
    fill_id: str | None = None,
    expected_value: Any = None,
    observed_value: Any = None,
    threshold: Any = None,
    evidence: dict[str, Any] | None = None,
    subject_id: str,
) -> dict[str, Any]:
    return {
        "toxic_event_id": toxic_event_id(
            registry_record_id=str(active.get("registry_record_id")),
            subject_id=subject_id,
            subtype=subtype,
        ),
        "branch": branch,
        "subtype": subtype,
        "severity": severity,
        "status": status,
        "detected_at": utc_now_iso(),
        "subject_event_at": subject_event_at,
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "timeframe": timeframe,
        "direction": direction,
        "context_event_id": context_event_id,
        "lifecycle_episode_id": lifecycle_episode_id,
        "prediction_id": prediction_id,
        "outcome_id": outcome_id,
        "trade_id": trade_id,
        "position_id": position_id,
        "order_id": order_id,
        "fill_id": fill_id,
        "expected_value": expected_value,
        "observed_value": observed_value,
        "threshold": threshold,
        "evidence": evidence or {},
    }


def append_unique(path: Path, row: dict[str, Any], *, existing_ids: set[str]) -> bool:
    tid = str(row.get("toxic_event_id") or "")
    if not tid or tid in existing_ids:
        return False
    append_jsonl(path, row)
    existing_ids.add(tid)
    return True
