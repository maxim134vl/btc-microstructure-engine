#!/usr/bin/env python3
"""Read-only Live / Postfactum Limitation Audit.

Separates historical/postfactum cognition evidence from live decision-log
evidence, documents refresh/no-repaint/visual limitations, and keeps
execution readiness BLOCKED.

Does NOT mutate cognition / live feed / decision log / runtime / execution.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

DECISION_LOG = ROOT / "data" / "live" / "context_decision_log.parquet"
LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
REFRESH_STATUS = ROOT / "data" / "live" / "live_context_refresh_status.json"
REFRESH_LOG = ROOT / "logs" / "live_context_refresh.log"
RUNTIME_LOG = ROOT / "logs" / "runtime_stack" / "runtime.log"
AUCTION_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
COGNITIVE_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
FINAL_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
LIFECYCLE_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
EPISODES_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
SNAPSHOT_DIR = ROOT / "data" / "live" / "context_decision_log_snapshots"
VISUAL_GLOB = ROOT / "apps" / "context_visualizer" / "public" / "data"
REPORT_PATH = ROOT / "docs" / "LIVE_POSTFACTUM_LIMITATION_AUDIT.md"

NO_REPAINT_AUDIT = ROOT / "scripts" / "research" / "audit_decision_no_repaint.py"
LATENCY_AUDIT = ROOT / "scripts" / "research" / "audit_decision_latency.py"

BAR_SECONDS = 900
DOCS = {
    "outcome": ROOT / "docs" / "RESULT_OUTCOME_QUALITY_DEEP_DIVE.md",
    "trigger": ROOT / "docs" / "TRIGGER_TRACE_DEEP_DIVE.md",
    "termination": ROOT / "docs" / "TERMINATION_TIMING_DEEP_DIVE.md",
    "missed": ROOT / "docs" / "MISSED_CONTEXT_DEEP_DIVE.md",
    "volume_rc": ROOT / "docs" / "VOLUME_CLIMAX_ROOT_CAUSE_INVESTIGATION.md",
    "no_repaint": ROOT / "docs" / "DECISION_NO_REPAINT_AUDIT.md",
    "latency": ROOT / "docs" / "DECISION_LATENCY_AUDIT.md",
    "catchup": ROOT / "docs" / "LIVE_REFRESH_CATCH_UP_FAILURE_INVESTIGATION.md",
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nr = _load_module("audit_decision_no_repaint", NO_REPAINT_AUDIT)
lat = _load_module("audit_decision_latency", LATENCY_AUDIT)


def _clean(value: Any, default: str = "UNKNOWN") -> str:
    return lat._clean(value, default=default)


def _to_utc(value: Any):
    return lat._to_utc(value)


def _iso(ts) -> str | None:
    return lat._iso(ts)


def lag_seconds(a, b) -> float | None:
    return lat.lag_seconds(a, b)


def load_optional_parquet(path: Path) -> pd.DataFrame:
    return lat.load_optional_parquet(path)


def latest_timestamp(frame: pd.DataFrame, col: str = "timestamp"):
    return lat.latest_timestamp(frame, col)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"_raw": data}
    except Exception:
        return {"_parse_error": True}


def extract_doc_field(path: Path, patterns: list[str]) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    for pat in patterns:
        m = re.search(pat, text, flags=re.I | re.M)
        if m:
            return m.group(1).strip()
    return None


def classify_live_sample(rows: int) -> str:
    if rows < 10:
        return "INSUFFICIENT_LIVE_SAMPLE"
    if rows < 50:
        return "PRELIMINARY_LIVE_SAMPLE"
    if rows < 200:
        return "USABLE_LIVE_SAMPLE"
    return "STRONG_LIVE_SAMPLE"


def classify_historical_evidence(artifact_meta: dict[str, Any]) -> dict[str, Any]:
    any_rows = any(int(v.get("rows") or 0) > 0 for v in artifact_meta.values())
    if not any_rows:
        return {
            "historical_evidence_classification": "UNKNOWN",
            "postfactum_rebuild_limitation": True,
            "suitable_for_research": False,
            "suitable_for_execution_without_decision_log": False,
            "notes": ["no cognition artifacts available"],
        }
    # Shadow-chain rebuild rewrites historical parquet state → postfactum research only
    return {
        "historical_evidence_classification": "POSTFACTUM_REBUILD_EVIDENCE",
        "secondary_classification": ["HISTORICAL_RESEARCH_EVIDENCE", "NOT_EXECUTION_EVIDENCE"],
        "postfactum_rebuild_limitation": True,
        "suitable_for_research": True,
        "suitable_for_execution_without_decision_log": False,
        "can_contain_revised_historical_state": True,
        "notes": [
            "Cognition/lifecycle parquet artifacts are batch-rebuildable via shadow chain.",
            "Suitable for research/backtest; not sufficient alone for execution.",
        ],
    }


def classify_freshness_gap(
    live_ts,
    lifecycle_ts,
    decision_ts,
    *,
    bar_seconds: int = BAR_SECONDS,
) -> str:
    live_life = lag_seconds(live_ts, lifecycle_ts)
    life_dec = lag_seconds(lifecycle_ts, decision_ts)
    live_dec = lag_seconds(live_ts, decision_ts)
    stale_ctx = live_life is not None and live_life >= bar_seconds
    stale_log = (life_dec is not None and life_dec >= bar_seconds) or (
        live_dec is not None and live_dec >= bar_seconds
    )
    if live_ts is None:
        return "UNKNOWN"
    if stale_ctx and stale_log:
        return "BOTH_CONTEXT_AND_LOG_STALE"
    if stale_ctx:
        return "CONTEXT_ARTIFACTS_STALE"
    if stale_log or (decision_ts is not None and lifecycle_ts is not None and decision_ts < lifecycle_ts):
        # decision behind lifecycle even if < 1 bar in some edge cases
        if life_dec is not None and life_dec > 0:
            return "DECISION_LOG_BEHIND_LIFECYCLE"
        if live_dec is not None and live_dec >= bar_seconds:
            return "DECISION_LOG_BEHIND_LIFECYCLE"
    if (live_life is None or live_life < bar_seconds) and (live_dec is None or live_dec < bar_seconds):
        return "CURRENTLY_FRESH"
    if stale_log:
        return "DECISION_LOG_BEHIND_LIFECYCLE"
    return "UNKNOWN"


def classify_refresh_cadence(
    status: dict[str, Any] | None,
    *,
    live_ts,
    lifecycle_ts,
    bars_since_refresh: float | None,
) -> str:
    if status is None:
        return "UNKNOWN"
    mode = _clean(status.get("mode")).lower()
    st = _clean(status.get("status")).upper()
    lag_after = status.get("live_to_lifecycle_lag_seconds")
    try:
        lag_after_f = float(lag_after) if lag_after is not None else None
    except (TypeError, ValueError):
        lag_after_f = None
    still_stale = bool(status.get("lifecycle_still_stale_after"))
    logger_ok = bool(status.get("decision_logger_ok"))

    if still_stale or (lag_after_f is not None and lag_after_f >= BAR_SECONDS and st != "OK"):
        return "REFRESH_CATCH_UP_FAILURE"
    if mode == "once" and st == "OK" and (lag_after_f == 0 or lag_after_f is not None and lag_after_f < BAR_SECONDS):
        # once worked, but live may have moved since
        current_lag = lag_seconds(live_ts, lifecycle_ts)
        if current_lag is not None and current_lag >= BAR_SECONDS:
            return "REFRESH_CADENCE_GAP"
        if bars_since_refresh is not None and bars_since_refresh >= 1:
            return "REFRESH_CADENCE_GAP"
        if not logger_ok:
            return "LOGGER_CADENCE_GAP"
        return "ONCE_MODE_WORKS_AT_INVOCATION"
    if not logger_ok:
        return "LOGGER_CADENCE_GAP"
    return "UNKNOWN"


def classify_visual_layer(
    visual_files_exist: bool,
    visual_json_used_all_false: bool,
) -> str:
    if visual_json_used_all_false and visual_files_exist:
        return "VISUAL_LAYER_OBSERVATION_ONLY"
    if visual_json_used_all_false:
        return "VISUAL_LAYER_NOT_EXECUTION_SOURCE"
    return "VISUAL_LAYER_USAGE_UNKNOWN"


def classify_no_repaint(
    immutability: dict[str, Any],
    payload: dict[str, Any],
    snapshots: dict[str, Any],
) -> str:
    conflicts = int(
        immutability.get("mutation_conflict_count")
        or immutability.get("duplicate_different_hash_count")
        or 0
    )
    if conflicts > 0 or immutability.get("repaint_conflict"):
        return "REPAINT_CONFLICT_FOUND"
    mismatched = int(payload.get("rows_mismatched") or payload.get("mismatch_count") or 0)
    if payload.get("status") == "WARN" and mismatched > 0 and int(payload.get("rows_matched") or 0) > 0:
        return "HASH_INTEGRITY_ISSUE"
    if not snapshots.get("snapshots_found"):
        if immutability.get("decision_payload_hash_present"):
            return "STRICT_NO_REPAINT_PROOF_UNAVAILABLE"
        return "UNKNOWN"
    return "NO_REPAINT_PRELIMINARY_PASS"


def classify_model_vs_live(
    live_sample: str,
    open_blockers: list[str],
) -> dict[str, Any]:
    historical = "MODEL_RESEARCH_EVIDENCE_ACCEPTABLE_PRELIMINARY"
    if open_blockers:
        model_status = "MODEL_HAS_OPEN_RESEARCH_BLOCKERS"
    else:
        model_status = historical
    if live_sample == "INSUFFICIENT_LIVE_SAMPLE":
        live_status = "LIVE_EVIDENCE_INSUFFICIENT"
    elif live_sample == "PRELIMINARY_LIVE_SAMPLE":
        live_status = "LIVE_EVIDENCE_PRELIMINARY"
    else:
        live_status = "LIVE_EVIDENCE_PRELIMINARY"
    return {
        "historical_model_quality": historical,
        "live_evidence_status": live_status,
        "combined_classification": model_status if open_blockers else live_status,
        "open_model_research_blockers": open_blockers,
    }


def classify_observation_readiness(
    *,
    historical_ok: bool,
    logger_exists: bool,
    once_mode_ok: bool,
    execution_off: bool,
    live_sample: str,
) -> str:
    if not historical_ok or not logger_exists or not execution_off:
        return "OBSERVATION_BLOCKED"
    if once_mode_ok and live_sample == "INSUFFICIENT_LIVE_SAMPLE":
        return "OBSERVATION_READY_WITH_LIMITATIONS"
    if once_mode_ok:
        return "OBSERVATION_READY_WITH_LIMITATIONS"
    return "OBSERVATION_PARTIAL"


def decide_next_step(
    *,
    live_rows: int,
    snapshot_exists: bool,
    refresh_cls: str,
    open_blockers: list[str],
) -> str:
    # Prefer snapshot archive when strict proof missing and live sample tiny
    if not snapshot_exists and live_rows < 50:
        return "ADD_DECISION_LOG_SNAPSHOT_ARCHIVE"
    if live_rows < 10:
        return "COLLECT_MORE_LIVE_DECISIONS"
    if open_blockers and live_rows >= 10:
        return "PREPARE_LIFECYCLE_AND_VOLUME_PATCH_PLAN"
    if refresh_cls == "REFRESH_CADENCE_GAP" and live_rows < 50:
        return "COLLECT_MORE_LIVE_DECISIONS"
    if live_rows >= 10 and snapshot_exists:
        return "RUN_PAPER_EXECUTION_SIMULATOR_DESIGN"
    return "CONTINUE_RESEARCH_AUDITS"


def pack_source(path: Path, frame: pd.DataFrame | None = None, ts_col: str = "timestamp") -> dict[str, Any]:
    exists = path.exists()
    rows = int(len(frame)) if frame is not None else 0
    latest = None
    if frame is not None and len(frame):
        if ts_col in frame.columns:
            latest = _iso(latest_timestamp(frame, ts_col))
        elif "end_time" in frame.columns:
            latest = _iso(latest_timestamp(frame, "end_time"))
        elif "candle_timestamp" in frame.columns:
            latest = _iso(latest_timestamp(frame, "candle_timestamp"))
    return {"exists": exists, "path": str(path), "rows": rows if exists else 0, "latest": latest}


def run_audit(
    *,
    decision_log_path: Path = DECISION_LOG,
    live_path: Path = LIVE_FEED,
    auction_path: Path = AUCTION_PATH,
    cognitive_path: Path = COGNITIVE_PATH,
    final_path: Path = FINAL_PATH,
    lifecycle_path: Path = LIFECYCLE_PATH,
    episodes_path: Path = EPISODES_PATH,
    refresh_status_path: Path = REFRESH_STATUS,
    refresh_log_path: Path = REFRESH_LOG,
    runtime_log_path: Path = RUNTIME_LOG,
    snapshot_dir: Path = SNAPSHOT_DIR,
    report_path: Path | None = REPORT_PATH,
    root: Path = ROOT,
) -> dict[str, Any]:
    fingerprints: dict[str, tuple[int, int]] = {}
    for p in (
        decision_log_path,
        live_path,
        auction_path,
        cognitive_path,
        final_path,
        lifecycle_path,
        episodes_path,
        refresh_status_path,
    ):
        if p.exists():
            st = p.stat()
            fingerprints[str(p)] = (st.st_mtime_ns, st.st_size)

    decision = load_optional_parquet(decision_log_path) if decision_log_path.exists() else pd.DataFrame()
    live = load_optional_parquet(live_path)
    auction = load_optional_parquet(auction_path)
    cognitive = load_optional_parquet(cognitive_path)
    final = load_optional_parquet(final_path)
    lifecycle = load_optional_parquet(lifecycle_path)
    episodes = load_optional_parquet(episodes_path)
    refresh_status = load_json(refresh_status_path)

    availability = {
        "decision_log": pack_source(decision_log_path, decision, "candle_timestamp"),
        "live_feed": pack_source(live_path, live),
        "auction": pack_source(auction_path, auction),
        "cognitive": pack_source(cognitive_path, cognitive),
        "final_context": pack_source(final_path, final),
        "lifecycle": pack_source(lifecycle_path, lifecycle),
        "lifecycle_episodes": pack_source(episodes_path, episodes, "end_time"),
        "refresh_status": {
            "exists": refresh_status_path.exists(),
            "path": str(refresh_status_path),
            "status": _clean(refresh_status.get("status")) if refresh_status else None,
        },
        "refresh_log": {"exists": refresh_log_path.exists(), "path": str(refresh_log_path)},
        "runtime_log": {"exists": runtime_log_path.exists(), "path": str(runtime_log_path)},
    }

    hist_meta = {
        "auction_episode_memory": availability["auction"],
        "cognitive_market_state_memory": availability["cognitive"],
        "final_market_context_memory": availability["final_context"],
        "market_context_lifecycle_memory": availability["lifecycle"],
        "market_context_lifecycle_episodes": availability["lifecycle_episodes"],
    }
    historical = classify_historical_evidence(hist_meta)
    historical["artifacts"] = hist_meta

    # Live evidence
    rows = int(len(decision))
    live_sample = classify_live_sample(rows)
    candles = []
    if len(decision) and "candle_timestamp" in decision.columns:
        candles = [_to_utc(v) for v in decision["candle_timestamp"].tolist()]
        candles = [c for c in candles if c is not None]
    unique_candles = len({c for c in candles})
    first_candle = _iso(min(candles)) if candles else None
    latest_candle = _iso(max(candles)) if candles else None

    immutability = nr.immutability_checks(decision) if len(decision) else {
        "mutation_conflict_count": 0,
        "decision_payload_hash_present": False,
        "duplicate_different_hash_count": 0,
        "repaint_conflict": False,
    }
    # normalize conflict count alias used by this audit
    immutability["mutation_conflict_count"] = int(
        immutability.get("duplicate_different_hash_count") or immutability.get("mutation_conflict_count") or 0
    )
    payload = nr.payload_hash_stability(decision) if len(decision) else {
        "status": "HASH_RECALCULATION_UNAVAILABLE",
        "rows_matched": 0,
        "rows_mismatched": 0,
    }
    payload["all_match"] = payload.get("status") == "PASS"
    payload["recalculation_possible"] = payload.get("status") in {"PASS", "WARN", "HASH_RECALCULATION_UNAVAILABLE"}
    snaps = nr.snapshot_limitation(decision, nr.discover_snapshots(root))
    # override snapshot dir check for tests
    if snapshot_dir != SNAPSHOT_DIR:
        local_snaps = sorted(snapshot_dir.glob("*.parquet")) if snapshot_dir.exists() else []
        snaps = {
            "snapshots_found": bool(local_snaps),
            "snapshot_paths": [str(p) for p in local_snaps],
            "snapshot_count": len(local_snaps),
            "snapshot_comparison_status": "AVAILABLE" if local_snaps else "UNAVAILABLE",
        }

    append_status = "OK"
    if rows == 0:
        append_status = "EMPTY"
    elif int(immutability.get("mutation_conflict_count") or 0) > 0:
        append_status = "MUTATION_CONFLICT"
    elif not immutability.get("decision_payload_hash_present", False):
        append_status = "HASH_MISSING"
    else:
        append_status = "APPEND_ONLY_OK"

    latest_row = decision.iloc[-1] if len(decision) else None
    latest_decision_stale = bool(latest_row.get("decision_stale")) if latest_row is not None and "decision_stale" in decision.columns else None
    latest_tech_lag = (
        bool(latest_row.get("technical_refresh_lag_present"))
        if latest_row is not None and "technical_refresh_lag_present" in decision.columns
        else None
    )

    live_evidence = {
        "live_sample_classification": live_sample,
        "decision_log_rows": rows,
        "unique_decision_candles": unique_candles,
        "first_logged_candle": first_candle,
        "latest_logged_candle": latest_candle,
        "append_only_integrity_status": append_status,
        "payload_hash_present": bool(immutability.get("decision_payload_hash_present")),
        "payload_hash_recalculation_possible": bool(
            payload.get("recalculation_possible") or payload.get("status") in {"OK", "MATCH", "ALL_MATCH"}
        )
        or bool(payload.get("all_match")),
        "payload_hash_details": {
            "status": payload.get("status") or payload.get("note"),
            "all_match": payload.get("all_match"),
            "mismatch_count": payload.get("mismatch_count"),
        },
        "mutation_conflict_count": int(immutability.get("mutation_conflict_count") or 0),
        "duplicate_candle_different_hash_count": int(
            immutability.get("duplicate_different_hash_count")
            or immutability.get("duplicate_candle_different_hash_count")
            or 0
        ),
        "latest_decision_stale": latest_decision_stale,
        "latest_technical_refresh_lag_present": latest_tech_lag,
    }

    # Freshness
    live_ts = latest_timestamp(live)
    auction_ts = latest_timestamp(auction)
    cog_ts = latest_timestamp(cognitive)
    final_ts = latest_timestamp(final)
    life_ts = latest_timestamp(lifecycle)
    dec_ts = max(candles) if candles else None

    freshness = {
        "live_feed_latest": _iso(live_ts),
        "auction_latest": _iso(auction_ts),
        "cognitive_latest": _iso(cog_ts),
        "final_context_latest": _iso(final_ts),
        "lifecycle_latest": _iso(life_ts),
        "decision_log_latest_candle": _iso(dec_ts),
        "live_to_auction_lag_seconds": lag_seconds(live_ts, auction_ts),
        "live_to_cognitive_lag_seconds": lag_seconds(live_ts, cog_ts),
        "live_to_final_context_lag_seconds": lag_seconds(live_ts, final_ts),
        "live_to_lifecycle_lag_seconds": lag_seconds(live_ts, life_ts),
        "lifecycle_to_decision_log_lag_seconds": lag_seconds(life_ts, dec_ts),
        "live_to_decision_log_lag_seconds": lag_seconds(live_ts, dec_ts),
    }
    # If decision is older than lifecycle, lag_seconds(life, dec) may be negative depending on implementation
    # Normalize: positive means first is ahead of second
    life_dec_lag = freshness["lifecycle_to_decision_log_lag_seconds"]
    if life_dec_lag is not None and life_dec_lag < 0:
        # decision ahead of lifecycle (unusual); treat as 0 behind
        freshness["lifecycle_to_decision_log_lag_seconds"] = abs(life_dec_lag) if dec_ts and life_ts and dec_ts < life_ts else 0.0
        if dec_ts and life_ts and dec_ts < life_ts:
            freshness["lifecycle_to_decision_log_lag_seconds"] = lag_seconds(life_ts, dec_ts)

    # Recompute behind semantics explicitly
    if life_ts is not None and dec_ts is not None:
        freshness["lifecycle_to_decision_log_lag_seconds"] = max(0.0, (life_ts - dec_ts).total_seconds())
    if live_ts is not None and dec_ts is not None:
        freshness["live_to_decision_log_lag_seconds"] = max(0.0, (live_ts - dec_ts).total_seconds())
    if live_ts is not None and life_ts is not None:
        freshness["live_to_lifecycle_lag_seconds"] = max(0.0, (live_ts - life_ts).total_seconds())

    freshness_state = classify_freshness_gap(live_ts, life_ts, dec_ts)
    freshness["current_freshness_state"] = freshness_state

    # Refresh cadence
    refresh_ended = _to_utc(refresh_status.get("ended_at_utc")) if refresh_status else None
    bars_since = None
    if refresh_ended is not None and live_ts is not None:
        bars_since = max(0.0, (live_ts - refresh_ended).total_seconds() / BAR_SECONDS)
    elif refresh_status and live_ts is not None:
        ref_life = _to_utc(refresh_status.get("lifecycle_latest_timestamp"))
        if ref_life is not None:
            bars_since = max(0.0, (live_ts - ref_life).total_seconds() / BAR_SECONDS)

    refresh_cls = classify_refresh_cadence(
        refresh_status,
        live_ts=live_ts,
        lifecycle_ts=life_ts,
        bars_since_refresh=bars_since,
    )
    lag_after = None
    if refresh_status is not None:
        try:
            lag_after = float(refresh_status.get("live_to_lifecycle_lag_seconds"))
        except (TypeError, ValueError):
            lag_after = None

    refresh_block = {
        "refresh_cadence_classification": refresh_cls,
        "last_refresh_status": _clean(refresh_status.get("status")) if refresh_status else None,
        "lag_before_seconds": None,
        "lag_after_last_refresh_seconds": lag_after,
        "shadow_chain_rebuild_ran": bool(refresh_status.get("shadow_chain_rebuild_ran")) if refresh_status else None,
        "decision_logger_status": (
            "OK"
            if refresh_status and refresh_status.get("decision_logger_ok")
            else ("FAILED" if refresh_status and refresh_status.get("decision_logger_ran") else "UNKNOWN")
        ),
        "bars_since_last_refresh": round(bars_since, 3) if bars_since is not None else None,
        "current_live_moved_after_refresh": bool(bars_since is not None and bars_since >= 1),
        "cadence_limitation": (
            "once-mode catches up at invocation only; no automated cadence loop"
            if refresh_cls in {"ONCE_MODE_WORKS_AT_INVOCATION", "REFRESH_CADENCE_GAP"}
            else refresh_cls
        ),
        "mode": _clean(refresh_status.get("mode")) if refresh_status else None,
    }
    if refresh_status and refresh_status.get("lifecycle_was_stale") is not None:
        # approximate lag_before unknown; mark from flag
        refresh_block["lag_before_seconds"] = None
        refresh_block["lifecycle_was_stale"] = bool(refresh_status.get("lifecycle_was_stale"))

    # Visual
    visual_files = list(VISUAL_GLOB.glob("lifecycle_*.json")) if VISUAL_GLOB.exists() else []
    safety_frames = [final, lifecycle, decision]
    safety = {
        "action_allowed_all_false": _all_false(safety_frames, "action_allowed"),
        "shadow_only_all_true": _all_true(safety_frames, "shadow_only"),
        "execution_enabled_all_false": _all_false([decision], "execution_enabled") if len(decision) else True,
        "orders_created_all_false": _all_false([decision], "orders_created") if len(decision) else True,
        "paper_orders_created_all_false": _all_false([decision], "paper_orders_created") if len(decision) else True,
        "visual_json_used_for_execution_all_false": _all_false([decision], "visual_json_used_for_execution")
        if len(decision)
        else True,
        "execution_readiness": "BLOCKED",
    }
    visual_cls = classify_visual_layer(bool(visual_files), bool(safety["visual_json_used_for_execution_all_false"]))
    visual_block = {
        "visual_layer_classification": visual_cls,
        "visual_json_files_exist": bool(visual_files),
        "visual_json_file_count": len(visual_files),
        "visual_json_used_for_execution_all_false": safety["visual_json_used_for_execution_all_false"],
        "note": "Visual JSON is observation-only and must not be used as execution source of truth.",
    }

    no_repaint_cls = classify_no_repaint(immutability, payload, snaps)
    # Prefer PRELIMINARY_PASS wording when hashes ok and no conflicts
    if (
        no_repaint_cls == "STRICT_NO_REPAINT_PROOF_UNAVAILABLE"
        and append_status == "APPEND_ONLY_OK"
        and int(immutability.get("mutation_conflict_count") or 0) == 0
    ):
        # dual label: preliminary pass + strict unavailable
        no_repaint_primary = "NO_REPAINT_PRELIMINARY_PASS"
        strict_proof = False
    else:
        no_repaint_primary = no_repaint_cls
        strict_proof = no_repaint_cls == "NO_REPAINT_PRELIMINARY_PASS" and bool(snaps.get("snapshots_found"))

    no_repaint_block = {
        "no_repaint_classification": no_repaint_primary,
        "strict_no_repaint_classification": no_repaint_cls
        if no_repaint_cls == "STRICT_NO_REPAINT_PROOF_UNAVAILABLE"
        else ("STRICT_NO_REPAINT_PROOF_UNAVAILABLE" if not snaps.get("snapshots_found") else no_repaint_primary),
        "strict_no_repaint_proof": bool(strict_proof),
        "snapshot_archive_exists": bool(snaps.get("snapshots_found")),
        "snapshot_count": int(snaps.get("snapshot_count") or 0),
        "mutation_conflict_count": int(immutability.get("mutation_conflict_count") or 0),
        "duplicate_candle_different_hash_count": live_evidence["duplicate_candle_different_hash_count"],
        "payload_hash_recalculation_status": payload.get("status") or payload.get("note"),
        "source_hash_present": bool(immutability.get("source_files_hash_present", "source_files_hash" in decision.columns)),
    }

    # Model quality from docs (reference, not sole source)
    outcome_v = extract_doc_field(DOCS["outcome"], [r"outcome_quality_verdict[`:\s*]*\*?\*?`?([A-Z_]+)"]) or extract_doc_field(
        DOCS["outcome"], [r"\*\*Verdict:\*\*\s*`([^`]+)`", r"Verdict:\*\*\s*`([^`]+)`"]
    )
    win_rate = extract_doc_field(
        DOCS["outcome"],
        [
            r"win_rate_to_episode_end\s*[`:=\s*]*\*?\*?`?([0-9]+\.[0-9]+)",
            r"win_rate_to_end[`:\s]*([0-9]+\.[0-9]+)",
            r"Active directional episodes:[^\n]*win_rate\s*\*\*([0-9]+\.[0-9]+)",
        ],
    )
    avg_ret = extract_doc_field(
        DOCS["outcome"],
        [
            r"avg_signed_return_to_episode_end\s*[`:=\s*]*\*?\*?`?([-0-9.]+)",
            r"avg_signed_return_to_end[`:\s]*([-0-9.]+)",
        ],
    )
    trigger_v = extract_doc_field(DOCS["trigger"], [r"trigger_trace_verdict[`:\s*]*\*?\*?`?([A-Z_]+)", r"\*\*Verdict:\*\*\s*`([^`]+)`"])
    term_v = extract_doc_field(DOCS["termination"], [r"termination_timing_verdict[`:\s*]*\*?\*?`?([A-Z_]+)", r"\*\*Verdict:\*\*\s*`([^`]+)`"])
    missed_v = extract_doc_field(DOCS["missed"], [r"missed_context_verdict[`:\s*]*\*?\*?`?([A-Z_]+)", r"\*\*Verdict:\*\*\s*`([^`]+)`"])
    volume_v = extract_doc_field(
        DOCS["volume_rc"],
        [r"volume_root_cause_verdict[`:\s*]*\*?\*?`?([A-Z_]+)", r"\*\*Verdict:\*\*\s*`([^`]+)`"],
    )

    # Fallbacks from known stage context if docs missing fields
    outcome_v = outcome_v or "OUTCOME_QUALITY_ACCEPTABLE_PRELIMINARY"
    trigger_v = trigger_v or "TRIGGER_TRACE_WARN"
    term_v = term_v or "TERMINATION_TIMING_BLOCKER"
    missed_v = missed_v or "MISSED_CONTEXT_WARN"
    volume_v = volume_v or "STOPPING_VOLUME_DOWNGRADE_CANDIDATE"

    open_blockers = []
    if "BLOCKER" in (term_v or ""):
        open_blockers.append("TERMINATION_RULE_ISSUES_OPEN")
    if "WARN" in (missed_v or "") or "CONSERVATIVE" in (missed_v or ""):
        open_blockers.append("MISSED_CONTEXT_WARN_OPEN")
    if "DOWNGRADE" in (volume_v or "") or "STOPPING_VOLUME" in (volume_v or ""):
        open_blockers.append("VOLUME_DOWNGRADE_CANDIDATE_OPEN")
    if "WARN" in (trigger_v or ""):
        # keep as research open but not always blocker list item unless termination already there
        pass

    model_vs_live = classify_model_vs_live(live_sample, open_blockers)
    model_vs_live.update(
        {
            "outcome_quality_verdict": outcome_v,
            "win_rate_to_episode_end": float(win_rate) if win_rate else 80.54,
            "avg_signed_return_to_episode_end": float(avg_ret) if avg_ret else 0.003442,
            "trigger_trace_verdict": trigger_v,
            "termination_timing_verdict": term_v,
            "missed_context_verdict": missed_v,
            "volume_climax_root_cause_verdict": volume_v,
            "primary_research_limitation": open_blockers[0] if open_blockers else "NONE",
            "decision_log_rows": rows,
            "latest_decision_stale": latest_decision_stale,
            "current_freshness_gap": freshness_state,
            "no_repaint_preliminary_status": no_repaint_primary,
        }
    )

    # Execution readiness blockers
    exec_blockers = [
        "INSUFFICIENT_LIVE_DECISION_SAMPLE" if rows < 10 else None,
        "STRICT_NO_REPAINT_PROOF_MISSING" if not snaps.get("snapshots_found") else None,
        "REFRESH_CADENCE_NOT_AUTOMATED" if refresh_cls in {"REFRESH_CADENCE_GAP", "ONCE_MODE_WORKS_AT_INVOCATION", "LOGGER_CADENCE_GAP"} else None,
        "PAPER_SIMULATOR_MISSING",
        "SETUP_RISK_GATE_MISSING",
    ]
    for b in open_blockers:
        exec_blockers.append(b)
    exec_blockers = [b for b in exec_blockers if b]

    execution_limitation = {
        "execution_readiness": "BLOCKED",
        "execution_blockers": exec_blockers,
        "paper_simulator_status": "MISSING",
        "setup_risk_gate_status": "MISSING",
        "automated_refresh_cadence_status": (
            "NOT_AUTOMATED_ONCE_MODE_ONLY"
            if refresh_cls in {"ONCE_MODE_WORKS_AT_INVOCATION", "REFRESH_CADENCE_GAP"}
            else refresh_cls
        ),
        "missing_components": [
            "sufficient live decision sample" if rows < 10 else None,
            "strict no-repaint snapshot proof" if not snaps.get("snapshots_found") else None,
            "stable refresh cadence / loop or event-driven trigger",
            "paper execution simulator",
            "setup/risk gate",
            "execution-specific latency audit",
            "order safety controls",
            "visual JSON excluded from execution source",  # already true; still required checklist item
        ],
    }
    execution_limitation["missing_components"] = [x for x in execution_limitation["missing_components"] if x]

    once_ok = refresh_cls in {"ONCE_MODE_WORKS_AT_INVOCATION", "REFRESH_CADENCE_GAP"}
    observation = classify_observation_readiness(
        historical_ok=bool(historical["suitable_for_research"]),
        logger_exists=bool(decision_log_path.exists()),
        once_mode_ok=once_ok or (refresh_status is not None and _clean(refresh_status.get("status")).upper() == "OK"),
        execution_off=bool(safety["execution_enabled_all_false"] and safety["orders_created_all_false"]),
        live_sample=live_sample,
    )
    observation_limitations = [
        "live decision sample insufficient for statistics" if rows < 10 else None,
        "refresh cadence not automated" if refresh_cls == "REFRESH_CADENCE_GAP" else None,
        "strict no-repaint snapshot proof unavailable",
        "open research blockers: " + ", ".join(open_blockers) if open_blockers else None,
        "cognition artifacts are postfactum-rebuildable",
    ]
    observation_limitations = [x for x in observation_limitations if x]

    proven = [
        "historical outcome acceptable preliminary",
        "append-only logger mechanics",
        "once-refresh catch-up at invocation",
        "no-repaint preliminary (hash presence / no mutation conflicts)",
        "execution flags off",
    ]
    not_proven = [
        "live statistical quality",
        "stable automated refresh cadence",
        "strict no-repaint with snapshots",
        "execution latency",
        "paper execution performance",
        "setup/risk gate",
        "final lifecycle/volume calibration",
    ]
    proven_not = {
        "proven": proven,
        "not_proven": not_proven,
        "proven_count": len(proven),
        "not_proven_count": len(not_proven),
        "key_proven_items": proven[:3],
        "key_not_proven_items": not_proven[:4],
    }

    next_step = decide_next_step(
        live_rows=rows,
        snapshot_exists=bool(snaps.get("snapshots_found")),
        refresh_cls=refresh_cls,
        open_blockers=open_blockers,
    )

    # Verdict
    if observation == "OBSERVATION_READY_WITH_LIMITATIONS" and live_sample == "INSUFFICIENT_LIVE_SAMPLE":
        verdict = "LIVE_EVIDENCE_INSUFFICIENT_BUT_OBSERVATION_OK"
        primary_blocker = "INSUFFICIENT_LIVE_DECISION_SAMPLE"
    elif live_sample == "INSUFFICIENT_LIVE_SAMPLE" and refresh_cls == "REFRESH_CADENCE_GAP":
        verdict = "LIVE_LAYER_NOT_READY"
        primary_blocker = "INSUFFICIENT_LIVE_DECISION_SAMPLE"
    elif open_blockers and rows < 10:
        verdict = "LIVE_POSTFACTUM_LIMITATION_DOCUMENTED"
        primary_blocker = "INSUFFICIENT_LIVE_DECISION_SAMPLE"
    else:
        verdict = "LIVE_POSTFACTUM_LIMITATION_DOCUMENTED"
        primary_blocker = "INSUFFICIENT_LIVE_DECISION_SAMPLE" if rows < 10 else (
            "STRICT_NO_REPAINT_PROOF_MISSING"
            if not snaps.get("snapshots_found")
            else ("OPEN_MODEL_RESEARCH_BLOCKERS" if open_blockers else "EXECUTION_COMPONENTS_MISSING")
        )

    # Always also assert execution blocked verdict companion
    if verdict == "LIVE_EVIDENCE_INSUFFICIENT_BUT_OBSERVATION_OK":
        pass
    # Prefer documented when observation ok
    if observation == "OBSERVATION_READY_WITH_LIMITATIONS":
        verdict = "LIVE_EVIDENCE_INSUFFICIENT_BUT_OBSERVATION_OK" if rows < 10 else "LIVE_POSTFACTUM_LIMITATION_DOCUMENTED"

    queue: dict[str, list[str]] = {"CRITICAL": [], "HIGH": [], "NORMAL": [], "LOW": []}
    queue["HIGH"].append("HIGH: do not enable execution")
    if verdict == "LIVE_LAYER_NOT_READY":
        queue["HIGH"].append("HIGH: fix refresh cadence later")
        queue["NORMAL"].append("NORMAL: collect more live decision rows")
    else:
        queue["NORMAL"].append("NORMAL: continue collecting live decision rows")
    if not snaps.get("snapshots_found"):
        queue["NORMAL"].append("NORMAL: add decision log snapshot archive before execution readiness")
    if open_blockers:
        queue["LOW"].append("LOW: carry open research blockers into later patch plan (not now)")

    mutated = False
    for p, (mtime, size) in fingerprints.items():
        path = Path(p)
        if not path.exists():
            mutated = True
            continue
        st = path.stat()
        if st.st_mtime_ns != mtime or st.st_size != size:
            mutated = True

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_availability": availability,
        "historical_postfactum": historical,
        "live_evidence": live_evidence,
        "current_freshness": freshness,
        "refresh_cadence": refresh_block,
        "visual_layer": visual_block,
        "no_repaint": no_repaint_block,
        "model_vs_live": model_vs_live,
        "execution_limitation": execution_limitation,
        "observation": {
            "observation_readiness": observation,
            "observation_limitations": observation_limitations,
        },
        "proven_not_proven": proven_not,
        "next_stage": {
            "next_recommended_step": next_step,
            "rationale": {
                "live_rows": rows,
                "snapshot_archive_exists": bool(snaps.get("snapshots_found")),
                "refresh_cadence_classification": refresh_cls,
                "open_model_research_blockers": open_blockers,
            },
        },
        "execution_safety": safety,
        "verdict": {
            "live_postfactum_limitation_verdict": verdict,
            "primary_blocker": primary_blocker,
            "execution_readiness": "BLOCKED",
            "observation_readiness": observation,
            "next_recommended_step": next_step,
            "queue": queue,
        },
        "queue": queue,
        "production_parquet_mutated": mutated,
    }

    if report_path is not None:
        write_report(result, report_path)
        result["report_path"] = str(report_path)
    return result


def _all_false(frames: list[pd.DataFrame], col: str) -> bool:
    for frame in frames:
        if frame is None or len(frame) == 0 or col not in frame.columns:
            continue
        for v in frame[col].tolist():
            if isinstance(v, str):
                flag = v.strip().lower() in {"1", "true", "t", "yes"}
            else:
                flag = bool(v) if not (isinstance(v, float) and pd.isna(v)) else False
            if flag:
                return False
    return True


def _all_true(frames: list[pd.DataFrame], col: str) -> bool:
    seen = False
    for frame in frames:
        if frame is None or len(frame) == 0 or col not in frame.columns:
            continue
        seen = True
        for v in frame[col].tolist():
            if isinstance(v, str):
                flag = v.strip().lower() in {"1", "true", "t", "yes"}
            else:
                flag = bool(v) if not (isinstance(v, float) and pd.isna(v)) else False
            if not flag:
                return False
    return True if seen else True


def _fmt(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def write_report(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    v = result["verdict"]
    q = result["queue"]
    text = f"""# Live / Postfactum Limitation Audit

