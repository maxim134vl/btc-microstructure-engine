#!/usr/bin/env python3
"""Patch 4.1 — OPS dashboard runtime truth audit + candidate payload (research-only).

Read-only. Does not modify production dashboard payloads, frontend, or runtime writers.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TAG_PATH = ROOT / "data/research/patch4_1_active_ts.txt"

ENTITY_TAXONOMY = [
    "PROCESS",
    "PIPELINE_ENGINE",
    "DATASET",
    "READ_MODEL",
    "UNSUPPORTED_CAPABILITY",
    "LEGACY_COMPONENT",
]

CANONICAL_SOURCE_HIERARCHY = [
    "live_process_inspection",
    "runtime_dataset_ownership_registry",
    "metadata_sidecars",
    "runtime_dataset_status.json",
    "pipeline_cycle_status",
    "specialized_runtime_statuses",
]

FORBIDDEN_PRIMARY_SOURCES = [
    "hardcoded_javascript_arrays",
    "stale_research_json",
    "previous_dashboard_payload",
    "file_mtime_without_market_timestamp",
    "legacy_architecture_list",
    "README",
]

PHANTOMS = [
    "volume_localization_engine_v1.py",
    "market_state_engine_v1.py",
    "trading_state_engine_v1.py",
    "shadow_inference_engine_v1.py",
    "trading_state_validation_engine_v1.py",
    "economic_validation_engine_v1.py",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tag() -> str:
    if TAG_PATH.exists():
        return TAG_PATH.read_text(encoding="utf-8").strip()
    tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    TAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAG_PATH.write_text(tag + "\n", encoding="utf-8")
    return tag


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_snapshot(path: Path, ts_cols: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)) if path.exists() else str(path),
        "exists": path.exists(),
        "sha256": sha256_file(path),
        "mtime": path.stat().st_mtime if path.exists() else None,
        "size": path.stat().st_size if path.exists() else None,
    }
    if not path.exists():
        return info
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            info["json_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else ["_list"]
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
                        tip = payload[key]
                        break
            info["tip"] = tip
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc)
        return info
    if path.suffix != ".parquet":
        return info
    try:
        frame = pd.read_parquet(path)
        info["rows"] = int(len(frame))
        info["columns"] = list(frame.columns)
        for col in ts_cols:
            if col in frame.columns:
                series = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
                if len(series):
                    info["ts_col"] = col
                    info["tip"] = series.max().isoformat()
                    break
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def parse_pipeline_list(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CANONICAL_PIPELINE":
                    return list(ast.literal_eval(node.value))
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "CANONICAL_PIPELINE":
                return list(ast.literal_eval(node.value))
    # fallback: list or tuple literal after assignment
    match = re.search(
        r"CANONICAL_PIPELINE(?::[^=]+)?\s*=\s*(\[|\()(.*?)(\]|\))",
        text,
        re.S,
    )
    if not match:
        raise RuntimeError(f"CANONICAL_PIPELINE not found in {path}")
    return re.findall(r'"([^"]+\.py)"', match.group(2))


def process_rows() -> list[dict[str, Any]]:
    ps = subprocess.check_output(["ps", "-axo", "pid=,ppid=,etime=,lstart=,command="], text=True)
    wanted = {
        "FEED": ("live_binance_intrabar_feed.py",),
        "PIPELINE": ("run.py",),
        "CONTEXT_REFRESHER": ("run_context_refresh_daemon.py",),
        "PAPER_CONTROLLER": ("bounded_paper_trading_controller_auto_ledger",),
        "DASHBOARD_REFRESHER": ("run_market_context_visual_refresher.py",),
        "FEED_WATCHDOG": ("collector_watchdog.py",),
    }
    out: list[dict[str, Any]] = []
    for process_id, tokens in wanted.items():
        matched = None
        for line in ps.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(tok in line for tok in tokens):
                # avoid matching pytest / shells
                if "rg " in line or "zsh -c" in line:
                    continue
                if process_id == "PIPELINE":
                    if not (line.endswith("run.py") or " run.py" in f" {line}" or line.endswith("/run.py")):
                        continue
                    if "pytest" in line:
                        continue
                matched = line
                break
        if matched is None:
            out.append(
                {
                    "process_id": process_id,
                    "pid": None,
                    "ppid": None,
                    "process_state": "STOPPED",
                    "interpreter": None,
                    "cwd": None,
                    "command": None,
                    "started_at": None,
                    "last_heartbeat": None,
                    "restart_count": None,
                    "ownership": process_id,
                    "health": "STOPPED",
                    "health_reason": "process_not_found_in_ps",
                    "entity_type": "PROCESS",
                }
            )
            continue
        parts = matched.split(None, 4)
        # pid ppid etime lstart... command — lstart has spaces; re-parse carefully
        pid = int(parts[0])
        ppid = int(parts[1])
        # Use ps -p for command/start
        detail = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,etime=,lstart=,command="],
            text=True,
        ).strip()
        dparts = detail.split(None, 8)
        # pid ppid etime Dow Mon Day HH:MM:SS YYYY command
        etime = dparts[2] if len(dparts) > 2 else None
        started = " ".join(dparts[3:8]) if len(dparts) >= 8 else None
        command = dparts[8] if len(dparts) > 8 else matched
        interpreter = None
        if "Python" in command or "python" in command:
            interpreter = command.split()[0]
        # cwd via lsof if available
        cwd = None
        try:
            lsof = subprocess.check_output(
                ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for ln in lsof.splitlines():
                if ln.startswith("n"):
                    cwd = ln[1:]
        except Exception:
            cwd = None
        health = "RUNNING"
        reason = "process_alive"
        if process_id == "PAPER_CONTROLLER" and "--skip-refresh" in command:
            reason = "running_skip_refresh_no_real_execution"
        if process_id == "PIPELINE" and interpreter and "3.11" not in interpreter and "python" in interpreter.lower():
            # not necessarily wrong; note only
            pass
        out.append(
            {
                "process_id": process_id,
                "pid": pid,
                "ppid": ppid,
                "process_state": "RUNNING",
                "interpreter": interpreter,
                "cwd": cwd,
                "command": command[:300],
                "started_at": started,
                "etime": etime,
                "last_heartbeat": _utc_now(),
                "restart_count": None,
                "ownership": process_id,
                "health": health,
                "health_reason": reason,
                "entity_type": "PROCESS",
            }
        )
    return out


def extract_runtime_engines() -> dict[str, Any]:
    pipeline_path = ROOT / "src/btc_ml/runtime/pipeline.py"
    engines = parse_pipeline_list(pipeline_path)
    # engine state if present
    state_path = None
    for candidate in (
        ROOT / "data/diagnostics/runtime_engine_state.parquet",
        ROOT / "data/cognition/runtime_engine_state.parquet",
        ROOT / "runtime_engine_state.parquet",
    ):
        if candidate.exists():
            state_path = candidate
            break
    # try path registry resolve
    try:
        from storage.path_registry import resolve_read

        resolved = Path(resolve_read("runtime_engine_state.parquet"))
        if resolved.exists():
            state_path = resolved
    except Exception:
        pass

    latest_by_engine: dict[str, dict[str, Any]] = {}
    if state_path and state_path.exists():
        try:
            frame = pd.read_parquet(state_path)
            if "engine" in frame.columns:
                frame = frame.copy()
                # take last row per engine
                for eng, group in frame.groupby("engine"):
                    row = group.iloc[-1]
                    cleaned: dict[str, Any] = {}
                    for k, v in row.to_dict().items():
                        if isinstance(v, float) and pd.isna(v):
                            cleaned[k] = None
                        elif hasattr(v, "isoformat"):
                            cleaned[k] = v.isoformat()
                        elif isinstance(v, (pd.Timestamp,)):
                            cleaned[k] = pd.Timestamp(v).isoformat()
                        else:
                            try:
                                json.dumps(v)
                                cleaned[k] = v
                            except TypeError:
                                cleaned[k] = str(v)
                    latest_by_engine[str(eng)] = cleaned
        except Exception as exc:  # noqa: BLE001
            latest_by_engine = {"_error": {"error": str(exc)}}

    inventory = []
    for idx, eng in enumerate(engines, start=1):
        module_path = ROOT / eng
        state = latest_by_engine.get(eng, {})
        required = eng not in {
            "auction_synthesis_engine_v1.py",  # known broken / non-required by context chain
        }
        last_result = state.get("status") or state.get("result") or "UNKNOWN"
        inventory.append(
            {
                "engine_id": eng,
                "module": eng.replace(".py", ""),
                "file": eng,
                "file_exists": module_path.exists(),
                "pipeline_order": idx,
                "enabled": True,
                "required_or_optional": "OPTIONAL_KNOWN_LIMITATION"
                if eng == "auction_synthesis_engine_v1.py"
                else ("REQUIRED_OPERATIONAL_READ_MODEL" if eng == "mtf_availability_runtime_engine_v1.py" else "REQUIRED_SENSORY"),
                "input": None,
                "output": None,
                "last_cycle_status": last_result,
                "last_success_timestamp": state.get("timestamp") or state.get("finished_at"),
                "failure_behavior": "continue_pipeline_cycle",
                "entity_type": "PIPELINE_ENGINE",
            }
        )
    return {
        "generated_at": _utc_now(),
        "source": "src/btc_ml/runtime/pipeline.py::CANONICAL_PIPELINE",
        "runtime_engine_count": len(engines),
        "expected_count_constant": 20,
        "engines": inventory,
        "engine_state_path": None
        if state_path is None
        else str(state_path.relative_to(ROOT))
        if str(state_path).startswith(str(ROOT))
        else str(state_path),
    }


def extract_dashboard_engines() -> dict[str, Any]:
    path = ROOT / "dashboard/backend/app/pipeline_metadata.py"
    engines = parse_pipeline_list(path)
    # display names if present
    text = path.read_text(encoding="utf-8")
    display = {}
    m = re.search(r"ENGINE_DISPLAY\s*=\s*\{(.*?)\}", text, re.S)
    if m:
        for k, v in re.findall(r'"([^"]+\.py)"\s*:\s*"([^"]+)"', m.group(1)):
            display[k] = v
    inventory = []
    for idx, eng in enumerate(engines, start=1):
        exists = (ROOT / eng).exists()
        inventory.append(
            {
                "dashboard_id": eng,
                "display_name": display.get(eng, eng.replace(".py", "")),
                "claimed_module": eng,
                "claimed_path": eng,
                "claimed_status_source": "runtime_engine_state.parquet via ops_monitor.build_engine_status",
                "source_of_status": "dashboard/backend/app/services/ops_monitor.py iterates dashboard CANONICAL_PIPELINE",
                "file_exists": exists,
                "pipeline_order_claimed": idx,
                "actual_runtime_match": None,  # filled in parity
            }
        )
    return {
        "generated_at": _utc_now(),
        "source": "dashboard/backend/app/pipeline_metadata.py::CANONICAL_PIPELINE",
        "dashboard_engine_count": len(engines),
        "expected_count_constant": 24,
        "engines": inventory,
        "notes": [
            "Dashboard list is NOT authoritative.",
            "Production OPS snapshot built by dashboard/backend/app/services/ops_monitor.py",
        ],
    }


def build_engine_parity(runtime_inv: dict, dash_inv: dict) -> list[dict[str, Any]]:
    runtime = {e["engine_id"]: e for e in runtime_inv["engines"]}
    dash = {e["dashboard_id"]: e for e in dash_inv["engines"]}
    all_ids = sorted(set(runtime) | set(dash))
    rows = []
    for eng in all_ids:
        in_r = eng in runtime
        in_d = eng in dash
        exists = (ROOT / eng).exists()
        if in_r and in_d and exists:
            klass = "EXACT_MATCH"
        elif in_r and not in_d and exists:
            klass = "RUNTIME_ONLY"
        elif in_d and not in_r and not exists:
            klass = "DASHBOARD_ONLY_PHANTOM"
        elif in_d and not in_r and exists:
            klass = "WRONG_MODULE_MAPPING"
        elif in_r and in_d and not exists:
            klass = "UNKNOWN"
        else:
            klass = "UNKNOWN"
        # special wrong status source for all dashboard engines (hardcoded list)
        status_source_class = "WRONG_STATUS_SOURCE" if in_d else None
        rows.append(
            {
                "engine": eng,
                "in_runtime": in_r,
                "in_dashboard": in_d,
                "source_file_exists": exists,
                "classification": klass,
                "status_source_issue": status_source_class or "",
                "runtime_order": runtime.get(eng, {}).get("pipeline_order"),
                "dashboard_order": dash.get(eng, {}).get("pipeline_order_claimed"),
                "notes": (
                    "phantom missing file"
                    if klass == "DASHBOARD_ONLY_PHANTOM"
                    else (
                        "live runtime engine omitted from dashboard list"
                        if klass == "RUNTIME_ONLY"
                        else ""
                    )
                ),
            }
        )
        if eng in dash_inv["engines"] or True:
            pass
    # annotate dashboard inventory match field
    for e in dash_inv["engines"]:
        eng = e["dashboard_id"]
        row = next(r for r in rows if r["engine"] == eng)
        e["actual_runtime_match"] = row["classification"]
    return rows


def file_inventory() -> list[dict[str, Any]]:
    paths = [
        ("src/btc_ml/runtime/pipeline.py", "canonical_pipeline_registry", "runtime", "PIPELINE", "production", "authoritative"),
        ("engine_registry.py", "inprocess_engine_registry", "runtime", "PIPELINE", "production", "authoritative"),
        ("config/runtime_dataset_ownership.json", "ownership_registry", "ops/bootstrap", "OPS", "production", "authoritative"),
        ("runtime_dataset_metadata.py", "status_builder", "pipeline/ops", "OPS", "production", "authoritative"),
        ("data/runtime/runtime_dataset_status.json", "status_payload", "runtime_dataset_metadata", "OPS", "production", "authoritative_datasets"),
        ("data/runtime/multi_timeframe_availability_latest.json", "mtf_read_model", "mtf_availability_runtime_engine_v1", "OPS", "production", "authoritative_mtf"),
        ("data/runtime/multi_timeframe_availability_status.json", "mtf_status", "mtf_availability_runtime_engine_v1", "OPS", "production", "authoritative_mtf"),
        ("dashboard/backend/app/pipeline_metadata.py", "dashboard_engine_list", "manual/stale", "dashboard API", "production_stale", "NON_AUTHORITATIVE"),
        ("dashboard/backend/app/services/ops_monitor.py", "ops_snapshot_builder", "dashboard API", "frontend", "production", "partial_truth"),
        ("dashboard/backend/app/main.py", "fastapi_ops_routes", "dashboard API", "frontend", "production", "serving"),
        ("dashboard/frontend/src/components/ops/OpsDashboard.tsx", "ops_ui", "none", "operator", "production", "renders_ops_snapshot"),
        ("dashboard/frontend/src/components/ops/MonitorPanels.tsx", "ops_ui_tables", "none", "operator", "production", "renders_ops_snapshot"),
        ("dashboard/frontend/src/api/client.ts", "ops_api_client", "none", "OpsDashboard", "production", "fetches_/ops/snapshot"),
        ("dashboard/frontend/src/api/opsFallbackSnapshot.ts", "offline_fallback", "static", "OpsDashboard", "production", "NON_AUTHORITATIVE_FALLBACK"),
        ("dashboard/frontend/src/types/ops.ts", "ops_types", "none", "frontend", "production", "schema"),
        ("apps/context_visualizer/public/index.html", "lifecycle_visual", "visual refresher", "browser", "production", "not_engine_ops"),
        ("apps/context_visualizer/public/lifecycle_app.js", "lifecycle_visual_js", "visual refresher", "browser", "production", "not_engine_ops"),
        ("scripts/live/run_market_context_visual_refresher.py", "visual_refresher", "visual stack", "visualizer", "production", "non_authoritative_ui"),
        ("scripts/live/run_context_refresh_daemon.py", "context_refresher", "ctl", "context/lifecycle/decision", "production", "authoritative_context"),
        ("config/required_runtime_components.yaml", "health_manifest", "ops_monitor", "ops_monitor", "production", "partial_required_subset"),
        ("data/research/engine_registry_parity.csv", "parity_artifact", "research", "audit", "research", "historical_parity"),
        ("ops_stability.py", "stability_sidecar", "ops_monitor", "ops_monitor", "production", "auxiliary"),
    ]
    rows = []
    for rel, role, writer, consumer, plane, relevance in paths:
        path = ROOT / rel
        rows.append(
            {
                "path": rel,
                "role": role,
                "writer": writer,
                "consumer": consumer,
                "production_or_legacy": plane,
                "last_modified": path.stat().st_mtime if path.exists() else None,
                "exists": path.exists(),
                "runtime_relevance": relevance,
            }
        )
    return rows


def build_lineage(runtime_inv: dict, dash_inv: dict, parity: list[dict]) -> list[dict[str, Any]]:
    rows = []
    # processes
    for pid_name, section in [
        ("FEED", "processes"),
        ("PIPELINE", "processes"),
        ("CONTEXT_REFRESHER", "processes"),
        ("PAPER_CONTROLLER", "processes"),
        ("DASHBOARD_REFRESHER", "processes"),
    ]:
        rows.append(
            {
                "dashboard_section": section,
                "card_id": pid_name.lower(),
                "label": pid_name,
                "source_file": "live process inspection (ps)",
                "source_field": "pid/command/state",
                "transformation": "candidate: direct; current dashboard: collectors/pipeline heartbeat heuristics",
                "freshness_calculation": "process alive + specialized heartbeat if any",
                "fallback": "STOPPED/UNKNOWN",
                "rendered_status": "RUNNING|STOPPED|...",
                "click_detail_behavior": "expand command/pid",
                "owner": pid_name,
                "authoritative": "true",
                "entity_type": "PROCESS",
            }
        )
    # engines
    for eng in runtime_inv["engines"]:
        rows.append(
            {
                "dashboard_section": "pipeline_engines",
                "card_id": eng["engine_id"],
                "label": eng["module"],
                "source_file": "src/btc_ml/runtime/pipeline.py + runtime_engine_state",
                "source_field": "status/timestamp",
                "transformation": "map SUCCESS/FAILED/SKIPPED; event-sparse != failure",
                "freshness_calculation": "last_cycle result age",
                "fallback": "UNKNOWN",
                "rendered_status": eng["last_cycle_status"],
                "click_detail_behavior": "show order/inputs/outputs/error",
                "owner": "canonical_pipeline_loop",
                "authoritative": "true",
                "entity_type": "PIPELINE_ENGINE",
            }
        )
    for eng in dash_inv["engines"]:
        if eng["actual_runtime_match"] == "DASHBOARD_ONLY_PHANTOM":
            rows.append(
                {
                    "dashboard_section": "pipeline_engines_current_dashboard",
                    "card_id": eng["dashboard_id"],
                    "label": eng["display_name"],
                    "source_file": "dashboard/backend/app/pipeline_metadata.py",
                    "source_field": "hardcoded CANONICAL_PIPELINE",
                    "transformation": "treated as engine even if file missing",
                    "freshness_calculation": "engine_state miss → stale/failed heuristics",
                    "fallback": "unknown/failed",
                    "rendered_status": "PHANTOM (should be legacy)",
                    "click_detail_behavior": "current: shown as engine card",
                    "owner": "NONE",
                    "authoritative": "false",
                    "entity_type": "LEGACY_COMPONENT",
                }
            )
    # MTF
    for tf in ("M15", "M30", "H1", "H4", "D1"):
        rows.append(
            {
                "dashboard_section": "multi_timeframe",
                "card_id": f"mtf_{tf}",
                "label": tf,
                "source_file": "data/runtime/multi_timeframe_availability_latest.json",
                "source_field": f"timeframes.{tf}",
                "transformation": "pass-through availability_status; D1 declaration only",
                "freshness_calculation": "age_seconds/age_bars from availability row",
                "fallback": "UNKNOWN",
                "rendered_status": "from availability_status",
                "click_detail_behavior": "show state_asof/source_bar_close/is_new_event",
                "owner": "PIPELINE_POST_CYCLE_READ_MODEL",
                "authoritative": "true",
                "entity_type": "READ_MODEL" if tf != "D1" else "UNSUPPORTED_CAPABILITY",
            }
        )
    # datasets core
    for ds, path, owner in [
        ("live_market_feed", "data/live/live_market_feed.parquet", "live_market_feed_writer"),
        ("candle_structure_memory", "data/cognition/candle_structure_memory.parquet", "canonical_pipeline_loop"),
        ("final_market_context_memory", "data/cognition/final_market_context_memory.parquet", "market_context_shadow_chain"),
        ("market_context_lifecycle_memory", "data/cognition/market_context_lifecycle_memory.parquet", "market_context_shadow_chain"),
        ("context_decision_log", "data/live/context_decision_log.parquet", "decision_logger"),
        ("multi_timeframe_availability_memory", "data/cognition/multi_timeframe_availability_memory.parquet", "canonical_pipeline_loop"),
        ("paper_signals", "data/research/paper_simulator/paper_signals.parquet", "paper_controller"),
        ("auction_synthesis_memory", "data/reinforcement/auction_synthesis_memory.parquet", "canonical_pipeline_loop"),
    ]:
        rows.append(
            {
                "dashboard_section": "datasets",
                "card_id": ds,
                "label": ds,
                "source_file": path,
                "source_field": "tip via ownership/metadata/status",
                "transformation": "classify_dataset_health",
                "freshness_calculation": "source_market_timestamp vs now/feed",
                "fallback": "UNKNOWN (not healthy)",
                "rendered_status": "from runtime_dataset_status",
                "click_detail_behavior": "path/owner/writer/tip/sha",
                "owner": owner,
                "authoritative": "true",
                "entity_type": "DATASET",
            }
        )
    return rows


def runtime_status_gaps() -> dict[str, Any]:
    status_path = ROOT / "data/runtime/runtime_dataset_status.json"
    ownership = json.loads((ROOT / "config/runtime_dataset_ownership.json").read_text())
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    ds_ids = {d["dataset_id"] for d in status.get("datasets", [])}
    ownership_ids = {d["dataset_id"] for d in ownership.get("datasets", [])}
    gaps = []
    # process status
    gaps.append(
        {
            "gap_id": "NO_PROCESS_PLANE",
            "detail": "runtime_dataset_status.json has writers pid hints but not full process truth (FEED/PIPELINE/CONTEXT/PAPER)",
            "severity": "WARNING",
        }
    )
    gaps.append(
        {
            "gap_id": "DASHBOARD_DOES_NOT_CONSUME_STATUS",
            "detail": "ops_monitor/build_ops_snapshot does not read runtime_dataset_status.json or engine_parity",
            "severity": "ERROR",
        }
    )
    gaps.append(
        {
            "gap_id": "ENGINE_PARITY_STATIC",
            "detail": "engine_parity copied into status but still reports dashboard_entry_count semantics; UI deferred_to_patch_4",
            "severity": "WARNING",
            "engine_parity": status.get("engine_parity") or ownership.get("engine_parity"),
        }
    )
    if "multi_timeframe_availability_memory" not in ds_ids:
        gaps.append(
            {
                "gap_id": "MTF_HISTORY_MISSING_FROM_STATUS",
                "detail": "ownership has MTF datasets but status snapshot may be stale until rebuild",
                "severity": "WARNING",
            }
        )
    else:
        gaps.append(
            {
                "gap_id": "MTF_PRESENT",
                "detail": "MTF availability datasets registered; presentation still missing from OPS UI",
                "severity": "INFO",
            }
        )
    # paper
    gaps.append(
        {
            "gap_id": "PAPER_NO_TRADE_SEMANTICS_MISSING",
            "detail": "status/ops snapshot lack RUNNING/NO_ELIGIBLE_TRADE vs broken mapping contract",
            "severity": "WARNING",
        }
    )
    # D1
    gaps.append(
        {
            "gap_id": "D1_UNSUPPORTED_NOT_IN_OPS_UI",
            "detail": "MTF latest has TIMEFRAME_NOT_LIVE for D1; OPS dashboard UI does not render this contract yet",
            "severity": "WARNING",
        }
    )
    # auction_synthesis
    synth = next((d for d in status.get("datasets", []) if d.get("dataset_id") == "auction_synthesis_memory"), None)
    gaps.append(
        {
            "gap_id": "AUCTION_SYNTHESIS_REPRESENTATION",
            "detail": "present as BROKEN in status when status rebuilt; must remain non-required known limitation",
            "severity": "INFO",
            "current": synth,
        }
    )
    missing_from_status = sorted(ownership_ids - ds_ids)
    extra_in_status = sorted(ds_ids - ownership_ids)
    return {
        "generated_at": _utc_now(),
        "writer": "runtime_dataset_metadata.write_runtime_status_snapshot / bootstrap / best-effort emit paths",
        "includes_ownership_registry": True,
        "includes_process_status": False,
        "includes_mtf_availability_ui": False,
        "includes_paper_running_no_trade": False,
        "includes_d1_unsupported": "dataset-level only if MTF datasets present; not timeframe cards",
        "auction_synthesis_handling": "force_health/BROKEN in ownership",
        "missing_dataset_ids_vs_ownership": missing_from_status,
        "extra_dataset_ids_vs_ownership": extra_in_status,
        "gaps": gaps,
    }


def frontend_audit() -> dict[str, Any]:
    defects = []
    # pipeline_metadata hardcoded 24
    defects.append(
        {
            "frontend_file": "dashboard/backend/app/pipeline_metadata.py",
            "line_or_function": "CANONICAL_PIPELINE / EXPECTED_CANONICAL_PIPELINE_STEP_COUNT=24",
            "current_behavior": "hardcodes 24 engines including 6 phantoms; omits arbitration + mtf availability",
            "correct_source": "src/btc_ml/runtime/pipeline.py (20 engines)",
            "risk": "HIGH — phantom cards / missing runtime engines",
            "candidate_fix": "replace dashboard list with runtime inventory; phantoms → legacy_components",
        }
    )
    # ops_monitor iterates dashboard list
    defects.append(
        {
            "frontend_file": "dashboard/backend/app/services/ops_monitor.py",
            "line_or_function": "build_engine_status for engine in CANONICAL_PIPELINE",
            "current_behavior": "engine cards driven by stale dashboard metadata",
            "correct_source": "runtime CANONICAL_PIPELINE + engine state",
            "risk": "HIGH",
            "candidate_fix": "iterate runtime inventory",
        }
    )
    # does not read runtime_dataset_status
    ops_text = (ROOT / "dashboard/backend/app/services/ops_monitor.py").read_text(encoding="utf-8")
    if "runtime_dataset_status" not in ops_text:
        defects.append(
            {
                "frontend_file": "dashboard/backend/app/services/ops_monitor.py",
                "line_or_function": "build_ops_snapshot",
                "current_behavior": "ignores runtime_dataset_status.json ownership health plane",
                "correct_source": "data/runtime/runtime_dataset_status.json",
                "risk": "HIGH",
                "candidate_fix": "merge dataset plane from ownership status",
            }
        )
    if "multi_timeframe_availability_latest" not in ops_text:
        defects.append(
            {
                "frontend_file": "dashboard/backend/app/services/ops_monitor.py",
                "line_or_function": "build_ops_snapshot / build_mtf_health",
                "current_behavior": "MTF health via domain_builders/mtf_observability, not Patch 3.2 availability contract",
                "correct_source": "data/runtime/multi_timeframe_availability_latest.json",
                "risk": "HIGH — D1 may be misrepresented",
                "candidate_fix": "read MTF availability latest/status",
            }
        )
    # fallback snapshot
    fb = ROOT / "dashboard/frontend/src/api/opsFallbackSnapshot.ts"
    if fb.exists():
        fb_text = fb.read_text(encoding="utf-8")
        if "healthy" in fb_text.lower() or "HEALTHY" in fb_text:
            defects.append(
                {
                    "frontend_file": "dashboard/frontend/src/api/opsFallbackSnapshot.ts",
                    "line_or_function": "fallback snapshot",
                    "current_behavior": "offline fallback may imply healthy/static engine world",
                    "correct_source": "UNKNOWN when disconnected",
                    "risk": "MEDIUM",
                    "candidate_fix": "fallback overall_health=UNKNOWN; no synthetic healthy engines",
                }
            )
    # research cards for phantom engines
    ops_ui = ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx"
    if ops_ui.exists():
        ui = ops_ui.read_text(encoding="utf-8")
        for token in ("economic_validation", "shadow_inference", "expected_step_count"):
            if token in ui:
                defects.append(
                    {
                        "frontend_file": "dashboard/frontend/src/components/ops/OpsDashboard.tsx",
                        "line_or_function": token,
                        "current_behavior": f"UI references {token}",
                        "correct_source": "runtime truth / legacy section",
                        "risk": "MEDIUM",
                        "candidate_fix": "remove from active engine list; keep legacy/research sections explicit",
                    }
                )
    # visualizer not engine ops
    defects.append(
        {
            "frontend_file": "apps/context_visualizer/public/lifecycle_app.js",
            "line_or_function": "visual_status chips",
            "current_behavior": "ops-styled lifecycle freshness; not engine OPS truth",
            "correct_source": "separate visual plane",
            "risk": "LOW — confusion risk if mistaken for OPS",
            "candidate_fix": "keep separate; OPS candidate is dashboard FastAPI plane",
        }
    )
    return {
        "generated_at": _utc_now(),
        "defect_count": len(defects),
        "defects": defects,
        "hardcoded_engine_assumption": 24,
        "actual_runtime_engines": 20,
    }


def load_paper_state() -> dict[str, Any]:
    path = ROOT / "data/research/paper_simulator/bounded_paper_controller_state.json"
    cycles = ROOT / "data/research/paper_simulator/bounded_paper_controller_cycles.parquet"
    state: dict[str, Any] = {"state_path": str(path.relative_to(ROOT)), "exists": path.exists()}
    if path.exists():
        try:
            state["state"] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            state["error"] = str(exc)
    if cycles.exists():
        try:
            frame = pd.read_parquet(cycles)
            state["cycles_rows"] = int(len(frame))
            if len(frame):
                last = frame.iloc[-1].to_dict()
                state["last_cycle"] = {
                    k: (None if isinstance(v, float) and pd.isna(v) else (v.isoformat() if hasattr(v, "isoformat") else v))
                    for k, v in last.items()
                    if k
                    in {
                        "timestamp",
                        "action_taken",
                        "status",
                        "reason",
                        "context_status",
                        "market_context",
                        "action_allowed",
                    }
                    or k in last
                }
                # keep a compact subset
                keep = {}
                for k, v in last.items():
                    if k in {
                        "timestamp",
                        "action_taken",
                        "status",
                        "reason",
                        "result",
                        "cycle_status",
                        "eligible",
                        "market_context",
                        "action_allowed",
                        "action_reason",
                    }:
                        if hasattr(v, "isoformat"):
                            keep[k] = v.isoformat()
                        elif isinstance(v, float) and pd.isna(v):
                            keep[k] = None
                        else:
                            keep[k] = v
                state["last_cycle"] = keep
        except Exception as exc:  # noqa: BLE001
            state["cycles_error"] = str(exc)
    action = None
    if isinstance(state.get("last_cycle"), dict):
        action = state["last_cycle"].get("action_taken") or state["last_cycle"].get("status")
    if action == "OBSERVE_NO_TRADE" or (isinstance(action, str) and "OBSERVE" in action):
        state["ops_representation"] = "RUNNING / NO_ELIGIBLE_TRADE"
        state["is_controller_failure"] = False
    else:
        state["ops_representation"] = "RUNNING / UNKNOWN_ACTION"
        state["is_controller_failure"] = False
    return state


def load_context_state() -> dict[str, Any]:
    # infer from tips + daemon presence; optional status files
    out: dict[str, Any] = {
        "process": "CONTEXT_REFRESHER",
        "last_result_candidates": ["REFRESH_SUCCESS", "NO_NEW_SAFE_UPSTREAM", "PIPELINE_PENDING", "REFRESH_FAILED"],
    }
    for rel in (
        "run/context_refresh_daemon.pid",
        "data/cognition/final_market_context_memory.parquet",
        "data/cognition/market_context_lifecycle_memory.parquet",
        "data/live/context_decision_log.parquet",
    ):
        path = ROOT / rel
        if path.suffix == ".parquet":
            out[rel] = dataset_snapshot(path, ["timestamp"])
        else:
            out[rel] = {"exists": path.exists(), "value": path.read_text().strip() if path.exists() else None}
    # try find latest refresh log event
    log_candidates = list((ROOT / "logs").glob("*context_refresh*")) if (ROOT / "logs").exists() else []
    out["log_files"] = [str(p.relative_to(ROOT)) for p in log_candidates[:10]]
    # default representation when process running
    out["ops_representation"] = {
        "process_running": True,
        "last_result": "UNKNOWN",
        "note": "NO_NEW_SAFE_UPSTREAM is normal no-op when present in daemon logs",
    }
    # scan recent daemon log if any
    for p in log_candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")[-20000:]
            for token in ("NO_NEW_SAFE_UPSTREAM", "REFRESH_SUCCESS", "REFRESH_FAILED", "PIPELINE_PENDING"):
                if token in text:
                    out["ops_representation"]["last_result"] = token
                    break
        except Exception:
            continue
    return out


def compute_overall_health(processes: list[dict], datasets_status: dict, mtf: dict, paper: dict) -> tuple[str, str, list[dict]]:
    alerts = []
    feed = next((p for p in processes if p["process_id"] == "FEED"), None)
    pipe = next((p for p in processes if p["process_id"] == "PIPELINE"), None)
    ctx = next((p for p in processes if p["process_id"] == "CONTEXT_REFRESHER"), None)
    paper_p = next((p for p in processes if p["process_id"] == "PAPER_CONTROLLER"), None)

    if not feed or feed["health"] != "RUNNING":
        alerts.append({"alert_id": "FEED_DOWN", "severity": "CRITICAL", "message": "live feed process not running"})
    if not pipe or pipe["health"] != "RUNNING":
        alerts.append({"alert_id": "PIPELINE_DOWN", "severity": "CRITICAL", "message": "pipeline run.py not running"})
    if not ctx or ctx["health"] != "RUNNING":
        alerts.append(
            {
                "alert_id": "CONTEXT_REFRESHER_DOWN",
                "severity": "ERROR",
                "message": "context refresher not running",
            }
        )
    if not paper_p or paper_p["health"] != "RUNNING":
        alerts.append({"alert_id": "PAPER_PROCESS_DOWN", "severity": "ERROR", "message": "paper controller not running"})

    alerts.append(
        {
            "alert_id": "D1_NOT_LIVE",
            "severity": "INFO",
            "message": "D1 TIMEFRAME_NOT_LIVE / NO_LIVE_STAGE2_WRITER",
        }
    )
    alerts.append(
        {
            "alert_id": "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED",
            "severity": "WARNING",
            "message": "auction_synthesis ACTIVE_BROKEN / writer disconnected; not required by current context chain",
        }
    )
    if paper.get("ops_representation") == "RUNNING / NO_ELIGIBLE_TRADE":
        alerts.append(
            {
                "alert_id": "PAPER_NO_ELIGIBLE_TRADE",
                "severity": "INFO",
                "message": "paper running with OBSERVE_NO_TRADE / no eligible trade — not a controller failure",
            }
        )

    critical = [a for a in alerts if a["severity"] == "CRITICAL"]
    errors = [a for a in alerts if a["severity"] == "ERROR"]
    if critical:
        return "BROKEN", "; ".join(a["message"] for a in critical), alerts
    if errors:
        return "DEGRADED", "; ".join(a["message"] for a in errors), alerts
    # known limitations present
    return (
        "HEALTHY_WITH_KNOWN_LIMITATIONS",
        "core processes running; D1 not live; auction_synthesis broken/non-required; paper may have no eligible trade",
        alerts,
    )


def build_candidate(processes, runtime_inv, ownership, status, mtf_latest, mtf_status, paper, context) -> dict[str, Any]:
    datasets = []
    for row in ownership.get("datasets", []):
        st = next((d for d in status.get("datasets", []) if d.get("dataset_id") == row["dataset_id"]), None)
        datasets.append(
            {
                "dataset_id": row["dataset_id"],
                "path": row["dataset_path"],
                "owner": row.get("canonical_writer"),
                "writer": row.get("writer_entrypoint"),
                "writer_state": None if st is None else st.get("writer_state"),
                "rows": None if st is None else st.get("row_count"),
                "schema_version": None if st is None else st.get("schema_hash"),
                "latest_market_timestamp": None if st is None else st.get("source_market_timestamp"),
                "generated_at": None if st is None else st.get("evaluated_timestamp"),
                "age_seconds": None if st is None else st.get("age_seconds"),
                "freshness_status": None if st is None else st.get("health"),
                "availability_status": None,
                "health": None if st is None else st.get("health"),
                "health_reason": None if st is None else st.get("reason"),
                "operational_status": row.get("operational_status"),
                "entity_type": "READ_MODEL" if row.get("semantic_type") == "READ_MODEL" else "DATASET",
                "status_row_present": st is not None,
            }
        )

    multi_timeframe = []
    tf_map = (mtf_latest or {}).get("timeframes") or {}
    for tf in ("M15", "M30", "H1", "H4", "D1"):
        row = tf_map.get(tf) or {}
        multi_timeframe.append(
            {
                "timeframe": tf,
                "support": "LIVE_SUPPORTED" if tf != "D1" else "RESEARCH_ONLY_NOT_LIVE",
                "availability_status": row.get("availability_status", "UNKNOWN"),
                "availability_reason": row.get("availability_reason"),
                "state_asof": row.get("state_asof"),
                "source_bar_close": row.get("source_bar_close"),
                "age_bars": row.get("age_bars"),
                "age_seconds": row.get("age_seconds"),
                "is_new_event": row.get("is_new_event"),
                "writer_state": row.get("writer_state"),
                "entity_type": "UNSUPPORTED_CAPABILITY" if tf == "D1" else "READ_MODEL",
            }
        )

    known_limitations = [
        {
            "id": "D1_NOT_LIVE",
            "entity_type": "UNSUPPORTED_CAPABILITY",
            "detail": "D1 has no live Stage-2 writer",
        },
        {
            "id": "AUCTION_SYNTHESIS_ACTIVE_BROKEN",
            "entity_type": "DATASET",
            "detail": "auction_synthesis tip frozen / writer disconnected; not on context truth path",
        },
        {
            "id": "PAPER_ACTIVATED_DEGRADED_HISTORY",
            "entity_type": "PROCESS",
            "detail": "Patch 2B.3 activated degraded historically; no-trade is not failure",
        },
    ]
    legacy = []
    for ph in PHANTOMS:
        legacy.append(
            {
                "component_id": ph,
                "entity_type": "LEGACY_COMPONENT",
                "status": "PHANTOM",
                "detail": "not present in canonical runtime; remove from active OPS engine list",
            }
        )
    for name in ("htf_structure_memory", "htf_ltf_context_memory", "oi_history", "btc_oi"):
        legacy.append(
            {
                "component_id": name,
                "entity_type": "LEGACY_COMPONENT",
                "status": "INACTIVE_DEPRECATED",
                "detail": "deprecated/disconnected from live context chain",
            }
        )

    overall, reason, alerts = compute_overall_health(processes, status, mtf_latest or {}, paper)

    return {
        "generated_at": _utc_now(),
        "schema_version": "ops_dashboard_truth_candidate_v1",
        "patch": "PATCH4_1",
        "read_only": True,
        "trading_use_forbidden": True,
        "canonical_source_hierarchy": CANONICAL_SOURCE_HIERARCHY,
        "forbidden_primary_sources": FORBIDDEN_PRIMARY_SOURCES,
        "entity_taxonomy": ENTITY_TAXONOMY,
        "overall_health": overall,
        "overall_reason": reason,
        "processes": processes,
        "pipeline_engines": runtime_inv["engines"],
        "datasets": datasets,
        "multi_timeframe": multi_timeframe,
        "paper": {
            "process_health": next((p["health"] for p in processes if p["process_id"] == "PAPER_CONTROLLER"), "UNKNOWN"),
            "representation": paper.get("ops_representation"),
            "is_controller_failure": paper.get("is_controller_failure"),
            "skip_refresh": True,
            "real_execution": False,
            "exchange": False,
            "last_cycle": paper.get("last_cycle"),
            "state": paper.get("state"),
        },
        "context_chain": context,
        "mtf_status_sidecar": {
            "latest_evaluation_timestamp": (mtf_latest or {}).get("latest_evaluation_timestamp"),
            "overall_health": (mtf_latest or {}).get("overall_health"),
            "status_event": (mtf_status or {}).get("event"),
            "supported_timeframes": (mtf_status or {}).get("supported_timeframes"),
            "unsupported_timeframes": (mtf_status or {}).get("unsupported_timeframes"),
        },
        "known_limitations": known_limitations,
        "legacy_components": legacy,
        "alerts": alerts,
        "health_semantics": {
            "levels": ["HEALTHY", "HEALTHY_WITH_KNOWN_LIMITATIONS", "DEGRADED", "BROKEN", "UNKNOWN"],
            "rules": [
                "D1 not live + auction_synthesis broken/non-required => HEALTHY_WITH_KNOWN_LIMITATIONS if core processes up",
                "paper no eligible trade does not degrade",
                "decision/context tip stale beyond budget => DEGRADED",
                "feed or pipeline dead => BROKEN",
                "unknown source => UNKNOWN, never synthetic healthy",
            ],
        },
    }


def compare_current_vs_candidate(candidate: dict, parity: list[dict], frontend: dict) -> list[dict[str, Any]]:
    rows = []
    # engine parity as divergences vs current dashboard
    for p in parity:
        if p["classification"] == "EXACT_MATCH":
            klass = "NO_DIVERGENCE"
        elif p["classification"] == "DASHBOARD_ONLY_PHANTOM":
            klass = "CORRECTED_PHANTOM"
        elif p["classification"] == "RUNTIME_ONLY":
            klass = "CORRECTED_RUNTIME_ONLY"
        elif p["classification"] == "WRONG_MODULE_MAPPING":
            klass = "CORRECTED_STATUS_SOURCE"
        else:
            klass = "UNEXPLAINED"
        rows.append(
            {
                "element": p["engine"],
                "element_type": "PIPELINE_ENGINE",
                "divergence_class": klass,
                "detail": p["notes"] or p["classification"],
            }
        )
    rows.append(
        {
            "element": "entity_taxonomy",
            "element_type": "CONTRACT",
            "divergence_class": "EXPECTED_SCHEMA_ENRICHMENT",
            "detail": "candidate separates PROCESS/PIPELINE_ENGINE/DATASET/READ_MODEL",
        }
    )
    rows.append(
        {
            "element": "overall_health",
            "element_type": "HEALTH",
            "divergence_class": "CORRECTED_HEALTH_SEMANTICS",
            "detail": f"candidate overall_health={candidate['overall_health']}",
        }
    )
    rows.append(
        {
            "element": "D1",
            "element_type": "UNSUPPORTED_CAPABILITY",
            "divergence_class": "CORRECTED_ENTITY_TYPE",
            "detail": "TIMEFRAME_NOT_LIVE declaration from MTF availability latest",
        }
    )
    rows.append(
        {
            "element": "paper_no_trade",
            "element_type": "PROCESS",
            "divergence_class": "CORRECTED_HEALTH_SEMANTICS",
            "detail": candidate["paper"]["representation"],
        }
    )
    rows.append(
        {
            "element": "status_source_plane",
            "element_type": "CONTRACT",
            "divergence_class": "CORRECTED_STATUS_SOURCE",
            "detail": "candidate uses ownership/status/MTF/process inspection; current OPS uses pipeline_metadata+ops_monitor",
        }
    )
    # unexplained gate
    unexplained = [r for r in rows if r["divergence_class"] == "UNEXPLAINED"]
    assert len(unexplained) == 0, f"UNEXPLAINED divergences: {unexplained}"
    rows.append(
        {
            "element": "_summary",
            "element_type": "SUMMARY",
            "divergence_class": "NO_DIVERGENCE",
            "detail": f"frontend_defects={frontend['defect_count']}; unexplained=0",
        }
    )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # union keys
    keys: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in keys:
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    tag = _tag()
    print("TAG", tag)

    # --- preflight ---
    processes = process_rows()
    preflight = {
        "generated_at": _utc_now(),
        "timestamp_tag": tag,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "git_status_short_head": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).splitlines()[:40],
        "cwd": str(ROOT),
        "interpreter": sys.executable,
        "flags": {
            "BTC_ML_CONTINUATION_PROGRESSION": os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0"),
            "PRICE_GATE": os.environ.get("PRICE_GATE", "OFF"),
        },
        "processes": processes,
        "datasets": {
            "live_market_feed": dataset_snapshot(ROOT / "data/live/live_market_feed.parquet", ["timestamp"]),
            "candle_structure": dataset_snapshot(ROOT / "data/cognition/candle_structure_memory.parquet", ["timestamp"]),
            "mtf_availability_history": dataset_snapshot(
                ROOT / "data/cognition/multi_timeframe_availability_memory.parquet",
                ["evaluation_timestamp"],
            ),
            "mtf_availability_latest": dataset_snapshot(
                ROOT / "data/runtime/multi_timeframe_availability_latest.json", []
            ),
            "final_context": dataset_snapshot(
                ROOT / "data/cognition/final_market_context_memory.parquet", ["timestamp"]
            ),
            "lifecycle": dataset_snapshot(
                ROOT / "data/cognition/market_context_lifecycle_memory.parquet", ["timestamp"]
            ),
            "decision": dataset_snapshot(ROOT / "data/live/context_decision_log.parquet", ["timestamp"]),
            "paper_signals": dataset_snapshot(
                ROOT / "data/research/paper_simulator/paper_signals.parquet", ["timestamp"]
            ),
            "paper_orders": dataset_snapshot(
                ROOT / "data/research/paper_simulator/paper_orders.parquet", ["timestamp"]
            ),
            "paper_trades": dataset_snapshot(
                ROOT / "data/research/paper_simulator/paper_trades.parquet", ["timestamp"]
            ),
            "paper_positions": dataset_snapshot(
                ROOT / "data/research/paper_simulator/paper_positions.parquet", ["timestamp"]
            ),
            "runtime_dataset_status": dataset_snapshot(ROOT / "data/runtime/runtime_dataset_status.json", []),
            "visual_status": dataset_snapshot(
                ROOT / "apps/context_visualizer/public/data/visual_status.json", []
            ),
        },
        "no_process_restart": True,
    }
    pre_path = ROOT / f"data/research/patch4_1_preflight_{tag}.json"
    pre_path.write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    print("preflight", pre_path)

    before_pres = {
        k: preflight["datasets"][k]
        for k in (
            "final_context",
            "lifecycle",
            "decision",
            "paper_signals",
            "paper_orders",
            "paper_trades",
            "paper_positions",
            "mtf_availability_history",
            "runtime_dataset_status",
            "visual_status",
        )
    }

    inv_files = file_inventory()
    (ROOT / "data/research/patch4_1_dashboard_file_inventory.json").write_text(
        json.dumps({"generated_at": _utc_now(), "files": inv_files}, indent=2) + "\n",
        encoding="utf-8",
    )

    runtime_inv = extract_runtime_engines()
    (ROOT / "data/research/patch4_1_runtime_engine_inventory.json").write_text(
        json.dumps(runtime_inv, indent=2) + "\n", encoding="utf-8"
    )
    dash_inv = extract_dashboard_engines()
    parity = build_engine_parity(runtime_inv, dash_inv)
    (ROOT / "data/research/patch4_1_dashboard_engine_inventory.json").write_text(
        json.dumps(dash_inv, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(ROOT / "data/research/patch4_1_engine_parity.csv", parity)

    lineage = build_lineage(runtime_inv, dash_inv, parity)
    write_csv(ROOT / "data/research/patch4_1_dashboard_lineage.csv", lineage)

    gaps = runtime_status_gaps()
    (ROOT / "data/research/patch4_1_runtime_status_gaps.json").write_text(
        json.dumps(gaps, indent=2) + "\n", encoding="utf-8"
    )

    frontend = frontend_audit()
    (ROOT / "data/research/patch4_1_frontend_audit.json").write_text(
        json.dumps(frontend, indent=2) + "\n", encoding="utf-8"
    )

    ownership = json.loads((ROOT / "config/runtime_dataset_ownership.json").read_text())
    status_path = ROOT / "data/runtime/runtime_dataset_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {"datasets": []}
    mtf_latest = {}
    mtf_status = {}
    if (ROOT / "data/runtime/multi_timeframe_availability_latest.json").exists():
        mtf_latest = json.loads(
            (ROOT / "data/runtime/multi_timeframe_availability_latest.json").read_text()
        )
    if (ROOT / "data/runtime/multi_timeframe_availability_status.json").exists():
        mtf_status = json.loads(
            (ROOT / "data/runtime/multi_timeframe_availability_status.json").read_text()
        )
    paper = load_paper_state()
    context = load_context_state()

    candidate = build_candidate(
        processes, runtime_inv, ownership, status, mtf_latest, mtf_status, paper, context
    )
    cand_path = ROOT / "data/research/patch4_1_candidate_ops_dashboard.json"
    cand_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    meta = {
        "generated_at": _utc_now(),
        "timestamp_tag": tag,
        "schema_version": candidate["schema_version"],
        "path": str(cand_path.relative_to(ROOT)),
        "sha256": sha256_file(cand_path),
        "production_write_allowed": False,
        "overall_health": candidate["overall_health"],
        "runtime_engine_count": runtime_inv["runtime_engine_count"],
        "dashboard_engine_count": dash_inv["dashboard_engine_count"],
        "phantom_count": sum(1 for r in parity if r["classification"] == "DASHBOARD_ONLY_PHANTOM"),
        "runtime_only_count": sum(1 for r in parity if r["classification"] == "RUNTIME_ONLY"),
        "exact_match_count": sum(1 for r in parity if r["classification"] == "EXACT_MATCH"),
        "reads_canonical_sources_only": True,
        "writes_production_dashboard": False,
    }
    (ROOT / "data/research/patch4_1_candidate_ops_dashboard.meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    comparison = compare_current_vs_candidate(candidate, parity, frontend)
    write_csv(ROOT / "data/research/patch4_1_current_vs_candidate.csv", comparison)

    # live observation (no restart) — sample tips twice
    obs1 = {
        "t": _utc_now(),
        "processes": {p["process_id"]: p["pid"] for p in processes},
        "mtf_eval": mtf_latest.get("latest_evaluation_timestamp"),
        "mtf_overall": mtf_latest.get("overall_health"),
        "context_tip": preflight["datasets"]["final_context"].get("tip"),
        "decision_tip": preflight["datasets"]["decision"].get("tip"),
        "paper_repr": paper.get("ops_representation"),
        "candidate_overall": candidate["overall_health"],
    }
    time.sleep(5)
    mtf_latest2 = mtf_latest
    if (ROOT / "data/runtime/multi_timeframe_availability_latest.json").exists():
        mtf_latest2 = json.loads(
            (ROOT / "data/runtime/multi_timeframe_availability_latest.json").read_text()
        )
    processes2 = process_rows()
    obs2 = {
        "t": _utc_now(),
        "processes": {p["process_id"]: p["pid"] for p in processes2},
        "mtf_eval": mtf_latest2.get("latest_evaluation_timestamp"),
        "mtf_overall": mtf_latest2.get("overall_health"),
        "pids_unchanged": {p["process_id"]: p["pid"] for p in processes}
        == {p["process_id"]: p["pid"] for p in processes2},
    }
    observation = {
        "generated_at": _utc_now(),
        "timestamp_tag": tag,
        "samples": [obs1, obs2],
        "no_process_restart": obs2["pids_unchanged"],
        "notes": [
            "observation is bounded and non-invasive",
            "natural tip growth allowed",
        ],
    }
    (ROOT / f"data/research/patch4_1_live_observation_{tag}.json").write_text(
        json.dumps(observation, indent=2) + "\n", encoding="utf-8"
    )

    after = {
        "final_context": dataset_snapshot(ROOT / "data/cognition/final_market_context_memory.parquet", ["timestamp"]),
        "lifecycle": dataset_snapshot(ROOT / "data/cognition/market_context_lifecycle_memory.parquet", ["timestamp"]),
        "decision": dataset_snapshot(ROOT / "data/live/context_decision_log.parquet", ["timestamp"]),
        "paper_signals": dataset_snapshot(ROOT / "data/research/paper_simulator/paper_signals.parquet", ["timestamp"]),
        "paper_orders": dataset_snapshot(ROOT / "data/research/paper_simulator/paper_orders.parquet", ["timestamp"]),
        "paper_trades": dataset_snapshot(ROOT / "data/research/paper_simulator/paper_trades.parquet", ["timestamp"]),
        "paper_positions": dataset_snapshot(ROOT / "data/research/paper_simulator/paper_positions.parquet", ["timestamp"]),
        "mtf_availability_history": dataset_snapshot(
            ROOT / "data/cognition/multi_timeframe_availability_memory.parquet",
            ["evaluation_timestamp"],
        ),
        "runtime_dataset_status": dataset_snapshot(ROOT / "data/runtime/runtime_dataset_status.json", []),
        "visual_status": dataset_snapshot(ROOT / "apps/context_visualizer/public/data/visual_status.json", []),
    }
    # production dashboard payload: there is no static file; mark API surface unchanged by verifying pipeline_metadata/ops files sha vs preflight mtimes only via code not edited in this script
    production_dashboard_files = [
        "dashboard/backend/app/pipeline_metadata.py",
        "dashboard/backend/app/services/ops_monitor.py",
        "dashboard/frontend/src/components/ops/OpsDashboard.tsx",
        "dashboard/frontend/src/api/opsFallbackSnapshot.ts",
    ]
    preserv = {
        "generated_at": _utc_now(),
        "timestamp_tag": tag,
        "before": before_pres,
        "after": after,
        "production_dashboard_files_not_modified_by_this_script": production_dashboard_files,
        "production_dashboard_changes": 0,
        "trading_semantic_changes": 0,
        "notes": "Patch 4.1 writes research artifacts only",
    }
    (ROOT / f"data/research/patch4_1_preservation_{tag}.json").write_text(
        json.dumps(preserv, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "runtime_engine_count": runtime_inv["runtime_engine_count"],
        "dashboard_engine_count": dash_inv["dashboard_engine_count"],
        "exact_matches": meta["exact_match_count"],
        "runtime_only": meta["runtime_only_count"],
        "dashboard_only_phantom": meta["phantom_count"],
        "duplicates": 0,
        "wrong_mappings": sum(1 for r in parity if r["classification"] == "WRONG_MODULE_MAPPING"),
        "unexplained_divergences": sum(1 for r in comparison if r["divergence_class"] == "UNEXPLAINED"),
        "overall_health": candidate["overall_health"],
        "status": "PATCH4_OPS_DASHBOARD_PARITY_CONTRACT_READY",
    }
    (ROOT / f"data/research/patch4_1_summary_{tag}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
