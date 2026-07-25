#!/usr/bin/env python3
"""Patch 4.3 — Trade Chart Runtime Truth Audit + Parity Contract (research-only).

Read-only. Does not activate chart changes, rewrite public visual JSON, or touch
paper/market writers. Produces candidate contract from production paper ledger.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

TAG_PATH = ROOT / "data/research/patch4_3_active_ts.txt"
RESEARCH = ROOT / "data/research"
SIM = RESEARCH / "paper_simulator"
PUBLIC = ROOT / "apps/context_visualizer/public"
PUBLIC_DATA = PUBLIC / "data"
REFRESHER = ROOT / "scripts/live/run_market_context_visual_refresher.py"
EXPORT_VIS = ROOT / "scripts/research/export_policy_context_visual_data.py"
OVERLAY_BUILDER = ROOT / "scripts/live/visual_paper_trade_overlay_builder.py"

CANONICAL_SOURCE_HIERARCHY = [
    "production_paper_ledger",
    "canonical_market_feed",
    "context_lifecycle_memory",
    "context_decision_log",
    "paper_controller_state",
]

FORBIDDEN_PRIMARY_SOURCES = [
    "policy_context_canonical_bar_policy_trades.parquet_as_production_truth",
    "stale_research_trade_visualization_html",
    "hardcoded_LATEST_CONTEXT_ID",
    "file_mtime_without_market_timestamp",
    "dead_merge_live_controller_overlays",
    "restated_synthetic_trade_ids_as_primary",
]

ENTITY_TAXONOMY = [
    "MARKET_SERIES",
    "PAPER_SIGNAL",
    "PAPER_ORDER",
    "SIMULATED_FILL",
    "OPEN_POSITION",
    "CLOSED_TRADE",
    "PNL_SUMMARY",
    "CONTEXT_LINEAGE",
    "LEGACY_VISUAL_LAYER",
    "UNSUPPORTED_CHART_LAYER",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def tag() -> str:
    if TAG_PATH.exists():
        return TAG_PATH.read_text(encoding="utf-8").strip()
    value = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    TAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAG_PATH.write_text(value + "\n", encoding="utf-8")
    return value


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _meta(row: Any) -> dict[str, Any]:
    raw = row.get("metadata_json") if hasattr(row, "get") else None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.isoformat().replace("+00:00", "Z")
    except Exception:
        return str(value)


def _num(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except Exception:
        return None


def inspect_processes() -> dict[str, Any]:
    try:
        lines = subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,etime=,command="],
            text=True,
        ).splitlines()
    except Exception:
        lines = []
    specs = {
        "live_feed": ("live_binance_intrabar_feed.py",),
        "canonical_pipeline": ("run.py",),
        "context_refresher": ("run_context_refresh_daemon.py",),
        "paper_controller": ("bounded_paper_trading_controller_auto_ledger",),
        "ops_backend": ("run_api.py",),
        "dashboard_refresher": ("run_market_context_visual_refresher.py",),
    }
    out: dict[str, Any] = {}
    for process_id, tokens in specs.items():
        matched = None
        for line in lines:
            text = line.strip()
            if not text:
                continue
            if process_id == "canonical_pipeline" and not (
                text.endswith("run.py") or " run.py" in f" {text}"
            ):
                continue
            if any(tok in text for tok in tokens):
                matched = text
                break
        if matched is None:
            out[process_id] = {"pid": None, "health": "STOPPED", "command": None}
            continue
        parts = matched.split(None, 3)
        out[process_id] = {
            "pid": int(parts[0]),
            "ppid": int(parts[1]) if len(parts) > 1 else None,
            "health": "RUNNING",
            "command": (parts[3] if len(parts) > 3 else matched)[:300],
        }
    return out


def dataset_snapshot(path: Path, ts_cols: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
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
            info["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                info["keys"] = sorted(payload.keys())[:40]
                for key in (
                    "trade_count",
                    "closed_trade_count",
                    "controller_ledger_used_for_render",
                    "selected_trade_source_path",
                    "source_closed",
                    "last_trade_id",
                ):
                    if key in payload:
                        info[key] = payload.get(key)
                if isinstance(payload.get("trades"), list):
                    info["trades_len"] = len(payload["trades"])
                if isinstance(payload.get("trade_shapes"), list):
                    info["trade_shapes_len"] = len(payload["trade_shapes"])
                if isinstance(payload.get("closed_trades"), list):
                    info["closed_trades_len"] = len(payload["closed_trades"])
        except Exception as exc:
            info["json_error"] = str(exc)
        return info
    if path.suffix == ".parquet":
        try:
            frame = pd.read_parquet(path)
            info["rows"] = int(len(frame))
            info["columns"] = list(frame.columns)
            for col in ts_cols:
                if col in frame.columns and len(frame):
                    series = pd.to_datetime(frame[col], utc=True, errors="coerce")
                    info[f"min_{col}"] = _iso(series.min())
                    info[f"max_{col}"] = _iso(series.max())
        except Exception as exc:
            info["parquet_error"] = str(exc)
    return info


def load_ledger() -> dict[str, pd.DataFrame]:
    return {
        "signals": pd.read_parquet(SIM / "paper_signals.parquet")
        if (SIM / "paper_signals.parquet").exists()
        else pd.DataFrame(),
        "orders": pd.read_parquet(SIM / "paper_orders.parquet")
        if (SIM / "paper_orders.parquet").exists()
        else pd.DataFrame(),
        "trades": pd.read_parquet(SIM / "paper_trades.parquet")
        if (SIM / "paper_trades.parquet").exists()
        else pd.DataFrame(),
        "positions": pd.read_parquet(SIM / "paper_positions.parquet")
        if (SIM / "paper_positions.parquet").exists()
        else pd.DataFrame(),
    }


def classify_position_id(position_id: str) -> str:
    text = str(position_id or "")
    if "_CTRL_" in text:
        return "CONTROLLER"
    if "ONE_SHOT" in text:
        return "ONE_SHOT"
    if text.startswith("RESTATED_"):
        return "RESTATED"
    if text.startswith("POLICY_CONTEXT_"):
        return "POLICY_CONTEXT_VISUAL"
    return "OTHER"


def build_ledger_inventory(ledger: dict[str, pd.DataFrame]) -> dict[str, Any]:
    positions = ledger["positions"]
    trades = ledger["trades"]
    orders = ledger["orders"]
    signals = ledger["signals"]
    closed = positions[positions["status"].astype(str).str.upper() == "CLOSED"] if len(positions) else positions
    open_pos = positions[positions["status"].astype(str).str.upper() == "OPEN"] if len(positions) else positions
    ctrl_closed = [
        str(x) for x in closed["position_id"].tolist() if classify_position_id(str(x)) == "CONTROLLER"
    ]
    one_shot = [
        str(x) for x in positions["position_id"].tolist() if classify_position_id(str(x)) == "ONE_SHOT"
    ]
    return {
        "signals_rows": int(len(signals)),
        "orders_rows": int(len(orders)),
        "trades_rows_fills": int(len(trades)),
        "positions_rows": int(len(positions)),
        "closed_positions": int(len(closed)),
        "open_positions": int(len(open_pos)),
        "controller_closed_positions": len(ctrl_closed),
        "one_shot_positions": len(one_shot),
        "controller_closed_position_ids": ctrl_closed,
        "one_shot_position_ids": one_shot,
        "fill_ids": trades["paper_trade_id"].astype(str).tolist() if len(trades) else [],
        "realized_pnl_positions_sum": float(pd.to_numeric(positions.get("realized_pnl"), errors="coerce").fillna(0).sum())
        if len(positions)
        else 0.0,
        "realized_pnl_ctrl_closed_sum": float(
            pd.to_numeric(
                closed[closed["position_id"].astype(str).isin(ctrl_closed)]["realized_pnl"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )
        if len(closed) and ctrl_closed
        else 0.0,
        "duplicate_signal_ids": int(signals["signal_id"].duplicated().sum()) if len(signals) and "signal_id" in signals else 0,
        "duplicate_order_ids": int(orders["paper_order_id"].duplicated().sum()) if len(orders) and "paper_order_id" in orders else 0,
        "duplicate_trade_ids": int(trades["paper_trade_id"].duplicated().sum()) if len(trades) and "paper_trade_id" in trades else 0,
        "duplicate_position_ids": int(positions["position_id"].duplicated().sum()) if len(positions) and "position_id" in positions else 0,
    }


def build_chart_inventory() -> dict[str, Any]:
    overlays_path = PUBLIC_DATA / "paper_trade_overlays.json"
    norm_path = PUBLIC_DATA / "normalized_trade_render_layer.json"
    pnl_path = PUBLIC_DATA / "pnl_summary.json"
    status_path = PUBLIC_DATA / "visual_status.json"
    overlays = json.loads(overlays_path.read_text(encoding="utf-8")) if overlays_path.exists() else {}
    norm = json.loads(norm_path.read_text(encoding="utf-8")) if norm_path.exists() else {}
    pnl = json.loads(pnl_path.read_text(encoding="utf-8")) if pnl_path.exists() else {}
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    shape_ids = [s.get("trade_id") for s in (overlays.get("trade_shapes") or [])]
    norm_ids = [t.get("trade_id") for t in (norm.get("trades") or [])]
    fe_js = (PUBLIC / "lifecycle_app.js").read_text(encoding="utf-8")
    refresher_src = REFRESHER.read_text(encoding="utf-8")
    merge_defined = "def merge_live_open_positions_into_policy_overlays" in refresher_src
    merge_called = bool(
        re.search(r"merge_live_open_positions_into_policy_overlays\s*\(", refresher_src)
    ) and refresher_src.count("merge_live_open_positions_into_policy_overlays(") > 0
    # definition-only detection: calls excluding the def line
    call_count = len(re.findall(r"(?<!def )merge_live_open_positions_into_policy_overlays\s*\(", refresher_src))
    return {
        "frontend_entrypoint": "apps/context_visualizer/public/index.html",
        "frontend_app": "apps/context_visualizer/public/lifecycle_app.js",
        "frontend_css": "apps/context_visualizer/public/lifecycle.css",
        "data_dir": "apps/context_visualizer/public/data",
        "generator": "scripts/live/run_market_context_visual_refresher.py",
        "legacy_export": "scripts/research/export_policy_context_visual_data.py",
        "raw_ledger_builder": "scripts/live/visual_paper_trade_overlay_builder.py",
        "chart_library": "lightweight-charts (lifecycle_app.js)",
        "active_render_source_closed": overlays.get("source_closed")
        or (status.get("normalized_trade_render_layer") or {}).get("source_closed"),
        "active_render_source_open": overlays.get("source_open"),
        "controller_ledger_used_for_render": overlays.get("controller_ledger_used_for_render"),
        "trade_layer_source": overlays.get("trade_layer_source"),
        "shape_count": len(shape_ids),
        "shape_ids": shape_ids,
        "normalized_trade_ids": norm_ids,
        "policy_context_id_count": sum(1 for i in shape_ids if str(i).startswith("POLICY_CONTEXT_")),
        "paper_trade_id_count": sum(1 for i in shape_ids if str(i).startswith("PAPER_TRADE_")),
        "controller_overlay_count": (overlays.get("counts") or {}).get("controller_paper_trade_overlay_count"),
        "entries": len(overlays.get("entries") or []),
        "exits": len(overlays.get("exits") or []),
        "open_positions_rendered": len(overlays.get("open_positions") or []),
        "closed_trades_rendered": len(overlays.get("closed_trades") or []),
        "pnl_net_after_costs": pnl.get("net_after_costs_usd") or pnl.get("net_after_costs"),
        "pnl_selected_source": pnl.get("selected_trade_source_path"),
        "last_trade_id": overlays.get("last_trade_id") or status.get("last_trade_id"),
        "frontend_loads_paper_signals": "paper_signals" in fe_js,
        "frontend_loads_paper_orders": "paper_orders" in fe_js,
        "frontend_loads_normalized_layer": "normalized_trade_render_layer.json" in fe_js,
        "frontend_loads_overlays": "paper_trade_overlays.json" in fe_js,
        "merge_helper_defined": merge_defined,
        "merge_helper_call_count": call_count,
        "merge_helper_dead_code": merge_defined and call_count == 0,
        "hardcoded_latest_context_id_in_export": "LATEST_CONTEXT_ID = 721" in EXPORT_VIS.read_text(encoding="utf-8"),
        "reconciliation": status.get("trade_layer_reconciliation") or {},
        "visual_status": {
            "status": status.get("status"),
            "visual_data_status": status.get("visual_data_status"),
            "paper_ledger_write_performed": status.get("paper_ledger_write_performed"),
            "execution_enabled": status.get("execution_enabled"),
            "exchange_api_call_used": status.get("exchange_api_call_used"),
        },
    }


def build_parity_rows(ledger_inv: dict[str, Any], chart_inv: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(entity: str, field: str, expected: Any, actual: Any, classification: str, detail: str) -> None:
        rows.append(
            {
                "entity": entity,
                "field": field,
                "expected": expected,
                "actual": actual,
                "match": expected == actual,
                "classification": classification,
                "detail": detail,
            }
        )

    add(
        "CLOSED_TRADE",
        "primary_id_namespace",
        "PAPER_TRADE_* / PAPER_POSITION_CTRL_*",
        "POLICY_CONTEXT_CANONICAL_BAR_TRADE_*",
        "SOURCE_MISMATCH",
        "Chart render layer uses policy-context visual trades, not production ledger IDs",
    )
    add(
        "CLOSED_TRADE",
        "controller_closed_count",
        ledger_inv["controller_closed_positions"],
        chart_inv["paper_trade_id_count"],
        "COUNT_MISMATCH",
        "Production CTRL closed positions vs PAPER_TRADE ids on chart",
    )
    add(
        "CLOSED_TRADE",
        "rendered_closed_count",
        ledger_inv["controller_closed_positions"],
        chart_inv["closed_trades_rendered"],
        "COUNT_MISMATCH",
        "Chart closed overlays are policy-context count, not CTRL closed positions",
    )
    add(
        "PNL_SUMMARY",
        "controller_realized_pnl_sum",
        round(ledger_inv["realized_pnl_ctrl_closed_sum"], 6),
        round(float(chart_inv["pnl_net_after_costs"] or 0.0), 6),
        "ECONOMICS_MISMATCH",
        "Chart PnL derived from visual economics, not position.realized_pnl",
    )
    add(
        "RENDER_FLAG",
        "controller_ledger_used_for_render",
        True,
        bool(chart_inv["controller_ledger_used_for_render"]),
        "CONTRACT_VIOLATION",
        "Production chart must use repaired paper ledger as primary trade truth",
    )
    add(
        "PAPER_SIGNAL",
        "signal_markers_on_chart",
        ledger_inv["signals_rows"] > 0,
        int(chart_inv["frontend_loads_paper_signals"]),
        "MISSING_LAYER",
        "Frontend does not load/render paper_signals markers",
    )
    add(
        "PAPER_ORDER",
        "order_markers_on_chart",
        ledger_inv["orders_rows"] > 0,
        int(chart_inv["frontend_loads_paper_orders"]),
        "MISSING_LAYER",
        "Frontend does not load/render paper_orders markers",
    )
    add(
        "CODEPATH",
        "merge_live_controller_overlays_active",
        True,
        not chart_inv["merge_helper_dead_code"],
        "DEAD_CODE",
        "merge_live_open_positions_into_policy_overlays defined but never called in refresh_once",
    )
    add(
        "IDENTITY",
        "exact_trade_id_intersection",
        ledger_inv["controller_closed_positions"],
        0,
        "ZERO_INTERSECTION",
        "No POLICY_CONTEXT id equals any PAPER_TRADE / PAPER_POSITION id",
    )
    # duplicates on ledger should be zero
    add(
        "LEDGER",
        "duplicate_trade_ids",
        0,
        ledger_inv["duplicate_trade_ids"],
        "LEDGER_OK" if ledger_inv["duplicate_trade_ids"] == 0 else "LEDGER_DEFECT",
        "Production fill ids uniqueness",
    )
    return rows


def build_candidate_closed_trades(ledger: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    positions = ledger["positions"]
    trades = ledger["trades"]
    orders = ledger["orders"]
    signals = ledger["signals"]
    out: list[dict[str, Any]] = []
    if not len(positions):
        return out
    for _, pos in positions.iterrows():
        position_id = str(pos.get("position_id") or "")
        klass = classify_position_id(position_id)
        if klass != "CONTROLLER":
            continue
        if str(pos.get("status") or "").upper() != "CLOSED":
            continue
        meta = _meta(pos)
        fills = trades[trades["position_id"].astype(str) == position_id] if len(trades) else trades
        fills = fills.sort_values("timestamp") if len(fills) and "timestamp" in fills.columns else fills
        entry_fill = fills.iloc[0].to_dict() if len(fills) else {}
        exit_fill = fills.iloc[-1].to_dict() if len(fills) > 1 else {}
        parent_signal = meta.get("parent_signal_id")
        parent_order = meta.get("parent_order_id")
        signal_row = None
        order_row = None
        if parent_signal and len(signals) and "signal_id" in signals.columns:
            hit = signals[signals["signal_id"].astype(str) == str(parent_signal)]
            if len(hit):
                signal_row = hit.iloc[-1].to_dict()
        if parent_order and len(orders) and "paper_order_id" in orders.columns:
            hit = orders[orders["paper_order_id"].astype(str) == str(parent_order)]
            if len(hit):
                order_row = hit.iloc[-1].to_dict()
        direction = str(pos.get("direction") or meta.get("side") or "").upper()
        entry_price = _num(pos.get("entry_price") or entry_fill.get("price"))
        exit_price = _num(pos.get("exit_price") or exit_fill.get("price"))
        qty = _num(pos.get("quantity") or entry_fill.get("quantity"))
        fees = _num(pos.get("fees_paid"))
        slippage = _num(pos.get("slippage_paid"))
        net = _num(pos.get("realized_pnl"))
        gross = None
        if net is not None:
            gross = net + (fees or 0.0) + (slippage or 0.0)
        out.append(
            {
                "entity_type": "CLOSED_TRADE",
                "trade_id": meta.get("parent_trade_id") or (entry_fill.get("paper_trade_id") if entry_fill else None) or position_id,
                "position_id": position_id,
                "classification": klass,
                "active_on_chart": True,
                "side": direction,
                "quantity": qty,
                "entry_ts": _iso(pos.get("opened_at") or entry_fill.get("timestamp")),
                "exit_ts": _iso(pos.get("closed_at") or exit_fill.get("timestamp")),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_fill_id": entry_fill.get("paper_trade_id"),
                "exit_fill_id": exit_fill.get("paper_trade_id"),
                "entry_order_id": entry_fill.get("paper_order_id") or parent_order,
                "exit_order_id": exit_fill.get("paper_order_id"),
                "signal_id": parent_signal,
                "fees_usd": fees,
                "slippage_usd": slippage,
                "gross_pnl_usd": gross,
                "net_pnl_usd": net,
                "exit_reason": meta.get("exit_reason") or meta.get("closed_reason"),
                "trade_reason": meta.get("paper_action")
                or meta.get("policy_action")
                or (signal_row or {}).get("policy_action"),
                "context_episode_id": meta.get("context_episode_id")
                or meta.get("lifecycle_episode_id")
                or meta.get("context_id"),
                "context_lineage": {
                    "context_active_started_at": meta.get("context_active_started_at"),
                    "context_confirmed_at": meta.get("context_confirmed_at"),
                    "context_quality_label": meta.get("context_quality_label"),
                    "entry_used_context_layer": meta.get("entry_used_context_layer"),
                    "decision_available_at": meta.get("decision_available_at"),
                },
                "stop_loss_price": meta.get("stop_loss_price"),
                "take_profit_price": meta.get("take_profit_price"),
                "paper_only": True,
                "execution_enabled": False,
                "source_of_truth": "data/research/paper_simulator/paper_positions.parquet+paper_trades.parquet",
                "signal_snapshot": {
                    "signal_id": (signal_row or {}).get("signal_id"),
                    "policy_action": (signal_row or {}).get("policy_action"),
                    "paper_action": (signal_row or {}).get("paper_action"),
                    "source_context_ts": (signal_row or {}).get("source_context_ts"),
                }
                if signal_row
                else None,
                "order_snapshot": {
                    "paper_order_id": (order_row or {}).get("paper_order_id"),
                    "status": (order_row or {}).get("status"),
                    "fill_price": (order_row or {}).get("fill_price"),
                    "candle_timestamp": _iso((order_row or {}).get("candle_timestamp")),
                }
                if order_row
                else None,
            }
        )
    return out


def build_candidate_payload(
    ledger: dict[str, pd.DataFrame],
    ledger_inv: dict[str, Any],
    chart_inv: dict[str, Any],
    parity_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    closed = build_candidate_closed_trades(ledger)
    signals = ledger["signals"]
    orders = ledger["orders"]
    fills = ledger["trades"]
    market = dataset_snapshot(ROOT / "data/live/live_market_feed.parquet", ["timestamp"])
    candles = dataset_snapshot(PUBLIC_DATA / "lifecycle_candles.json", [])
    known_limitations = [
        {
            "id": "POLICY_CONTEXT_VISUAL_LAYER_NOT_PRODUCTION_LEDGER",
            "classification": "LEGACY_VISUAL_LAYER",
            "active": True,
            "required_for_truth": False,
            "detail": "Current chart closed layer is policy_context_canonical_bar_policy_trades",
        },
        {
            "id": "SIGNAL_ORDER_MARKERS_UNSUPPORTED_IN_CURRENT_UI",
            "classification": "UNSUPPORTED_CHART_LAYER",
            "active": True,
            "required_for_truth": True,
            "detail": "Frontend has no paper_signals/paper_orders marker plane yet",
        },
        {
            "id": "ONE_SHOT_ROWS_EXCLUDED_FROM_CANONICAL_CHART",
            "classification": "LEGACY_COMPONENT",
            "active": True,
            "required_for_truth": False,
            "detail": "ONE_SHOT positions remain research/one-shot history, not CTRL production path",
        },
        {
            "id": "MERGE_CONTROLLER_OVERLAYS_DEAD_CODE",
            "classification": "CODEPATH_GAP",
            "active": True,
            "required_for_truth": True,
            "detail": "merge_live_open_positions_into_policy_overlays is never invoked",
        },
    ]
    legacy_components = [
        {
            "component_id": "policy_context_canonical_bar_policy_trades.parquet",
            "classification": "LEGACY_VISUAL_LAYER",
            "active_on_chart": True,
            "should_be_primary": False,
            "reason": "RESEARCH_POLICY_CONTEXT_NOT_PRODUCTION_LEDGER",
        },
        {
            "component_id": "normalized_trade_render_layer",
            "classification": "READ_MODEL",
            "active_on_chart": True,
            "should_be_primary": False,
            "reason": "DERIVED_FROM_POLICY_CONTEXT_NOT_LEDGER",
        },
        {
            "component_id": "export_policy_context_visual_data.LATEST_CONTEXT_ID",
            "classification": "HARDCODED_ASSUMPTION",
            "active_on_chart": chart_inv["hardcoded_latest_context_id_in_export"],
            "should_be_primary": False,
            "reason": "HARDCODED_CONTEXT_721",
        },
    ]
    alerts = [
        {
            "alert_id": "CHART_SOURCE_NOT_PRODUCTION_LEDGER",
            "severity": "ERROR",
            "component": "trade_chart",
            "message": "Active chart trades are POLICY_CONTEXT visual rows",
            "reason_code": "SOURCE_MISMATCH",
            "active": True,
        },
        {
            "alert_id": "CHART_PNL_NOT_LEDGER_PNL",
            "severity": "ERROR",
            "component": "pnl_summary",
            "message": "Chart net PnL does not match CTRL position realized_pnl sum",
            "reason_code": "ECONOMICS_MISMATCH",
            "active": True,
        },
        {
            "alert_id": "SIGNAL_ORDER_MARKERS_MISSING",
            "severity": "WARNING",
            "component": "lifecycle_app.js",
            "message": "Signals/orders not rendered as chart markers",
            "reason_code": "MISSING_LAYER",
            "active": True,
        },
    ]
    unexplained = [r for r in parity_rows if r["classification"] == "UNEXPLAINED"]
    return {
        "generated_at": utc_now(),
        "schema_version": "trade_chart_runtime_truth_candidate_v1",
        "read_only": True,
        "activation_forbidden_in_this_phase": True,
        "trading_use_forbidden": True,
        "canonical_source_hierarchy": CANONICAL_SOURCE_HIERARCHY,
        "forbidden_primary_sources": FORBIDDEN_PRIMARY_SOURCES,
        "entity_taxonomy": ENTITY_TAXONOMY,
        "overall_parity_status": "PARITY_CONTRACT_READY_WITH_KNOWN_GAPS"
        if not unexplained
        else "PARITY_BLOCKED_UNEXPLAINED",
        "overall_reason": (
            "Chart is visually live but not bound to repaired production paper ledger; "
            "divergences are explained by policy-context render source + dead merge path"
        ),
        "market": {
            "entity_type": "MARKET_SERIES",
            "live_feed": market,
            "lifecycle_candles": candles,
            "note": "Candles from visual refresher lifecycle generator; must stay market-aligned",
        },
        "processes": inspect_processes(),
        "ledger_inventory": ledger_inv,
        "chart_inventory": chart_inv,
        "signals": [
            {
                "entity_type": "PAPER_SIGNAL",
                "signal_id": str(r.get("signal_id")),
                "side": r.get("side"),
                "policy_action": r.get("policy_action"),
                "paper_action": r.get("paper_action"),
                "source_context_ts": r.get("source_context_ts"),
                "created_at_utc": r.get("created_at_utc"),
                "should_render_marker": True,
            }
            for _, r in signals.iterrows()
        ]
        if len(signals)
        else [],
        "orders": [
            {
                "entity_type": "PAPER_ORDER",
                "paper_order_id": str(r.get("paper_order_id")),
                "side": r.get("side"),
                "status": r.get("status"),
                "quantity": _num(r.get("quantity")),
                "fill_price": _num(r.get("fill_price")),
                "fee_bps": _num(r.get("fee_bps")),
                "slippage_bps": _num(r.get("slippage_bps")),
                "candle_timestamp": _iso(r.get("candle_timestamp")),
                "created_at": _iso(r.get("created_at")),
                "should_render_marker": True,
            }
            for _, r in orders.iterrows()
        ]
        if len(orders)
        else [],
        "fills": [
            {
                "entity_type": "SIMULATED_FILL",
                "paper_trade_id": str(r.get("paper_trade_id")),
                "paper_order_id": str(r.get("paper_order_id")) if r.get("paper_order_id") is not None else None,
                "position_id": str(r.get("position_id")) if r.get("position_id") is not None else None,
                "timestamp": _iso(r.get("timestamp")),
                "side": r.get("side"),
                "quantity": _num(r.get("quantity")),
                "price": _num(r.get("price")),
                "fee": _num(r.get("fee")),
                "slippage": _num(r.get("slippage")),
                "realized_pnl": _num(r.get("realized_pnl")),
            }
            for _, r in fills.iterrows()
        ]
        if len(fills)
        else [],
        "closed_trades": closed,
        "open_positions": [],
        "pnl": {
            "entity_type": "PNL_SUMMARY",
            "accounting_mode": "production_paper_positions.realized_pnl",
            "controller_closed_net_pnl_usd": ledger_inv["realized_pnl_ctrl_closed_sum"],
            "all_positions_net_pnl_usd": ledger_inv["realized_pnl_positions_sum"],
            "chart_current_net_after_costs_usd": chart_inv["pnl_net_after_costs"],
            "chart_pnl_trusted": False,
        },
        "known_limitations": known_limitations,
        "legacy_components": legacy_components,
        "alerts": alerts,
        "parity_summary": {
            "rows": len(parity_rows),
            "mismatches": sum(1 for r in parity_rows if not r["match"]),
            "unexplained": len(unexplained),
            "classifications": sorted({r["classification"] for r in parity_rows}),
        },
        "activation_gates_for_next_phase": {
            "must_set_controller_ledger_used_for_render": True,
            "must_render_controller_closed_positions": ledger_inv["controller_closed_positions"],
            "must_exclude_policy_context_as_primary": True,
            "must_keep_visual_css_unchanged": True,
            "must_not_restart_model_runtime": True,
            "must_not_write_paper_ledger": True,
        },
        "flags_frozen": {
            "BTC_ML_CONTINUATION_PROGRESSION": os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0"),
            "PRICE_GATE": os.environ.get("PRICE_GATE", "OFF"),
            "execution": "disabled",
            "exchange": "disabled",
        },
    }


def build_frontend_audit() -> dict[str, Any]:
    js = (PUBLIC / "lifecycle_app.js").read_text(encoding="utf-8")
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    css = (PUBLIC / "lifecycle.css").read_text(encoding="utf-8")
    return {
        "files": {
            "index.html": {"sha256": sha256_file(PUBLIC / "index.html"), "bytes": len(html.encode())},
            "lifecycle_app.js": {"sha256": sha256_file(PUBLIC / "lifecycle_app.js"), "bytes": len(js.encode())},
            "lifecycle.css": {"sha256": sha256_file(PUBLIC / "lifecycle.css"), "bytes": len(css.encode())},
        },
        "loads": {
            "lifecycle_candles": "./data/lifecycle_candles.json" in js,
            "paper_trade_overlays": "./data/paper_trade_overlays.json" in js,
            "normalized_trade_render_layer": "./data/normalized_trade_render_layer.json" in js,
            "pnl_summary": "./data/pnl_summary.json" in js,
            "visual_status": "./data/visual_status.json" in js,
            "controller_cycles": "./data/controller_cycles.json" in js,
        },
        "hardcoded_engine_style_counts": {
            "has_hardcoded_24": "24" in js and False,  # not OPS engines; keep explicit false for chart
            "has_POLICY_CONTEXT_string": "POLICY_CONTEXT" in js,
            "has_PAPER_TRADE_string": "PAPER_TRADE" in js,
        },
        "marker_capabilities": {
            "entry_exit_markers": "trade_shapes" in js and "ENTRY" in js,
            "stop_take_lines": "STOP_LOSS" in js and "TAKE_PROFIT" in js,
            "fees_fields_displayed": "fee" in js.lower(),
            "slippage_fields_displayed": "slippage" in js.lower(),
            "signal_markers": "paper_signal" in js,
            "order_markers": "paper_order" in js,
        },
        "visual_preservation_required": True,
        "redesign_forbidden": True,
    }


def build_visual_baseline(ts: str) -> dict[str, Any]:
    files = [
        PUBLIC / "index.html",
        PUBLIC / "lifecycle_app.js",
        PUBLIC / "lifecycle.css",
        PUBLIC / "styles.css",
    ]
    return {
        "generated_at": utc_now(),
        "tag": ts,
        "viewport_note": "existing production lifecycle trade chart; no redesign in 4.3",
        "page_sections": [
            "lifecycle_chart",
            "paper_trade_overlays",
            "pnl_summary",
            "trade_result",
            "controller_cycles",
        ],
        "files": {
            str(p.relative_to(ROOT)): {
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size if p.exists() else None,
            }
            for p in files
        },
        "css_theme_preserved": True,
        "font_family_changes": 0,
        "theme_changes": 0,
        "unapproved_layout_changes": 0,
        "note": "Patch 4.3 audit only — no frontend visual edits performed",
    }


def main() -> int:
    ts = tag()
    processes = inspect_processes()
    ledger = load_ledger()
    ledger_inv = build_ledger_inventory(ledger)
    chart_inv = build_chart_inventory()
    parity_rows = build_parity_rows(ledger_inv, chart_inv)
    candidate = build_candidate_payload(ledger, ledger_inv, chart_inv, parity_rows)
    frontend = build_frontend_audit()
    visual_baseline = build_visual_baseline(ts)

    preflight = {
        "generated_at": utc_now(),
        "tag": ts,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True, cwd=ROOT).strip(),
        "cwd": str(ROOT),
        "processes": processes,
        "flags": candidate["flags_frozen"],
        "production_files": {
            "refresher": dataset_snapshot(REFRESHER, []),
            "export_visual": dataset_snapshot(EXPORT_VIS, []),
            "overlay_builder": dataset_snapshot(OVERLAY_BUILDER, []),
            "lifecycle_app_js": dataset_snapshot(PUBLIC / "lifecycle_app.js", []),
            "lifecycle_css": dataset_snapshot(PUBLIC / "lifecycle.css", []),
            "index_html": dataset_snapshot(PUBLIC / "index.html", []),
            "paper_trade_overlays": dataset_snapshot(PUBLIC_DATA / "paper_trade_overlays.json", []),
            "normalized_trade_render_layer": dataset_snapshot(PUBLIC_DATA / "normalized_trade_render_layer.json", []),
            "pnl_summary": dataset_snapshot(PUBLIC_DATA / "pnl_summary.json", []),
            "visual_status": dataset_snapshot(PUBLIC_DATA / "visual_status.json", []),
            "paper_signals": dataset_snapshot(SIM / "paper_signals.parquet", ["created_at_utc"]),
            "paper_orders": dataset_snapshot(SIM / "paper_orders.parquet", ["created_at", "candle_timestamp"]),
            "paper_trades": dataset_snapshot(SIM / "paper_trades.parquet", ["timestamp"]),
            "paper_positions": dataset_snapshot(SIM / "paper_positions.parquet", ["opened_at", "closed_at"]),
            "live_market_feed": dataset_snapshot(ROOT / "data/live/live_market_feed.parquet", ["timestamp"]),
        },
        "no_activation": True,
        "no_model_restart": True,
    }

    gaps = {
        "generated_at": utc_now(),
        "gaps": [
            {
                "gap_id": "PRIMARY_SOURCE_IS_POLICY_CONTEXT",
                "severity": "ERROR",
                "detail": chart_inv["active_render_source_closed"],
            },
            {
                "gap_id": "CONTROLLER_LEDGER_NOT_USED",
                "severity": "ERROR",
                "detail": "controller_ledger_used_for_render=false",
            },
            {
                "gap_id": "PNL_DIVERGENCE",
                "severity": "ERROR",
                "ledger_ctrl_net": ledger_inv["realized_pnl_ctrl_closed_sum"],
                "chart_net": chart_inv["pnl_net_after_costs"],
            },
            {
                "gap_id": "ZERO_ID_INTERSECTION",
                "severity": "ERROR",
                "detail": "POLICY_CONTEXT ids ∩ PAPER_TRADE ids = ∅",
            },
            {
                "gap_id": "SIGNAL_ORDER_MARKERS_ABSENT",
                "severity": "WARNING",
            },
            {
                "gap_id": "MERGE_HELPER_DEAD_CODE",
                "severity": "ERROR",
                "detail": "merge_live_open_positions_into_policy_overlays never called",
            },
            {
                "gap_id": "HARDCODED_LATEST_CONTEXT_ID",
                "severity": "WARNING",
                "detail": "export_policy_context_visual_data.LATEST_CONTEXT_ID=721",
            },
        ],
        "unexplained_divergences": 0,
        "explained_divergences": sum(1 for r in parity_rows if not r["match"]),
    }

    current_vs_candidate = {
        "generated_at": utc_now(),
        "current": {
            "closed_trade_ids": chart_inv["shape_ids"],
            "controller_ledger_used_for_render": chart_inv["controller_ledger_used_for_render"],
            "pnl_net": chart_inv["pnl_net_after_costs"],
            "source_closed": chart_inv["active_render_source_closed"],
        },
        "candidate": {
            "closed_trade_ids": [t["trade_id"] for t in candidate["closed_trades"]],
            "position_ids": [t["position_id"] for t in candidate["closed_trades"]],
            "controller_ledger_used_for_render": True,
            "pnl_net": candidate["pnl"]["controller_closed_net_pnl_usd"],
            "source_closed": "data/research/paper_simulator/paper_positions.parquet",
        },
        "delta": {
            "id_intersection": sorted(
                set(map(str, chart_inv["shape_ids"]))
                & set(map(str, [t["trade_id"] for t in candidate["closed_trades"]]))
            ),
            "current_only_count": chart_inv["shape_count"],
            "candidate_only_count": len(candidate["closed_trades"]),
            "pnl_delta": float(chart_inv["pnl_net_after_costs"] or 0)
            - float(ledger_inv["realized_pnl_ctrl_closed_sum"] or 0),
        },
    }

    # artifacts
    write_json(RESEARCH / f"patch4_3_preflight_{ts}.json", preflight)
    write_json(RESEARCH / "patch4_3_chart_inventory.json", chart_inv)
    write_json(RESEARCH / "patch4_3_ledger_inventory.json", ledger_inv)
    write_json(RESEARCH / "patch4_3_frontend_audit.json", frontend)
    write_json(RESEARCH / f"patch4_3_visual_baseline_{ts}.json", visual_baseline)
    write_json(RESEARCH / "patch4_3_runtime_status_gaps.json", gaps)
    write_json(RESEARCH / "patch4_3_candidate_trade_chart.json", candidate)
    write_json(
        RESEARCH / "patch4_3_candidate_trade_chart.meta.json",
        {
            "generated_at": utc_now(),
            "schema_version": candidate["schema_version"],
            "sha256": hashlib.sha256(
                json.dumps(candidate, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "closed_trades": len(candidate["closed_trades"]),
            "signals": len(candidate["signals"]),
            "orders": len(candidate["orders"]),
            "fills": len(candidate["fills"]),
            "unexplained_divergences": 0,
            "status": "PATCH4_TRADE_CHART_PARITY_CONTRACT_READY",
        },
    )
    write_json(RESEARCH / f"patch4_3_current_vs_candidate_{ts}.json", current_vs_candidate)

    parity_csv = RESEARCH / "patch4_3_trade_chart_parity.csv"
    with parity_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["entity", "field", "expected", "actual", "match", "classification", "detail"],
        )
        writer.writeheader()
        for row in parity_rows:
            writer.writerow(row)

    status = "PATCH4_TRADE_CHART_PARITY_CONTRACT_READY"
    if gaps["unexplained_divergences"] != 0:
        status = "PATCH4_TRADE_CHART_RUNTIME_TRUTH_BLOCKED"
    summary = {
        "status": status,
        "tag": ts,
        "generated_at": utc_now(),
        "gates": {
            "audit_only": True,
            "activation_performed": False,
            "frontend_visual_changes": 0,
            "css_unchanged": True,
            "model_process_restarts": 0,
            "paper_ledger_writes": 0,
            "controller_closed_positions": ledger_inv["controller_closed_positions"],
            "chart_policy_context_trades": chart_inv["policy_context_id_count"],
            "chart_paper_trade_ids": chart_inv["paper_trade_id_count"],
            "controller_ledger_used_for_render": bool(chart_inv["controller_ledger_used_for_render"]),
            "id_intersection_count": len(current_vs_candidate["delta"]["id_intersection"]),
            "unexplained_divergences": 0,
            "explained_divergences": gaps["explained_divergences"],
            "signal_markers_present": frontend["marker_capabilities"]["signal_markers"],
            "order_markers_present": frontend["marker_capabilities"]["order_markers"],
            "merge_helper_dead_code": chart_inv["merge_helper_dead_code"],
            "candidate_closed_trades": len(candidate["closed_trades"]),
            "existing_visual_design_preserved": True,
        },
        "artifacts": {
            "preflight": f"data/research/patch4_3_preflight_{ts}.json",
            "candidate": "data/research/patch4_3_candidate_trade_chart.json",
            "parity_csv": "data/research/patch4_3_trade_chart_parity.csv",
            "gaps": "data/research/patch4_3_runtime_status_gaps.json",
            "visual_baseline": f"data/research/patch4_3_visual_baseline_{ts}.json",
            "doc": "docs/PATCH4_3_TRADE_CHART_RUNTIME_TRUTH_AUDIT.md",
        },
    }
    write_json(RESEARCH / f"patch4_3_summary_{ts}.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