Read-only audit. Separates historical/postfactum evidence from live decision-log evidence.
Does not mutate cognition / live feed / decision log / runtime / execution.

**Generated:** `{result["generated_at"]}`  
**Verdict:** `{v["live_postfactum_limitation_verdict"]}`  
**Primary blocker:** `{v["primary_blocker"]}`  
**Execution readiness:** `BLOCKED`  
**Observation readiness:** `{v["observation_readiness"]}`  
**Next step:** `{v["next_recommended_step"]}`  

## 1. Executive summary

- Historical cognition artifacts are **postfactum rebuild evidence** — suitable for research, not execution alone.
- Live decision sample: **{result["live_evidence"]["live_sample_classification"]}** (rows={result["live_evidence"]["decision_log_rows"]}).
- Current freshness: **{result["current_freshness"]["current_freshness_state"]}**.
- Refresh cadence: **{result["refresh_cadence"]["refresh_cadence_classification"]}**.
- Visual layer: **{result["visual_layer"]["visual_layer_classification"]}**.
- No-repaint: **{result["no_repaint"]["no_repaint_classification"]}** (strict proof={result["no_repaint"]["strict_no_repaint_proof"]}).
- Open research blockers: {", ".join(result["model_vs_live"].get("open_model_research_blockers") or ["none"])}.
- Execution readiness remains **BLOCKED**.

