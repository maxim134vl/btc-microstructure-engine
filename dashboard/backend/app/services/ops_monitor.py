"""Operational runtime monitor — infrastructure supervision only."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd
import psutil

from app.config import CANONICAL_PIPELINE
from app.services.parquet_service import df_records, file_snapshot, read_parquet
from app.services.required_manifest import (
    is_required_collector,
    is_required_engine,
    is_required_parquet,
    manifest_summary,
    threshold,
)
from app.services.runtime_classification import (
    ARCHIVED_CLASSES,
    classify_collector,
    classify_engine,
    classify_parquet,
)
from ops_stability import update_stability
from runtime_config import LEGACY_LIVE_FEED_PARQUET, LIVE_MARKET_FEED_PARQUET
from storage.path_registry import PARQUET_REGISTRY, repo_root, resolve_read

IN_PROCESS_ENGINES = {
    "auction_convergence_engine_v1.py",
    "auction_reinforcement_engine_v1.py",
    "probabilistic_auction_engine_v1.py",
    "adaptive_meta_cognition_engine_v1.py",
    "stage2_cognition_runtime_v1.py",
    "state_transition_engine_v1.py",
}

PARQUET_LIVE_SECONDS = 900
PARQUET_DELAYED_SECONDS = 3600
COLLECTOR_LIVE_SECONDS = 120
ENGINE_STALE_SECONDS = 900

COLLECTOR_SOURCES = {
    "binance_live_feed": LIVE_MARKET_FEED_PARQUET,
    "live_feed_legacy_mirror": LEGACY_LIVE_FEED_PARQUET,
    "multi_exchange": "datasets/multi_exchange",
    "orderbook": "datasets/orderbook",
    "oi": "datasets/oi",
}

HEARTBEAT_DIR = repo_root() / "data" / "live" / "collector_heartbeats"


def _read_collector_heartbeat(name: str) -> dict[str, Any] | None:
    path = HEARTBEAT_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _threshold(name: str, default: float) -> float:
    return threshold(name, default)


def _heartbeat_age(name: str = "binance_live_feed") -> tuple[float | None, dict[str, Any] | None]:
    hb = _read_collector_heartbeat(name)
    if not hb or not hb.get("timestamp"):
        return None, hb
    try:
        return time.time() - pd.to_datetime(hb["timestamp"]).timestamp(), hb
    except Exception:
        return None, hb


def _ws_alive(collector_name: str = "binance_live_feed") -> tuple[bool, dict[str, Any] | None]:
    age, hb = _heartbeat_age(collector_name)
    if age is None:
        return False, hb
    return age <= _threshold("collector_ws", COLLECTOR_LIVE_SECONDS), hb


def _orchestration_active(pipeline: dict[str, Any], engines: list[dict[str, Any]]) -> bool:
    if _pipeline_is_cycling(pipeline):
        return True
    for engine in engines:
        if not is_required_engine(engine["engine"]):
            continue
        if engine["status"] in ("HEALTHY", "DEFERRED") and engine.get("last_run"):
            return True
    return False


def _collector_truly_dead(
    collector: dict[str, Any] | None,
    ws_alive: bool,
    *,
    orchestration_active: bool = False,
) -> bool:
    """CRITICAL only when websocket heartbeat absent beyond dead timeout."""
    if ws_alive or orchestration_active:
        return False
    if collector is None:
        return True
    hb_age = collector.get("heartbeat_age_seconds")
    dead_after = _threshold("collector_dead", 600)
    if hb_age is None:
        return collector.get("status") == "DISCONNECTED"
    return hb_age > dead_after


def _parquet_stale_tier(age_seconds: float | None) -> str:
    """Stale parquet severity — never CRITICAL, only informational tiers."""
    if age_seconds is None:
        return "DEGRADED"
    info_t = _threshold("parquet_stale_info", 1800)
    warn_t = _threshold("parquet_stale_warning", 7200)
    if age_seconds < info_t:
        return "INFO"
    if age_seconds < warn_t:
        return "WARNING"
    return "DEGRADED"


def _pipeline_is_cycling(pipeline: dict[str, Any]) -> bool:
    return pipeline.get("active_state") == "CYCLING" or pipeline.get("current_cycle", 0) > 0


def _no_live_ingestion(ws_alive: bool, feed: dict[str, Any] | None) -> bool:
    """CRITICAL ingestion failure — ws down AND no usable feed on disk."""
    if ws_alive:
        return False
    if feed is None or feed.get("freshness") == "MISSING":
        return True
    if feed.get("freshness") == "STALE":
        return True
    return False


def _required_parquet_freshness(snap: dict[str, Any], *, ws_alive: bool) -> str:
    if not snap.get("exists"):
        return "MISSING"
    age = float(snap.get("age_seconds") or 0)
    live_t = _threshold("parquet_live", PARQUET_LIVE_SECONDS)
    delayed_t = _threshold("parquet_delayed", PARQUET_DELAYED_SECONDS)
    if age <= live_t:
        return "LIVE"
    if snap["file"] == "live_market_feed.parquet" and ws_alive:
        return "DELAYED"
    if age <= delayed_t:
        return "DELAYED"
    return "STALE"


def _freshness_level(freshness: str, *, health_scope: bool) -> str:
    if not health_scope:
        return "GREY"
    if freshness == "LIVE":
        return "GREEN"
    if freshness == "DELAYED":
        return "YELLOW"
    if freshness == "MISSING":
        return "RED"
    return "YELLOW"


def _engine_context(parquet: dict[str, Any], collectors: dict[str, Any]) -> dict[str, Any]:
    ws_alive, _hb = _ws_alive()
    feed = next((p for p in parquet.get("all", []) if p["file"] == "live_market_feed.parquet"), None)
    feed_freshness = feed.get("freshness") if feed else "MISSING"
    return {
        "ws_alive": ws_alive,
        "feed_delayed": feed_freshness in ("DELAYED", "STALE", "MISSING"),
        "feed_stale": feed_freshness == "STALE",
        "feed_missing": feed_freshness == "MISSING",
        "pipeline_cycling": True,
    }


def _resolve_engine_status(
    engine: str,
    raw_status: str,
    ctx: dict[str, Any],
    *,
    synthesis_rows: int,
) -> tuple[str, str | None]:
    """Return (display_status, note). DEFERRED overrides STALE for dependency waits."""
    if engine == "state_transition_engine_v1.py" and synthesis_rows < 2:
        return "DEFERRED", "awaiting second synthesis snapshot"

    if engine == "auction_synthesis_engine_v1.py":
        return "DEFERRED", "dependency-gated or awaiting state change (append-only memory)"

    if (
        is_required_engine(engine)
        and raw_status == "STALE"
        and ctx.get("feed_delayed")
        and engine != "candle_structure_engine_v1.py"
    ):
        return "DEFERRED", "awaiting upstream feed refresh"

    if raw_status == "SUCCESS":
        return "HEALTHY", None
    if raw_status in ("WAITING", "DEFERRED"):
        return "DEFERRED", None
    if raw_status == "TIMEOUT":
        return "TIMEOUT", None
    if raw_status == "FAILED":
        return "FAILED", None
    if raw_status == "STALE":
        if is_required_engine(engine) and ctx.get("feed_delayed"):
            return "DEFERRED", "awaiting feed persistence"
        if not is_required_engine(engine):
            return "STALLED", "non-manifest engine idle"
        return "STALLED", "no recent execution"
    return "STALLED", None


def _ago_label(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    return f"{int(seconds // 3600)}h ago"


def _collector_display_status(name: str, raw_status: str) -> str:
    component_class = classify_collector(name)
    if component_class == "OPTIONAL" and raw_status == "DISCONNECTED":
        return "OPTIONAL_OFFLINE"
    if component_class in ARCHIVED_CLASSES:
        return "ARCHIVED"
    return raw_status


def _collector_level(name: str, display_status: str, base_level: str) -> str:
    component_class = classify_collector(name)
    if component_class in ARCHIVED_CLASSES:
        return "GREY"
    if component_class == "OPTIONAL" and display_status in ("DISCONNECTED", "OPTIONAL_OFFLINE"):
        return "GREY"
    return base_level


def _finalize_collector_entry(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    raw_status = entry["status"]
    entry["status"] = _collector_display_status(name, raw_status)
    entry["level"] = _collector_level(name, entry["status"], entry["level"])
    if entry["status"] == "ARCHIVED":
        entry["ignored_by_health"] = True
    elif classify_collector(name) == "OPTIONAL" and entry["status"] == "OPTIONAL_OFFLINE":
        entry["ignored_by_health"] = True
    else:
        entry["ignored_by_health"] = not entry["affects_health"]
    return entry


def _collector_status(name: str, path: str) -> dict[str, Any]:
    now = time.time()
    component_class = classify_collector(name)
    entry: dict[str, Any] = {
        "name": name,
        "path": path,
        "classification": component_class,
        "affects_health": is_required_collector(name),
        "status": "DISCONNECTED",
        "level": "RED",
        "last_message": None,
        "age_seconds": None,
        "latency_note": None,
    }

    try:
        if os.path.isdir(path):
            files = sorted(
                os.path.join(path, f)
                for f in os.listdir(path)
                if f.endswith(".parquet")
            )
            if not files:
                entry["status"] = "DISCONNECTED"
                return _finalize_collector_entry(name, entry)
            target = files[-1]
        elif os.path.exists(resolve_read(path) if path.endswith(".parquet") else path):
            target = resolve_read(path) if path.endswith(".parquet") else path
        else:
            alt = resolve_read(path) if path.endswith(".parquet") else path
            if not os.path.exists(alt):
                return _finalize_collector_entry(name, entry)
            target = alt

        if target.endswith(".parquet"):
            df = pd.read_parquet(target)
            if len(df) == 0:
                entry["status"] = "DISCONNECTED"
                return _finalize_collector_entry(name, entry)
            if "timestamp" in df.columns:
                ts = pd.to_datetime(df["timestamp"].iloc[-1])
                entry["last_message"] = ts.isoformat()
                age = now - ts.timestamp()
            else:
                age = now - os.path.getmtime(target)
        else:
            age = now - os.path.getmtime(target)

        entry["age_seconds"] = round(age, 1)
        if age <= COLLECTOR_LIVE_SECONDS:
            entry["status"] = "CONNECTED"
            entry["level"] = "GREEN"
        elif age <= COLLECTOR_LIVE_SECONDS * 5:
            entry["status"] = "DEGRADED"
            entry["level"] = "YELLOW"
            entry["latency_note"] = f"lag {int(age)}s"
        else:
            entry["status"] = "DISCONNECTED"
            entry["level"] = "RED"

        hb = _read_collector_heartbeat(name)
        if hb and hb.get("timestamp"):
            hb_age = now - pd.to_datetime(hb["timestamp"]).timestamp()
            entry["heartbeat"] = hb
            entry["heartbeat_age_seconds"] = round(hb_age, 1)
            ws_fresh = hb_age <= _threshold("collector_ws", COLLECTOR_LIVE_SECONDS)
            ws_unstable = hb_age <= _threshold("collector_ws", COLLECTOR_LIVE_SECONDS) * 5
            if ws_fresh:
                entry["status"] = "CONNECTED"
                entry["level"] = "GREEN"
                entry["latency_note"] = hb.get("event") or "websocket alive"
            elif ws_unstable:
                entry["status"] = "DEGRADED"
                entry["level"] = "YELLOW"
                entry["latency_note"] = "websocket unstable"
    except Exception as error:
        entry["status"] = "DISCONNECTED"
        entry["error"] = str(error)

    return _finalize_collector_entry(name, entry)


async def build_engine_status(
    parquet: dict[str, Any] | None = None,
    collectors: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    engine_state = await read_parquet("runtime_engine_state.parquet", tail=2000)
    synthesis = await read_parquet("auction_synthesis_memory.parquet", tail=2)
    synthesis_rows = len(synthesis)

    if parquet is None:
        parquet = await build_parquet_status()
    if collectors is None:
        collectors = await build_collector_status()

    ctx = _engine_context(parquet, collectors)
    ctx["synthesis_rows"] = synthesis_rows

    latest_by_engine: dict[str, dict[str, Any]] = {}
    for row in df_records(engine_state):
        latest_by_engine[row["engine"]] = row

    now = time.time()
    stale_cutoff = _threshold("engine_stale", ENGINE_STALE_SECONDS)
    rows: list[dict[str, Any]] = []

    for engine in CANONICAL_PIPELINE:
        entry = latest_by_engine.get(engine, {})
        raw_status = str(entry.get("status", "UNKNOWN"))
        duration = entry.get("duration")
        timestamp = entry.get("timestamp")
        note = None

        age_seconds = None
        if timestamp:
            try:
                age_seconds = now - pd.to_datetime(timestamp).timestamp()
            except Exception:
                age_seconds = None

        if raw_status == "UNKNOWN" or (age_seconds is not None and age_seconds > stale_cutoff):
            raw_status = "STALE"

        display_status, note = _resolve_engine_status(engine, raw_status, ctx, synthesis_rows=synthesis_rows)
        component_class = classify_engine(engine)
        health_required = is_required_engine(engine)
        ignored = (not health_required) or display_status == "DEFERRED"

        rows.append(
            {
                "engine": engine,
                "short_name": engine.replace("_engine_v1.py", "").replace("_memory_v1.py", ""),
                "status": display_status,
                "raw_status": raw_status,
                "classification": component_class,
                "affects_health": health_required and display_status in ("FAILED", "TIMEOUT", "STALLED"),
                "last_run": timestamp,
                "last_run_ago": _ago_label(age_seconds),
                "duration_s": duration,
                "mode": "in-process" if engine in IN_PROCESS_ENGINES else "subprocess",
                "note": note,
                "ignored_by_health": ignored,
            }
        )

    return rows


async def build_parquet_status(*, ws_alive: bool | None = None) -> dict[str, Any]:
    if ws_alive is None:
        ws_alive, _ = _ws_alive()

    registry_names = sorted(set(PARQUET_REGISTRY.keys()) | {"runtime_engine_state.parquet"})
    snapshots = [file_snapshot(name) for name in registry_names]
    grouped: list[dict[str, Any]] = []

    for snap in snapshots:
        component_class = classify_parquet(snap["file"])
        health_scope = is_required_parquet(snap["file"])
        ignored = component_class in ARCHIVED_CLASSES or not health_scope

        if health_scope:
            freshness = _required_parquet_freshness(snap, ws_alive=ws_alive)
        elif not snap["exists"]:
            freshness = "MISSING"
        elif snap.get("stale"):
            freshness = "STALE"
        else:
            freshness = "LIVE"

        level = _freshness_level(freshness, health_scope=health_scope)

        grouped.append(
            {
                "file": snap["file"],
                "freshness": freshness,
                "level": level,
                "classification": component_class,
                "affects_health": health_scope,
                "ignored_by_health": ignored,
                "mtime": snap.get("mtime"),
                "age_seconds": snap.get("age_seconds"),
                "row_count": snap.get("row_count"),
            }
        )

    required = [p for p in grouped if is_required_parquet(p["file"])]
    optional = [p for p in grouped if p["classification"] == "OPTIONAL"]
    archived = [p for p in grouped if p["classification"] in ARCHIVED_CLASSES]

    req_stale = [p for p in required if p["freshness"] == "STALE"]
    req_delayed = [p for p in required if p["freshness"] == "DELAYED"]
    req_missing = [p for p in required if p["freshness"] == "MISSING"]
    req_live = [p for p in required if p["freshness"] == "LIVE"]

    if req_missing:
        summary_level = "RED"
    elif req_stale or req_delayed:
        summary_level = "YELLOW"
    else:
        summary_level = "GREEN"

    return {
        "summary_level": summary_level,
        "live_count": len(req_live),
        "stale_count": len(req_stale),
        "delayed_count": len(req_delayed),
        "missing_count": len(req_missing),
        "stale_files": req_stale,
        "delayed_files": req_delayed,
        "missing_files": req_missing,
        "optional_stale_count": sum(1 for p in optional if p["freshness"] in ("STALE", "MISSING")),
        "archived_count": len(archived),
        "required": required,
        "optional": optional,
        "archived": archived,
        "all": grouped,
    }


async def build_collector_status() -> dict[str, Any]:
    collectors = [_collector_status(name, path) for name, path in COLLECTOR_SOURCES.items()]
    required = [c for c in collectors if is_required_collector(c["name"])]
    optional = [c for c in collectors if c["classification"] == "OPTIONAL"]
    legacy = [c for c in collectors if c["classification"] in ARCHIVED_CLASSES]

    ws_alive, _ = _ws_alive()
    for collector in required:
        if ws_alive and collector["status"] == "DISCONNECTED":
            collector["status"] = "DEGRADED"
            collector["level"] = "YELLOW"
            collector["latency_note"] = "websocket alive — persistence timestamp lagging"

    # Ribbon: GREEN when ws alive, YELLOW otherwise — never RED (reserved for global CRITICAL)
    level = "GREEN" if ws_alive else "YELLOW"

    return {
        "level": level,
        "collectors": collectors,
        "required": required,
        "optional": optional,
        "legacy": legacy,
    }


def build_feed_confidence(
    collectors: dict[str, Any],
    parquet: dict[str, Any],
) -> dict[str, Any]:
    ws_alive, hb = _ws_alive()
    feed = next((p for p in parquet.get("required", []) if p["file"] == "live_market_feed.parquet"), None)
    candle = next((p for p in parquet.get("required", []) if p["file"] == "candle_structure_memory.parquet"), None)

    ws_level = "GREEN" if ws_alive else "RED"
    ws_reason = "websocket heartbeat fresh" if ws_alive else "no fresh collector heartbeat"

    if feed is None or feed.get("freshness") == "MISSING":
        write_level, write_reason = "RED", "live_market_feed.parquet missing"
    elif feed.get("freshness") == "LIVE":
        write_level, write_reason = "GREEN", "parquet persistence current"
    elif feed.get("freshness") == "DELAYED":
        write_level = "YELLOW" if ws_alive else "RED"
        write_reason = (
            "feed connected — parquet persistence delayed (awaiting candle close)"
            if ws_alive
            else "parquet write delayed"
        )
    else:
        write_level, write_reason = "RED", "parquet persistence stale — no recent writes"

    if candle is None or candle.get("freshness") == "MISSING":
        consume_level, consume_reason = "RED", "candle_structure_memory.parquet missing"
    elif candle.get("freshness") in ("LIVE", "DELAYED"):
        consume_level, consume_reason = "GREEN", "pipeline consuming feed into cognition memory"
    else:
        consume_level, consume_reason = "YELLOW", "runtime consumption delayed"

    overall = "GREEN"
    if ws_level == "RED" and write_level == "RED":
        overall = "RED"
    elif "YELLOW" in (ws_level, write_level, consume_level) or ws_level == "RED":
        overall = "YELLOW"

    return {
        "overall": overall,
        "ws": {"level": ws_level, "label": "WS", "reason": ws_reason, "heartbeat": hb},
        "write": {"level": write_level, "label": "WRITE", "reason": write_reason},
        "consume": {"level": consume_level, "label": "CONSUME", "reason": consume_reason},
    }


async def build_pipeline_status() -> dict[str, Any]:
    try:
        from src.btc_ml.runtime import pipeline as runtime_pipeline

        cycle = getattr(runtime_pipeline, "_CYCLE_COUNT", 0)
    except Exception:
        cycle = 0

    loop_audit = os.path.join("reports", "runtime_loop", "pipeline_cycle_audit.jsonl")
    if cycle == 0 and os.path.exists(loop_audit):
        with open(loop_audit, encoding="utf-8") as handle:
            cycle = sum(1 for line in handle if line.strip())

    engine_state = await read_parquet("runtime_engine_state.parquet", tail=500)
    records = df_records(engine_state)

    recent_cycle_records = records[-17 * 3 :] if records else []
    durations = [float(r["duration"]) for r in recent_cycle_records if r.get("duration") is not None]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else None

    failed = sum(1 for r in records[-100:] if r.get("status") == "FAILED")
    timeouts = sum(1 for r in records[-100:] if r.get("status") == "TIMEOUT")

    blocking_chain_path = os.path.join("reports", "runtime_blocking", "runtime_blocking_chain.json")
    stalled = 0
    if os.path.exists(blocking_chain_path):
        with open(blocking_chain_path, encoding="utf-8") as handle:
            chain = json.load(handle).get("blocking_chain", [])
            stalled = sum(1 for e in chain[-50:] if e.get("event") in ("TIMEOUT", "STALL_DETECTED"))

    heartbeat = "GREEN"
    if timeouts or failed:
        heartbeat = "YELLOW" if failed + timeouts < 3 else "RED"

    return {
        "current_cycle": cycle,
        "average_cycle_duration_s": avg_duration,
        "uptime_seconds": round(time.time() - psutil.boot_time(), 1),
        "failed_engine_count": failed,
        "timeout_count": timeouts,
        "stalled_engine_count": stalled,
        "heartbeat_level": heartbeat,
        "active_state": "CYCLING" if cycle > 0 else "IDLE",
    }


def _build_health_summary(
    engines: list[dict[str, Any]],
    parquet: dict[str, Any],
    collectors: dict[str, Any],
    pipeline: dict[str, Any],
    feed_confidence: dict[str, Any],
    ws_connected: bool = True,
) -> dict[str, Any]:
    ws_alive, _ = _ws_alive()
    deferred = [e for e in engines if e["status"] == "DEFERRED"]
    required_failed = [
        e for e in engines
        if is_required_engine(e["engine"]) and e["status"] in ("FAILED", "TIMEOUT")
    ]

    feed = next((p for p in parquet.get("required", []) if p["file"] == "live_market_feed.parquet"), None)
    feed_missing = feed is not None and feed.get("freshness") == "MISSING"
    feed_delayed = feed is not None and feed.get("freshness") in ("DELAYED", "STALE")
    feed_stale = feed is not None and feed.get("freshness") == "STALE"

    required_coll = next((c for c in collectors.get("required", []) if c["name"] == "binance_live_feed"), None)
    orchestration_active = _orchestration_active(pipeline, engines)
    collector_truly_dead = _collector_truly_dead(
        required_coll, ws_alive, orchestration_active=orchestration_active
    )
    collector_degraded = (
        (required_coll and required_coll["status"] in ("DEGRADED", "DISCONNECTED"))
        or (not ws_alive and orchestration_active)
    )

    pipeline_cycling = _pipeline_is_cycling(pipeline)
    orchestration_failure = pipeline.get("timeout_count", 0) >= 3
    pipeline_stopped = (
        pipeline.get("current_cycle", 0) > 0
        and not pipeline_cycling
        and pipeline.get("stalled_engine_count", 0) > 0
    )

    missing_required = parquet.get("missing_files", [])
    no_ingestion = _no_live_ingestion(ws_alive, feed)

    critical_reasons: list[str] = []
    degraded_reasons: list[str] = []

    # --- CRITICAL: hard failures only ---
    if collector_truly_dead:
        critical_reasons.append("Required collector dead: binance_live_feed (no websocket beyond timeout)")
    for p in missing_required:
        critical_reasons.append(f"Required parquet missing: {p['file']}")
    if no_ingestion:
        critical_reasons.append("No live ingestion — websocket down and feed unavailable")
    if required_failed:
        names = ", ".join(e["engine"] for e in required_failed)
        critical_reasons.append(f"Required engine failure: {names}")
    if orchestration_failure:
        critical_reasons.append(f"Pipeline orchestration failure ({pipeline['timeout_count']} timeouts)")
    if pipeline_stopped:
        critical_reasons.append("Pipeline stopped — orchestration stalled")

    # --- DEGRADED: investigate later, never CRITICAL ---
    if ws_alive and feed_delayed:
        degraded_reasons.append("Feed connected but parquet persistence delayed")
    elif feed_delayed and not ws_alive:
        degraded_reasons.append("Live feed delayed — websocket unstable")
    if collector_degraded and not collector_truly_dead:
        if not ws_alive and orchestration_active:
            degraded_reasons.append("Collector heartbeat absent — pipeline appears active")
        elif ws_alive:
            degraded_reasons.append("Collector reconnecting or persistence timestamp lagging")
        else:
            degraded_reasons.append("Collector reconnecting or feed latency elevated")
    if not (ws_alive and feed_delayed):
        for p in parquet.get("stale_files", []):
            if p.get("classification") in ARCHIVED_CLASSES or p.get("ignored_by_health"):
                continue
            tier = _parquet_stale_tier(p.get("age_seconds"))
            if tier == "DEGRADED":
                degraded_reasons.append(f"Required parquet stale (>2h): {p['file']}")
    for p in parquet.get("delayed_files", []):
        if p["file"] != "live_market_feed.parquet" or not ws_alive:
            degraded_reasons.append(f"Required parquet delayed: {p['file']}")
    if feed_stale and ws_alive:
        degraded_reasons.append("Websocket alive — awaiting parquet catch-up")
    if not pipeline_cycling and pipeline.get("current_cycle", 0) == 0:
        degraded_reasons.append("Pipeline idle — awaiting first cycle")
    if pipeline.get("timeout_count", 0) in (1, 2):
        degraded_reasons.append(f"Recent engine timeout(s): {pipeline['timeout_count']}")

    optional_offline = sum(1 for c in collectors["collectors"] if c.get("status") == "OPTIONAL_OFFLINE")

    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    if mem > 95:
        critical_reasons.append(f"Host memory critical ({mem:.0f}%)")
    elif mem > 90:
        degraded_reasons.append(f"Host memory elevated ({mem:.0f}%)")
    if disk > 95:
        critical_reasons.append(f"Host disk critical ({disk:.0f}%)")
    elif disk > 90:
        degraded_reasons.append(f"Host disk elevated ({disk:.0f}%)")

    if critical_reasons:
        level = "CRITICAL"
        primary_reason = critical_reasons[0]
        reasons = critical_reasons + [r for r in degraded_reasons if r not in critical_reasons]
    elif degraded_reasons:
        level = "DEGRADED"
        primary_reason = degraded_reasons[0]
        reasons = degraded_reasons
    else:
        level = "HEALTHY"
        primary_reason = "Required runtime infrastructure nominal"
        reasons = [primary_reason]

    return {
        "level": level,
        "primary_reason": primary_reason,
        "reasons": reasons,
        "critical_reasons": critical_reasons,
        "degraded_reasons": degraded_reasons,
        "cpu_percent": psutil.cpu_percent(interval=0.05),
        "memory_percent": mem,
        "disk_percent": disk,
        "deferred_engine_count": len(deferred),
        "optional_offline_count": optional_offline,
    }


def _build_operational_alerts(
    engines: list[dict[str, Any]],
    parquet: dict[str, Any],
    collectors: dict[str, Any],
    pipeline: dict[str, Any],
    health: dict[str, Any],
    ws_connected: bool,
    *,
    orchestration_active: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    actionable: list[dict[str, Any]] = []
    informational: list[dict[str, Any]] = []
    now = datetime.now().isoformat()

    for engine in engines:
        if not is_required_engine(engine["engine"]) or engine.get("ignored_by_health"):
            continue
        if engine["status"] == "TIMEOUT":
            actionable.append(
                {
                    "id": f"timeout:{engine['engine']}",
                    "severity": "CRITICAL",
                    "type": "engine_timeout",
                    "message": f"Required engine timed out: {engine['engine']}",
                    "timestamp": now,
                    "actionable": True,
                }
            )
        elif engine["status"] == "FAILED":
            actionable.append(
                {
                    "id": f"failed:{engine['engine']}",
                    "severity": "CRITICAL",
                    "type": "engine_failed",
                    "message": f"Required engine failed: {engine['engine']}",
                    "timestamp": now,
                    "actionable": True,
                }
            )
        elif engine["status"] == "STALLED" and not engine.get("ignored_by_health"):
            actionable.append(
                {
                    "id": f"stalled:{engine['engine']}",
                    "severity": "WARNING",
                    "type": "stalled_engine",
                    "message": f"Required engine stalled: {engine['engine']}",
                    "timestamp": now,
                    "actionable": True,
                }
            )

    ws_alive, _ = _ws_alive()

    for p in parquet.get("stale_files", []):
        if p.get("classification") in ARCHIVED_CLASSES or p.get("ignored_by_health"):
            continue
        tier = _parquet_stale_tier(p.get("age_seconds"))
        alert = {
            "id": f"stale:{p['file']}",
            "type": "stale_parquet",
            "message": f"Required parquet stale: {p['file']}",
            "timestamp": now,
        }
        if tier == "INFO":
            informational.append({**alert, "severity": "INFO", "actionable": False, "ignored_by_health": True})
        elif tier == "WARNING":
            informational.append({**alert, "severity": "WARNING", "actionable": False, "ignored_by_health": True})
        else:
            informational.append({**alert, "severity": "WARNING", "actionable": False, "ignored_by_health": True})

    for p in parquet.get("delayed_files", []):
        informational.append(
            {
                "id": f"delayed:{p['file']}",
                "severity": "INFO",
                "type": "delayed_parquet",
                "message": f"Required parquet delayed: {p['file']}",
                "timestamp": now,
                "actionable": False,
                "ignored_by_health": True,
            }
        )

    for collector in collectors.get("required", []):
        if _collector_truly_dead(collector, ws_alive, orchestration_active=orchestration_active):
            actionable.append(
                {
                    "id": f"collector:{collector['name']}",
                    "severity": "CRITICAL",
                    "type": "collector_disconnected",
                    "message": f"Required collector dead: {collector['name']}",
                    "timestamp": now,
                    "actionable": True,
                }
            )
        elif collector["status"] in ("DEGRADED", "DISCONNECTED"):
            informational.append(
                {
                    "id": f"collector:{collector['name']}",
                    "severity": "INFO",
                    "type": "feed_latency",
                    "message": f"Collector persistence lag: {collector['name']} ({collector.get('latency_note')})",
                    "timestamp": now,
                    "actionable": False,
                }
            )

    for collector in collectors.get("optional", []):
        if collector.get("status") == "OPTIONAL_OFFLINE":
            informational.append(
                {
                    "id": f"collector:{collector['name']}",
                    "severity": "INFO",
                    "type": "optional_collector_offline",
                    "message": f"Optional collector offline: {collector['name']}",
                    "timestamp": now,
                    "ignored_by_health": True,
                    "actionable": False,
                }
            )

    if not ws_connected:
        informational.append(
            {
                "id": "dashboard_ws_disconnected",
                "severity": "INFO",
                "type": "dashboard_websocket",
                "message": "Dashboard websocket disconnected (runtime may still be healthy)",
                "timestamp": now,
                "actionable": False,
            }
        )

    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for alert in actionable:
        key = alert.get("message", alert["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alert)
    deduped.sort(key=lambda a: order.get(a["severity"], 9))
    return {"actionable": deduped, "informational": informational, "all": deduped + informational}


def _ribbon(
    runtime_level: str,
    feed_level: str,
    pipeline_level: str,
    collectors_level: str,
    parquet_level: str,
    alert_count: int,
    health_level: str,
) -> list[dict[str, Any]]:
    return [
        {"key": "runtime", "label": "RUNTIME", "level": runtime_level},
        {"key": "feed", "label": "FEED", "level": feed_level},
        {"key": "pipeline", "label": "PIPELINE", "level": pipeline_level},
        {"key": "collectors", "label": "COLLECTORS", "level": collectors_level},
        {"key": "parquet", "label": "PARQUET", "level": parquet_level},
        {"key": "alerts", "label": "ALERTS", "value": str(alert_count), "level": "RED" if alert_count else "GREEN"},
        {"key": "health", "label": "HEALTH", "level": health_level},
    ]


async def build_ops_snapshot(ws_connected: bool = True) -> dict[str, Any]:
    ws_alive, _ = _ws_alive()
    collectors = await build_collector_status()
    parquet = await build_parquet_status(ws_alive=ws_alive)
    feed_confidence = build_feed_confidence(collectors, parquet)
    engines = await build_engine_status(parquet=parquet, collectors=collectors)
    pipeline = await build_pipeline_status()

    feed = next((p for p in parquet.get("required", []) if p["file"] == "live_market_feed.parquet"), None)
    parquet_writing = feed is not None and feed.get("freshness") in ("LIVE", "DELAYED")
    pipeline_cycling = pipeline.get("active_state") == "CYCLING"

    stability = update_stability(
        pipeline_cycle=pipeline.get("current_cycle", 0),
        pipeline_cycling=pipeline_cycling,
        collector_connected=collectors["level"] == "GREEN",
        ws_connected=ws_alive,
        parquet_writing=parquet_writing,
        pipeline_timeout_count=pipeline.get("timeout_count", 0),
        pipeline_stalled=not pipeline_cycling and pipeline.get("current_cycle", 0) == 0,
    )

    health = _build_health_summary(engines, parquet, collectors, pipeline, feed_confidence, ws_connected)
    orchestration_active = _orchestration_active(pipeline, engines)
    alert_groups = _build_operational_alerts(
        engines, parquet, collectors, pipeline, health, ws_connected,
        orchestration_active=orchestration_active,
    )

    feed_collector = next((c for c in collectors["collectors"] if c["name"] == "binance_live_feed"), None)
    feed_level = feed_confidence["overall"]

    required_failed = [
        e for e in engines
        if is_required_engine(e["engine"]) and e["status"] in ("FAILED", "TIMEOUT")
    ]
    runtime_level = "RED" if required_failed else ("YELLOW" if health["level"] == "DEGRADED" else "GREEN")

    pipeline_cycling = _pipeline_is_cycling(pipeline)
    pipeline_level = "GREEN" if pipeline_cycling else "YELLOW"
    if pipeline.get("timeout_count", 0) >= 3:
        pipeline_level = "RED"

    feed_level = feed_confidence["overall"]
    if feed_level == "RED" and health["level"] != "CRITICAL":
        feed_level = "YELLOW"

    parquet_level = parquet["summary_level"]
    if parquet_level == "RED" and parquet.get("missing_count", 0) == 0:
        parquet_level = "YELLOW"

    critical_alerts = [a for a in alert_groups["actionable"] if a["severity"] == "CRITICAL"]

    ribbon = _ribbon(
        runtime_level=runtime_level,
        feed_level=feed_level,
        pipeline_level=pipeline_level,
        collectors_level=collectors["level"],
        parquet_level=parquet_level,
        alert_count=len(critical_alerts),
        health_level="GREEN" if health["level"] == "HEALTHY" else ("YELLOW" if health["level"] == "DEGRADED" else "RED"),
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "ribbon": ribbon,
        "engines": engines,
        "parquet": parquet,
        "collectors": collectors,
        "pipeline": pipeline,
        "feed_confidence": feed_confidence,
        "stability": stability,
        "health": health,
        "alerts": alert_groups["all"],
        "alert_groups": alert_groups,
        "manifest": manifest_summary(),
        "classification": {
            "required_only_health": True,
            "archived_parquet_count": parquet.get("archived_count", 0),
            "optional_offline_count": health.get("optional_offline_count", 0),
            "deferred_engine_count": health.get("deferred_engine_count", 0),
        },
    }
