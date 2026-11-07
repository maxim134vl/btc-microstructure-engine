"""Independent health writer for AUCTION_EPISODE_SHADOW."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contract import ShadowAuctionContract
from .resources import (
    directory_size_bytes,
    disk_bytes,
    lag_sec,
    rss_memory_mb,
    storage_status,
    update_growth_snapshot,
    utc_now,
)
from .storage import ShadowAuctionStore, atomic_write_json, free_bytes
from .watermark import Watermark

# Process-local peak RSS tracker (AES6C).
_PEAK_RSS_MB: float | None = None
_PROCESS_STARTED_AT: str | None = None


def mark_process_started(ts: str | None = None) -> str:
    global _PROCESS_STARTED_AT
    _PROCESS_STARTED_AT = ts or utc_now()
    return _PROCESS_STARTED_AT


def process_started_at() -> str | None:
    return _PROCESS_STARTED_AT


def _track_peak_rss(current: float | None) -> float | None:
    global _PEAK_RSS_MB
    if current is None:
        return _PEAK_RSS_MB
    if _PEAK_RSS_MB is None or current > _PEAK_RSS_MB:
        _PEAK_RSS_MB = current
    return _PEAK_RSS_MB


def build_health(
    *,
    contract: ShadowAuctionContract,
    store: ShadowAuctionStore,
    watermark: Watermark | None = None,
    status: str = "RUNNING",
    source_lag_ms: float | None = None,
    extra: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    wm = watermark.state if watermark is not None else None
    rss = rss_memory_mb()
    peak = _track_peak_rss(rss)
    total, used, free = disk_bytes(store.data_root)
    shadow_bytes = directory_size_bytes(store.data_root)
    growth_path = store.data_root / "health" / "storage_growth.json"
    try:
        growth = update_growth_snapshot(path=growth_path, shadow_total_bytes=shadow_bytes)
    except Exception:
        growth = {
            "shadow_total_bytes": shadow_bytes,
            "shadow_growth_1h": None,
            "shadow_growth_24h": None,
        }

    cfg = dict(config or {})
    min_free = int(cfg.get("min_free_bytes") or 0)
    warn = cfg.get("storage_warning_bytes")
    crit = cfg.get("storage_critical_bytes")
    if warn is None and isinstance(cfg.get("aes6"), dict):
        warn = cfg["aes6"].get("storage_warning_bytes")
        crit = crit if crit is not None else cfg["aes6"].get("storage_critical_bytes")
    stor = storage_status(
        free_bytes=free if free is not None else store.validation.storage_free_bytes,
        min_free_bytes=min_free,
        warning_bytes=None if warn is None else int(warn),
        critical_bytes=None if crit is None else int(crit),
    )

    payload: dict[str, Any] = {
        "status": status if stor != "STORAGE_CRITICAL" else "STORAGE_CRITICAL",
        "pid": os.getpid(),
        "process_started_at": _PROCESS_STARTED_AT,
        "updated_at": utc_now(),
        "shadow_name": contract.shadow_name,
        "logic_version": contract.logic_version,
        "schema_version": contract.schema_version,
        "logic_fingerprint": contract.logic_fingerprint,
        "observer_only": contract.observer_only,
        "enforcement_enabled": contract.enforcement_enabled,
        "data_root": str(store.data_root),
        "storage_mounted": bool(store.validation.storage_mounted),
        "storage_writable": bool(store.validation.storage_writable),
        "storage_free_bytes": store.validation.storage_free_bytes
        if store.validation.storage_free_bytes is not None
        else free_bytes(store.data_root),
        "disk_total_bytes": total,
        "disk_used_bytes": used,
        "disk_free_bytes": free,
        "shadow_total_bytes": shadow_bytes,
        "shadow_growth_1h": growth.get("shadow_growth_1h"),
        "shadow_growth_24h": growth.get("shadow_growth_24h"),
        "storage_status": stor,
        "last_source_event_id": None if wm is None else wm.last_processed_source_event_id,
        "last_source_timestamp": None if wm is None else wm.last_processed_timestamp,
        "source_lag_ms": source_lag_ms,
        "duplicates_dropped": 0 if wm is None else int(wm.duplicates_dropped),
        "ordering_violations": 0 if wm is None else int(wm.ordering_violations),
        "write_errors": int(store.write_errors),
        "rss_memory_mb": rss,
        "peak_rss_memory_mb": peak,
    }
    if extra:
        payload.update(dict(extra))
        # Derive TF lags if last event timestamps present.
        now = payload.get("updated_at")
        for tf in ("m15", "m30", "h1", "h4"):
            key = f"{tf}_last_event_timestamp"
            if key in payload and f"{tf}_source_lag_sec" not in payload:
                payload[f"{tf}_source_lag_sec"] = lag_sec(str(now) if now else None, payload.get(key))
        if payload.get("last_hierarchy_timestamp") and "hierarchy_lag_sec" not in payload:
            payload["hierarchy_lag_sec"] = lag_sec(
                str(now) if now else None, payload.get("last_hierarchy_timestamp")
            )
    return payload


def write_health(
    *,
    contract: ShadowAuctionContract,
    store: ShadowAuctionStore,
    watermark: Watermark | None = None,
    status: str = "RUNNING",
    source_lag_ms: float | None = None,
    extra: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> Path:
    payload = build_health(
        contract=contract,
        store=store,
        watermark=watermark,
        status=status,
        source_lag_ms=source_lag_ms,
        extra=extra,
        config=config,
    )
    return atomic_write_json(
        store.data_root / "health" / "health.json",
        payload,
        data_root=store.data_root,
        repo=store.repo,
    )
