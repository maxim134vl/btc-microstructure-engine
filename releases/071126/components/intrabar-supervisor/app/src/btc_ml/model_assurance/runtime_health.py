"""Shared lifecycle handling for Model Assurance health artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _read_health(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}

    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def _same_pid(
    left: Any,
    right: Any,
) -> bool:
    if left in (
        None,
        "",
    ):
        return True

    try:
        return int(left) == int(right)
    except (
        TypeError,
        ValueError,
    ):
        return str(left) == str(right)


def _atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        )
        + "\n"
    )

    descriptor, temp_name = (
        tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=str(path.parent),
        )
    )

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp_name,
            path,
        )
    finally:
        if os.path.exists(
            temp_name
        ):
            try:
                os.unlink(
                    temp_name
                )
            except OSError:
                pass


def mark_health_stopped(
    *,
    health_path: str | Path,
    pid: int | None,
    stop_reason: str = "PROCESS_EXIT",
) -> dict[str, Any]:
    """Persist a stopped state without overwriting a newer process health."""
    path = Path(
        health_path
    )
    payload = _read_health(
        path
    )

    existing_pid = payload.get(
        "pid"
    )

    if (
        pid is not None
        and not _same_pid(
            existing_pid,
            pid,
        )
    ):
        # A newer process already owns this health artifact.
        return payload

    now = utc_now_iso()

    payload.update(
        {
            "status":
                payload.get(
                    "status"
                )
                or "STOPPED",
            "alive":
                False,
            "pid":
                pid
                if pid is not None
                else existing_pid,
            "stop_reason":
                stop_reason,
            "stopped_at":
                now,
            "updated_at":
                now,
        }
    )

    _atomic_write_json(
        path,
        payload,
    )

    return payload
