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

PHANTOM_ENGINES = (
    "volume_localization_engine_v1.py",
    "market_state_engine_v1.py",
    "trading_state_engine_v1.py",
    "shadow_inference_engine_v1.py",
    "trading_state_validation_engine_v1.py",
    "economic_validation_engine_v1.py",
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


def parse_canonical_pipeline(path: Path | None = None) -> list[str]:
    path = path or (ROOT / "src/btc_ml/runtime/pipeline.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CANONICAL_PIPELINE":
                    return list(ast.literal_eval(node.value))
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "CANONICAL_PIPELINE":
                return list(ast.literal_eval(node.value))
    raise RuntimeError(f"CANONICAL_PIPELINE not found in {path}")


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
                    "pid": None,
                    "ppid": None,
                    "process_state": "STOPPED",
                    "interpreter": None,
                    "cwd": None,
                    "command": None,
                    "started_at": None,
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
        out.append(
            {
                "process_id": process_id,
                "display_name": process_id,
                "pid": pid,
                "ppid": ppid,
                "process_state": proc_state,
                "interpreter": interpreter,
                "cwd": str(ROOT),
                "command": command[:300],
                "started_at": None,
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


def build_pipeline_engines() -> list[dict[str, Any]]:
    engines = parse_canonical_pipeline()
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

    rows = []
    for idx, eng in enumerate(engines, start=1):
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
        required = eng != "auction_synthesis_engine_v1.py"
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
                "display_name": eng.replace("_engine_v1.py", "").replace("_v1.py", ""),
                "module": eng.replace(".py", ""),
                "file": eng,
                "pipeline_order": idx,
                "enabled": True,
                "required": required,
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


def build_timeframe_traders() -> dict[str, Any]:
    """S4.1 read-only view: manager, command bus, four independent trader books.

    Data binding only — no new visual language, no writes.
    """
    activation = _read_json(S4_ACTIVATION_PATH)
    manager_latest = _read_json(ROOT / "data/runtime/timeframe_manager_latest.json") or {}
    portfolio = _read_json(ROOT / "data/trading/manager/portfolio_summary.json") or {}
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
    gross_risk = 0.0
    realized_total = 0.0
    unrealized_total = 0.0
    open_positions = 0
    for tf in S4_TIMEFRAMES:
        book = ROOT / "data/trading/timeframe_traders" / tf
        entry: dict[str, Any] = {
            "timeframe": tf,
            "entity_type": "TIMEFRAME_TRADER",
            "book_path": f"data/trading/timeframe_traders/{tf}",
            "book_exists": book.exists(),
            "open_position_id": None,
            "direction": "FLAT",
            "entry_price": None,
            "quantity": None,
            "open_risk_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "closed_trades": 0,
            "last_command_id": None,
            "last_command_intent": None,
            "command_cursor": None,
            "paper_only": True,
            "execution_enabled": False,
        }
        state = _read_json(book / "controller_state.json") or {}
        entry["last_command_id"] = state.get("last_command_id")
        entry["last_command_intent"] = state.get("last_command_intent") or state.get("last_intent")
        entry["command_cursor"] = state.get("cursor_evaluation_timestamp") or state.get("command_cursor")
        try:
            import pandas as pd

            positions_path = book / "positions.parquet"
            if positions_path.exists():
                frame = pd.read_parquet(positions_path)
                if len(frame) and "status" in frame.columns:
                    open_rows = frame[frame["status"].astype(str).str.upper() == "OPEN"]
                    if len(open_rows):
                        row = open_rows.iloc[-1].to_dict()
                        entry["open_position_id"] = row.get("position_id")
                        entry["direction"] = str(row.get("direction") or "FLAT").upper()
                        entry["entry_price"] = _sf(row.get("entry_price"))
                        entry["quantity"] = _sf(row.get("quantity"))
                        entry["open_risk_usd"] = _sf(row.get("risk_amount_usd")) or 0.0
                        open_positions += 1
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
        entry["last_command"] = commands_by_tf.get(tf)
        gross_risk += float(entry["open_risk_usd"] or 0.0)
        realized_total += float(entry["realized_pnl_usd"] or 0.0)
        unrealized_total += float(entry["unrealized_pnl_usd"] or 0.0)
        traders.append(entry)

    portfolio_max_risk = _sf(portfolio.get("portfolio_max_risk_usd")) or 1000.0
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
            "open_positions": open_positions,
            "gross_long_notional": _sf(portfolio.get("gross_long_notional")),
            "gross_short_notional": _sf(portfolio.get("gross_short_notional")),
            "net_notional": _sf(portfolio.get("net_notional")),
            "net_notional_semantics": "REPORTING_ONLY_NEVER_NETTED",
            "gross_open_risk_usd": gross_risk,
            "portfolio_max_risk_usd": portfolio_max_risk,
            "available_risk_usd": max(0.0, portfolio_max_risk - gross_risk),
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
    """Deterministic read-only OPS truth snapshot."""
    processes = inspect_processes()
    engines = build_pipeline_engines()
    ids = [e["engine_id"] for e in engines]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate engine ids in runtime inventory")
    if len(engines) != 20:
        raise RuntimeError(f"expected 20 runtime engines, got {len(engines)}")
    for required in (
        "auction_context_arbitration_engine_v1.py",
        "mtf_availability_runtime_engine_v1.py",
    ):
        if required not in ids:
            raise RuntimeError(f"runtime-only engine missing: {required}")
    for phantom in PHANTOM_ENGINES:
        if phantom in ids:
            raise RuntimeError(f"phantom present in active runtime inventory: {phantom}")

    datasets = build_datasets()
    multi_timeframe = build_multi_timeframe()
    paper = build_paper()
    # sync paper process health from inspection
    timeframe_traders = build_timeframe_traders()
    paper_proc = next((p for p in processes if p["process_id"] == "paper_controller"), None)
    if paper_proc:
        paper["process_health"] = paper_proc["health"]
        paper["pid"] = paper_proc["pid"]
        if paper_proc["health"] != "RUNNING":
            if timeframe_traders["activated"]:
                # Expected after the S4.1 cutover: execution moved to timeframe traders.
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
    context_chain = build_context_chain()
    ctx_proc = next((p for p in processes if p["process_id"] == "context_refresher"), None)
    if ctx_proc:
        context_chain["process_health"] = ctx_proc["health"]
        if ctx_proc["health"] != "RUNNING":
            context_chain["health"] = "DEGRADED"

    overall, reason, alerts = compute_overall_health(processes, paper)
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

    return {
        "generated_at": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "trading_use_forbidden": True,
        "canonical_source_hierarchy": CANONICAL_SOURCE_HIERARCHY,
        "entity_taxonomy": ENTITY_TAXONOMY,
        "overall_health": overall,
        "overall_reason": reason,
        "processes": processes,
        "pipeline_engines": engines,
        "datasets": datasets,
        "multi_timeframe": multi_timeframe,
        "context_chain": context_chain,
        "paper": paper,
        "timeframe_traders": timeframe_traders,
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
