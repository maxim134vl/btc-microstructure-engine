"""AES6 resource telemetry helpers — disk/RSS/growth; no market logic."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rss_memory_mb() -> float | None:
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss <= 0:
            return None
        if rss > 10_000_000:
            return round(rss / (1024 * 1024), 3)
        return round(rss / 1024, 3)
    except Exception:
        return None


def disk_bytes(path: Path | str) -> tuple[int | None, int | None, int | None]:
    """Return (total, used, free) bytes for the filesystem containing path."""
    try:
        st = os.statvfs(str(path))
    except OSError:
        return None, None, None
    total = int(st.f_blocks) * int(st.f_frsize)
    free = int(st.f_bavail) * int(st.f_frsize)
    used = max(0, total - int(st.f_bfree) * int(st.f_frsize))
    return total, used, free


def directory_size_bytes(path: Path | str) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def lag_sec(now_ts: str | None, event_ts: str | None) -> float | None:
    if not now_ts or not event_ts:
        return None
    a = _parse(now_ts)
    b = _parse(event_ts)
    if a is None or b is None:
        return None
    return max(0.0, (a - b).total_seconds())


def _parse(value: str) -> datetime | None:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_growth_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_growth_snapshot(
    *,
    path: Path,
    shadow_total_bytes: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Track samples for 1h/24h growth estimates. Bounded history."""
    import json

    now = now or datetime.now(timezone.utc)
    raw = load_growth_snapshot(path)
    samples = list(raw.get("samples") or [])
    samples.append({"ts": now.timestamp(), "bytes": int(shadow_total_bytes)})
    # Keep ~48h of samples at ~5 min cadence upper bound → 600 samples max.
    samples = samples[-600:]
    growth_1h = _growth_since(samples, now.timestamp() - 3600)
    growth_24h = _growth_since(samples, now.timestamp() - 86400)
    payload = {
        "updated_at": utc_now(),
        "shadow_total_bytes": int(shadow_total_bytes),
        "shadow_growth_1h": growth_1h,
        "shadow_growth_24h": growth_24h,
        "samples": samples,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return payload


def _growth_since(samples: list[dict[str, Any]], since_ts: float) -> int | None:
    older = [s for s in samples if float(s.get("ts") or 0) <= since_ts]
    if not samples:
        return None
    latest = int(samples[-1].get("bytes") or 0)
    if not older:
        return None
    return latest - int(older[-1].get("bytes") or 0)


def storage_status(
    *,
    free_bytes: int | None,
    min_free_bytes: int,
    warning_bytes: int | None,
    critical_bytes: int | None,
) -> str:
    if free_bytes is None:
        return "UNKNOWN"
    if critical_bytes is not None and free_bytes <= int(critical_bytes):
        return "STORAGE_CRITICAL"
    if free_bytes < int(min_free_bytes):
        return "STORAGE_CRITICAL"
    if warning_bytes is not None and free_bytes <= int(warning_bytes):
        return "STORAGE_WARNING"
    return "OK"
