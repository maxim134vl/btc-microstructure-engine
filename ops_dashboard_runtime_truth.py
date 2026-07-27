#!/usr/bin/env python3
"""Canonical OPS dashboard runtime truth builder (Patch 4.1 / 4.2).

Read-only. Shared by FastAPI OPS backend, research audits, and tests.
Does not start writers, refreshers, paper, or exchange clients.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

SCHEMA_VERSION = "ops_dashboard_runtime_truth_v1"

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
    "src/btc_ml/runtime/pipeline.py",
    "config/runtime_dataset_ownership.json",
    "metadata_sidecars",
    "data/runtime/runtime_dataset_status.json",
    "specialized_runtime_statuses",
]

# Legacy / excluded modules. volume_localization is live in Stage-1B+ chains and
# must not be treated as phantom when present in the resolved active pipeline.
LEGACY_PHANTOM_CANDIDATES = (
    "volume_localization_engine_v1.py",
    "market_state_engine_v1.py",
    "trading_state_engine_v1.py",
    "shadow_inference_engine_v1.py",
    "trading_state_validation_engine_v1.py",
    "economic_validation_engine_v1.py",
)

# Default phantom set for inactive legacy engines (volume_localization excluded —
# it is an active producer under BTC_ML_VOLUME_LOCALIZATION_LIVE / Stage 1B+).
PHANTOM_ENGINES = (
    "market_state_engine_v1.py",
    "trading_state_engine_v1.py",
    "shadow_inference_engine_v1.py",
    "trading_state_validation_engine_v1.py",
    "economic_validation_engine_v1.py",
)

STAGE2_SYNTHESIS_INPUTS_LIVE_ENV = "BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE"
VOLUME_LOCALIZATION_LIVE_ENV = "BTC_ML_VOLUME_LOCALIZATION_LIVE"

# Health-affecting required engines (required_manifest contract; not full pipeline size).
REQUIRED_HEALTH_ENGINES = (
    "candle_structure_engine_v1.py",
    "runtime_cognition_engine_v1.py",
    "probabilistic_auction_engine_v1.py",
)

SAFE_PIPELINE_BUILDERS = frozenset(
    {
        "canonical_pipeline_with_volume_localization_candidate",
        "canonical_pipeline_with_stage2_synthesis_inputs_candidate",
    }
)

S4_ACTIVATION_PATH = ROOT / "data/trading/manager/activation.json"
S4_TIMEFRAMES = ("M15", "M30", "H1", "H4")


def s4_activated() -> bool:
    """True once the S4.1 manager/trader architecture owns paper execution."""
    return S4_ACTIVATION_PATH.exists()


def _process_specs() -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    activated = s4_activated()
    specs: list[tuple[str, tuple[str, ...], bool]] = [
        ("live_feed", ("live_binance_intrabar_feed.py",), True),
        ("canonical_pipeline", ("run.py",), True),
        ("context_refresher", ("run_context_refresh_daemon.py",), True),
        # Legacy global controller is required only until the S4.1 cutover.
        ("paper_controller", ("bounded_paper_trading_controller_auto_ledger",), not activated),
        ("ops_backend", ("run_api.py", "dashboard/backend"), False),
        ("dashboard_refresher", ("run_market_context_visual_refresher.py",), False),
        ("timeframe_manager", ("timeframe_manager_daemon.py",), activated),
    ]
    specs.extend(
        (
            f"trader_{tf}",
            (f"timeframe_trader_daemon.py --timeframe {tf}",),
            activated,
        )
        for tf in S4_TIMEFRAMES
    )
    return tuple(specs)


PROCESS_SPECS = _process_specs()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_flag_enabled(name: str, default: str = "0") -> bool:
    raw = os.environ.get(name, default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def active_runtime_flags(environ: dict[str, str] | None = None) -> dict[str, bool]:
    env = environ if environ is not None else os.environ
    def _on(name: str) -> bool:
        raw = str(env.get(name, "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    return {
        STAGE2_SYNTHESIS_INPUTS_LIVE_ENV: _on(STAGE2_SYNTHESIS_INPUTS_LIVE_ENV),
        VOLUME_LOCALIZATION_LIVE_ENV: _on(VOLUME_LOCALIZATION_LIVE_ENV),
    }


def _literal_list_assign(tree: ast.AST, name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return list(ast.literal_eval(node.value))
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return list(ast.literal_eval(node.value))
    raise RuntimeError(f"{name} literal assignment not found")


def _literal_str_assign(tree: ast.AST, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return str(ast.literal_eval(node.value))
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return str(ast.literal_eval(node.value))
    raise RuntimeError(f"{name} string assignment not found")


def _compose_volume_localization_pipeline(tree: ast.AST) -> list[str]:
    base = _literal_list_assign(tree, "_BASE_CANONICAL_PIPELINE_WITHOUT_VOLUME_LOCALIZATION")
    engine = _literal_str_assign(tree, "VOLUME_LOCALIZATION_LIVE_WIRING_ENGINE")
    after = _literal_str_assign(tree, "VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER")
    if engine in base:
        return list(base)
    if after not in base:
        raise RuntimeError(f"missing insert anchor {after}")
    if "volume_response_engine_v1.py" not in base:
        raise RuntimeError("missing volume_response_engine_v1.py in base pipeline")
    idx = base.index(after) + 1
    return base[:idx] + [engine] + base[idx:]


def _compose_stage2_synthesis_pipeline(tree: ast.AST) -> list[str]:
    base = _compose_volume_localization_pipeline(tree)
    extras = _literal_list_assign(tree, "STAGE2_SYNTHESIS_INPUT_ENGINES")
    before = _literal_str_assign(tree, "STAGE2_SYNTHESIS_INPUT_INSERT_BEFORE")
    for engine in extras:
        if engine in base:
            raise RuntimeError(f"stage2 synthesis input already present: {engine}")
    if before not in base:
        raise RuntimeError(f"missing insert anchor {before}")
    idx = base.index(before)
    return base[:idx] + list(extras) + base[idx:]


def _resolve_pipeline_value(node: ast.AST, tree: ast.AST) -> list[str]:
    """Resolve CANONICAL_PIPELINE RHS without eval/exec or importing pipeline.py."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(ast.literal_eval(node))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise RuntimeError("unsupported pipeline builder call form")
        name = node.func.id
        if name not in SAFE_PIPELINE_BUILDERS:
            raise RuntimeError(f"unsafe/unknown pipeline builder: {name}")
        if node.args or node.keywords:
            # Only no-arg builder calls are permitted (source contract).
            raise RuntimeError(f"pipeline builder {name} must be called with no args")
        if name == "canonical_pipeline_with_volume_localization_candidate":
            return _compose_volume_localization_pipeline(tree)
        if name == "canonical_pipeline_with_stage2_synthesis_inputs_candidate":
            return _compose_stage2_synthesis_pipeline(tree)
    if isinstance(node, ast.Name):
        # Reference to another constant list name.
        return _literal_list_assign(tree, node.id)
    raise RuntimeError(f"unsupported CANONICAL_PIPELINE value: {type(node).__name__}")


def _eval_stage2_guard(test: ast.AST, flags: dict[str, bool]) -> bool | None:
    """Return True/False if test is the known stage2 enable helper; else None."""
    # _stage2_synthesis_inputs_live_enabled()
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name):
        if test.func.id == "_stage2_synthesis_inputs_live_enabled" and not test.args and not test.keywords:
            return bool(flags.get(STAGE2_SYNTHESIS_INPUTS_LIVE_ENV, False))
    return None