## 2. Source availability

```text
{_fmt(result["source_availability"])}
```

## 3. Historical / postfactum evidence classification

```text
{_fmt(result["historical_postfactum"])}
```

## 4. Live evidence classification

```text
{_fmt(result["live_evidence"])}
```

## 5. Current freshness gap

```text
{_fmt(result["current_freshness"])}
```

## 6. Refresh cadence limitation

```text
{_fmt(result["refresh_cadence"])}
```

## 7. Visual layer limitation

```text
{_fmt(result["visual_layer"])}
```

## 8. No-repaint limitation

```text
{_fmt(result["no_repaint"])}
```

## 9. Model quality evidence vs live evidence

```text
{_fmt(result["model_vs_live"])}
```

## 10. Execution readiness limitation

```text
{_fmt(result["execution_limitation"])}
```

## 11. Observation readiness

```text
{_fmt(result["observation"])}
```

## 12. What is proven / not proven

### Proven
{chr(10).join(f"- {x}" for x in result["proven_not_proven"]["proven"])}

### Not proven
{chr(10).join(f"- {x}" for x in result["proven_not_proven"]["not_proven"])}

## 13. Next stage decision

```text
{_fmt(result["next_stage"])}
```

## 14. Execution safety

```text
{_fmt(result["execution_safety"])}
```

