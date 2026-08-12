"""Read-only Shadow Auction dashboard summary (bounded; no full JSONL scans)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _tail_last_jsonl(path: Path, *, max_bytes: int = 65536) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # drop partial first line
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = [ln for ln in chunk.splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            return row
    return None


def _pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, TypeError, OSError):
        return False


def _uptime_sec(started_at: Any, updated_at: Any) -> float | None:
    start = _parse_ts(started_at)
    end = _parse_ts(updated_at) or datetime.now(timezone.utc)
    if start is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_data_root(repo: Path) -> Path:
    cfg = _read_json(repo / "config" / "shadow_auction.json") or {}
    raw = cfg.get("data_root") or "/Volumes/MaksTiger/btc-ml/shadow_auction"
    return Path(str(raw)).expanduser()


def build_dashboard_snapshot(*, repo: Path | None = None) -> dict[str, Any]:
    """Assemble a compact, read-only Shadow Auction panel payload."""
    root = repo or Path(__file__).resolve().parents[4]
    cfg = _read_json(root / "config" / "shadow_auction.json") or {}
    data_root = resolve_data_root(root)
    health = _read_json(data_root / "health" / "health.json") or {}
    integrity = _read_json(data_root / "health" / "integrity_audit_latest.json") or {}
    latest_verdict = _tail_last_jsonl(data_root / "memory" / "checkpoint_verdict_memory.jsonl")
    latest_postmortem = _tail_last_jsonl(data_root / "memory" / "postmortem_memory.jsonl")
    latest_outcome = _tail_last_jsonl(data_root / "memory" / "shadow_outcome_memory.jsonl")

    pid = health.get("pid")
    alive = bool(pid is not None and _pid_alive(pid))
    status = str(health.get("status") or ("STOPPED" if not alive else "UNKNOWN"))
    if not alive and status == "RUNNING":
        status = "STOPPED"

    def _tf(key: str) -> dict[str, Any]:
        return {
            "auction_family": health.get(f"{key}_auction_family") or health.get(f"{key}_family"),
            "episode_phase": health.get(f"{key}_episode_phase"),
            "episode_id": health.get(f"{key}_episode_id"),
            "last_event_timestamp": health.get(f"{key}_last_event_timestamp"),
            "source_lag_sec": health.get(f"{key}_source_lag_sec"),
        }

    funnel = integrity.get("funnel") if isinstance(integrity.get("funnel"), dict) else {}
    counts = integrity.get("counts") if isinstance(integrity.get("counts"), dict) else {}

    research_checkpoint = None
    if latest_verdict:
        research_checkpoint = {
            "checkpoint_type": latest_verdict.get("checkpoint_type"),
            "canonical_timeframe": latest_verdict.get("canonical_timeframe"),
            "canonical_side": latest_verdict.get("canonical_side"),
            "checkpoint_timestamp": latest_verdict.get("canonical_timestamp")
            or latest_verdict.get("checkpoint_timestamp"),
            "checkpoint_verdict": latest_verdict.get("checkpoint_verdict"),
            "coverage_status": latest_verdict.get("coverage_status"),
            "label": "Research comparison",
        }

    postmortem = None
    if latest_postmortem and str(latest_postmortem.get("postmortem_status") or "").upper() in {
        "COMPLETE",
        "COMPLETED",
    }:
        postmortem = {
            "eventual_resolution": latest_postmortem.get("eventual_anchor_resolution"),
            "retrospective_structure_label": latest_postmortem.get("retrospective_structure_label"),
            "time_to_resolution_sec": latest_postmortem.get("time_to_resolution_sec"),
            "max_propagation_depth": latest_postmortem.get("max_propagation_depth"),
            "postmortem_status": latest_postmortem.get("postmortem_status"),
        }

    economic = None
    if latest_outcome or any(
        health.get(k)
        for k in (
            "shadow_avoided_loss_count",
            "shadow_missed_win_count",
            "shadow_better_entry_count",
            "canonical_better_entry_count",
        )
    ):
        economic = {
            "SHADOW_AVOIDED_LOSS": health.get("shadow_avoided_loss_count"),
            "SHADOW_MISSED_WIN": health.get("shadow_missed_win_count"),
            "SHADOW_BETTER_ENTRY": health.get("shadow_better_entry_count"),
            "CANONICAL_BETTER_ENTRY": health.get("canonical_better_entry_count"),
        }

    return {
        "mode": "RESEARCH_OBSERVER",
        "read_only": True,
        "no_execution": True,
        "observer_only": bool(health.get("observer_only", cfg.get("observer_only", True))),
        "enforcement_enabled": bool(
            health.get("enforcement_enabled", cfg.get("enforcement_enabled", False))
        ),
        "status": status,
        "process_health": "RUNNING" if alive else "STOPPED",
        "alive": alive,
        "pid": pid,
        "uptime_seconds": _uptime_sec(health.get("process_started_at"), health.get("updated_at")),
        "process_started_at": health.get("process_started_at"),
        "updated_at": health.get("updated_at"),
        "source_lag_ms": health.get("source_lag_ms"),
        "last_source_timestamp": health.get("last_source_timestamp"),
        "data_root": str(data_root),
        "timeframes": {
            "M15": _tf("m15"),
            "M30": _tf("m30"),
            "H1": _tf("h1"),
            "H4": _tf("h4"),
        },
        "hierarchy": {
            "hierarchy_state": health.get("hierarchy_state"),
            "m15_m30_relation": health.get("m15_m30_relation"),
            "m30_h1_relation": health.get("m30_h1_relation"),
            "h1_h4_relation": health.get("h1_h4_relation"),
            "propagation_direction": health.get("propagation_direction"),
            "propagation_depth": health.get("propagation_depth"),
            "local_vs_structural_state": health.get("local_vs_structural_state"),
            "conflict_state": health.get("conflict_state"),
        },
        "research_checkpoint": research_checkpoint,
        "funnel": {
            "canonical_checkpoints": health.get("checkpoint_count")
            or counts.get("aes4_checkpoint_count")
            or funnel.get("contexts_checkpointed"),
            "checkpoint_verdicts": health.get("verdict_count")
            or counts.get("aes5_verdict_count")
            or funnel.get("checkpoint_verdicts"),
            "closed_cases_evaluated": health.get("closed_cases_evaluated")
            or funnel.get("closed_cases_evaluated"),
            "open_cases_waiting_close": health.get("open_cases_waiting_close")
            or funnel.get("open_cases_waiting_close"),
            "coverage_complete": health.get("complete_coverage_count")
            or funnel.get("complete_coverage_cases"),
            "coverage_partial": health.get("partial_coverage_count")
            or funnel.get("partial_coverage_cases"),
            "coverage_stale": health.get("stale_coverage_count")
            or funnel.get("stale_coverage_cases"),
            "coverage_missing": health.get("missing_coverage_count")
            or funnel.get("missing_coverage_cases"),
            "postmortem_complete": health.get("postmortems_complete")
            or funnel.get("postmortems_complete"),
            "postmortem_waiting": health.get("postmortems_waiting")
            or funnel.get("postmortems_waiting"),
            "postmortem_expired": health.get("postmortems_expired")
            or funnel.get("postmortems_expired"),
        },
        "verdicts": {
            "SUPPORT": health.get("support_verdicts"),
            "WAIT": health.get("wait_verdicts"),
            "REJECT": health.get("reject_verdicts"),
            "OPPOSITE": health.get("opposite_verdicts"),
            "UNRESOLVED": health.get("unresolved_verdicts"),
        },
        "economic_research": economic,
        "postmortem": postmortem,
        "integrity": {
            "status": integrity.get("status") or "UNKNOWN",
            "lookahead_violations": integrity.get("lookahead_violations", 0),
            "duplicates": integrity.get("duplicates", 0),
            "payload_conflicts": integrity.get("payload_conflicts", 0),
            "broken_references": integrity.get("broken_references", 0),
            "ordering_warnings": integrity.get("ordering_violations", 0),
            "fail_count": integrity.get("fail_count", 0),
            "warning_count": integrity.get("warning_count", 0),
        },
        "resources": {
            "rss_memory_mb": health.get("rss_memory_mb"),
            "shadow_total_bytes": health.get("shadow_total_bytes"),
            "disk_free_bytes": health.get("disk_free_bytes") or health.get("storage_free_bytes"),
            "storage_status": health.get("storage_status"),
            "shadow_growth_1h": health.get("shadow_growth_1h"),
            "shadow_growth_24h": health.get("shadow_growth_24h"),
            "storage_mounted": health.get("storage_mounted"),
            "storage_writable": health.get("storage_writable"),
        },
        "source_path": str((data_root / "health" / "health.json")),
    }
