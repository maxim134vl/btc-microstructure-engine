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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from btc_ml.trading.trading_performance_truth import (  # noqa: E402
    build_trading_performance_truth as _build_canonical_trading_performance_truth,
)

SCHEMA_VERSION = "ops_dashboard_runtime_truth_v1"
PERFORMANCE_ADAPTER_PATH = "src/btc_ml/trading/trading_performance_truth.py"

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
MANAGER_PORTFOLIO_SUMMARY_PATH = ROOT / "data/trading/manager/portfolio_summary.json"


def _json_safe(value: Any) -> Any:
    """Reject NaN/Inf for API JSON; preserve None."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # noqa: PLR0124
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def project_trading_performance_for_ops(payload: dict[str, Any]) -> dict[str, Any]:
    """Schema projection only — never recalculates economics.

    Maps canonical ``trading_performance_truth`` into OPS
    ``trading_operations.performance``.
    """
    portfolio = dict(payload.get("portfolio") or {})
    source_policy = dict(payload.get("source_policy") or {})
    sample = dict(payload.get("sample_status") or {})
    descriptive = dict(payload.get("descriptive_metrics") or {})
    risk_adj = dict(payload.get("risk_adjusted_metrics") or {})
    data_quality = dict(payload.get("data_quality") or {})
    closed = list(payload.get("closed_trades") or [])
    starts = [str(r.get("entry_ts")) for r in closed if r.get("entry_ts")]
    ends = [str(r.get("exit_ts")) for r in closed if r.get("exit_ts")]
    recon = str(data_quality.get("reconciliation_status") or "OK")
    status = "AVAILABLE" if recon == "OK" else "DEGRADED"
    reasons: list[str] = []
    if descriptive.get("reason"):
        reasons.append(str(descriptive["reason"]))
    for item in risk_adj.get("reasons") or []:
        if item:
            reasons.append(str(item))
    sample_quality = {
        "closed_trade_count": portfolio.get("closed_trade_count"),
        "observation_start": min(starts) if starts else None,
        "observation_end": max(ends) if ends else None,
        "sample_status": sample.get("descriptive") or descriptive.get("status"),
        "descriptive_metrics_status": descriptive.get("status") or sample.get("descriptive"),
        "risk_adjusted_metrics_status": risk_adj.get("status") or sample.get("risk_adjusted"),
        "reasons": reasons,
    }
    return _json_safe(
        {
            "status": status,
            "source": {
                "adapter": PERFORMANCE_ADAPTER_PATH,
                "schema_version": payload.get("schema_version"),
                "generated_at": payload.get("generated_at"),
                "mark_source": source_policy.get("mark_source"),
                "mark_timestamp": portfolio.get("mark_timestamp"),
                "mtm_basis": portfolio.get("mtm_basis"),
                "included_sources": list(source_policy.get("included_sources") or []),
                "excluded_sources": list(source_policy.get("excluded_sources") or []),
            },
            "portfolio": portfolio,
            "timeframes": dict(payload.get("timeframes") or {}),
            "descriptive_metrics": descriptive,
            "risk_adjusted_metrics": risk_adj,
            "sample_quality": sample_quality,
            "data_quality": data_quality,
            # Backward-compatible aliases for existing OPS frontend fields.
            "realized_pnl": portfolio.get("realised_net_pnl_usd"),
            "unrealized_pnl": portfolio.get("unrealised_gross_pnl_usd"),
        }
    )


def apply_performance_aliases_to_timeframe_traders(
    plane: dict[str, Any],
    performance_payload: dict[str, Any],
) -> None:
    """Overlay canonical performance onto trader cards / portfolio aliases.

    Does not touch risk fields. Does not recompute PnL.
    """
    per_tf = dict(performance_payload.get("timeframes") or {})
    portfolio = dict(performance_payload.get("portfolio") or {})
    for entry in plane.get("traders") or []:
        tf = str(entry.get("timeframe") or "")
        tf_perf = per_tf.get(tf) or {}
        entry["realized_pnl_usd"] = tf_perf.get("realised_net_pnl_usd")
        entry["unrealized_pnl_usd"] = tf_perf.get("unrealised_gross_pnl_usd")
        entry["closed_trades"] = tf_perf.get("closed_trade_count")
        entry["closed_trade_count"] = tf_perf.get("closed_trade_count")
        # Keep book-derived open_position_count for risk; overlay canonical count
        # when adapter provides it (parity expected).
        if tf_perf.get("open_position_count") is not None:
            entry["performance_open_position_count"] = tf_perf.get("open_position_count")
        entry["performance_wins"] = tf_perf.get("wins")
        entry["performance_losses"] = tf_perf.get("losses")
        entry["total_fees_usd"] = tf_perf.get("total_fees_usd")
        entry["total_slippage_usd"] = tf_perf.get("total_slippage_usd")
        entry["latest_trade_tip"] = tf_perf.get("latest_trade_tip")
        entry["latest_position_tip"] = tf_perf.get("latest_position_tip")
        entry["performance_source"] = PERFORMANCE_ADAPTER_PATH

    port = plane.setdefault("portfolio", {})
    port["realized_pnl"] = portfolio.get("realised_net_pnl_usd")
    port["unrealized_pnl"] = portfolio.get("unrealised_gross_pnl_usd")
    port["realised_gross_pnl_usd"] = portfolio.get("realised_gross_pnl_usd")
    port["realised_net_pnl_usd"] = portfolio.get("realised_net_pnl_usd")
    port["unrealised_gross_pnl_usd"] = portfolio.get("unrealised_gross_pnl_usd")
    port["unrealised_net_pnl_usd"] = portfolio.get("unrealised_net_pnl_usd")
    port["total_gross_pnl_usd"] = portfolio.get("total_gross_pnl_usd")
    port["total_net_pnl_usd"] = portfolio.get("total_net_pnl_usd")
    port["total_fees_usd"] = portfolio.get("total_fees_usd")
    port["total_slippage_usd"] = portfolio.get("total_slippage_usd")
    port["initial_equity_usd"] = portfolio.get("initial_equity_usd")
    port["closed_equity_usd"] = portfolio.get("closed_equity_usd")
    port["mark_to_market_equity_usd"] = portfolio.get("mark_to_market_equity_usd")
    port["closed_trade_count"] = portfolio.get("closed_trade_count")
    port["performance_open_position_count"] = portfolio.get("open_position_count")
    port["mtm_basis"] = portfolio.get("mtm_basis")
    port["mark_price"] = portfolio.get("mark_price")
    port["mark_timestamp"] = portfolio.get("mark_timestamp")
    port["mark_status"] = portfolio.get("mark_status")
    port["performance_source"] = PERFORMANCE_ADAPTER_PATH


def _restore_live1b_open_position_presentation(plane: dict[str, Any]) -> None:
    """Re-apply LIVE1B open-position risk/MTM after performance alias overlay."""
    if not isinstance(plane, dict):
        return
    if plane.get("activation_mode") != "LIVE1B_INTRABAR_RULES_V1" and not live1b_paper_active():
        return
    from btc_ml.trading.intrabar_paper.mark import (
        mark_price_for_side,
        mark_side_label,
        position_notional_usd,
        risk_reward_ratio,
        unrealized_pnl_usd,
    )

    eid = str(plane.get("paper_epoch_id") or "")
    books_root = ROOT / "data/trading/intrabar_paper" / eid / "books"
    open_rows = _load_live1b_open_positions(books_root=books_root, paper_epoch_id=eid) if eid else []
    open_by_tf = {
        str(r.get("timeframe") or "").upper(): r
        for r in open_rows
        if str(r.get("timeframe") or "").upper() in S4_TIMEFRAMES
    }
    bbo = _latest_book_ticker_bbo()
    mark_ts = None if bbo is None else bbo.get("mark_timestamp")
    mark_source = None if bbo is None else bbo.get("mark_source")
    max_risk = float((plane.get("portfolio") or {}).get("max_risk_usd") or 1000.0)
    gross_open_risk = 0.0
    gross_long = 0.0
    gross_short = 0.0
    gross_unrealized = 0.0
    portfolio_mark = None
    portfolio_mark_side = None
    open_count = 0

    for entry in plane.get("traders") or []:
        tf = str(entry.get("timeframe") or "")
        pos = open_by_tf.get(tf)
        if pos is None:
            entry["open_risk_usd"] = 0.0
            entry["reserved_risk_usd"] = 0.0
            if entry.get("direction") in (None, "FLAT"):
                entry["unrealized_pnl_usd"] = 0.0
            continue
        open_count += 1
        side = str(pos.get("side") or "LONG").upper()
        entry_px = _sf(pos.get("entry_price"))
        qty = _sf(pos.get("quantity"))
        risk = _sf(pos.get("risk_amount_usd"))
        stop = _sf(pos.get("stop_loss_price"))
        take = _sf(pos.get("take_profit_price"))
        notional = (
            position_notional_usd(quantity=qty, entry_price=entry_px)
            if entry_px is not None and qty is not None
            else None
        )
        mark_px = None
        upnl = None
        mark_side = None
        if bbo is not None and entry_px is not None and qty is not None:
            mark_px = mark_price_for_side(
                side=side, best_bid=float(bbo["best_bid"]), best_ask=float(bbo["best_ask"])
            )
            mark_side = mark_side_label(side)
            upnl = unrealized_pnl_usd(
                side=side, entry_price=entry_px, quantity=qty, mark_price=mark_px
            )
            portfolio_mark = mark_px
            portfolio_mark_side = mark_side
            gross_unrealized += float(upnl)
        if risk is not None:
            gross_open_risk += float(risk)
        if notional is not None:
            if side == "LONG":
                gross_long += float(notional)
            else:
                gross_short += float(notional)
        entry["open_position_id"] = pos.get("position_id")
        entry["direction"] = side
        entry["status"] = "OPEN"
        entry["entry_price"] = entry_px
        entry["entry_fill_price"] = entry_px
        entry["entry_fill_timestamp"] = pos.get("opened_at")
        entry["quantity"] = qty
        entry["position_notional"] = notional
        entry["risk_amount_usd"] = risk
        entry["stop_loss_price"] = stop
        entry["take_profit_price"] = take
        entry["risk_reward_ratio"] = (
            risk_reward_ratio(
                side=side, entry_price=entry_px or 0.0, stop_loss_price=stop, take_profit_price=take
            )
            if entry_px is not None
            else None
        )
        entry["open_risk_usd"] = risk
        entry["reserved_risk_usd"] = risk
        entry["mark_price"] = mark_px
        entry["mark_timestamp"] = mark_ts
        entry["mark_side"] = mark_side
        entry["mark_source"] = mark_source
        entry["unrealized_pnl_usd"] = upnl
        entry["open_position_count"] = 1
        entry["risk_source"] = "LIVE1B_INTRABAR_PAPER_POSITIONS"

    available = max(0.0, max_risk - gross_open_risk)
    port = plane.setdefault("portfolio", {})
    port["open_positions"] = open_count
    port["open_position_count"] = open_count
    port["gross_open_risk_usd"] = gross_open_risk
    port["reserved_open_risk_usd"] = gross_open_risk
    port["available_risk_usd"] = available
    port["portfolio_max_risk_usd"] = max_risk
    port["max_risk_usd"] = max_risk
    port["gross_long_notional"] = gross_long
    port["gross_short_notional"] = gross_short
    port["gross_open_notional_usd"] = gross_long + gross_short
    port["risk_source"] = "LIVE1B_INTRABAR_PAPER_POSITIONS"
    if bbo is not None:
        port["unrealized_pnl"] = gross_unrealized
        port["unrealised_gross_pnl_usd"] = gross_unrealized
        port["mark_price"] = portfolio_mark
        port["mark_timestamp"] = mark_ts
        port["mark_side"] = portfolio_mark_side
        port["mark_source"] = mark_source
        port["mark_status"] = "AVAILABLE"
        closed_eq = _sf(port.get("closed_equity_usd")) or _sf(port.get("initial_equity_usd")) or 0.0
        port["mark_to_market_equity_usd"] = float(closed_eq) + float(gross_unrealized)


def clear_performance_aliases_on_timeframe_traders(plane: dict[str, Any]) -> None:
    """On performance failure: null PnL aliases (never coerce to 0)."""
    for entry in plane.get("traders") or []:
        entry["realized_pnl_usd"] = None
        entry["unrealized_pnl_usd"] = None
        entry["closed_trades"] = None
        entry["closed_trade_count"] = None
        entry["performance_source"] = None
        entry["performance_status"] = "SOURCE_UNAVAILABLE"
    port = plane.setdefault("portfolio", {})
    port["realized_pnl"] = None
    port["unrealized_pnl"] = None
    port["closed_trade_count"] = None
    port["performance_source"] = None
    port["performance_status"] = "SOURCE_UNAVAILABLE"


def build_trading_operations_block(
    *,
    timeframe_traders: dict[str, Any],
    performance: dict[str, Any] | None,
    performance_error: str | None = None,
) -> dict[str, Any]:
    """OPS Trading Operations groups: manager / risk / performance."""
    port = (timeframe_traders or {}).get("portfolio") or {}
    risk = {
        "max_risk_usd": port.get("max_risk_usd"),
        "portfolio_max_risk_usd": port.get("portfolio_max_risk_usd"),
        "reserved_open_risk_usd": port.get("reserved_open_risk_usd"),
        "gross_open_risk_usd": port.get("gross_open_risk_usd"),
        "available_risk_usd": port.get("available_risk_usd"),
        "risk_utilisation_pct": port.get("risk_utilisation_pct"),
        "risk_status": port.get("risk_status"),
        "risk_semantics": port.get("risk_semantics"),
        "per_timeframe": [
            {
                "timeframe": t.get("timeframe"),
                "reserved_risk_usd": t.get("reserved_risk_usd"),
                "open_risk_usd": t.get("open_risk_usd"),
                "risk_status": t.get("risk_status"),
            }
            for t in (timeframe_traders or {}).get("traders") or []
        ],
    }
    if performance is None:
        perf_section: dict[str, Any] = {
            "status": "UNKNOWN",
            "error": performance_error or "trading_performance unavailable",
            "source": {"adapter": PERFORMANCE_ADAPTER_PATH},
        }
    else:
        perf_section = performance
    return {
        "manager": (timeframe_traders or {}).get("manager") or {},
        "risk": risk,
        "performance": perf_section,
    }


def live1b_paper_active() -> bool:
    """True when INTRABAR_RULES_V1 paper epoch owns active execution."""
    path = ROOT / "data/trading/paper_epochs/active.json"
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return False
    return str(payload.get("rule_contract_version") or "").startswith("INTRABAR_RULES")


def live1b_active_epoch() -> dict[str, Any] | None:
    path = ROOT / "data/trading/paper_epochs/active.json"
    if not live1b_paper_active():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def s4_activated() -> bool:
    """True once the S4.1 manager/trader architecture owns paper execution."""
    return S4_ACTIVATION_PATH.exists()


def _process_specs() -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    live1b = live1b_paper_active()
    activated = s4_activated() and not live1b
    specs: list[tuple[str, tuple[str, ...], bool]] = [
        ("live_feed", ("live_binance_intrabar_feed.py",), True),
        ("canonical_pipeline", ("run.py",), True),
        ("context_refresher", ("run_context_refresh_daemon.py",), True),
        # Legacy global controller is required only until the S4.1 cutover.
        ("paper_controller", ("bounded_paper_trading_controller_auto_ledger",), not activated and not live1b),
        ("ops_backend", ("run_api.py", "dashboard/backend"), False),
        ("dashboard_refresher", ("run_market_context_visual_refresher.py",), False),
        (
            "shadow_structural_protection",
            ("run_shadow_structural_protection.py",),
            False,
        ),
        (
            "shadow_economic_correlation",
            ("run_shadow_economic_correlation.py",),
            False,
        ),
    ]
    if live1b:
        specs.extend(
            [
                ("intrabar_cognition", ("run_intrabar_cognition_service.py",), True),
                ("intrabar_paper_manager", ("run_intrabar_paper_manager.py",), True),
            ]
        )
    else:
        specs.append(("timeframe_manager", ("timeframe_manager_daemon.py",), activated))
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


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    except OSError:
        return []
    return rows


def _load_live1b_open_positions(*, books_root: Path, paper_epoch_id: str) -> list[dict[str, Any]]:
    """Latest OPEN rows from active-epoch positions.jsonl (legacy/void excluded)."""
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl_rows(books_root / "positions.jsonl"):
        pid = str(row.get("position_id") or "")
        if not pid:
            continue
        latest[pid] = row
    out: list[dict[str, Any]] = []
    for row in latest.values():
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        if str(row.get("paper_epoch_id") or "") != str(paper_epoch_id):
            continue
        out.append(row)
    return out


def _load_context_event_by_id(context_event_id: str | None) -> dict[str, Any] | None:
    if not context_event_id:
        return None
    path = ROOT / "data/cognition/intrabar_context_events/events.jsonl"
    for row in _read_jsonl_rows(path):
        if str(row.get("context_event_id") or "") == str(context_event_id):
            return row
    return None


def _latest_book_ticker_bbo() -> dict[str, Any] | None:
    """Fresh presentation BBO; prefer PAPER manager live WebSocket snapshot."""
    import json as _json

    health_path = ROOT / "data/runtime/intrabar_paper_health.json"
    try:
        health = _json.loads(health_path.read_text(encoding="utf-8"))
        current = health.get("current_bbo") or {}
        bid = _sf(current.get("best_bid"))
        ask = _sf(current.get("best_ask"))
        freshness_ms = _sf(current.get("freshness_ms"))
        max_age_ms = _sf(health.get("max_bbo_age_ms")) or 2000.0

        if (
            health.get("alive") is True
            and health.get("paper_only") is True
            and health.get("real_execution_enabled") is False
            and bid is not None
            and ask is not None
            and ask >= bid
            and freshness_ms is not None
            and freshness_ms <= max_age_ms
        ):
            return {
                "best_bid": float(bid),
                "best_ask": float(ask),
                "mark_timestamp": current.get("bbo_receive_timestamp"),
                "mark_source": "intrabar_paper_health/current_bbo",
            }
    except Exception:
        pass

    # Legacy archive fallback is allowed only while genuinely fresh.
    root = ROOT / "data/raw_market_events_v2/book_ticker"
    if not root.exists():
        return None
    try:
        import pandas as pd
    except Exception:
        return None

    dates = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("date="))
    if not dates:
        return None
    hours = sorted(p for p in dates[-1].iterdir() if p.is_dir() and p.name.startswith("hour="))
    if not hours:
        return None
    files = sorted(hours[-1].glob("*.parquet"))
    if not files:
        return None

    try:
        frame = pd.read_parquet(files[-1])
        if frame is None or not len(frame):
            return None
        row = frame.iloc[-1]
        bid = _sf(row["best_bid_price"])
        ask = _sf(row["best_ask_price"])
        ts = row["local_receive_timestamp"]
        parsed_ts = pd.to_datetime(ts, utc=True)
        age_ms = (pd.Timestamp.now(tz="UTC") - parsed_ts).total_seconds() * 1000.0
    except Exception:
        return None

    if bid is None or ask is None or ask < bid or age_ms > 5000.0:
        return None

    ts_s = str(ts)
    if ts_s.endswith("+00:00"):
        ts_s = ts_s.replace("+00:00", "Z")
    return {
        "best_bid": float(bid),
        "best_ask": float(ask),
        "mark_timestamp": ts_s,
        "mark_source": "raw_market_events_v2/book_ticker",
    }

def _build_live1b_timeframe_traders(
    *,
    performance_payload: dict[str, Any] | None = None,
    load_performance: bool = True,
) -> dict[str, Any]:
    """Active LIVE1B plane: epoch books only; legacy S4 books excluded."""
    from btc_ml.trading.intrabar_paper.mark import (
        mark_price_for_side,
        mark_side_label,
        position_notional_usd,
        risk_reward_ratio,
        unrealized_pnl_usd,
    )

    epoch = live1b_active_epoch() or {}
    paper_health = _read_json(ROOT / "data/runtime/intrabar_paper_health.json") or {}
    cognition_health = _read_json(ROOT / "data/runtime/intrabar_cognition_health.json") or {}
    eid = str(epoch.get("paper_epoch_id") or paper_health.get("paper_epoch_id") or "")
    books_root = ROOT / "data/trading/intrabar_paper" / eid / "books"
    sleeves = paper_health.get("sleeves") if isinstance(paper_health.get("sleeves"), dict) else {}
    capital_model = str(
        paper_health.get("capital_model")
        or epoch.get("capital_model")
        or ("PER_TIMEFRAME_REALIZED_EQUITY" if sleeves else "SHARED_MASTER_REALIZED_EQUITY")
    )
    initial = float(
        paper_health.get("master_initial_equity_usd")
        if paper_health.get("master_initial_equity_usd") is not None
        else epoch.get("master_initial_equity_usd")
        if epoch.get("master_initial_equity_usd") is not None
        else epoch.get("initial_equity_usd")
        if epoch.get("initial_equity_usd") is not None
        else paper_health.get("initial_equity_usd")
        if paper_health.get("initial_equity_usd") is not None
        else 100000.0
    )
    equity = float(
        paper_health.get("master_current_equity_usd")
        if paper_health.get("master_current_equity_usd") is not None
        else paper_health.get("equity_usd")
        if paper_health.get("equity_usd") is not None
        else initial
    )
    realized = float(
        paper_health.get("master_realized_net_pnl_usd")
        if paper_health.get("master_realized_net_pnl_usd") is not None
        else paper_health.get("realized_pnl_usd")
        or 0.0
    )
    max_risk = float(
        paper_health.get("master_risk_capacity_usd")
        if paper_health.get("master_risk_capacity_usd") is not None
        else paper_health.get("max_risk_per_trade_usd")
        or 1000.0
    )

    manager_proc = {}
    cognition_proc = {}
    try:
        for proc in inspect_processes():
            if proc.get("process_id") == "intrabar_paper_manager":
                manager_proc = proc
            if proc.get("process_id") == "intrabar_cognition":
                cognition_proc = proc
    except Exception:
        pass

    manager_alive = bool(manager_proc.get("alive")) or bool(paper_health)
    lanes = paper_health.get("execution_lanes") or {
        tf: "ACTIVE" if manager_alive else "INACTIVE" for tf in S4_TIMEFRAMES
    }

    open_rows = _load_live1b_open_positions(books_root=books_root, paper_epoch_id=eid) if eid else []
    open_by_tf: dict[str, dict[str, Any]] = {}
    for row in open_rows:
        tf = str(row.get("timeframe") or "").upper()
        if tf in S4_TIMEFRAMES:
            open_by_tf[tf] = row

    bbo = _latest_book_ticker_bbo()
    mark_ts = None if bbo is None else bbo.get("mark_timestamp")
    mark_source = None if bbo is None else bbo.get("mark_source")

    traders: list[dict[str, Any]] = []
    open_count = 0
    gross_open_risk = 0.0
    gross_long_notional = 0.0
    gross_short_notional = 0.0
    gross_unrealized = 0.0
    portfolio_mark: float | None = None
    portfolio_mark_side: str | None = None

    for tf in S4_TIMEFRAMES:
        pos = open_by_tf.get(tf)
        has_pos = pos is not None
        lane = str(lanes.get(tf) or ("ACTIVE" if manager_alive else "INACTIVE")).upper()
        entry: dict[str, Any] = {
            "timeframe": tf,
            "entity_type": "INTRABAR_PAPER_EXECUTION_LANE",
            "book_path": f"data/trading/intrabar_paper/{eid}/books",
            "book_exists": books_root.exists(),
            "pid": manager_proc.get("pid"),
            "alive": manager_alive,
            "process_health": "RUNNING" if manager_alive else "STOPPED",
            "execution_lane": lane,
            "execution_lane_status": lane,
            "open_position_id": None,
            "direction": "FLAT",
            "status": "FLAT",
            "entry_price": None,
            "entry_fill_price": None,
            "entry_fill_timestamp": None,
            "quantity": None,
            "position_notional": None,
            "risk_amount_usd": None,
            "stop_loss_price": None,
            "take_profit_price": None,
            "risk_reward_ratio": None,
            "context_event_id": None,
            "lifecycle_episode_id": None,
            "context_started_at": None,
            "context_price": None,
            "context_price_timestamp": None,
            "mark_price": None,
            "mark_timestamp": None,
            "mark_side": None,
            "mark_source": None,
            "open_risk_usd": 0.0,
            "reserved_risk_usd": 0.0,
            "risk_status": "ZERO_CONFIRMED",
            "risk_source": "LIVE1B_INTRABAR_PAPER_POSITIONS",
            "risk_source_tip": paper_health.get("updated_at"),
            "risk_freshness": "FRESH",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "initial_equity_usd": None,
            "current_equity_usd": None,
            "risk_pct_per_trade": None,
            "next_risk_budget_usd": None,
            "available_risk_usd": None,
            "open_position_count": 0,
            "closed_trades": 0,
            "closed_trade_count": 0,
            "last_command_id": (paper_health.get("last_command") or {}).get("command_id")
            if isinstance(paper_health.get("last_command"), dict)
            else None,
            "last_command_intent": None,
            "command_cursor": paper_health.get("last_consumed_context_event_id"),
            "book_tip": None,
            "paper_only": True,
            "execution_enabled": False,
            "paper_epoch_id": eid,
        }
        if has_pos and pos is not None:
            open_count += 1
            side = str(pos.get("side") or "LONG").upper()
            entry_px = _sf(pos.get("entry_price"))
            qty = _sf(pos.get("quantity"))
            risk = _sf(pos.get("risk_amount_usd"))
            stop = _sf(pos.get("stop_loss_price"))
            take = _sf(pos.get("take_profit_price"))
            notional = None
            if entry_px is not None and qty is not None:
                notional = position_notional_usd(quantity=qty, entry_price=entry_px)
            ctx_id = pos.get("entry_context_event_id")
            ctx = _load_context_event_by_id(None if ctx_id is None else str(ctx_id))
            mark_px = None
            upnl = None
            mark_side = None
            if bbo is not None and entry_px is not None and qty is not None:
                mark_px = mark_price_for_side(
                    side=side,
                    best_bid=float(bbo["best_bid"]),
                    best_ask=float(bbo["best_ask"]),
                )
                mark_side = mark_side_label(side)
                upnl = unrealized_pnl_usd(
                    side=side,
                    entry_price=entry_px,
                    quantity=qty,
                    mark_price=mark_px,
                )
                portfolio_mark = mark_px
                portfolio_mark_side = mark_side
                gross_unrealized += float(upnl)
            if risk is not None:
                gross_open_risk += float(risk)
            if notional is not None:
                if side == "LONG":
                    gross_long_notional += float(notional)
                else:
                    gross_short_notional += float(notional)
            entry.update(
                {
                    "open_position_id": pos.get("position_id"),
                    "direction": side,
                    "status": "OPEN",
                    "entry_price": entry_px,
                    "entry_fill_price": entry_px,
                    "entry_fill_timestamp": pos.get("opened_at"),
                    "quantity": qty,
                    "position_notional": notional,
                    "risk_amount_usd": risk,
                    "stop_loss_price": stop,
                    "take_profit_price": take,
                    "risk_reward_ratio": risk_reward_ratio(
                        side=side,
                        entry_price=entry_px or 0.0,
                        stop_loss_price=stop,
                        take_profit_price=take,
                    )
                    if entry_px is not None
                    else None,
                    "context_event_id": ctx_id,
                    "lifecycle_episode_id": pos.get("lifecycle_episode_id"),
                    "context_started_at": None if ctx is None else ctx.get("event_timestamp"),
                    "context_price": None
                    if ctx is None
                    else (_sf(ctx.get("context_event_price"))),
                    "context_price_timestamp": None if ctx is None else ctx.get("last_trade_timestamp"),
                    "mark_price": mark_px,
                    "mark_timestamp": mark_ts,
                    "mark_side": mark_side,
                    "mark_source": mark_source,
                    "open_risk_usd": risk,
                    "reserved_risk_usd": risk,
                    "risk_status": "AVAILABLE" if risk and abs(float(risk)) > 1e-12 else "ZERO_CONFIRMED",
                    "unrealized_pnl_usd": upnl,
                    "open_position_count": 1,
                }
            )
        sleeve = sleeves.get(tf) if isinstance(sleeves.get(tf), dict) else None
        if sleeve is not None:
            entry.update(
                {
                    "initial_equity_usd": _sf(sleeve.get("initial_equity_usd")),
                    "current_equity_usd": _sf(sleeve.get("current_equity_usd")),
                    "risk_pct_per_trade": _sf(sleeve.get("risk_pct_per_trade")),
                    "next_risk_budget_usd": _sf(sleeve.get("next_risk_budget_usd")),
                    "available_risk_usd": _sf(sleeve.get("available_risk_usd")),
                    "realized_pnl_usd": _sf(sleeve.get("cumulative_realized_net_pnl_usd")) or 0.0,
                    "closed_trades": int(sleeve.get("closed_trades_count") or 0),
                    "closed_trade_count": int(sleeve.get("closed_trades_count") or 0),
                }
            )
            if not has_pos:
                entry["open_risk_usd"] = float(sleeve.get("open_position_risk_usd") or 0.0)
        traders.append(entry)

    if capital_model == "PER_TIMEFRAME_REALIZED_EQUITY":
        available = float(
            paper_health.get("master_available_risk_usd")
            if paper_health.get("master_available_risk_usd") is not None
            else max(0.0, max_risk - gross_open_risk)
        )
        if paper_health.get("master_open_risk_usd") is not None:
            gross_open_risk = float(paper_health.get("master_open_risk_usd") or 0.0)
    else:
        available = max(0.0, max_risk - gross_open_risk)
    util = round(100.0 * gross_open_risk / max_risk, 6) if max_risk > 0 else 0.0
    mtm_equity = equity + gross_unrealized

    plane = {
        "entity_type": "INTRABAR_PAPER_TRADING_PLANE",
        "activated": True,
        "activation_mode": "LIVE1B_INTRABAR_RULES_V1",
        "paper_epoch_id": eid,
        "activation_timestamp": epoch.get("activated_at"),
        "supported_timeframes": list(S4_TIMEFRAMES),
        "unsupported_timeframes": {"D1": "TIMEFRAME_NOT_LIVE/NO_LIVE_STAGE2_WRITER"},
        "d1_trader": False,
        "legacy_excluded": True,
        "legacy_void_status": "VOID_PRE_INTRABAR_RULE_CONTRACT",
        "manager": {
            "display_name": "Paper Manager",
            "status": "CONNECTED" if manager_alive else "DISCONNECTED",
            "process_id": "intrabar_paper_manager",
            "pid": manager_proc.get("pid") or paper_health.get("pid"),
            "manager_cycle_id": None,
            "evaluation_timestamp": paper_health.get("updated_at"),
            "generated_at": paper_health.get("updated_at"),
            "commands": {},
            "writes_paper_ledger": True,
            "writes_cognition": False,
            "directional_netting": False,
            "context_consumer": str(
                paper_health.get("context_consumer_status")
                or ("CONNECTED" if manager_alive else "DISCONNECTED")
            ),
            "intrabar_cognition": {
                "status": "CONNECTED" if cognition_proc.get("alive") else "DISCONNECTED",
                "pid": cognition_proc.get("pid") or cognition_health.get("pid"),
            },
        },
        "command_bus": {
            "path": "data/cognition/intrabar_context_events",
            "exists": (ROOT / "data/cognition/intrabar_context_events").exists(),
            "append_only": True,
            "rows": 0,
            "health": "CONNECTED" if manager_alive else "DISCONNECTED",
            "source": "INTRABAR_CONTEXT_JOURNAL",
        },
        "traders": traders,
        "portfolio": {
            "open_positions": open_count,
            "open_position_count": open_count,
            "gross_long_notional": gross_long_notional,
            "gross_short_notional": gross_short_notional,
            "gross_open_notional_usd": gross_long_notional + gross_short_notional,
            "net_notional": gross_long_notional - gross_short_notional,
            "net_notional_semantics": "REPORTING_ONLY_NEVER_NETTED",
            "gross_open_risk_usd": gross_open_risk,
            "reserved_open_risk_usd": gross_open_risk,
            "portfolio_max_risk_usd": max_risk,
            "max_risk_usd": max_risk,
            "available_risk_usd": available,
            "risk_utilisation_pct": util,
            "risk_source": "LIVE1B_INTRABAR_PAPER_POSITIONS",
            "risk_source_tip": paper_health.get("updated_at"),
            "risk_status": "ZERO_CONFIRMED" if open_count == 0 else "AVAILABLE",
            "risk_freshness": "FRESH",
            "risk_semantics": RISK_SEMANTICS_RESERVED_OPEN,
            "observability_health": "OPERATIONAL",
            "realized_pnl": realized,
            "unrealized_pnl": gross_unrealized if bbo is not None else None,
            "closed_trade_count": int(paper_health.get("trades_count") or 0),
            "initial_equity_usd": initial,
            "closed_equity_usd": equity,
            "mark_to_market_equity_usd": mtm_equity if bbo is not None else equity,
            "risk_aggregation": "GROSS_NO_NETTING",
            "paper_epoch_id": eid,
            "capital_model": capital_model,
            "master_initial_equity_usd": initial,
            "master_current_equity_usd": equity,
            "master_realized_net_pnl_usd": realized,
            "master_unrealized_pnl_usd": gross_unrealized if bbo is not None else None,
            "master_open_risk_usd": gross_open_risk,
            "master_risk_capacity_usd": max_risk,
            "master_available_risk_usd": available,
            "master_open_notional_usd": gross_long_notional + gross_short_notional,
            "mark_price": portfolio_mark,
            "mark_timestamp": mark_ts,
            "mark_side": portfolio_mark_side,
            "mark_source": mark_source,
            "mark_status": "AVAILABLE" if bbo is not None else "MARK_UNAVAILABLE",
        },
        "execution_lanes": {tf: str(lanes.get(tf) or "ACTIVE") for tf in S4_TIMEFRAMES},
        "read_only": True,
        "paper_only": True,
        "real_execution": False,
        "exchange_calls": 0,
    }

    perf = performance_payload
    if perf is None and load_performance:
        try:
            perf = _build_canonical_trading_performance_truth()
        except Exception as exc:  # noqa: BLE001
            plane["performance_load_error"] = f"{type(exc).__name__}: {exc}"
            clear_performance_aliases_on_timeframe_traders(plane)
            # Keep LIVE1B risk/MTM already computed above.
            return plane
    if perf is not None:
        apply_performance_aliases_to_timeframe_traders(plane, perf)
        _restore_live1b_open_position_presentation(plane)
    return plane


def build_timeframe_traders(
    *,
    performance_payload: dict[str, Any] | None = None,
    load_performance: bool = True,
) -> dict[str, Any]:
    """S4.1 / LIVE1B read-only view.

    When LIVE1B epoch is ACTIVE, legacy closed-bar books and portfolio_summary
    are excluded from the active plane. Single paper manager owns all TF lanes.
    """
    if live1b_paper_active():
        return _build_live1b_timeframe_traders(
            performance_payload=performance_payload,
            load_performance=load_performance,
        )

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
            # Performance aliases filled only from trading_performance_truth.
            "realized_pnl_usd": None,
            "unrealized_pnl_usd": None,
            "open_position_count": 0,
            "closed_trades": None,
            "closed_trade_count": None,
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
            # Intentionally do NOT sum trades.parquet for realised PnL / closed counts.
            # Canonical performance comes from trading_performance_truth only.
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        trader_view = ((portfolio.get("traders") or {}).get(tf)) or {}
        # Do not copy manager unrealised into OPS — adapter owns MTM basis.
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
        traders.append(entry)

    aggregate = _resolve_aggregate_portfolio_risk(portfolio, book_open_positions=book_open_positions)
    if tf_attribution_gaps and aggregate.get("risk_status") in {"AVAILABLE", "ZERO_CONFIRMED"}:
        aggregate["observability_health"] = "OPERATIONAL_WITH_LIMITATIONS"
    elif aggregate.get("risk_status") == "SOURCE_UNAVAILABLE":
        aggregate["observability_health"] = "DEGRADED_OBSERVABILITY"

    plane = {
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
            # Aliases filled only from canonical performance adapter.
            "realized_pnl": None,
            "unrealized_pnl": None,
            "closed_trade_count": None,
            "risk_aggregation": "GROSS_NO_NETTING",
        },
        "read_only": True,
        "paper_only": True,
        "real_execution": False,
        "exchange_calls": 0,
    }

    perf = performance_payload
    if perf is None and load_performance:
        try:
            perf = _build_canonical_trading_performance_truth()
        except Exception as exc:  # noqa: BLE001
            plane["performance_load_error"] = f"{type(exc).__name__}: {exc}"
            clear_performance_aliases_on_timeframe_traders(plane)
            return plane
    if perf is not None:
        apply_performance_aliases_to_timeframe_traders(plane, perf)
    return plane


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
    live1b_roles_tracked = any(
        p["process_id"] in {"intrabar_cognition", "intrabar_paper_manager"} for p in processes
    )
    if live1b_paper_active() and live1b_roles_tracked:
        down("intrabar_cognition", "INTRABAR_COGNITION_DOWN", "CRITICAL")
        down("intrabar_paper_manager", "INTRABAR_PAPER_MANAGER_DOWN", "ERROR")
        # Legacy closed-bar stack must stay stopped under LIVE1B.
        for pid_name, alert_id in (
            ("timeframe_manager", "LEGACY_TIMEFRAME_MANAGER_RUNNING_AFTER_LIVE1B"),
            *((f"trader_{tf}", f"LEGACY_TRADER_RUNNING_AFTER_LIVE1B_{tf}") for tf in S4_TIMEFRAMES),
        ):
            legacy = by_id.get(pid_name)
            if legacy and legacy.get("health") == "RUNNING":
                alerts.append(
                    {
                        "alert_id": alert_id,
                        "severity": "CRITICAL",
                        "component": pid_name,
                        "message": f"{pid_name} running after LIVE1B cutover",
                        "reason_code": "LEGACY_AND_LIVE1B_CONCURRENT",
                        "started_at": utc_now(),
                        "last_seen": utc_now(),
                        "active": True,
                    }
                )
    elif s4_activated() and s4_roles_tracked:
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
        timeframe_traders = build_timeframe_traders(load_performance=False)
    except Exception as exc:  # noqa: BLE001
        timeframe_traders = {
            "activated": s4_activated(),
            "traders": [],
            "status": "UNKNOWN",
            "error": f"{type(exc).__name__}: {exc}",
        }
        section_errors["trader_truth"] = f"{type(exc).__name__}: {exc}"

    trading_operations: dict[str, Any]
    performance_section: dict[str, Any] | None = None
    try:
        perf_raw = _build_canonical_trading_performance_truth()
        performance_section = project_trading_performance_for_ops(perf_raw)
        if isinstance(timeframe_traders, dict) and timeframe_traders.get("traders") is not None:
            apply_performance_aliases_to_timeframe_traders(timeframe_traders, perf_raw)
            _restore_live1b_open_position_presentation(timeframe_traders)
        trading_operations = build_trading_operations_block(
            timeframe_traders=timeframe_traders if isinstance(timeframe_traders, dict) else {},
            performance=performance_section,
        )
    except Exception as exc:  # noqa: BLE001
        section_errors["trading_performance"] = f"{type(exc).__name__}: {exc}"
        if isinstance(timeframe_traders, dict) and timeframe_traders.get("traders") is not None:
            clear_performance_aliases_on_timeframe_traders(timeframe_traders)
        trading_operations = build_trading_operations_block(
            timeframe_traders=timeframe_traders if isinstance(timeframe_traders, dict) else {},
            performance=None,
            performance_error=section_errors["trading_performance"],
        )

    paper_proc = next((p for p in processes if p["process_id"] == "paper_controller"), None)
    if paper_proc and isinstance(paper, dict):
        paper["process_health"] = paper_proc["health"]
        paper["pid"] = paper_proc["pid"]
        if paper_proc["health"] != "RUNNING":
            if live1b_paper_active() or timeframe_traders.get("activated"):
                paper["representation"] = (
                    "MIGRATED_TO_INTRABAR_PAPER"
                    if live1b_paper_active()
                    else "MIGRATED_TO_TIMEFRAME_TRADERS"
                )
                paper["display_status"] = "MIGRATED"
                paper["requirement"] = "NOT_REQUIRED"
                paper["health"] = "HEALTHY"
                paper["is_controller_failure"] = False
                paper["health_reason"] = (
                    "legacy_global_controller_stopped_at_live1b_cutover"
                    if live1b_paper_active()
                    else "legacy_global_controller_stopped_at_s4_1_cutover"
                )
                paper["legacy_ledger_role"] = "READ_ONLY_ARCHIVED_VOID"
                paper["detail"] = (
                    "Replaced by LIVE1B intrabar paper manager (M15/M30/H1/H4 lanes)"
                    if live1b_paper_active()
                    else "Replaced by independent M15, M30, H1 and H4 traders"
                )
            else:
                paper["representation"] = "STOPPED"
                paper["display_status"] = "FAILED"
                paper["requirement"] = "REQUIRED"
                paper["health"] = "BROKEN"
                paper["is_controller_failure"] = True

    if live1b_paper_active() and isinstance(paper, dict):
        paper_mgr = next((p for p in processes if p["process_id"] == "intrabar_paper_manager"), None)
        paper["paper_epoch_id"] = (live1b_active_epoch() or {}).get("paper_epoch_id")
        paper["paper_mode"] = True
        paper["real_execution"] = False
        paper["controller"] = "intrabar_paper_manager"
        if paper_mgr:
            paper["intrabar_paper_manager_health"] = paper_mgr.get("health")
            paper["intrabar_paper_manager_pid"] = paper_mgr.get("pid")
            paper["intrabar_paper_manager_status"] = (
                "CONNECTED" if paper_mgr.get("health") == "RUNNING" else "DISCONNECTED"
            )

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

    live1b_epoch = live1b_active_epoch() if live1b_paper_active() else None
    paper_health = _read_json(ROOT / "data/runtime/intrabar_paper_health.json") or {}
    cognition_health = _read_json(ROOT / "data/runtime/intrabar_cognition_health.json") or {}
    # Active-epoch research shadows only.
    #
    # Never fall back to root-level health.json here: those files may belong
    # to a previous PAPER epoch and must not appear as current dashboard truth.
    active_shadow_epoch_id = str(
        (live1b_epoch or {}).get("paper_epoch_id") or ""
    )
    active_shadow_fingerprint = str(
        (live1b_epoch or {}).get("trading_contract_fingerprint") or ""
    )

    process_by_id = {
        str(p.get("process_id")): p
        for p in processes
        if isinstance(p, dict)
    }

    def _shadow_process_truth(process_id: str) -> dict[str, Any]:
        proc = process_by_id.get(process_id) or {}
        return {
            "process_id": process_id,
            "pid": proc.get("pid"),
            "alive": bool(proc.get("alive")),
            "process_health": proc.get("health") or "STOPPED",
            "process_state": proc.get("process_state") or "STOPPED",
            "uptime_seconds": proc.get("uptime_seconds"),
            "started_at": proc.get("started_at"),
            "command": proc.get("command"),
            "health_reason": proc.get("health_reason"),
        }

    def _epoch_shadow_health(
        component_dir: str,
        process_id: str,
    ) -> dict[str, Any]:
        if not active_shadow_epoch_id:
            return {
                "mode": "OBSERVE_ONLY",
                "read_only": True,
                "enforcement_enabled": False,
                "status": "ACTIVE_EPOCH_UNAVAILABLE",
                "binding_status": "ACTIVE_EPOCH_UNAVAILABLE",
                **_shadow_process_truth(process_id),
            }

        path = (
            ROOT
            / "data/trading"
            / component_dir
            / "epochs"
            / active_shadow_epoch_id
            / "health.json"
        )

        payload = _read_json(path) or {}

        proc = _shadow_process_truth(process_id)

        if not payload:
            return {
                "mode": "OBSERVE_ONLY",
                "read_only": True,
                "enforcement_enabled": False,
                "status": "ACTIVE_EPOCH_DATA_MISSING",
                "binding_status": "ACTIVE_EPOCH_DATA_MISSING",
                "source_epoch_id": active_shadow_epoch_id,
                "source_path": str(path.relative_to(ROOT)),
                **proc,
            }

        result = dict(payload)

        source_epoch = str(result.get("source_epoch_id") or "")
        source_fp = str(
            result.get("source_contract_fingerprint")
            or result.get("trading_contract_fingerprint")
            or ""
        )

        epoch_match = source_epoch == active_shadow_epoch_id
        fingerprint_match = (
            bool(active_shadow_fingerprint)
            and source_fp == active_shadow_fingerprint
        )

        original_status = result.get("status")

        if not epoch_match:
            binding_status = "EPOCH_MISMATCH"
        elif not fingerprint_match:
            binding_status = "FINGERPRINT_MISMATCH"
        else:
            binding_status = "BOUND_CURRENT"

        result.update(
            {
                "mode": result.get("mode") or "OBSERVE_ONLY",
                "read_only": True,
                "enforcement_enabled": False,
                "research_status": original_status,
                "active_paper_epoch_id": active_shadow_epoch_id,
                "active_trading_fingerprint": active_shadow_fingerprint,
                "epoch_match": epoch_match,
                "fingerprint_match": fingerprint_match,
                "binding_status": binding_status,
                "source_path": str(path.relative_to(ROOT)),
                **proc,
            }
        )

        # Fail visibly instead of silently presenting wrong-epoch metrics.
        if binding_status != "BOUND_CURRENT":
            result["status"] = binding_status

        return result

    shadow_stp = _epoch_shadow_health(
        "shadow_structural_protection",
        "shadow_structural_protection",
    )

    shadow_eqcorr = _epoch_shadow_health(
        "shadow_economic_correlation",
        "shadow_economic_correlation",
    )

    # Read-only cross-layer outcome reconciliation diagnostics (TRD-OUTCOME2)
    cross_layer = _read_json(ROOT / "output/audits/trd_outcome2/latest.json") or {}
    cross_layer_block = None
    if cross_layer:
        summary = cross_layer.get("summary") or {}
        counts = cross_layer.get("counts") or {}
        stp_m = cross_layer.get("stp_manifest") or {}
        cross_layer_block = {
            "read_only": True,
            "status": cross_layer.get("status"),
            "audit_timestamp": cross_layer.get("generated_at") or cross_layer.get("audit_timestamp_utc"),
            "active_paper_epoch": cross_layer.get("active_epoch"),
            "active_trading_fingerprint": cross_layer.get("active_trading_contract_fingerprint"),
            "active_stp_manifest": stp_m.get("active_stp_manifest_fingerprint"),
            "active_stp_manifest_version": stp_m.get("active_stp_manifest_version"),
            "closed_paper_trades": counts.get("closed_trades"),
            "fully_reconciled_trades": summary.get("fully_reconciled_trades"),
            "pending_eqcorr_outcomes": summary.get("pending_eqcorr_outcomes"),
            "pending_stp_outcomes": summary.get("pending_stp_outcomes"),
            "paper_lifecycle_ok": summary.get("paper_lifecycle_ok"),
            "paper_pnl_ok": summary.get("paper_pnl_ok"),
            "sleeve_ok": summary.get("sleeve_ok"),
            "master_ok": summary.get("master_ok"),
            "eqcorr_baseline_divergences": summary.get("eqcorr_baseline_divergences"),
            "stp_baseline_divergences": summary.get("stp_baseline_divergences"),
            "immutability_ok": summary.get("immutability_ok"),
            "lookahead_ok": summary.get("lookahead_ok"),
            "last_reconciled_trade": summary.get("last_reconciled_trade"),
            "last_reconciled_exit_timestamp": summary.get("last_reconciled_exit_timestamp"),
            "blockers": cross_layer.get("blockers") or [],
        }
    live1b_block = None
    if live1b_epoch is not None:
        by_id = {p["process_id"]: p for p in processes}
        live1b_block = {
            "status": "ACTIVE",
            "paper_epoch_id": live1b_epoch.get("paper_epoch_id"),
            "activated_at": live1b_epoch.get("activated_at"),
            "paper_mode": True,
            "real_execution": False,
            "intrabar_cognition": {
                "status": "CONNECTED"
                if (by_id.get("intrabar_cognition") or {}).get("health") == "RUNNING"
                else "DISCONNECTED",
                "pid": (by_id.get("intrabar_cognition") or {}).get("pid")
                or cognition_health.get("pid"),
            },
            "paper_manager": {
                "status": "CONNECTED"
                if (by_id.get("intrabar_paper_manager") or {}).get("health") == "RUNNING"
                else "DISCONNECTED",
                "pid": (by_id.get("intrabar_paper_manager") or {}).get("pid")
                or paper_health.get("pid"),
            },
            "context_consumer": {
                "status": str(
                    paper_health.get("context_consumer_status")
                    or (
                        "CONNECTED"
                        if (by_id.get("intrabar_paper_manager") or {}).get("health") == "RUNNING"
                        else "DISCONNECTED"
                    )
                ),
                "last_consumed_context_event_id": paper_health.get(
                    "last_consumed_context_event_id"
                ),
            },
            "execution_lanes": {
                tf: str((paper_health.get("execution_lanes") or {}).get(tf) or "ACTIVE")
                for tf in S4_TIMEFRAMES
            },
            "active_history": {
                "signals": 0,
                "orders": 0,
                "fills": 0,
                "trades": int(paper_health.get("trades_count") or 0),
                "positions": int(
                    len(paper_health.get("active_positions_by_timeframe") or {})
                ),
                "equity_usd": paper_health.get("equity_usd"),
                "realized_pnl_usd": paper_health.get("realized_pnl_usd"),
                "unrealized_pnl_usd": paper_health.get("unrealized_pnl_usd"),
            },
            "legacy_archive_path": "data/paper_trading/archive/pre_intrabar_rules_20260728_110636",
        }

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
        "trading_operations": trading_operations,
        "live1b_paper": live1b_block,
        "shadow_economic_correlation": shadow_eqcorr or {
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "status": "NOT_STARTED",
        },
        "shadow_structural_protection": shadow_stp or {
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "status": "NOT_STARTED",
            "exact_intrabar_data": "UNKNOWN",
        },
        "cross_layer_outcome_reconciliation": cross_layer_block or {
            "read_only": True,
            "status": "NO_AUDIT_YET",
        },
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