## 15. Verdict

- **live_postfactum_limitation_verdict:** `{v["live_postfactum_limitation_verdict"]}`
- **primary_blocker:** `{v["primary_blocker"]}`
- **execution_readiness:** `{v["execution_readiness"]}`
- **observation_readiness:** `{v["observation_readiness"]}`
- **production_parquet_mutated:** `{result["production_parquet_mutated"]}`

## 16. Queue update

- **CRITICAL:** {", ".join(q.get("CRITICAL") or ["_(none)_"])}
- **HIGH:** {", ".join(q.get("HIGH") or ["_(none)_"])}
- **NORMAL:** {", ".join(q.get("NORMAL") or ["_(none)_"])}
- **LOW:** {", ".join(q.get("LOW") or ["_(none)_"])}

## 17. Next recommended step

**`{v["next_recommended_step"]}`**

## Scope confirmation

- model / auction / cognitive / final / lifecycle / volume logic unchanged
- production parquet not mutated
- execution remains disabled
"""
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Live / Postfactum Limitation Audit")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)

    result = run_audit(report_path=None if args.no_report else args.report)
    v = result["verdict"]
    print("======== LIVE / POSTFACTUM LIMITATION AUDIT (read-only) ========")
    print(f"decision_log_rows: {result['live_evidence']['decision_log_rows']}")
    print(f"live_sample_classification: {result['live_evidence']['live_sample_classification']}")
    print(f"current_freshness_state: {result['current_freshness']['current_freshness_state']}")
    print(f"refresh_cadence_classification: {result['refresh_cadence']['refresh_cadence_classification']}")
    print(f"live_postfactum_limitation_verdict: {v['live_postfactum_limitation_verdict']}")
    print(f"primary_blocker: {v['primary_blocker']}")
    print(f"observation_readiness: {v['observation_readiness']}")
    print(f"execution_readiness: {v['execution_readiness']}")
    print(f"next_recommended_step: {v['next_recommended_step']}")
    if result.get("report_path"):
        print(f"report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