def _collect_pipeline_assignments(
    nodes: list[ast.stmt],
    guards: tuple[tuple[str, bool], ...],
    out: list[dict[str, Any]],
    flags: dict[str, bool],
) -> None:
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CANONICAL_PIPELINE":
                    out.append({"guards": guards, "value": node.value})
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "CANONICAL_PIPELINE":
                out.append({"guards": guards, "value": node.value})
        elif isinstance(node, ast.If):
            decision = _eval_stage2_guard(node.test, flags)
            if decision is None:
                _collect_pipeline_assignments(
                    list(node.body), guards + (("unknown", True),), out, flags
                )
                _collect_pipeline_assignments(
                    list(node.orelse), guards + (("unknown", False),), out, flags
                )
            else:
                _collect_pipeline_assignments(
                    list(node.body),
                    guards + ((STAGE2_SYNTHESIS_INPUTS_LIVE_ENV, decision),),
                    out,
                    flags,
                )
                _collect_pipeline_assignments(
                    list(node.orelse),
                    guards + ((STAGE2_SYNTHESIS_INPUTS_LIVE_ENV, not decision),),
                    out,
                    flags,
                )
        elif isinstance(
            node,
            (
                ast.For,
                ast.While,
                ast.With,
                ast.Try,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue


def resolve_active_canonical_pipeline(
    path: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve active CANONICAL_PIPELINE from source AST + runtime flags (no import)."""
    path = path or (ROOT / "src/btc_ml/runtime/pipeline.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    flags = active_runtime_flags(environ)
    assignments: list[dict[str, Any]] = []
    _collect_pipeline_assignments(list(tree.body), (), assignments, flags)
    if not assignments:
        raise RuntimeError(f"CANONICAL_PIPELINE not found in {path}")

    selected = None
    for item in assignments:
        guards = item["guards"]
        if not guards:
            selected = item
            continue
        if any(name == "unknown" for name, _ in guards):
            continue
        if all(active for _name, active in guards):
            selected = item
            break
    if selected is None:
        for item in assignments:
            if not item["guards"]:
                selected = item
                break
    if selected is None:
        raise RuntimeError(f"no active CANONICAL_PIPELINE branch for flags={flags}")

    engines = _resolve_pipeline_value(selected["value"], tree)
    builder = None
    value = selected["value"]
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        builder = value.func.id
    elif isinstance(value, (ast.List, ast.Tuple)):
        builder = "literal_list"

    phantoms = tuple(e for e in LEGACY_PHANTOM_CANDIDATES if e not in engines)
    required = [e for e in engines if e in REQUIRED_HEALTH_ENGINES]
    informational = [e for e in engines if e not in REQUIRED_HEALTH_ENGINES]
    return {
        "active_builder": builder,
        "active_flags": flags,
        "ordered_engine_names": list(engines),
        "total_engine_count": len(engines),
        "required_engine_names": required,
        "required_engine_count": len(required),
        "informational_engine_names": informational,
        "ignored_by_health": informational,
        "phantom_engines": list(phantoms),
        "source_path": str(path),
    }


def parse_canonical_pipeline(path: Path | None = None) -> list[str]:
    """Return ordered active pipeline engine list (env-aware AST resolve)."""
    return list(resolve_active_canonical_pipeline(path)["ordered_engine_names"])


def build_pipeline_metadata(path: Path | None = None) -> dict[str, Any]:
    return resolve_active_canonical_pipeline(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _sf(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
    except Exception:
        return None
    return None if out != out else out


def _ps_lines() -> list[str]:
    try:
        return subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,etime=,command="],
            text=True,
        ).splitlines()
    except Exception:
        return []


def _process_create_time(pid: int) -> tuple[float | None, float | None, str | None]:
    """Return (create_time_epoch, uptime_seconds, reason)."""
    try:
        import psutil  # type: ignore

        proc = psutil.Process(pid)
        created = float(proc.create_time())
        uptime = max(0.0, time.time() - created)
        return created, uptime, None
    except Exception:
        pass
    try:
        # macOS/Linux fallback via ps etime is lossy; prefer lstart when available.
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
        ).strip()
        if not out:
            return None, None, "PIPELINE_PID_UNAVAILABLE"
        import time as _time
        from email.utils import parsedate_to_datetime

        # ps lstart format e.g. "Mon Jul 27 09:06:40 2026"
        try:
            from datetime import datetime as _dt

            created_dt = _dt.strptime(out, "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
            # lstart is local wall clock; convert via timestamp() using local interpretation:
            created = _dt.strptime(out, "%a %b %d %H:%M:%S %Y").timestamp()
        except Exception:
            return None, None, "PIPELINE_PID_CREATE_TIME_UNPARSEABLE"
        return created, max(0.0, _time.time() - created), None
    except Exception:
        return None, None, "PIPELINE_PID_UNAVAILABLE"


def inspect_processes() -> list[dict[str, Any]]:
    lines = _ps_lines()
    out: list[dict[str, Any]] = []
    for process_id, tokens, required in _process_specs():
        matched = None
        for line in lines:
            text = line.strip()
            if not text or "rg " in text or "zsh -c" in text or "pytest" in text:
                continue
            if process_id == "canonical_pipeline":
                if not (text.endswith("run.py") or " run.py" in f" {text}" or text.endswith("/run.py")):
                    continue
            if process_id == "ops_backend":
                if "run_api.py" not in text and "uvicorn" not in text:
                    continue
            if any(tok in text for tok in tokens):
                matched = text
                break
        if matched is None:
            out.append(
                {
                    "process_id": process_id,
                    "display_name": process_id,
                    "role": process_id,
                    "pid": None,
                    "ppid": None,
                    "alive": False,
                    "process_state": "STOPPED",
                    "interpreter": None,
                    "cwd": None,
                    "command": None,
                    "started_at": None,
                    "create_time": None,
                    "uptime_seconds": None,
                    "uptime_reason": "PROCESS_NOT_FOUND",
                    "last_heartbeat": utc_now(),
                    "restart_count": None,
                    "owner": process_id,
                    "health": "STOPPED",
                    "health_reason": "process_not_found_in_ps",
                    "required": required,
                    "entity_type": "PROCESS",
                }
            )
            continue
        parts = matched.split(None, 3)
        pid = int(parts[0])
        ppid = int(parts[1]) if len(parts) > 1 else None
        command = parts[3] if len(parts) > 3 else matched
        interpreter = command.split()[0] if command else None
        proc_state = "RUNNING"
        health = "RUNNING"
        reason = "process_alive_identity_matched"
        try:
            state_out = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "state="],
                text=True,
            ).strip()
            if state_out.startswith("Z"):
                proc_state = "ZOMBIE"
                health = "ZOMBIE"
                reason = "pid_identity_matched_but_zombie"
        except Exception:
            pass
        if health == "RUNNING" and interpreter:
            base = os.path.basename(interpreter)
            # Trading/model processes must not run under system python3 without project venv markers.
            if process_id in {
                "canonical_pipeline",
                "paper_controller",
                "context_refresher",
                "live_feed",
                "timeframe_manager",
            } or process_id.startswith("trader_"):
                if base in {"python", "python3"} and "/.venv/" not in interpreter and "venv" not in interpreter:
                    # Allow bare python3 when cwd/command still bind to repo scripts (common launch style).
                    if "btc-ml" not in command and str(ROOT) not in command:
                        proc_state = "WRONG_INTERPRETER"
                        health = "WRONG_INTERPRETER"
                        reason = "interpreter_identity_mismatch"
        if process_id == "paper_controller" and "--skip-refresh" in command and health == "RUNNING":
            reason = "running_skip_refresh_no_real_execution"
        if process_id == "ops_backend" and health == "RUNNING":
            reason = "ops_backend_alive_not_trading_pipeline"
        created, uptime, uptime_reason = _process_create_time(pid)
        started_at = None
        if created is not None:
            started_at = datetime.fromtimestamp(created, timezone.utc).isoformat().replace("+00:00", "Z")
        out.append(
            {
                "process_id": process_id,
                "display_name": process_id,
                "role": process_id,
                "pid": pid,
                "ppid": ppid,
                "alive": health == "RUNNING",
                "process_state": proc_state,
                "interpreter": interpreter,
                "cwd": str(ROOT),
                "command": command[:300],
                "started_at": started_at,
                "create_time": created,
                "uptime_seconds": uptime,
                "uptime_reason": uptime_reason,
                "last_heartbeat": utc_now(),
                "restart_count": None,
                "owner": process_id,
                "health": health,
                "health_reason": reason,
                "required": required,
                "entity_type": "PROCESS",
            }
        )
    return out


def pipeline_runtime_uptime(processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Runtime age from canonical pipeline PID create_time — never host boot time."""
    rows = processes if processes is not None else inspect_processes()
    pipe = next((p for p in rows if p.get("process_id") == "canonical_pipeline"), None)
    if not pipe or not pipe.get("pid") or pipe.get("health") != "RUNNING":
        return {
            "runtime_uptime_seconds": None,
            "pipeline_pid": None if not pipe else pipe.get("pid"),
            "source": "pipeline_pid_create_time",
            "reason": "PIPELINE_PID_UNAVAILABLE",
            "host_boot_time_substituted": False,
        }
    created, uptime, reason = _process_create_time(int(pipe["pid"]))
    if uptime is None:
        return {
            "runtime_uptime_seconds": None,
            "pipeline_pid": pipe["pid"],
            "source": "pipeline_pid_create_time",
            "reason": reason or "PIPELINE_PID_UNAVAILABLE",
            "host_boot_time_substituted": False,
        }
    return {
        "runtime_uptime_seconds": uptime,
        "pipeline_pid": pipe["pid"],
        "create_time": created,
        "source": "pipeline_pid_create_time",
        "reason": None,
        "host_boot_time_substituted": False,
    }

def build_pipeline_engines(
    engines: list[str] | None = None,
    *,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    meta = metadata if metadata is not None else resolve_active_canonical_pipeline()
    engine_names = list(engines) if engines is not None else list(meta["ordered_engine_names"])
    state_path = ROOT / "data/diagnostics/runtime_engine_state.parquet"
    latest: dict[str, dict[str, Any]] = {}
    try:
        from storage.path_registry import resolve_read

        resolved = Path(resolve_read("runtime_engine_state.parquet"))
        if resolved.exists():
            state_path = resolved
    except Exception:
        pass
    if state_path.exists():
        try:
            import pandas as pd

            frame = pd.read_parquet(state_path)
            if "engine" in frame.columns:
                for eng, group in frame.groupby("engine"):
                    row = group.iloc[-1].to_dict()
                    cleaned = {}
                    for k, v in row.items():
                        if hasattr(v, "isoformat"):
                            cleaned[k] = v.isoformat()
                        elif isinstance(v, float) and pd.isna(v):
                            cleaned[k] = None
                        else:
                            cleaned[k] = v
                    latest[str(eng)] = cleaned
        except Exception:
            latest = {}

    required_set = set(REQUIRED_HEALTH_ENGINES)
    rows = []
    for idx, eng in enumerate(engine_names, start=1):
        st = latest.get(eng, {})
        raw = str(st.get("status") or st.get("result") or "UNKNOWN")
        mapped = raw.upper()
        if mapped in {"SUCCESS", "OK"}:
            result = "SUCCESS"
        elif mapped in {"SUCCESS_NO_NEW_OUTPUT", "NO_NEW_OUTPUT"}:
            result = "SUCCESS_NO_NEW_OUTPUT"
        elif mapped in {"EVENT_SPARSE_NO_EVENT", "EVENT_SPARSE", "NO_EVENT"}:
            result = "EVENT_SPARSE_NO_EVENT"
        elif mapped in {"FAILED", "ERROR", "TIMEOUT"}:
            result = "FAILED"
        elif mapped in {"SKIPPED", "DEFERRED", "SKIPPED_BY_DESIGN"}:
            result = "SKIPPED_BY_DESIGN"
        elif mapped in {"WAITING_FOR_INPUT", "WAITING"}:
            result = "WAITING_FOR_INPUT"
        elif mapped in {"DISABLED", "DEPRECATED"}:
            result = mapped
        else:
            result = "UNKNOWN" if mapped in {"", "UNKNOWN", "NONE", "NULL"} else mapped
        is_required_health = eng in required_set
        # auction_synthesis remains non-blocking for overall health (known limitation).
        required = is_required_health
        non_failure = {
            "SUCCESS",
            "SUCCESS_NO_NEW_OUTPUT",
            "EVENT_SPARSE_NO_EVENT",
            "SKIPPED_BY_DESIGN",
            "WAITING_FOR_INPUT",
            "DISABLED",
            "DEPRECATED",
        }
        if result == "FAILED":
            eng_health = "FAILED"
        elif result == "UNKNOWN":
            eng_health = "UNKNOWN"
        elif result in non_failure:
            eng_health = "HEALTHY"
        else:
            eng_health = "UNKNOWN"
        rows.append(
            {
                "engine_id": eng,
                "display_name": eng.replace("_engine_v1.py", "").replace("_engine_v3.py", "").replace("_v1.py", ""),
                "module": eng.replace(".py", ""),
                "file": eng,
                "pipeline_order": idx,
                "enabled": True,
                "required": required,
                "ignored_by_health": not is_required_health,
                "phantom": False,
                "last_cycle_id": st.get("cycle") or st.get("cycle_id"),
                "last_result": result,
                "last_success": st.get("timestamp") or st.get("finished_at"),
                "duration_ms": None
                if st.get("duration") is None
                else int(float(st["duration"]) * 1000)
                if isinstance(st.get("duration"), (int, float))
                else None,
                "input_tip": None,
                "output_tip": None,
                "health": eng_health,
                "health_reason": f"last_result={result}",
                "entity_type": "PIPELINE_ENGINE",
            }
        )
    return rows


def build_datasets() -> list[dict[str, Any]]:
    ownership = _read_json(ROOT / "config/runtime_dataset_ownership.json") or {"datasets": []}
    status = _read_json(ROOT / "data/runtime/runtime_dataset_status.json") or {"datasets": []}
    by_id = {d.get("dataset_id"): d for d in status.get("datasets") or []}
    rows = []
    for row in ownership.get("datasets") or []:
        st = by_id.get(row.get("dataset_id")) or {}
        rows.append(
            {
                "dataset_id": row.get("dataset_id"),
                "display_name": row.get("logical_state") or row.get("dataset_id"),
                "entity_type": "READ_MODEL"
                if row.get("semantic_type") == "READ_MODEL"
                else "DATASET",
                "path": row.get("dataset_path"),
                "owner": row.get("canonical_writer"),
                "writer": row.get("writer_entrypoint"),
                "writer_state": st.get("writer_state"),
                "rows": st.get("row_count"),
                "schema_version": st.get("schema_hash"),
                "latest_market_timestamp": st.get("source_market_timestamp"),
                "generated_at": st.get("evaluated_timestamp"),
                "age_seconds": st.get("age_seconds"),
                "freshness_status": st.get("health"),
                "availability_status": None,
                "health": st.get("health") or "UNKNOWN",
                "health_reason": st.get("reason") or "status_row_missing",
                "required": bool(row.get("require_live_writer")),
                "operational_status": row.get("operational_status"),
                "status_row_present": bool(st),
            }
        )
    return rows


def build_multi_timeframe() -> list[dict[str, Any]]:
    latest = _read_json(ROOT / "data/runtime/multi_timeframe_availability_latest.json") or {}
    tf_map = latest.get("timeframes") or {}
    rows = []
    for tf in ("M15", "M30", "H1", "H4", "D1"):
        row = tf_map.get(tf) or {}
        if tf == "D1":
            rows.append(
                {
                    "timeframe": "D1",
                    "support": "RESEARCH_ONLY_NOT_LIVE",
                    "availability_status": row.get("availability_status") or "TIMEFRAME_NOT_LIVE",
                    "availability_reason": row.get("availability_reason") or "NO_LIVE_STAGE2_WRITER",
                    "display_status": "NOT_LIVE",
                    "requirement": "EXPECTED",
                    "detail": "No live Stage-2 writer · No D1 timeframe trader",
                    "state_asof": None,
                    "source_state_timestamp": None,
                    "source_bar_close": None,
                    "age_seconds": None,
                    "age_bars": None,
                    "is_new_event": False,
                    "writer_state": row.get("writer_state") or "NOT_IMPLEMENTED_LIVE",
                    "entity_type": "UNSUPPORTED_CAPABILITY",
                }
            )
            continue
        rows.append(
            {
                "timeframe": tf,
                "support": "LIVE_SUPPORTED",
                "availability_status": row.get("availability_status") or "UNKNOWN",
                "availability_reason": row.get("availability_reason"),
                "state_asof": row.get("state_asof"),
                "source_state_timestamp": row.get("source_state_timestamp"),
                "source_bar_close": row.get("source_bar_close"),
                "age_seconds": row.get("age_seconds"),
                "age_bars": row.get("age_bars"),
                "is_new_event": row.get("is_new_event"),
                "writer_state": row.get("writer_state"),
                "entity_type": "READ_MODEL",
            }
        )
    return rows


def build_paper() -> dict[str, Any]:
    state = _read_json(ROOT / "data/research/paper_simulator/bounded_paper_controller_state.json")
    cycles_path = ROOT / "data/research/paper_simulator/bounded_paper_controller_cycles.parquet"
    last_cycle: dict[str, Any] = {}
    if cycles_path.exists():
        try:
            import pandas as pd

            frame = pd.read_parquet(cycles_path)
            if len(frame):
                row = frame.iloc[-1].to_dict()
                for k in (
                    "timestamp",
                    "action_taken",
                    "status",
                    "reason",
                    "market_context",
                    "action_allowed",
                    "action_reason",
                ):
                    if k in row:
                        v = row[k]
                        last_cycle[k] = v.isoformat() if hasattr(v, "isoformat") else (
                            None if isinstance(v, float) and pd.isna(v) else v
                        )
        except Exception:
            last_cycle = {}
    action = str(last_cycle.get("action_taken") or last_cycle.get("status") or "")
    if "OBSERVE" in action or action in {"NO_ELIGIBLE_TRADE", "NON_DIRECTIONAL", "NO_CONTEXT_START"}:
        representation = "RUNNING_NO_ELIGIBLE_TRADE"
        failure = False
    elif action:
        representation = "RUNNING_NO_ELIGIBLE_TRADE"
        failure = False
    else:
        representation = "UNKNOWN"
        failure = False
    return {
        "process_health": "RUNNING",
        "mode": "paper_only",
        "skip_refresh": True,
        "real_execution": False,
        "exchange_enabled": False,
        "last_cycle_result": action or None,
        "representation": representation,
        "is_controller_failure": failure,
        "last_cycle": last_cycle,
        "state": state,
        "health": "HEALTHY",
        "health_reason": "no_trade_is_not_controller_failure"
        if representation == "RUNNING_NO_ELIGIBLE_TRADE"
        else "paper_state_unknown",
    }


# VIS0B — canonical manager risk for OPS (observability only; never invent $0).
MANAGER_PORTFOLIO_SUMMARY_PATH = ROOT / "data/trading/manager/portfolio_summary.json"
RISK_SOURCE_STALE_SECONDS = 30 * 60
RISK_SEMANTICS_RESERVED_OPEN = "reserved_open_risk"


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _risk_freshness(tip: str | None, *, now: datetime | None = None) -> str:
    """Freshness of a manager risk tip. Unchanged open positions are not stale by themselves."""
    if not tip:
        return "UNAVAILABLE"
    try:
        stamp = datetime.fromisoformat(str(tip).replace("Z", "+00:00"))
    except Exception:
        return "UNAVAILABLE"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - stamp.astimezone(timezone.utc)).total_seconds()
    if age < 0:
        return "FRESH"
    if age <= RISK_SOURCE_STALE_SECONDS:
        return "FRESH"
    if age <= RISK_SOURCE_STALE_SECONDS * 4:
        return "CARRIED_FORWARD"
    return "STALE"


def _resolve_reserved_open_risk_usd(
    *,
    open_position_count: int,
    trader_view: dict[str, Any],
    position_row: dict[str, Any] | None,
    portfolio_tip: str | None,
) -> dict[str, Any]:
    """Resolve per-TF reserved open risk. Missing never becomes 0 when a position is open."""
    tip = portfolio_tip
    if open_position_count <= 0:
        return {
            "reserved_risk_usd": 0.0,
            "open_risk_usd": 0.0,
            "risk_status": "ZERO_CONFIRMED",
            "risk_source": "flat_no_open_position",
            "risk_source_tip": tip,
            "risk_freshness": _risk_freshness(tip) if tip else "FRESH",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
        }

    # Level 2 — manager portfolio_summary traders[TF].open_risk_usd (entry-gate peer).
    if "open_risk_usd" in trader_view and trader_view.get("open_risk_usd") is not None:
        value = _sf(trader_view.get("open_risk_usd"))
        if value is None:
            pass
        else:
            status = "ZERO_CONFIRMED" if abs(float(value)) < 1e-12 else "AVAILABLE"
            freshness = _risk_freshness(tip)
            if freshness == "STALE":
                return {
                    "reserved_risk_usd": None,
                    "open_risk_usd": None,
                    "risk_status": "SOURCE_STALE",
                    "risk_source": "manager_portfolio_summary.traders[].open_risk_usd",
                    "risk_source_tip": tip,
                    "risk_freshness": freshness,
                    "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
                }
            return {
                "reserved_risk_usd": float(value),
                "open_risk_usd": float(value),
                "risk_status": status,
                "risk_source": "manager_portfolio_summary.traders[].open_risk_usd",
                "risk_source_tip": tip,
                "risk_freshness": freshness,
                "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            }

    # Level 3 — same formula PaperTraderEngine.snapshot uses (metadata approved_risk_usd).
    meta = _parse_json_object((position_row or {}).get("metadata_json"))
    approved = _sf(meta.get("approved_risk_usd"))
    if approved is None:
        approved = _sf((position_row or {}).get("risk_amount_usd"))
    if approved is not None:
        status = "ZERO_CONFIRMED" if abs(float(approved)) < 1e-12 else "AVAILABLE"
        return {
            "reserved_risk_usd": float(approved),
            "open_risk_usd": float(approved),
            "risk_status": status,
            "risk_source": "position.metadata_json.approved_risk_usd",
            "risk_source_tip": tip,
            "risk_freshness": _risk_freshness(tip) if tip else "CARRIED_FORWARD",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
        }

    # Level 4 — explicit unavailable (never coerce open+missing → 0).
    return {
        "reserved_risk_usd": None,
        "open_risk_usd": None,
        "risk_status": "ATTRIBUTION_UNAVAILABLE",
        "risk_source": None,
        "risk_source_tip": tip,
        "risk_freshness": "UNAVAILABLE",
        "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
    }


def _resolve_aggregate_portfolio_risk(
    portfolio: dict[str, Any],
    *,
    book_open_positions: int,
) -> dict[str, Any]:
    """Level 1 aggregate risk from manager portfolio_summary (entry-gate source)."""
    tip = portfolio.get("generated_at") or portfolio.get("evaluation_timestamp")
    tip_s = None if tip is None else str(tip)
    freshness = _risk_freshness(tip_s)
    has_manager = bool(portfolio) and (
        portfolio.get("gross_open_risk_usd") is not None
        or portfolio.get("portfolio_max_risk_usd") is not None
        or portfolio.get("available_risk_usd") is not None
    )
    if not has_manager:
        return {
            "max_risk_usd": None,
            "portfolio_max_risk_usd": None,
            "reserved_open_risk_usd": None,
            "gross_open_risk_usd": None,
            "available_risk_usd": None,
            "risk_utilisation_pct": None,
            "open_positions": book_open_positions,
            "open_position_count": book_open_positions,
            "risk_source": None,
            "risk_source_tip": tip_s,
            "risk_status": "SOURCE_UNAVAILABLE",
            "risk_freshness": "UNAVAILABLE",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            "observability_health": "DEGRADED_OBSERVABILITY",
        }

    if freshness == "STALE":
        open_count = portfolio.get("open_positions")
        open_count_i = book_open_positions if open_count is None else int(open_count)
        return {
            "max_risk_usd": None,
            "portfolio_max_risk_usd": None,
            "reserved_open_risk_usd": None,
            "gross_open_risk_usd": None,
            "available_risk_usd": None,
            "risk_utilisation_pct": None,
            "open_positions": open_count_i,
            "open_position_count": open_count_i,
            "risk_source": "data/trading/manager/portfolio_summary.json",
            "risk_source_tip": tip_s,
            "risk_status": "SOURCE_STALE",
            "risk_freshness": freshness,
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            "observability_health": "DEGRADED_OBSERVABILITY",
        }

    max_risk = _sf(portfolio.get("portfolio_max_risk_usd"))
    reserved = _sf(portfolio.get("gross_open_risk_usd"))
    available = _sf(portfolio.get("available_risk_usd"))
    if available is None and max_risk is not None and reserved is not None:
        available = max(0.0, float(max_risk) - float(reserved))
    util = None
    if max_risk is not None and float(max_risk) > 0 and reserved is not None:
        util = round(100.0 * float(reserved) / float(max_risk), 6)
    open_count = portfolio.get("open_positions")
    open_count_i = book_open_positions if open_count is None else int(open_count)
    status = "AVAILABLE"
    if reserved is not None and abs(float(reserved)) < 1e-12:
        status = "ZERO_CONFIRMED"
    return {
        "max_risk_usd": max_risk,
        "portfolio_max_risk_usd": max_risk,
        "reserved_open_risk_usd": reserved,
        "gross_open_risk_usd": reserved,
        "available_risk_usd": available,
        "risk_utilisation_pct": util,
        "open_positions": open_count_i,
        "open_position_count": open_count_i,
        "risk_source": "data/trading/manager/portfolio_summary.json",
        "risk_source_tip": tip_s,
        "risk_status": status,
        "risk_freshness": freshness,
        "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
        "observability_health": "OPERATIONAL",
    }


def build_timeframe_traders() -> dict[str, Any]:
    """S4.1 read-only view: manager, command bus, four independent trader books.

    Data binding only — no new visual language, no writes.
    """
    activation = _read_json(S4_ACTIVATION_PATH)
    manager_latest = _read_json(ROOT / "data/runtime/timeframe_manager_latest.json") or {}
    portfolio = _read_json(MANAGER_PORTFOLIO_SUMMARY_PATH) or {}
    portfolio_tip = portfolio.get("generated_at") or portfolio.get("evaluation_timestamp")
    portfolio_tip_s = None if portfolio_tip is None else str(portfolio_tip)
    bus_path = ROOT / "data/trading/manager/timeframe_command_memory.parquet"
    bus: dict[str, Any] = {
        "path": "data/trading/manager/timeframe_command_memory.parquet",
        "exists": bus_path.exists(),
        "append_only": True,
        "rows": 0,
        "duplicate_command_ids": 0,
        "latest_evaluation_timestamp": None,
        "health": "NOT_ACTIVATED" if activation is None else "UNKNOWN",
    }
    commands_by_tf: dict[str, dict[str, Any]] = {}
    if bus_path.exists():
        try:
            import pandas as pd

            frame = pd.read_parquet(bus_path)
            bus["rows"] = int(len(frame))
            if len(frame):
                bus["duplicate_command_ids"] = int(
                    len(frame) - frame["command_id"].astype(str).nunique()
                )
                stamps = pd.to_datetime(frame["evaluation_timestamp"], utc=True, errors="coerce")
                tip = stamps.max()
                bus["latest_evaluation_timestamp"] = (
                    None if pd.isna(tip) else tip.isoformat().replace("+00:00", "Z")
                )
                ordered = frame.assign(_ts=stamps).sort_values("_ts")
                for tf in S4_TIMEFRAMES:
                    slice_ = ordered[ordered["timeframe"].astype(str) == tf]
                    if not len(slice_):
                        continue
                    row = slice_.iloc[-1].to_dict()
                    commands_by_tf[tf] = {
                        "command_id": row.get("command_id"),
                        "intent": row.get("intent"),
                        "evaluation_timestamp": row.get("evaluation_timestamp"),
                        "timeframe_direction": row.get("timeframe_direction"),
                        "availability_status": row.get("availability_status"),
                        "approved_risk_usd": _sf(row.get("approved_risk_usd")),
                    }
            bus["health"] = "HEALTHY" if bus["duplicate_command_ids"] == 0 else "BROKEN"
        except Exception as exc:  # noqa: BLE001
            bus["health"] = "UNKNOWN"
            bus["error"] = f"{type(exc).__name__}: {exc}"

    traders: list[dict[str, Any]] = []
    realized_total = 0.0
    unrealized_total = 0.0
    book_open_positions = 0
    tf_attribution_gaps = 0
    process_by_tf: dict[str, dict[str, Any]] = {}
    try:
        for proc in inspect_processes():
            pid_name = str(proc.get("process_id") or "")
            if pid_name.startswith("trader_"):
                process_by_tf[pid_name.replace("trader_", "", 1)] = proc
    except Exception:
        process_by_tf = {}
    for tf in S4_TIMEFRAMES:
        book = ROOT / "data/trading/timeframe_traders" / tf
        proc = process_by_tf.get(tf) or {}
        entry: dict[str, Any] = {
            "timeframe": tf,
            "entity_type": "TIMEFRAME_TRADER",
            "book_path": f"data/trading/timeframe_traders/{tf}",
            "book_exists": book.exists(),
            "pid": proc.get("pid"),
            "alive": bool(proc.get("alive")),
            "process_health": proc.get("health"),
            "open_position_id": None,
            "direction": "FLAT",
            "entry_price": None,
            "quantity": None,
            "open_risk_usd": None,
            "reserved_risk_usd": None,
            "risk_status": "SOURCE_UNAVAILABLE",
            "risk_source": None,
            "risk_source_tip": portfolio_tip_s,
            "risk_freshness": "UNAVAILABLE",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "open_position_count": 0,
            "closed_trades": 0,
            "last_command_id": None,
            "last_command_intent": None,
            "command_cursor": None,
            "book_tip": None,
            "paper_only": True,
            "execution_enabled": False,
        }
        state = _read_json(book / "controller_state.json") or {}
        entry["last_command_id"] = state.get("last_command_id")
        entry["last_command_intent"] = state.get("last_command_intent") or state.get("last_intent")
        entry["command_cursor"] = state.get("cursor_evaluation_timestamp") or state.get("command_cursor")
        position_row: dict[str, Any] | None = None
        try:
            import pandas as pd

            positions_path = book / "positions.parquet"
            if positions_path.exists():
                frame = pd.read_parquet(positions_path)
                entry["book_tip"] = None
                if "opened_at" in frame.columns and len(frame):
                    tip = pd.to_datetime(frame["opened_at"], utc=True, errors="coerce").max()
                    if pd.notna(tip):
                        entry["book_tip"] = tip.isoformat().replace("+00:00", "Z")
                if len(frame) and "status" in frame.columns:
                    open_rows = frame[frame["status"].astype(str).str.upper() == "OPEN"]
                    entry["open_position_count"] = int(len(open_rows))
                    if len(open_rows):
                        position_row = open_rows.iloc[-1].to_dict()
                        entry["open_position_id"] = position_row.get("position_id")
                        entry["direction"] = str(position_row.get("direction") or "FLAT").upper()
                        entry["entry_price"] = _sf(position_row.get("entry_price"))
                        entry["quantity"] = _sf(position_row.get("quantity"))
                        book_open_positions += 1
            trades_path = book / "trades.parquet"
            if trades_path.exists():
                trades = pd.read_parquet(trades_path)
                entry["closed_trades"] = int(len(trades))
                if len(trades) and "net_pnl_usd" in trades.columns:
                    entry["realized_pnl_usd"] = float(
                        pd.to_numeric(trades["net_pnl_usd"], errors="coerce").fillna(0).sum()
                    )
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        trader_view = ((portfolio.get("traders") or {}).get(tf)) or {}
        if trader_view.get("unrealized_pnl_usd") is not None:
            entry["unrealized_pnl_usd"] = _sf(trader_view.get("unrealized_pnl_usd")) or 0.0
        risk_fields = _resolve_reserved_open_risk_usd(
            open_position_count=int(entry["open_position_count"] or 0),
            trader_view=trader_view,
            position_row=position_row,
            portfolio_tip=portfolio_tip_s,
        )
        entry.update(risk_fields)
        if entry["open_position_count"] and entry.get("reserved_risk_usd") is None:
            tf_attribution_gaps += 1
        entry["last_command"] = commands_by_tf.get(tf)
        realized_total += float(entry["realized_pnl_usd"] or 0.0)
        unrealized_total += float(entry["unrealized_pnl_usd"] or 0.0)
        traders.append(entry)

    aggregate = _resolve_aggregate_portfolio_risk(portfolio, book_open_positions=book_open_positions)
    if tf_attribution_gaps and aggregate.get("risk_status") in {"AVAILABLE", "ZERO_CONFIRMED"}:
        aggregate["observability_health"] = "OPERATIONAL_WITH_LIMITATIONS"
    elif aggregate.get("risk_status") == "SOURCE_UNAVAILABLE":
        aggregate["observability_health"] = "DEGRADED_OBSERVABILITY"

    return {
        "entity_type": "TIMEFRAME_TRADING_PLANE",
        "activated": activation is not None,
        "activation_timestamp": (activation or {}).get("activation_timestamp"),
        "supported_timeframes": list(S4_TIMEFRAMES),
        "unsupported_timeframes": {"D1": "TIMEFRAME_NOT_LIVE/NO_LIVE_STAGE2_WRITER"},
        "d1_trader": False,
        "manager": {
            "manager_cycle_id": manager_latest.get("manager_cycle_id"),
            "evaluation_timestamp": manager_latest.get("evaluation_timestamp"),
            "generated_at": manager_latest.get("generated_at"),
            "commands": manager_latest.get("commands") or commands_by_tf,
            "writes_paper_ledger": False,
            "writes_cognition": False,
            "directional_netting": False,
        },
        "command_bus": bus,
        "traders": traders,
        "portfolio": {
            "open_positions": aggregate["open_positions"],
            "open_position_count": aggregate["open_position_count"],
            "gross_long_notional": _sf(portfolio.get("gross_long_notional")),
            "gross_short_notional": _sf(portfolio.get("gross_short_notional")),
            "net_notional": _sf(portfolio.get("net_notional")),
            "net_notional_semantics": "REPORTING_ONLY_NEVER_NETTED",
            "gross_open_risk_usd": aggregate["gross_open_risk_usd"],
            "reserved_open_risk_usd": aggregate["reserved_open_risk_usd"],
            "portfolio_max_risk_usd": aggregate["portfolio_max_risk_usd"],
            "max_risk_usd": aggregate["max_risk_usd"],
            "available_risk_usd": aggregate["available_risk_usd"],
            "risk_utilisation_pct": aggregate["risk_utilisation_pct"],
            "risk_source": aggregate["risk_source"],
            "risk_source_tip": aggregate["risk_source_tip"],
            "risk_status": aggregate["risk_status"],
            "risk_freshness": aggregate["risk_freshness"],
            "risk_semantics": aggregate["risk_semantics"],
            "observability_health": aggregate["observability_health"],
            "realized_pnl": realized_total,
            "unrealized_pnl": unrealized_total,
            "risk_aggregation": "GROSS_NO_NETTING",
        },
        "read_only": True,
        "paper_only": True,
        "real_execution": False,
        "exchange_calls": 0,
    }


def build_context_chain() -> dict[str, Any]:
    def tip(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            import pandas as pd

            frame = pd.read_parquet(path)
            if "timestamp" not in frame.columns or not len(frame):
                return None
            return pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").max().isoformat()
        except Exception:
            return None

    last_result = "UNKNOWN"
    for log in (ROOT / "logs").glob("*context_refresh*") if (ROOT / "logs").exists() else []:
        try:
            text = log.read_text(encoding="utf-8", errors="ignore")[-30000:]
            for token in ("NO_NEW_SAFE_UPSTREAM", "REFRESH_SUCCESS", "REFRESH_FAILED", "PIPELINE_PENDING"):
                if token in text:
                    last_result = token
                    break
            if last_result != "UNKNOWN":
                break
        except Exception:
            continue
    healthy_noop = last_result in {"REFRESH_SUCCESS", "NO_NEW_SAFE_UPSTREAM", "PIPELINE_PENDING", "UNKNOWN"}
    return {
        "process_health": "RUNNING",
        "last_poll": utc_now(),
        "last_result": last_result,
        "safe_upstream_tip": tip(ROOT / "data/cognition/candle_structure_memory.parquet"),
        "final_context_tip": tip(ROOT / "data/cognition/final_market_context_memory.parquet"),
        "lifecycle_tip": tip(ROOT / "data/cognition/market_context_lifecycle_memory.parquet"),
        "decision_tip": tip(ROOT / "data/live/context_decision_log.parquet"),
        "lag_seconds": None,
        "rows_added_last_cycle": None,
        "health": "HEALTHY" if healthy_noop and last_result != "REFRESH_FAILED" else "DEGRADED",
        "health_reason": (
            "NO_NEW_SAFE_UPSTREAM_is_normal_noop"
            if last_result == "NO_NEW_SAFE_UPSTREAM"
            else f"last_result={last_result}"
        ),
    }


def compute_overall_health(
    processes: list[dict[str, Any]],
    paper: dict[str, Any],
    *,
    decision_materially_stale: bool = False,
    critical_source_unknown: bool = False,
) -> tuple[str, str, list[dict[str, Any]]]:
    alerts: list[dict[str, Any]] = []
    by_id = {p["process_id"]: p for p in processes}

    def down(pid: str, alert_id: str, severity: str) -> None:
        proc = by_id.get(pid)
        if not proc or proc.get("health") != "RUNNING":
            alerts.append(
                {
                    "alert_id": alert_id,
                    "severity": severity,
                    "component": pid,
                    "message": f"{pid} not running",
                    "reason_code": alert_id,
                    "started_at": utc_now(),
                    "last_seen": utc_now(),
                    "active": True,
                }
            )

    down("live_feed", "FEED_DOWN", "CRITICAL")
    down("canonical_pipeline", "PIPELINE_DOWN", "CRITICAL")
    down("context_refresher", "CONTEXT_CHAIN_STALE", "ERROR")
    # A snapshot carries the S4.1 roles only once the cutover happened, so the
    # process list itself decides which controller contract applies.
    s4_roles_tracked = any(
        p["process_id"] == "timeframe_manager" or str(p["process_id"]).startswith("trader_")
        for p in processes
    )
    if s4_activated() and s4_roles_tracked:
        # After the S4.1 cutover the legacy global controller must stay stopped and
        # the manager plus four independent traders own paper execution.
        down("timeframe_manager", "TIMEFRAME_MANAGER_DOWN", "ERROR")
        for tf in S4_TIMEFRAMES:
            down(f"trader_{tf}", f"TIMEFRAME_TRADER_DOWN_{tf}", "ERROR")
        legacy = by_id.get("paper_controller")
        if legacy and legacy.get("health") == "RUNNING":
            alerts.append(
                {
                    "alert_id": "LEGACY_PAPER_CONTROLLER_RUNNING_AFTER_CUTOVER",
                    "severity": "CRITICAL",
                    "component": "paper_controller",
                    "message": "legacy global paper controller running alongside timeframe traders",
                    "reason_code": "LEGACY_AND_NEW_CONTROLLERS_CONCURRENT",
                    "started_at": utc_now(),
                    "last_seen": utc_now(),
                    "active": True,
                }
            )
    else:
        down("paper_controller", "PAPER_PROCESS_DOWN", "ERROR")

    if decision_materially_stale:
        alerts.append(
            {
                "alert_id": "DECISION_STALE",
                "severity": "ERROR",
                "component": "context_decision_log",
                "message": "decision tip materially stale",
                "reason_code": "DECISION_STALE",
                "started_at": utc_now(),
                "last_seen": utc_now(),
                "active": True,
            }
        )

    alerts.append(
        {
            "alert_id": "D1_NOT_LIVE",
            "severity": "INFO",
            "component": "multi_timeframe.D1",
            "message": "D1 NOT LIVE / EXPECTED — no live Stage-2 writer, no D1 timeframe trader",
            "reason_code": "D1_NOT_LIVE",
            "started_at": utc_now(),
            "last_seen": utc_now(),
            "active": True,
            "actionable": False,
            "known_limitation": True,
        }
    )
    alerts.append(
        {
            "alert_id": "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED",
            "severity": "INFO",
            "component": "auction_synthesis_memory",
            "message": "Auction Synthesis KNOWN LIMITATION / NON-REQUIRED — frozen output, not on context truth path",
            "reason_code": "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED",
            "started_at": utc_now(),
            "last_seen": utc_now(),
            "active": True,
            "actionable": False,
            "known_limitation": True,
        }
    )
    if paper.get("representation") == "RUNNING_NO_ELIGIBLE_TRADE":
        alerts.append(
            {
                "alert_id": "PAPER_NO_ELIGIBLE_TRADE",
                "severity": "INFO",
                "component": "paper_controller",
                "message": "paper running with no eligible trade — not a failure",
                "reason_code": "PAPER_NO_ELIGIBLE_TRADE",
                "started_at": utc_now(),
                "last_seen": utc_now(),
                "active": True,
            }
        )

    if critical_source_unknown:
        alerts.append(
            {
                "alert_id": "UNKNOWN_CRITICAL_SOURCE",
                "severity": "ERROR",
                "component": "runtime_truth",
                "message": "critical source unknown — fail closed",
                "reason_code": "UNKNOWN_CRITICAL_SOURCE",
                "started_at": utc_now(),
                "last_seen": utc_now(),
                "active": True,
            }
        )
        return "UNKNOWN", "critical source unknown", alerts

    if any(a["severity"] == "CRITICAL" for a in alerts):
        return "FAILED", "critical process down", alerts
    if any(a["reason_code"] == "DECISION_STALE" for a in alerts):
        return "DEGRADED", "decision materially stale", alerts
    if any(a["severity"] == "ERROR" for a in alerts):
        return "DEGRADED", "required support process down", alerts
    return (
        "OPERATIONAL_WITH_LIMITATIONS",
        "core processes running; D1 not live; auction_synthesis broken/non-required",
        alerts,
    )


def build_runtime_truth_snapshot() -> dict[str, Any]:
    """Deterministic read-only OPS truth snapshot with section failure isolation."""
    section_errors: dict[str, str] = {}

    # --- process truth (independent) ---
    try:
        processes = inspect_processes()
    except Exception as exc:  # noqa: BLE001
        processes = []
        section_errors["process_truth"] = f"{type(exc).__name__}: {exc}"

    # --- pipeline metadata (independent; must not erase other sections) ---
    metadata: dict[str, Any] | None = None
    engines: list[dict[str, Any]] = []
    try:
        metadata = resolve_active_canonical_pipeline()
        engines = build_pipeline_engines(metadata=metadata)
        ids = [e["engine_id"] for e in engines]
        if len(ids) != len(set(ids)):
            raise RuntimeError("duplicate engine ids in runtime inventory")
        if len(engines) != int(metadata["total_engine_count"]):
            raise RuntimeError(
                f"engine list length mismatch: {len(engines)} != {metadata['total_engine_count']}"
            )
        for required in (
            "auction_context_arbitration_engine_v1.py",
            "mtf_availability_runtime_engine_v1.py",
        ):
            if required not in ids:
                raise RuntimeError(f"runtime-only engine missing: {required}")
        active_phantoms = [
            e for e in LEGACY_PHANTOM_CANDIDATES if e not in ids and e in PHANTOM_ENGINES
        ]
        # Active pipeline engines are never phantoms.
        for eng in ids:
            if eng in LEGACY_PHANTOM_CANDIDATES and eng not in PHANTOM_ENGINES:
                continue
            if eng in PHANTOM_ENGINES:
                raise RuntimeError(f"phantom present in active runtime inventory: {eng}")
        _ = active_phantoms
    except Exception as exc:  # noqa: BLE001
        section_errors["pipeline_metadata"] = f"{type(exc).__name__}: {exc}"
        metadata = {
            "status": "UNKNOWN",
            "error": section_errors["pipeline_metadata"],
            "ordered_engine_names": [],
            "total_engine_count": 0,
            "required_engine_count": 0,
            "required_engine_names": [],
            "informational_engine_names": [],
            "active_builder": None,
            "active_flags": active_runtime_flags(),
        }
        engines = []

    # --- remaining independent sections ---
    try:
        datasets = build_datasets()
    except Exception as exc:  # noqa: BLE001
        datasets = []
        section_errors["datasets"] = f"{type(exc).__name__}: {exc}"

    try:
        multi_timeframe = build_multi_timeframe()
    except Exception as exc:  # noqa: BLE001
        multi_timeframe = []
        section_errors["multi_timeframe"] = f"{type(exc).__name__}: {exc}"

    try:
        paper = build_paper()
    except Exception as exc:  # noqa: BLE001
        paper = {}
        section_errors["paper"] = f"{type(exc).__name__}: {exc}"

    try:
        timeframe_traders = build_timeframe_traders()
    except Exception as exc:  # noqa: BLE001
        timeframe_traders = {
            "activated": s4_activated(),
            "traders": [],
            "status": "UNKNOWN",
            "error": f"{type(exc).__name__}: {exc}",
        }
        section_errors["trader_truth"] = f"{type(exc).__name__}: {exc}"

    paper_proc = next((p for p in processes if p["process_id"] == "paper_controller"), None)
    if paper_proc and isinstance(paper, dict):
        paper["process_health"] = paper_proc["health"]
        paper["pid"] = paper_proc["pid"]
        if paper_proc["health"] != "RUNNING":
            if timeframe_traders.get("activated"):
                paper["representation"] = "MIGRATED_TO_TIMEFRAME_TRADERS"
                paper["display_status"] = "MIGRATED"
                paper["requirement"] = "NOT_REQUIRED"
                paper["health"] = "HEALTHY"
                paper["is_controller_failure"] = False
                paper["health_reason"] = "legacy_global_controller_stopped_at_s4_1_cutover"
                paper["legacy_ledger_role"] = "READ_ONLY_HISTORICAL_BOOK"
                paper["detail"] = "Replaced by independent M15, M30, H1 and H4 traders"
            else:
                paper["representation"] = "STOPPED"
                paper["display_status"] = "FAILED"
                paper["requirement"] = "REQUIRED"
                paper["health"] = "BROKEN"
                paper["is_controller_failure"] = True

    try:
        context_chain = build_context_chain()
    except Exception as exc:  # noqa: BLE001
        context_chain = {
            "status": "UNKNOWN",
            "error": f"{type(exc).__name__}: {exc}",
            "health": "UNKNOWN",
        }
        section_errors["context_chain"] = f"{type(exc).__name__}: {exc}"

    ctx_proc = next((p for p in processes if p["process_id"] == "context_refresher"), None)
    if ctx_proc and isinstance(context_chain, dict):
        context_chain["process_health"] = ctx_proc["health"]
        if ctx_proc["health"] != "RUNNING":
            context_chain["health"] = "DEGRADED"

    overall, reason, alerts = compute_overall_health(processes, paper if isinstance(paper, dict) else {})
    if "pipeline_metadata" in section_errors and overall in {
        "OPERATIONAL_WITH_LIMITATIONS",
        "HEALTHY_WITH_KNOWN_LIMITATIONS",
        "HEALTHY",
        "OPERATIONAL",
    }:
        # Metadata gap is a limitation, not a process-down failure.
        reason = f"{reason}; pipeline_metadata={section_errors['pipeline_metadata']}"

    mtf_status = _read_json(ROOT / "data/runtime/multi_timeframe_availability_status.json") or {}
    mtf_latest = _read_json(ROOT / "data/runtime/multi_timeframe_availability_latest.json") or {}

    known_limitations = [
        {
            "id": "D1_NOT_LIVE",
            "entity_type": "UNSUPPORTED_CAPABILITY",
            "display_status": "NOT_LIVE",
            "requirement": "EXPECTED",
            "detail": "No live Stage-2 writer · No D1 timeframe trader",
        },
        {
            "id": "AUCTION_SYNTHESIS_ACTIVE_BROKEN",
            "entity_type": "DATASET",
            "classification": "KNOWN_LIMITATION",
            "display_status": "KNOWN_LIMITATION",
            "requirement": "NON_REQUIRED",
            "required_by_current_runtime": False,
            "reason": "WRITER_DISCONNECTED",
            "detail": "Frozen output · Not used by canonical context truth path",
        },
        {
            "id": "LEGACY_PAPER_CONTROLLER_MIGRATED",
            "entity_type": "PROCESS",
            "display_status": "MIGRATED",
            "requirement": "NOT_REQUIRED",
            "detail": "Replaced by independent M15, M30, H1 and H4 traders",
        },
        {
            "id": "RESEARCH_READINESS_INCOMPLETE",
            "entity_type": "RESEARCH",
            "display_status": "RESEARCH_INCOMPLETE",
            "requirement": "NON_BLOCKING",
            "detail": "Governance / economic / shadow research artifacts incomplete for promotion",
        },
        {
            "id": "TOXIC_BOX_HISTORICAL",
            "entity_type": "RESEARCH",
            "display_status": "HISTORICAL_ONLY",
            "requirement": "NON_BLOCKING",
            "detail": "Legacy toxic baseline retained; not connected to current S4 trades",
        },
    ]
    if "pipeline_metadata" in section_errors:
        known_limitations.append(
            {
                "id": "PIPELINE_METADATA_UNKNOWN",
                "entity_type": "PIPELINE_ENGINE",
                "display_status": "UNKNOWN",
                "requirement": "NON_BLOCKING_WHEN_PROCESSES_HEALTHY",
                "detail": section_errors["pipeline_metadata"],
            }
        )

    active_ids = {e["engine_id"] for e in engines}
    legacy_components = [
        {
            "component_id": eng,
            "entity_type": "LEGACY_COMPONENT",
            "classification": "PHANTOM",
            "display_status": "NOT_IN_CANONICAL_RUNTIME",
            "active": False,
            "reason": "NOT_PRESENT_IN_CANONICAL_RUNTIME",
            "process_badge": None,
        }
        for eng in PHANTOM_ENGINES
        if eng not in active_ids
    ]
    for name in ("htf_structure_memory", "htf_ltf_context_memory", "oi_history", "btc_oi"):
        legacy_components.append(
            {
                "component_id": name,
                "entity_type": "LEGACY_COMPONENT",
                "classification": "INACTIVE_DEPRECATED",
                "display_status": "DEPRECATED",
                "active": False,
                "required_by_current_runtime": False,
                "process_badge": None,
            }
        )

    runtime_uptime = pipeline_runtime_uptime(processes)

    return {
        "generated_at": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "trading_use_forbidden": True,
        "canonical_source_hierarchy": CANONICAL_SOURCE_HIERARCHY,
        "entity_taxonomy": ENTITY_TAXONOMY,
        "overall_health": overall,
        "overall_reason": reason,
        "section_errors": section_errors,
        "pipeline_metadata": metadata,
        "processes": processes,
        "pipeline_engines": engines,
        "datasets": datasets,
        "multi_timeframe": multi_timeframe,
        "context_chain": context_chain,
        "paper": paper,
        "timeframe_traders": timeframe_traders,
        "runtime_uptime": runtime_uptime,
        "known_limitations": known_limitations,
        "legacy_components": legacy_components,
        "alerts": alerts,
        "mtf_status_sidecar": {
            "latest_evaluation_timestamp": mtf_latest.get("latest_evaluation_timestamp"),
            "overall_health": mtf_latest.get("overall_health"),
            "status_event": mtf_status.get("event"),
            "supported_timeframes": mtf_status.get("supported_timeframes") or ["M15", "M30", "H1", "H4"],
            "unsupported_timeframes": mtf_status.get("unsupported_timeframes") or ["D1"],
        },
        "flags_frozen": {
            "BTC_ML_CONTINUATION_PROGRESSION": os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0"),
            "BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE": os.environ.get(
                STAGE2_SYNTHESIS_INPUTS_LIVE_ENV, "0"
            ),
            "BTC_ML_VOLUME_LOCALIZATION_LIVE": os.environ.get(VOLUME_LOCALIZATION_LIVE_ENV, "0"),
            "PRICE_GATE": os.environ.get("PRICE_GATE", "OFF"),
            "execution": "disabled",
        },
    }


def overall_health_to_ops_level(overall: str) -> str:
    if overall in {
        "HEALTHY",
        "OPERATIONAL",
        "HEALTHY_WITH_KNOWN_LIMITATIONS",
        "OPERATIONAL_WITH_LIMITATIONS",
    }:
        return "GREEN"
    if overall == "DEGRADED":
        return "YELLOW"
    if overall in {"BROKEN", "FAILED"}:
        return "RED"
    return "GREY"
