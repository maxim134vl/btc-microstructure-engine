#!/usr/bin/env python3
"""Market context + paper trade visual refresher (visual-only).

Reads live/cognition/paper/controller sources and writes ONLY visual JSON under
apps/context_visualizer/public/data plus research status files.

Forbidden:
  - paper ledger writes
  - decision log writes
  - live refresh / shadow-chain rebuild
  - controller stop/restart
  - execution / exchange API / dashboard / model fit
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "live"))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

from btc_ml.visual.canonical_trade_view import (  # noqa: E402
    ECONOMICS_VERSION as CANONICAL_ECONOMICS_VERSION,
    LEGACY_TIMEFRAME,
    PRODUCTION_VIEW_PARQUET as CANONICAL_VISUAL_TRADE_VIEW,
    write_canonical_visual_trades,
)

from paper_trade_economics import (  # type: ignore  # noqa: E402
    ECONOMICS_SOURCE,
    ENTRY_FEE_BPS,
    EXIT_FEE_BPS,
    INITIAL_CAPITAL_USD,
    MAX_RISK_PER_TRADE_FRACTION,
    MAX_RISK_PER_TRADE_PCT,
    NORMAL_ENTRY_SLIPPAGE_BPS,
    NORMAL_EXIT_SLIPPAGE_BPS,
    POSITION_SIZING_MODE,
    STOP_FORCED_EXIT_SLIPPAGE_BPS,
    closed_trade_economics,
    execution_quality_status,
    resolve_risk_sizing,
)

PUBLIC_DATA = ROOT / "apps" / "context_visualizer" / "public" / "data"
PAPER_DIR = ROOT / "data" / "research" / "paper_simulator"
RESEARCH_DIR = ROOT / "data" / "research"

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
DECISION_LOG = ROOT / "data" / "live" / "context_decision_log.parquet"
FINAL_CONTEXT = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"

PID_PATH = ROOT / "runtime_context_visual_refresher.pid"
LOCK_PATH = ROOT / "runtime_context_visual_refresher.lock"
LOG_PATH = ROOT / "logs" / "context_visual_refresher.log"

CONTEXT_VISUAL_OUT = PUBLIC_DATA / "context_visual.json"
PAPER_OVERLAYS_OUT = PUBLIC_DATA / "paper_trade_overlays.json"
NORMALIZED_TRADE_RENDER_LAYER_JSON = PUBLIC_DATA / "normalized_trade_render_layer.json"
CLOSED_TRADE_REPORT_JSON = PUBLIC_DATA / "closed_trade_report.json"
OPEN_POSITIONS_OUT = PUBLIC_DATA / "open_positions.json"
CLOSED_TRADES_OUT = PUBLIC_DATA / "closed_trades.json"
CONTROLLER_CYCLES_OUT = PUBLIC_DATA / "controller_cycles.json"
VISUAL_STATUS_OUT = PUBLIC_DATA / "visual_status.json"
TRADE_RESULT_SUMMARY_OUT = PUBLIC_DATA / "trade_result_summary.json"
PNL_SUMMARY_OUT = PUBLIC_DATA / "pnl_summary.json"
RESTATED_TRADES_OUT = PUBLIC_DATA / "restated_paper_trades.json"
SUPERSEDED_TRADES_OUT = PUBLIC_DATA / "superseded_paper_trades.json"
TRADE_ENTRY_CONTEXT_CHECK = RESEARCH_DIR / "trade_entry_context_check.json"
TRADE_EXIT_CONTEXT_CHECK = RESEARCH_DIR / "trade_exit_context_check.json"
CANONICAL_VISUAL_TRADES_SOURCE = CANONICAL_VISUAL_TRADE_VIEW
POLICY_CONTEXT_SECONDARY_SOURCE = PAPER_DIR / "policy_context_canonical_bar_policy_trades.parquet"
OPEN_PAPER_POSITIONS_SOURCE = PAPER_DIR / "paper_positions.parquet"
NORMALIZED_TRADE_RENDER_LAYER_PARQUET = PAPER_DIR / "normalized_trade_render_layer.parquet"
NORMALIZED_TRADE_RENDER_LAYER_XLSX = RESEARCH_DIR / "normalized_trade_render_layer.xlsx"
CLOSED_TRADE_REPORT_PARQUET = PAPER_DIR / "closed_trade_report.parquet"
CLOSED_TRADE_REPORT_XLSX = RESEARCH_DIR / "closed_trade_report.xlsx"
TRADE_LAYER_RECONCILIATION_PARQUET = PAPER_DIR / "trade_layer_reconciliation.parquet"
TRADE_LAYER_RECONCILIATION_XLSX = RESEARCH_DIR / "trade_layer_reconciliation.xlsx"

DEFAULT_INTERVAL_SECONDS = 20
VISUAL_STALE_SECONDS = 90.0
SYNTHETIC_PRICES = {99950.0, 100000.0, 100050.0}
CANONICAL_RENDER_TRADE_SOURCE = "CANONICAL_VISUAL_CONTEXT_TRADE"
OPEN_RENDER_TRADE_SOURCE = "OPEN_CONTROLLER_POSITION"
DEFAULT_REPORT_DEPOSIT_USD = INITIAL_CAPITAL_USD
REPORT_MAX_RISK_PCT = MAX_RISK_PER_TRADE_PCT
REPORT_MAX_RISK_FRACTION = MAX_RISK_PER_TRADE_FRACTION
REPORT_ENTRY_FEE_RATE = ENTRY_FEE_BPS / 10000.0
REPORT_EXIT_FEE_RATE = EXIT_FEE_BPS / 10000.0
REPORT_ENTRY_SLIPPAGE_RATE = NORMAL_ENTRY_SLIPPAGE_BPS / 10000.0
REPORT_EXIT_SLIPPAGE_RATE = NORMAL_EXIT_SLIPPAGE_BPS / 10000.0
REPORT_STOP_EXIT_SLIPPAGE_RATE = STOP_FORCED_EXIT_SLIPPAGE_BPS / 10000.0
REPORT_SLIPPAGE_RATE = REPORT_EXIT_SLIPPAGE_RATE
REPORT_SIZING_METHOD = POSITION_SIZING_MODE
REPORT_ECONOMICS_SOURCE = ECONOMICS_SOURCE
SIZING_STATUS_OK = "OK"
SIZING_BLOCKED_MISSING_STOP = "SIZING_BLOCKED_MISSING_STOP"
SIZING_BLOCKED_INVALID_STOP = "SIZING_BLOCKED_INVALID_STOP"
REQUIRED_TRADE_RENDER_COLUMNS = [
    "trade_id",
    "trade_source",
    "context_id",
    "context_label",
    "open_ts",
    "close_ts",
    "status",
    "direction",
    "entry_price",
    "exit_price",
    "current_price",
    "stop_loss_price",
    "take_profit_price",
    "deposit_usd",
    "max_risk_pct_of_deposit",
    "max_risk_usd",
    "risk_amount_usd",
    "risk_distance_price",
    "stop_distance_usd",
    "risk_per_asset_at_stop",
    "expected_loss_at_stop_usd",
    "position_size_asset",
    "position_size_btc",
    "position_size_usd",
    "position_notional_usd",
    "entry_notional_usd",
    "exit_notional_usd",
    "entry_fee_rate_pct",
    "exit_fee_rate_pct",
    "slippage_rate_pct",
    "entry_fee_usd",
    "exit_fee_usd",
    "entry_slippage_usd",
    "exit_slippage_usd",
    "total_fees_usd",
    "fees_usd",
    "total_slippage_usd",
    "slippage_usd",
    "slippage_bps",
    "slippage_R",
    "total_costs_usd",
    "gross_price_pnl_usd",
    "gross_pnl_before_fees_slippage",
    "net_realized_pnl_usd",
    "net_pnl_after_fees_slippage",
    "r_multiple",
    "R",
    "entry_execution_source",
    "exit_execution_source",
    "execution_quality_status",
    "context_quality",
    "paper_entry_basis",
    "sizing_method",
    "sizing_status",
    "economics_source",
    "copied_canonical_economics",
    "fixed_notional_used",
]
TRADE_RENDER_EXTRA_COLUMNS = [
    "timeframe",
    "source_book",
    "source_trade_id",
    "manager_command_id",
    "position_id",
    "lineage_status",
    "activation_epoch",
    "economics_version",
    "context_episode_id",
    "open_time_unix",
    "close_time_unix",
    "visual_style",
    "dedupe_key",
    "stop_price",
    "take_price",
    "unrealized_pnl_usd",
    "canonical_position_notional_usd",
]
CLOSED_TRADE_REPORT_COLUMNS = [
    "trade_id",
    "date_time_open",
    "date_time_close",
    "context_label",
    "context_id",
    "direction",
    "position_size_asset",
    "position_size_usd",
    "entry_fee_rate_pct",
    "exit_fee_rate_pct",
    "entry_fee_usd",
    "exit_fee_usd",
    "slippage_rate_pct",
    "entry_slippage_usd",
    "exit_slippage_usd",
    "total_slippage_usd",
    "entry_price",
    "exit_price",
    "gross_price_pnl_usd",
    "net_realized_pnl_usd",
    "r_multiple",
    "stop_loss_price",
    "max_risk_usd",
    "expected_loss_at_stop_usd",
    "sizing_status",
]
RECONCILIATION_COLUMNS = [
    "issue_type",
    "severity",
    "source_table",
    "trade_id",
    "position_id",
    "order_id",
    "signal_id",
    "details",
    "used_for_rendering",
    "canonical_position_notional_usd",
    "report_position_size_usd",
    "stop_loss_price",
    "max_risk_usd",
    "expected_loss_at_stop_usd",
    "sizing_method",
    "sizing_status",
    "economics_source",
    "copied_canonical_economics",
    "fixed_notional_used",
]

FORBIDDEN_WRITE_GLOBS = (
    "data/live/context_decision_log.parquet",
    "data/live/live_market_feed.parquet",
    "data/research/paper_simulator/paper_*.parquet",
    "data/cognition/*.parquet",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        import pandas as pd

        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None


def _iso_ts(value: Any) -> str | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unix(value: Any) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return int(parsed.timestamp())


def _safe_float(value: Any) -> float | None:
    try:
        import math

        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    try:
        import pandas as pd

        if isinstance(value, float) and pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def _meta(row: Any) -> dict[str, Any]:
    raw = None
    if hasattr(row, "get"):
        raw = row.get("metadata_json")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _is_synthetic_price(*prices: Any) -> bool:
    for price in prices:
        f = _safe_float(price)
        if f is None:
            continue
        if f in SYNTHETIC_PRICES:
            return True
        # Legacy research synthetics cluster near 100k.
        if 99000.0 <= f <= 101000.0:
            return True
    return False


def log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_iso_now()} {message}"
    print(line, flush=True)
    if sys.stdout.isatty():
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_is_visual_refresher(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        import subprocess

        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
        return "run_market_context_visual_refresher.py" in out
    except Exception:
        return _pid_alive(pid)


def acquire_lock() -> bool:
    if LOCK_PATH.exists():
        try:
            existing = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            existing = 0
        if existing != os.getpid() and _pid_is_visual_refresher(existing):
            log_line(f"[lock] refresher already running pid={existing}")
            return False
        log_line(f"[lock] replacing stale lock pid={existing}")
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass
    LOCK_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True


def release_lock() -> None:
    for path in (LOCK_PATH, PID_PATH):
        try:
            if path.exists():
                existing = int(path.read_text(encoding="utf-8").strip() or "0")
                if existing == os.getpid():
                    path.unlink(missing_ok=True)
        except Exception:
            pass


def read_latest_ts(path: Path, *columns: str) -> str | None:
    if not path.exists():
        return None
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
        if frame.empty:
            return None
        for col in columns:
            if col in frame.columns:
                return _iso_ts(frame[col].iloc[-1])
        for col in ("timestamp", "ts", "time", "event_time", "candle_timestamp"):
            if col in frame.columns:
                return _iso_ts(frame[col].iloc[-1])
    except Exception:
        return None
    return None


def read_latest_close() -> float | None:
    if not LIVE_FEED.exists():
        return None
    try:
        import pandas as pd

        frame = pd.read_parquet(LIVE_FEED, columns=["close"])
        if frame.empty:
            return None
        return _safe_float(frame["close"].iloc[-1])
    except Exception:
        try:
            import pandas as pd

            frame = pd.read_parquet(LIVE_FEED)
            if "close" in frame.columns and len(frame):
                return _safe_float(frame["close"].iloc[-1])
        except Exception:
            return None
    return None


def run_lifecycle_visual_generate() -> dict[str, Any]:
    """Rebuild lifecycle_* visual JSON only (no cognition rebuild, no ledger writes)."""
    import generate_lifecycle_context_data as gen

    code = int(gen.main())
    if code != 0:
        raise RuntimeError(f"generate_lifecycle_context_data exit={code}")
    # Policy/research episode export is diagnostics-only. Never overwrite the
    # decision-driving lifecycle episode bands used as Active trading context.
    canon = ROOT / "data" / "research" / "paper_simulator" / "canonical_policy_context_episodes.json"
    trades = ROOT / "data" / "research" / "paper_simulator" / "policy_context_trades.json"
    if canon.exists() and trades.exists():
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "research"))
            import export_policy_context_visual_data as export_mod  # type: ignore

            # Keep a separate shadow/diagnostics artifact if exporter supports it;
            # do not replace lifecycle_context_episodes.json primary path.
            if hasattr(export_mod, "export_visual_shadow_only"):
                export_mod.export_visual_shadow_only()
            else:
                shadow_out = PUBLIC_DATA / "shadow_policy_context_episodes.json"
                payload = json.loads(canon.read_text(encoding="utf-8"))
                write_json(
                    shadow_out,
                    {
                        "label": "Shadow diagnostics",
                        "is_active_trading_context": False,
                        "source": str(canon.relative_to(ROOT)),
                        "episodes": payload if isinstance(payload, list) else payload.get("episodes") or payload,
                    },
                )
        except Exception:
            pass
    latest = {}
    latest_path = PUBLIC_DATA / "lifecycle_latest.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    return {"ok": True, "latest": latest}


def load_parquet(path: Path) -> Any:
    import pandas as pd

    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def _safe_round(value: Any, digits: int = 6) -> float | None:
    f = _safe_float(value)
    return None if f is None else round(f, digits)


def _implied_rate_pct(amount: Any, notional: Any) -> float | None:
    amount_f = _safe_float(amount)
    notional_f = _safe_float(notional)
    if amount_f is None or notional_f is None or notional_f == 0:
        return None
    return round(amount_f / abs(notional_f) * 100.0, 8)


def _row_ids(row: Any, *columns: str) -> set[str]:
    out: set[str] = set()
    for col in columns:
        if col not in getattr(row, "index", []):
            continue
        value = _safe_text(row.get(col))
        if value:
            out.add(value)
    return out


def _frame_ids(frame: Any, *columns: str) -> set[str]:
    out: set[str] = set()
    if frame is None or not len(frame):
        return out
    for _, row in frame.iterrows():
        out.update(_row_ids(row, *columns))
    return out


def _normalized_context_label(context_id: Any) -> str | None:
    ctx = _context_number(context_id)
    return f"CTX {ctx}" if ctx is not None else None


def _render_context_label(context_id: Any, fallback_id: Any = None) -> str | None:
    label = _normalized_context_label(context_id)
    if label:
        return label
    fallback = _safe_text(fallback_id)
    if fallback:
        return f"CTRL {fallback[-8:]}"
    return None


def _configured_paper_deposit_usd() -> float:
    try:
        if PNL_SUMMARY_OUT.exists():
            payload = json.loads(PNL_SUMMARY_OUT.read_text(encoding="utf-8"))
            candidates = [
                (payload.get("detailed_pnl") or {}).get("initial_capital_usd"),
                (payload.get("detailed_pnl") or {}).get("initial_capital"),
                payload.get("initial_capital"),
            ]
            for candidate in candidates:
                value = _safe_float(candidate)
                if value is not None and value > 0:
                    return value
    except Exception:
        pass
    return DEFAULT_REPORT_DEPOSIT_USD


def _closed_trade_risk_economics(
    *,
    direction: str,
    entry_price: float | None,
    exit_price: float | None,
    stop_loss_price: float | None,
    take_profit_price: float | None = None,
    exit_reason: Any = None,
    entry_execution_source: Any = None,
    exit_execution_source: Any = None,
    context_quality: Any = None,
    paper_entry_basis: Any = None,
) -> dict[str, Any]:
    deposit_usd = _configured_paper_deposit_usd()
    max_risk_usd = deposit_usd * REPORT_MAX_RISK_FRACTION
    base: dict[str, Any] = {
        "deposit_usd": _safe_round(deposit_usd),
        "max_risk_pct_of_deposit": _safe_round(REPORT_MAX_RISK_PCT, 8),
        "max_risk_usd": _safe_round(max_risk_usd),
        "risk_amount_usd": _safe_round(max_risk_usd),
        "risk_distance_price": None,
        "stop_distance_usd": None,
        "risk_per_asset_at_stop": None,
        "expected_loss_at_stop_usd": None,
        "position_size_asset": None,
        "position_size_btc": None,
        "position_size_usd": None,
        "position_notional_usd": None,
        "entry_notional_usd": None,
        "exit_notional_usd": None,
        "entry_fee_rate_pct": _safe_round(REPORT_ENTRY_FEE_RATE * 100.0, 8),
        "exit_fee_rate_pct": _safe_round(REPORT_EXIT_FEE_RATE * 100.0, 8),
        "slippage_rate_pct": _safe_round(REPORT_EXIT_SLIPPAGE_RATE * 100.0, 8),
        "entry_fee_usd": None,
        "exit_fee_usd": None,
        "entry_slippage_usd": None,
        "exit_slippage_usd": None,
        "total_fees_usd": None,
        "fees_usd": None,
        "total_slippage_usd": None,
        "slippage_usd": None,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS + NORMAL_EXIT_SLIPPAGE_BPS,
        "slippage_R": None,
        "total_costs_usd": None,
        "gross_price_pnl_usd": None,
        "gross_pnl_before_fees_slippage": None,
        "net_realized_pnl_usd": None,
        "net_pnl_after_fees_slippage": None,
        "r_multiple": None,
        "R": None,
        "sizing_method": REPORT_SIZING_METHOD,
        "sizing_status": SIZING_STATUS_OK,
        "economics_source": REPORT_ECONOMICS_SOURCE,
        "copied_canonical_economics": False,
        "fixed_notional_used": False,
        "entry_execution_source": entry_execution_source,
        "exit_execution_source": exit_execution_source,
        "execution_quality_status": execution_quality_status(execution_source=exit_execution_source, exit_reason=exit_reason),
        "context_quality": context_quality,
        "paper_entry_basis": paper_entry_basis,
    }

    if stop_loss_price is None:
        base["sizing_status"] = SIZING_BLOCKED_MISSING_STOP
        return base
    if entry_price is None or entry_price <= 0:
        base["sizing_status"] = SIZING_BLOCKED_INVALID_STOP
        return base

    sizing = resolve_risk_sizing(
        side=direction,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
    )
    base["risk_distance_price"] = _safe_round(sizing.stop_distance, 8)
    base["stop_distance_usd"] = _safe_round(sizing.stop_distance, 8)
    base["risk_per_asset_at_stop"] = _safe_round(sizing.effective_loss_per_unit_at_stop, 8)
    base["expected_loss_at_stop_usd"] = _safe_round(sizing.estimated_loss_at_stop_usd)
    if not sizing.allowed:
        base["sizing_status"] = SIZING_BLOCKED_INVALID_STOP
        return base

    qty = float(sizing.position_size_btc or 0.0)
    economics = closed_trade_economics(
        side=direction,
        entry_price=entry_price,
        exit_price=exit_price if exit_price is not None else entry_price,
        position_size_btc=qty,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        risk_amount_usd=max_risk_usd,
        exit_reason=exit_reason,
        exit_execution_source=exit_execution_source,
    )
    base.update(
        {
            "position_size_asset": _safe_round(qty, 10),
            "position_size_btc": _safe_round(qty, 10),
            "position_size_usd": _safe_round(economics["position_notional_usd"]),
            "position_notional_usd": _safe_round(economics["position_notional_usd"]),
            "entry_notional_usd": _safe_round(economics["entry_notional_usd"]),
            "exit_notional_usd": _safe_round(economics["exit_notional_usd"]) if exit_price is not None else None,
            "entry_fee_usd": _safe_round(economics["entry_fee_usd"]),
            "exit_fee_usd": _safe_round(economics["exit_fee_usd"]) if exit_price is not None else None,
            "entry_slippage_usd": _safe_round(economics["entry_slippage_usd"]),
            "exit_slippage_usd": _safe_round(economics["exit_slippage_usd"]) if exit_price is not None else None,
            "total_fees_usd": _safe_round(economics["fees_usd"]) if exit_price is not None else None,
            "fees_usd": _safe_round(economics["fees_usd"]) if exit_price is not None else None,
            "total_slippage_usd": _safe_round(economics["slippage_usd"]) if exit_price is not None else None,
            "slippage_usd": _safe_round(economics["slippage_usd"]) if exit_price is not None else None,
            "slippage_bps": _safe_round(economics["slippage_bps"], 8),
            "slippage_R": _safe_round(economics["slippage_R"], 8) if exit_price is not None else None,
            "total_costs_usd": _safe_round(economics["fees_usd"] + economics["slippage_usd"]) if exit_price is not None else None,
            "gross_price_pnl_usd": _safe_round(economics["gross_pnl_before_fees_slippage"]) if exit_price is not None else None,
            "gross_pnl_before_fees_slippage": _safe_round(economics["gross_pnl_before_fees_slippage"]) if exit_price is not None else None,
            "net_realized_pnl_usd": _safe_round(economics["net_pnl_after_fees_slippage"]) if exit_price is not None else None,
            "net_pnl_after_fees_slippage": _safe_round(economics["net_pnl_after_fees_slippage"]) if exit_price is not None else None,
            "r_multiple": _safe_round(economics["R"], 8) if exit_price is not None else None,
            "R": _safe_round(economics["R"], 8) if exit_price is not None else None,
            "execution_quality_status": economics["execution_quality_status"],
        }
    )
    return base



def _split_cost_legs(total: float | None, entry_leg: float | None, exit_leg: float | None) -> tuple[float | None, float | None]:
    """Scale derived per-leg costs so they sum exactly to the settled total."""
    if total is None:
        return None, None
    if entry_leg is None or exit_leg is None:
        half = total / 2.0
        return half, total - half
    derived = entry_leg + exit_leg
    if derived <= 0:
        half = total / 2.0
        return half, total - half
    scale = total / derived
    scaled_entry = entry_leg * scale
    return scaled_entry, total - scaled_entry


def _apply_ledger_economics(economics: dict[str, Any], row: Any) -> dict[str, Any]:
    """Overlay settled ledger economics onto the derived render economics.

    Patch 4.3 §10: the visual displays what the canonical book recorded and
    never substitutes its own P&L. Rows without settled economics keep the
    derived values.
    """
    gross = _safe_float(row.get("gross_pnl_usd"))
    net = _safe_float(row.get("net_pnl_usd"))
    if gross is None or net is None:
        return economics

    quantity = _safe_float(row.get("quantity"))
    fees = _safe_float(row.get("fees_usd"))
    slippage = _safe_float(row.get("slippage_usd"))
    entry_price = _safe_float(row.get("entry_price"))
    exit_price = _safe_float(row.get("exit_price"))
    notional = _safe_float(row.get("notional_usd") or row.get("position_notional_usd"))
    if notional is None and quantity is not None and entry_price is not None:
        notional = quantity * entry_price

    entry_fee, exit_fee = _split_cost_legs(
        fees,
        quantity * entry_price * REPORT_ENTRY_FEE_RATE if None not in (quantity, entry_price) else None,
        quantity * exit_price * REPORT_EXIT_FEE_RATE if None not in (quantity, exit_price) else None,
    )
    entry_slip, exit_slip = _split_cost_legs(
        slippage,
        quantity * entry_price * REPORT_ENTRY_SLIPPAGE_RATE if None not in (quantity, entry_price) else None,
        quantity * exit_price * REPORT_EXIT_SLIPPAGE_RATE if None not in (quantity, exit_price) else None,
    )
    costs = None if fees is None or slippage is None else fees + slippage
    max_risk = _safe_float(economics.get("max_risk_usd"))
    r_multiple = _safe_float(row.get("r_multiple"))
    if r_multiple is None and max_risk:
        r_multiple = net / max_risk

    updated = dict(economics)
    updated.update(
        {
            "position_size_asset": _safe_round(quantity, 8),
            "position_size_btc": _safe_round(quantity, 8),
            "position_size_usd": _safe_round(notional),
            "position_notional_usd": _safe_round(notional),
            "entry_notional_usd": _safe_round(
                quantity * entry_price if None not in (quantity, entry_price) else notional
            ),
            "exit_notional_usd": _safe_round(
                quantity * exit_price if None not in (quantity, exit_price) else notional
            ),
            "entry_fee_usd": _safe_round(entry_fee),
            "exit_fee_usd": _safe_round(exit_fee),
            "entry_slippage_usd": _safe_round(entry_slip),
            "exit_slippage_usd": _safe_round(exit_slip),
            "total_fees_usd": _safe_round(fees),
            "fees_usd": _safe_round(fees),
            "total_slippage_usd": _safe_round(slippage),
            "slippage_usd": _safe_round(slippage),
            "total_costs_usd": _safe_round(costs),
            "gross_price_pnl_usd": _safe_round(gross),
            "gross_pnl_before_fees_slippage": _safe_round(gross),
            "net_realized_pnl_usd": _safe_round(net),
            "net_pnl_after_fees_slippage": _safe_round(net),
            "r_multiple": _safe_round(r_multiple, 6),
            "R": _safe_round(r_multiple, 6),
            "economics_source": CANONICAL_ECONOMICS_VERSION.lower(),
            "copied_canonical_economics": True,
            "sizing_status": SIZING_STATUS_OK,
        }
    )
    return updated


def _render_closed_canonical_row(row: Any) -> dict[str, Any]:
    trade_id = _safe_text(row.get("trade_id"))
    context_id = _safe_text(row.get("context_id"))
    open_ts = _iso_ts(row.get("entry_ts"))
    close_ts = _iso_ts(row.get("exit_ts"))
    direction = (_safe_text(row.get("side"), "LONG") or "LONG").upper()
    entry_price = _safe_float(row.get("entry_price"))
    exit_price = _safe_float(row.get("exit_price"))
    stop_loss_price = _safe_float(row.get("stop_loss_price"))
    take_profit_price = _safe_float(row.get("take_profit_price"))
    canonical_position_notional = _safe_float(row.get("position_notional_usd") or row.get("notional_usd"))
    context_episode_id = _context_number(row.get("context_episode_id") or row.get("lifecycle_episode_id") or context_id)
    economics = _closed_trade_risk_economics(
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        entry_execution_source=row.get("entry_execution_source") or row.get("entry_price_source"),
        exit_execution_source=row.get("exit_execution_source") or row.get("exit_price_source"),
        context_quality=row.get("context_quality") or row.get("context_quality_label"),
        paper_entry_basis=row.get("paper_entry_basis") or "CANONICAL_CONTEXT_BAR_POLICY",
    )
    economics = _apply_ledger_economics(economics, row)
    return {
        "trade_id": trade_id,
        "trade_source": CANONICAL_RENDER_TRADE_SOURCE,
        "context_id": context_id,
        "context_label": _normalized_context_label(context_id),
        "open_ts": open_ts,
        "close_ts": close_ts,
        "status": "CLOSED",
        "direction": direction,
        "entry_price": _safe_round(entry_price, 8),
        "exit_price": _safe_round(exit_price, 8),
        "current_price": None,
        "stop_loss_price": _safe_round(stop_loss_price, 8),
        "take_profit_price": _safe_round(take_profit_price, 8),
        **economics,
        "context_episode_id": context_episode_id,
        "open_time_unix": _unix(open_ts),
        "close_time_unix": _unix(close_ts),
        "visual_style": "normal_trade_style",
        "dedupe_key": f"trade_id:{trade_id}" if trade_id else None,
        "stop_price": _safe_round(stop_loss_price, 8),
        "take_price": _safe_round(take_profit_price, 8),
        "unrealized_pnl_usd": None,
        "canonical_position_notional_usd": _safe_round(canonical_position_notional),
        "timeframe": _safe_text(row.get("timeframe")) or LEGACY_TIMEFRAME,
        "source_book": _safe_text(row.get("source_book")),
        "source_trade_id": _safe_text(row.get("source_trade_id")),
        "manager_command_id": _safe_text(row.get("manager_command_id")),
        "position_id": _safe_text(row.get("position_id")),
        "lineage_status": _safe_text(row.get("lineage_status")),
        "activation_epoch": _safe_text(row.get("activation_epoch")),
        "economics_version": CANONICAL_ECONOMICS_VERSION,
    }


def _unrealized_open_pnl(direction: Any, entry_price: Any, current_price: Any, quantity: Any) -> float | None:
    side = str(direction or "").upper()
    entry = _safe_float(entry_price)
    current = _safe_float(current_price)
    qty = _safe_float(quantity)
    if entry is None or current is None or qty is None:
        return None
    if side == "SHORT":
        return round((entry - current) * qty, 6)
    return round((current - entry) * qty, 6)


def _render_open_position_row(row: Any, mark_price: float | None) -> dict[str, Any] | None:
    position_id = _safe_text(row.get("position_id"))
    if not position_id or "ONE_SHOT" in position_id:
        return None
    status = _safe_text(row.get("status"), "") or ""
    if status.upper() != "OPEN":
        return None
    metadata = _meta(row)
    trade_id = position_id or _safe_text(metadata.get("parent_trade_id"))
    context_id = _safe_text(metadata.get("context_id") or metadata.get("context_episode_id") or metadata.get("lifecycle_episode_id"))
    direction = (_safe_text(row.get("direction") or metadata.get("side"), "LONG") or "LONG").upper()
    open_ts = _iso_ts(row.get("opened_at") or metadata.get("opened_at") or metadata.get("source_context_ts"))
    entry_price = _safe_float(row.get("entry_price"))
    quantity = _safe_float(row.get("quantity") or metadata.get("quantity_btc"))
    notional = _safe_float(row.get("notional") or metadata.get("notional_usd"))
    stop_loss_price = _safe_float(metadata.get("stop_loss_price"))
    take_profit_price = _safe_float(metadata.get("take_profit_price"))
    deposit_usd = _configured_paper_deposit_usd()
    max_risk_usd = deposit_usd * REPORT_MAX_RISK_FRACTION
    risk_distance = None
    risk_per_asset = None
    expected_loss = None
    sizing_status = SIZING_BLOCKED_MISSING_STOP if stop_loss_price is None else SIZING_STATUS_OK
    if entry_price is not None and stop_loss_price is not None:
        risk_distance = entry_price - stop_loss_price if direction == "LONG" else stop_loss_price - entry_price
        if risk_distance <= 0:
            sizing_status = SIZING_BLOCKED_INVALID_STOP
        else:
            risk_per_asset = risk_distance + entry_price * (REPORT_ENTRY_FEE_RATE + REPORT_ENTRY_SLIPPAGE_RATE) + stop_loss_price * (REPORT_EXIT_FEE_RATE + REPORT_STOP_EXIT_SLIPPAGE_RATE)
            expected_loss = quantity * risk_per_asset if quantity is not None else None
    return {
        "trade_id": trade_id,
        "trade_source": OPEN_RENDER_TRADE_SOURCE,
        "context_id": context_id,
        "context_label": _render_context_label(context_id, trade_id),
        "open_ts": open_ts,
        "close_ts": None,
        "status": "OPEN",
        "direction": direction,
        "entry_price": _safe_round(entry_price, 8),
        "exit_price": None,
        "current_price": _safe_round(mark_price, 8),
        "stop_loss_price": _safe_round(stop_loss_price, 8),
        "take_profit_price": _safe_round(take_profit_price, 8),
        "deposit_usd": _safe_round(deposit_usd),
        "max_risk_pct_of_deposit": _safe_round(REPORT_MAX_RISK_PCT, 8),
        "max_risk_usd": _safe_round(max_risk_usd),
        "risk_amount_usd": _safe_round(max_risk_usd),
        "risk_distance_price": _safe_round(risk_distance, 8),
        "stop_distance_usd": _safe_round(risk_distance, 8),
        "risk_per_asset_at_stop": _safe_round(risk_per_asset, 8),
        "expected_loss_at_stop_usd": _safe_round(expected_loss),
        "position_size_asset": _safe_round(quantity, 10),
        "position_size_btc": _safe_round(quantity, 10),
        "position_size_usd": _safe_round(notional),
        "position_notional_usd": _safe_round(notional),
        "entry_notional_usd": _safe_round(notional),
        "exit_notional_usd": None,
        "entry_fee_rate_pct": _safe_round(REPORT_ENTRY_FEE_RATE * 100.0, 8),
        "exit_fee_rate_pct": _safe_round(REPORT_EXIT_FEE_RATE * 100.0, 8),
        "slippage_rate_pct": _safe_round(REPORT_EXIT_SLIPPAGE_RATE * 100.0, 8),
        "entry_fee_usd": None,
        "exit_fee_usd": None,
        "entry_slippage_usd": None,
        "exit_slippage_usd": None,
        "total_fees_usd": None,
        "fees_usd": None,
        "total_slippage_usd": None,
        "slippage_usd": None,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS + NORMAL_EXIT_SLIPPAGE_BPS,
        "slippage_R": None,
        "total_costs_usd": None,
        "gross_price_pnl_usd": None,
        "gross_pnl_before_fees_slippage": None,
        "net_realized_pnl_usd": None,
        "net_pnl_after_fees_slippage": None,
        "r_multiple": None,
        "R": None,
        "entry_execution_source": metadata.get("entry_execution_source") or metadata.get("entry_price_source"),
        "exit_execution_source": None,
        "execution_quality_status": execution_quality_status(execution_source=metadata.get("entry_execution_source")),
        "context_quality": metadata.get("context_quality"),
        "paper_entry_basis": metadata.get("paper_entry_basis"),
        "sizing_method": REPORT_SIZING_METHOD,
        "sizing_status": sizing_status,
        "economics_source": REPORT_ECONOMICS_SOURCE,
        "copied_canonical_economics": False,
        "fixed_notional_used": False,
        "context_episode_id": _context_number(context_id),
        "open_time_unix": _unix(open_ts),
        "close_time_unix": None,
        "visual_style": "normal_trade_style",
        "dedupe_key": f"trade_id:{trade_id}" if trade_id else None,
        "stop_price": _safe_round(stop_loss_price, 8),
        "take_price": _safe_round(take_profit_price, 8),
        "unrealized_pnl_usd": _unrealized_open_pnl(direction, entry_price, mark_price, quantity),
        "canonical_position_notional_usd": None,
    }


def build_normalized_trade_render_layer(generated_at: str, mark_price: float | None) -> dict[str, Any]:
    import pandas as pd

    # Rebuild the canonical union (archived legacy closed book + timeframe
    # trader tail) so the chart always reflects the settled books, then render
    # from it. The policy-context layer stays available as a research overlay.
    view_meta = write_canonical_visual_trades()
    closed_source = load_parquet(CANONICAL_VISUAL_TRADES_SOURCE)
    open_source = load_parquet(OPEN_PAPER_POSITIONS_SOURCE)
    rows: list[dict[str, Any]] = []
    closed_count = 0
    open_count = 0
    if len(closed_source):
        for _, row in closed_source.iterrows():
            normalized = _render_closed_canonical_row(row)
            if normalized.get("trade_id"):
                rows.append(normalized)
                closed_count += 1
    if len(open_source) and "status" in open_source.columns:
        open_rows = open_source[open_source["status"].astype(str).str.upper() == "OPEN"]
        for _, row in open_rows.iterrows():
            normalized = _render_open_position_row(row, mark_price)
            if normalized and normalized.get("trade_id"):
                rows.append(normalized)
                open_count += 1
    columns = [*REQUIRED_TRADE_RENDER_COLUMNS, *TRADE_RENDER_EXTRA_COLUMNS]
    frame = pd.DataFrame(rows, columns=columns)
    NORMALIZED_TRADE_RENDER_LAYER_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(NORMALIZED_TRADE_RENDER_LAYER_PARQUET, index=False)
    NORMALIZED_TRADE_RENDER_LAYER_XLSX.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(NORMALIZED_TRADE_RENDER_LAYER_XLSX, index=False)
    trade_ids = [str(row.get("trade_id")) for row in rows if row.get("trade_id")]
    duplicate_ids = sorted({tid for tid in trade_ids if trade_ids.count(tid) > 1})
    missing_required = [
        str(row.get("trade_id"))
        for row in rows
        if not row.get("open_ts") or not row.get("status") or not row.get("direction") or row.get("entry_price") is None
        or (str(row.get("status") or "").upper() == "CLOSED" and (not row.get("close_ts") or row.get("exit_price") is None))
    ]
    payload = {
        "generated_at_utc": generated_at,
        "source_closed": _rel(CANONICAL_VISUAL_TRADES_SOURCE),
        "source_open": _rel(OPEN_PAPER_POSITIONS_SOURCE),
        "secondary_research_layer": _rel(POLICY_CONTEXT_SECONDARY_SOURCE),
        "economics_version": CANONICAL_ECONOMICS_VERSION,
        "canonical_view": view_meta,
        "json_path": _rel(NORMALIZED_TRADE_RENDER_LAYER_JSON),
        "parquet_path": _rel(NORMALIZED_TRADE_RENDER_LAYER_PARQUET),
        "xlsx_path": _rel(NORMALIZED_TRADE_RENDER_LAYER_XLSX),
        "renderer_source": True,
        "trade_identity": "trade_id",
        "context_id_role": "label_only",
        "closed_trade_count": closed_count,
        "open_trade_count": open_count,
        "total_render_trade_count": int(len(rows)),
        "source_closed_trade_count": int(len(closed_source)),
        "source_open_trade_count": int((open_source["status"].astype(str).str.upper() == "OPEN").sum()) if len(open_source) and "status" in open_source.columns else 0,
        "one_row_per_trade": len(rows) == len(set(trade_ids)),
        "required_columns": list(REQUIRED_TRADE_RENDER_COLUMNS),
        "trades": rows,
        "validation": {
            "duplicate_trade_ids": duplicate_ids,
            "missing_required_render_fields": missing_required,
            "render_layer_count_matches_sources": int(len(rows)) == closed_count + open_count,
            "controller_ledger_used_for_render": True,
            "one_shot_rows_excluded_from_render": all("ONE_SHOT" not in tid for tid in trade_ids),
        },
    }
    write_json(NORMALIZED_TRADE_RENDER_LAYER_JSON, payload)
    return payload


def build_closed_trade_report(render_layer: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    closed_rows = []
    for row in render_layer.get("trades") or []:
        if not isinstance(row, dict) or str(row.get("status") or "").upper() != "CLOSED":
            continue
        closed_rows.append(
            {
                "trade_id": row.get("trade_id"),
                "date_time_open": row.get("open_ts"),
                "date_time_close": row.get("close_ts"),
                "context_label": row.get("context_label"),
                "context_id": row.get("context_id"),
                "direction": row.get("direction"),
                "position_size_asset": row.get("position_size_asset"),
                "position_size_usd": row.get("position_size_usd"),
                "entry_fee_rate_pct": row.get("entry_fee_rate_pct"),
                "exit_fee_rate_pct": row.get("exit_fee_rate_pct"),
                "entry_fee_usd": row.get("entry_fee_usd"),
                "exit_fee_usd": row.get("exit_fee_usd"),
                "slippage_rate_pct": row.get("slippage_rate_pct"),
                "entry_slippage_usd": row.get("entry_slippage_usd"),
                "exit_slippage_usd": row.get("exit_slippage_usd"),
                "total_slippage_usd": row.get("total_slippage_usd"),
                "entry_price": row.get("entry_price"),
                "exit_price": row.get("exit_price"),
                "gross_price_pnl_usd": row.get("gross_price_pnl_usd"),
                "net_realized_pnl_usd": row.get("net_realized_pnl_usd"),
                "r_multiple": row.get("r_multiple"),
                "stop_loss_price": row.get("stop_loss_price"),
                "max_risk_usd": row.get("max_risk_usd"),
                "expected_loss_at_stop_usd": row.get("expected_loss_at_stop_usd"),
                "sizing_status": row.get("sizing_status"),
            }
        )
    frame = pd.DataFrame(closed_rows, columns=CLOSED_TRADE_REPORT_COLUMNS)
    CLOSED_TRADE_REPORT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(CLOSED_TRADE_REPORT_PARQUET, index=False)
    CLOSED_TRADE_REPORT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(CLOSED_TRADE_REPORT_XLSX, index=False)
    trade_ids = [str(row.get("trade_id")) for row in closed_rows if row.get("trade_id")]
    payload = {
        "generated_at_utc": render_layer.get("generated_at_utc"),
        "source": "normalized_trade_render_layer.status=CLOSED",
        "json_path": _rel(CLOSED_TRADE_REPORT_JSON),
        "parquet_path": _rel(CLOSED_TRADE_REPORT_PARQUET),
        "xlsx_path": _rel(CLOSED_TRADE_REPORT_XLSX),
        "closed_report_trade_count": int(len(closed_rows)),
        "open_trades_excluded": True,
        "required_columns": list(CLOSED_TRADE_REPORT_COLUMNS),
        "required_columns_present": all(column in frame.columns for column in CLOSED_TRADE_REPORT_COLUMNS),
        "one_row_per_closed_trade": len(trade_ids) == len(set(trade_ids)),
        "trades": closed_rows,
    }
    write_json(CLOSED_TRADE_REPORT_JSON, payload)
    return payload


def _shape_from_normalized_trade(row: dict[str, Any]) -> dict[str, Any]:
    trade_id = row.get("trade_id")
    status = str(row.get("status") or "CLOSED").upper()
    pnl_value = (
        row.get("net_pnl_after_fees_slippage")
        if status == "CLOSED" and row.get("net_pnl_after_fees_slippage") is not None
        else row.get("net_realized_pnl_usd")
        if status == "CLOSED"
        else row.get("unrealized_pnl_usd")
    )
    stop_loss = row.get("stop_loss_price") if row.get("stop_loss_price") is not None else row.get("stop_price")
    take_profit = row.get("take_profit_price") if row.get("take_profit_price") is not None else row.get("take_price")
    shape = {
        "trade_id": trade_id,
        "entry_trade_id": trade_id,
        "exit_trade_id": trade_id,
        "trade_source": row.get("trade_source"),
        "visual_source": "normalized_trade_render_layer",
        "source": row.get("trade_source"),
        "timeframe": row.get("timeframe") or LEGACY_TIMEFRAME,
        "source_book": row.get("source_book"),
        "source_trade_id": row.get("source_trade_id"),
        "manager_command_id": row.get("manager_command_id"),
        "position_id": row.get("position_id"),
        "lineage_status": row.get("lineage_status"),
        "activation_epoch": row.get("activation_epoch"),
        "economics_version": row.get("economics_version") or CANONICAL_ECONOMICS_VERSION,
        "context_id": row.get("context_id"),
        "context_label": row.get("context_label"),
        "context_episode_id": row.get("context_episode_id"),
        "entry_ts": row.get("open_ts"),
        "exit_ts": row.get("close_ts"),
        "entry_action_ts": row.get("open_ts"),
        "exit_action_ts": row.get("close_ts"),
        "entry_time_unix": row.get("open_time_unix"),
        "exit_time_unix": row.get("close_time_unix"),
        "side": row.get("direction"),
        "direction": row.get("direction"),
        "position_size_btc": row.get("position_size_btc") if row.get("position_size_btc") is not None else row.get("position_size_asset"),
        "position_notional_usd": row.get("position_notional_usd") if row.get("position_notional_usd") is not None else row.get("position_size_usd"),
        "entry_price": row.get("entry_price"),
        "exit_price": row.get("exit_price"),
        "current_price": row.get("current_price"),
        "gross_price_pnl_usd": row.get("gross_price_pnl_usd") if row.get("gross_price_pnl_usd") is not None else row.get("gross_pnl_before_fees_slippage"),
        "gross_pnl_usd": row.get("gross_pnl_before_fees_slippage") if row.get("gross_pnl_before_fees_slippage") is not None else row.get("gross_price_pnl_usd"),
        "gross_pnl_before_fees_slippage": row.get("gross_pnl_before_fees_slippage") if row.get("gross_pnl_before_fees_slippage") is not None else row.get("gross_price_pnl_usd"),
        "net_realized_pnl_usd": row.get("net_realized_pnl_usd") if row.get("net_realized_pnl_usd") is not None else row.get("net_pnl_after_fees_slippage"),
        "net_pnl_usd": row.get("net_pnl_after_fees_slippage") if row.get("net_pnl_after_fees_slippage") is not None else row.get("net_realized_pnl_usd"),
        "net_pnl_after_fees_slippage": row.get("net_pnl_after_fees_slippage") if row.get("net_pnl_after_fees_slippage") is not None else row.get("net_realized_pnl_usd"),
        "unrealized_pnl_usd": row.get("unrealized_pnl_usd"),
        "pnl": pnl_value,
        "entry_fee_usd": row.get("entry_fee_usd"),
        "exit_fee_usd": row.get("exit_fee_usd"),
        "entry_slippage_usd": row.get("entry_slippage_usd"),
        "exit_slippage_usd": row.get("exit_slippage_usd"),
        "slippage_usd": row.get("slippage_usd") if row.get("slippage_usd") is not None else row.get("total_slippage_usd"),
        "fees_usd": row.get("fees_usd") if row.get("fees_usd") is not None else row.get("total_fees_usd"),
        "risk_amount_usd": row.get("risk_amount_usd") if row.get("risk_amount_usd") is not None else row.get("max_risk_usd"),
        "stop_distance_usd": row.get("stop_distance_usd") if row.get("stop_distance_usd") is not None else row.get("risk_distance_price"),
        "slippage_bps": row.get("slippage_bps"),
        "slippage_R": row.get("slippage_R"),
        "entry_execution_source": row.get("entry_execution_source"),
        "exit_execution_source": row.get("exit_execution_source"),
        "execution_quality_status": row.get("execution_quality_status"),
        "context_quality": row.get("context_quality"),
        "paper_entry_basis": row.get("paper_entry_basis"),
        "stop_price": stop_loss,
        "take_price": take_profit,
        "stop_loss_price": stop_loss,
        "take_profit_price": take_profit,
        "r_multiple": row.get("r_multiple") if row.get("r_multiple") is not None else row.get("R"),
        "R": row.get("R") if row.get("R") is not None else row.get("r_multiple"),
        "sizing_status": row.get("sizing_status"),
        "sizing_method": row.get("sizing_method"),
        "status": row.get("status") or "CLOSED",
        "visual_style": "normal_trade_style",
        "uniform_style": True,
        "dedupe_key": row.get("dedupe_key") or (f"trade_id:{trade_id}" if trade_id else None),
        "inspector": dict(row),
    }
    shape["stop_take_lines"] = []
    if stop_loss is not None:
        shape["stop_take_lines"].append({"kind": "STOP_LOSS", "price": stop_loss, "visible": True, "trade_id": trade_id})
    if take_profit is not None:
        shape["stop_take_lines"].append({"kind": "TAKE_PROFIT", "price": take_profit, "visible": True, "trade_id": trade_id})
    return shape


def build_overlays_from_trade_render_layer(layer: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in layer.get("trades") or [] if isinstance(row, dict)]
    shapes = [_shape_from_normalized_trade(row) for row in rows]
    closed = [shape for shape in shapes if str(shape.get("status") or "").upper() == "CLOSED"]
    open_positions = [shape for shape in shapes if str(shape.get("status") or "").upper() == "OPEN"]
    entries = [
        {
            "trade_id": shape.get("trade_id"),
            "marker_type": "ENTRY",
            "ts": shape.get("entry_ts"),
            "time_unix": shape.get("entry_time_unix"),
            "price": shape.get("entry_price"),
            "side": shape.get("side"),
            "context_label": shape.get("context_label"),
            "source": shape.get("trade_source"),
        }
        for shape in shapes
        if shape.get("entry_ts")
    ]
    exits = [
        {
            "trade_id": shape.get("trade_id"),
            "marker_type": "EXIT",
            "ts": shape.get("exit_ts"),
            "time_unix": shape.get("exit_time_unix"),
            "price": shape.get("exit_price"),
            "side": shape.get("side"),
            "context_label": shape.get("context_label"),
            "source": shape.get("trade_source"),
        }
        for shape in shapes
        if shape.get("exit_ts")
    ]
    last = shapes[-1] if shapes else {}
    counts = {
        "entry_markers": len(entries),
        "exit_markers": len(exits),
        "closed_trade_overlays": len(closed),
        "open_position_overlays": len(open_positions),
        "trade_shapes": len(shapes),
        "normalized_trade_render_layer_count": len(shapes),
        "visual_trade_overlay_count_expected": int(layer.get("total_render_trade_count") or 0),
        "visual_trade_overlay_count_rendered": len(shapes),
        "visible_stop_loss_line_count": sum(1 for shape in shapes if shape.get("stop_price") is not None or shape.get("stop_loss_price") is not None),
        "visible_take_profit_line_count": sum(1 for shape in shapes if shape.get("take_price") is not None or shape.get("take_profit_price") is not None),
        "controller_paper_trade_overlay_count": 0,
    }
    return ensure_latest_trade_explainability(
        {
            "generated_at_utc": layer.get("generated_at_utc"),
            "trade_layer_source": "normalized_trade_render_layer.json",
            "renderer_source": _rel(NORMALIZED_TRADE_RENDER_LAYER_JSON),
            "source_closed": layer.get("source_closed"),
            "source_open": layer.get("source_open"),
            "trade_identity": "trade_id",
            "context_id_role": "label_only",
            "controller_ledger_used_for_render": True,
            "secondary_research_layer": layer.get("secondary_research_layer"),
            "economics_version": CANONICAL_ECONOMICS_VERSION,
            "canonical_view": layer.get("canonical_view"),
            "one_shot_rows_excluded_from_render": True,
            "trade_visual_style_mode": "normal_trade_style",
            "entries": entries,
            "exits": exits,
            "trade_shapes": shapes,
            "closed_trades": closed,
            "open_positions": open_positions,
            "restated_trades": [],
            "superseded_paper_trades": [],
            "counts": counts,
            "last_trade_id": last.get("trade_id"),
            "last_trade_result": "OPEN" if str(last.get("status") or "").upper() == "OPEN" else "WIN" if (_safe_float(last.get("net_pnl_usd")) or 0.0) >= 0 else "LOSS" if last else None,
            "missing_rendered_trade_ids": [],
        }
    )


def _reconciliation_issue(issue_type: str, source_table: str, row: Any = None, **extra: Any) -> dict[str, Any]:
    payload = {
        "issue_type": issue_type,
        "severity": extra.pop("severity", "INFO"),
        "source_table": source_table,
        "trade_id": extra.pop("trade_id", None),
        "position_id": extra.pop("position_id", None),
        "order_id": extra.pop("order_id", None),
        "signal_id": extra.pop("signal_id", None),
        "details": extra.pop("details", None),
        "used_for_rendering": False,
        "canonical_position_notional_usd": extra.pop("canonical_position_notional_usd", None),
        "report_position_size_usd": extra.pop("report_position_size_usd", None),
        "stop_loss_price": extra.pop("stop_loss_price", None),
        "max_risk_usd": extra.pop("max_risk_usd", None),
        "expected_loss_at_stop_usd": extra.pop("expected_loss_at_stop_usd", None),
        "sizing_method": extra.pop("sizing_method", None),
        "sizing_status": extra.pop("sizing_status", None),
        "economics_source": extra.pop("economics_source", None),
        "copied_canonical_economics": extra.pop("copied_canonical_economics", None),
        "fixed_notional_used": extra.pop("fixed_notional_used", None),
    }
    if row is not None:
        payload["trade_id"] = payload["trade_id"] or _safe_text(row.get("trade_id") if hasattr(row, "get") else None) or _safe_text(row.get("paper_trade_id") if hasattr(row, "get") else None)
        payload["position_id"] = payload["position_id"] or _safe_text(row.get("position_id") if hasattr(row, "get") else None)
        payload["order_id"] = payload["order_id"] or _safe_text(row.get("paper_order_id") if hasattr(row, "get") else None)
        payload["signal_id"] = payload["signal_id"] or _safe_text(row.get("signal_id") if hasattr(row, "get") else None)
    return payload


def build_trade_layer_reconciliation(render_layer: dict[str, Any], closed_report: dict[str, Any], overlays: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    render_rows = [row for row in render_layer.get("trades") or [] if isinstance(row, dict)]
    render_ids = [str(row.get("trade_id")) for row in render_rows if row.get("trade_id")]
    render_set = set(render_ids)
    status_by_trade = {str(row.get("trade_id")): str(row.get("status") or "").upper() for row in render_rows if row.get("trade_id")}
    render_by_trade = {str(row.get("trade_id")): row for row in render_rows if row.get("trade_id")}
    closed_rows = [row for row in closed_report.get("trades") or [] if isinstance(row, dict)]
    closed_by_trade = {str(row.get("trade_id")): row for row in closed_rows if row.get("trade_id")}
    closed_ids = [str(row.get("trade_id")) for row in closed_rows if row.get("trade_id")]
    closed_set = set(closed_ids)
    shapes = [shape for shape in overlays.get("trade_shapes") or [] if isinstance(shape, dict)]
    rendered_ids = [str(shape.get("trade_id")) for shape in shapes if shape.get("trade_id")]
    rows: list[dict[str, Any]] = []

    for trade_id in sorted({tid for tid in render_ids if render_ids.count(tid) > 1}):
        rows.append(_reconciliation_issue("DUPLICATE_TRADE_ID", "normalized_trade_render_layer", trade_id=trade_id, severity="ERROR"))
    for trade_id in sorted({tid for tid in closed_ids if closed_ids.count(tid) > 1}):
        rows.append(_reconciliation_issue("DUPLICATE_CLOSED_REPORT_TRADE_ID", "closed_trade_report", trade_id=trade_id, severity="ERROR"))
    for trade_id in sorted({tid for tid in rendered_ids if rendered_ids.count(tid) > 1}):
        rows.append(_reconciliation_issue("DUPLICATED_RENDER_ROW", "paper_trade_overlays", trade_id=trade_id, severity="ERROR"))

    for trade_id in sorted(render_set):
        status = status_by_trade.get(trade_id)
        if status == "OPEN" and trade_id not in closed_set:
            rows.append(_reconciliation_issue("OPEN_TRADE_PRESENT_IN_RENDER_ABSENT_FROM_CLOSED_REPORT", "normalized_trade_render_layer", trade_id=trade_id, severity="INFO"))
        if status == "CLOSED" and trade_id in closed_set:
            render_row = render_by_trade.get(trade_id, {})
            report_row = closed_by_trade.get(trade_id, {})
            rows.append(
                _reconciliation_issue(
                    "CLOSED_TRADE_PRESENT_IN_CLOSED_REPORT",
                    "closed_trade_report",
                    trade_id=trade_id,
                    severity="INFO",
                    canonical_position_notional_usd=render_row.get("canonical_position_notional_usd"),
                    report_position_size_usd=report_row.get("position_size_usd"),
                    stop_loss_price=report_row.get("stop_loss_price"),
                    max_risk_usd=report_row.get("max_risk_usd"),
                    expected_loss_at_stop_usd=report_row.get("expected_loss_at_stop_usd"),
                    sizing_method=render_row.get("sizing_method"),
                    sizing_status=report_row.get("sizing_status"),
                    economics_source=render_row.get("economics_source"),
                    copied_canonical_economics=render_row.get("copied_canonical_economics"),
                    fixed_notional_used=render_row.get("fixed_notional_used"),
                )
            )
        render_row = render_by_trade.get(trade_id, {})
        if status == "CLOSED" and render_row.get("sizing_status") in {SIZING_BLOCKED_MISSING_STOP, SIZING_BLOCKED_INVALID_STOP}:
            rows.append(
                _reconciliation_issue(
                    str(render_row.get("sizing_status")),
                    "normalized_trade_render_layer",
                    trade_id=trade_id,
                    severity="WARN",
                    canonical_position_notional_usd=render_row.get("canonical_position_notional_usd"),
                    report_position_size_usd=render_row.get("position_size_usd"),
                    stop_loss_price=render_row.get("stop_loss_price"),
                    max_risk_usd=render_row.get("max_risk_usd"),
                    expected_loss_at_stop_usd=render_row.get("expected_loss_at_stop_usd"),
                    sizing_method=render_row.get("sizing_method"),
                    sizing_status=render_row.get("sizing_status"),
                    economics_source=render_row.get("economics_source"),
                    copied_canonical_economics=render_row.get("copied_canonical_economics"),
                    fixed_notional_used=render_row.get("fixed_notional_used"),
                )
            )

    entry_ids = [str(item.get("trade_id")) for item in overlays.get("entries") or [] if isinstance(item, dict) and item.get("trade_id")]
    exit_ids = [str(item.get("trade_id")) for item in overlays.get("exits") or [] if isinstance(item, dict) and item.get("trade_id")]
    for trade_id in sorted(render_set):
        status = status_by_trade.get(trade_id)
        expected_exits = 0 if status == "OPEN" else 1
        if entry_ids.count(trade_id) != 1 or exit_ids.count(trade_id) != expected_exits:
            rows.append(
                _reconciliation_issue(
                    "ENTRY_EXIT_MARKER_TRADE_ID_MISMATCH",
                    "paper_trade_overlays",
                    trade_id=trade_id,
                    severity="ERROR",
                    details=f"status={status} entry_count={entry_ids.count(trade_id)} exit_count={exit_ids.count(trade_id)} expected_exit_count={expected_exits}",
                )
            )

    paper_positions = load_parquet(PAPER_DIR / "paper_positions.parquet")
    paper_trades = load_parquet(PAPER_DIR / "paper_trades.parquet")
    paper_orders = load_parquet(PAPER_DIR / "paper_orders.parquet")
    paper_signals = load_parquet(PAPER_DIR / "paper_signals.parquet")

    if len(paper_trades) and "position_id" in paper_trades.columns:
        missing_position = paper_trades[paper_trades["position_id"].isna() | (paper_trades["position_id"].astype(str).str.strip() == "")]
        for _, row in missing_position.iterrows():
            rows.append(_reconciliation_issue("PAPER_TRADES_ROW_WITHOUT_POSITION_ID", "paper_trades", row, severity="WARN"))
    if len(paper_orders) and "paper_order_id" in paper_orders.columns:
        one_shot = paper_orders[paper_orders["paper_order_id"].astype(str).str.startswith("PAPER_ORDER_ONE_SHOT_")]
        for _, row in one_shot.iterrows():
            rows.append(_reconciliation_issue("PAPER_ORDER_ONE_SHOT_SYNTHETIC_LEGACY_ROW", "paper_orders", row, severity="INFO"))

    position_ids = _frame_ids(paper_positions, "position_id", "trade_id", "paper_trade_id")
    if len(paper_positions) and "position_id" in paper_positions.columns:
        controller_closed = paper_positions[
            paper_positions["position_id"].astype(str).str.contains("_CTRL_", na=False)
            & (paper_positions.get("status", pd.Series(dtype=object)).astype(str).str.upper() == "CLOSED")
        ]
        for _, row in controller_closed.iterrows():
            ids = _row_ids(row, "position_id", "trade_id", "paper_trade_id")
            if not ids.intersection(render_set):
                rows.append(_reconciliation_issue("CONTROLLER_ONLY_CLOSED_POSITION_NOT_USED_FOR_RENDER", "paper_positions", row, severity="INFO"))
        for _, row in paper_positions.iterrows():
            ids = _row_ids(row, "position_id", "trade_id", "paper_trade_id")
            if ids and not ids.intersection(render_set):
                rows.append(_reconciliation_issue("PAPER_POSITION_NOT_FOUND_IN_VISUAL_LAYER", "paper_positions", row, severity="INFO"))
    for trade_id in sorted(render_set):
        if trade_id not in position_ids:
            rows.append(_reconciliation_issue("VISUAL_TRADE_NOT_FOUND_IN_PAPER_POSITIONS", "normalized_trade_render_layer", trade_id=trade_id, severity="INFO"))

    frame = pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)
    TRADE_LAYER_RECONCILIATION_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(TRADE_LAYER_RECONCILIATION_PARQUET, index=False)
    TRADE_LAYER_RECONCILIATION_XLSX.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(TRADE_LAYER_RECONCILIATION_XLSX, index=False)
    issue_series = frame.get("issue_type", pd.Series(dtype=object))
    return {
        "generated_at_utc": render_layer.get("generated_at_utc"),
        "parquet_path": _rel(TRADE_LAYER_RECONCILIATION_PARQUET),
        "xlsx_path": _rel(TRADE_LAYER_RECONCILIATION_XLSX),
        "issue_count": int(len(frame)),
        "controller_closed_positions_not_rendered": int((issue_series == "CONTROLLER_ONLY_CLOSED_POSITION_NOT_USED_FOR_RENDER").sum()) if len(frame) else 0,
        "controller_only_positions_count": int((issue_series == "CONTROLLER_ONLY_CLOSED_POSITION_NOT_USED_FOR_RENDER").sum()) if len(frame) else 0,
        "visual_only_trades_count": int((issue_series == "VISUAL_TRADE_NOT_FOUND_IN_PAPER_POSITIONS").sum()) if len(frame) else 0,
        "paper_positions_not_found_in_visual_layer_count": int((issue_series == "PAPER_POSITION_NOT_FOUND_IN_VISUAL_LAYER").sum()) if len(frame) else 0,
        "paper_trades_without_position_id_count": int((issue_series == "PAPER_TRADES_ROW_WITHOUT_POSITION_ID").sum()) if len(frame) else 0,
        "one_shot_rows_count": int((issue_series == "PAPER_ORDER_ONE_SHOT_SYNTHETIC_LEGACY_ROW").sum()) if len(frame) else 0,
        "open_in_render_not_report_count": int((issue_series == "OPEN_TRADE_PRESENT_IN_RENDER_ABSENT_FROM_CLOSED_REPORT").sum()) if len(frame) else 0,
        "closed_in_report_count": int((issue_series == "CLOSED_TRADE_PRESENT_IN_CLOSED_REPORT").sum()) if len(frame) else 0,
        "duplicate_trade_ids": sorted({tid for tid in render_ids if render_ids.count(tid) > 1}),
        "canonical_100k_preserved_as_debug_only": bool(
            len(frame)
            and "canonical_position_notional_usd" in frame.columns
            and (frame["canonical_position_notional_usd"].dropna().astype(float) == 100000.0).any()
        ),
        "report_uses_risk_based_stop_sizing": bool(
            len(frame)
            and "sizing_method" in frame.columns
            and (frame["sizing_method"].dropna().astype(str) == REPORT_SIZING_METHOD).any()
        ),
        "copied_canonical_economics": bool(
            len(frame)
            and "copied_canonical_economics" in frame.columns
            and frame["copied_canonical_economics"].fillna(False).astype(bool).any()
        ),
        "fixed_notional_used": bool(
            len(frame)
            and "fixed_notional_used" in frame.columns
            and frame["fixed_notional_used"].fillna(False).astype(bool).any()
        ),
        "blocked_missing_stop_count": int((issue_series == SIZING_BLOCKED_MISSING_STOP).sum()) if len(frame) else 0,
        "blocked_invalid_stop_count": int((issue_series == SIZING_BLOCKED_INVALID_STOP).sum()) if len(frame) else 0,
        "controller_ledger_used_for_render": True,
    }


def _context_number(value: Any) -> int | None:
    if value is None:
        return None
    digits = ""
    for ch in reversed(str(value)):
        if ch.isdigit():
            digits = ch + digits
        elif digits:
            break
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _shape_context_number(shape: dict[str, Any]) -> int | None:
    for key in ("context_episode_id", "lifecycle_episode_id", "context_id"):
        out = _context_number(shape.get(key))
        if out is not None:
            return out
    return None


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _drop_forced_latest_fields(row: dict[str, Any]) -> None:
    forced_keys = {
        "latest_context_trade",
        "latest_context_id",
        "latest_trade_label",
        "latest_trade_label_visible",
        "latest_entry_marker_visible",
        "latest_exit_marker_visible",
        "latest_stop_line_visible",
        "latest_take_line_visible",
        "latest_trade_box_visible",
        "latest_trade_above_context_band",
        "latest_trade_explainability_badge_visible",
        "latest_trade_label_always_visible",
        "latest_marker_label",
        "visual_priority",
        "render_priority",
        "trade_span_border_width",
        "trade_box_opacity",
        "entry_exit_marker_size",
        "marker_size",
        "trade_layer_z_index",
        "context_layer_z_index",
        "z_index",
    }
    for key in list(row.keys()):
        if key in forced_keys or key.startswith("latest_"):
            row.pop(key, None)
    for label_key in ("label_text", "entry_label_text", "exit_label_text", "stop_label_text", "take_label_text"):
        label = _safe_text(row.get(label_key))
        if label and "CTX 721" in label:
            row.pop(label_key, None)


def ensure_latest_trade_explainability(overlays: dict[str, Any]) -> dict[str, Any]:
    """Remove forced latest-trade styling; trades render with normal trade style by default."""
    if not isinstance(overlays, dict):
        return overlays
    for key in list(overlays.keys()):
        if key.startswith("latest_") or key in {
            "visual_trade_overlay_count_expected",
            "visual_trade_overlay_count_rendered",
            "missing_rendered_trade_ids",
        }:
            overlays.pop(key, None)
    for section in ("trade_shapes", "open_positions", "closed_trades", "entries", "exits"):
        for item in overlays.get(section) or []:
            if not isinstance(item, dict):
                continue
            _drop_forced_latest_fields(item)
            inspector = item.get("inspector")
            if isinstance(inspector, dict):
                _drop_forced_latest_fields(inspector)
            for line in item.get("stop_take_lines") or []:
                if isinstance(line, dict):
                    _drop_forced_latest_fields(line)
    overlays["latest_context_popup_enabled"] = False
    overlays["trade_visual_style_mode"] = "normal_trade_style"
    return overlays


def build_paper_overlays(mark_price: float | None) -> dict[str, Any]:
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_paper_overlays as _build,
    )

    return ensure_latest_trade_explainability(_build(mark_price))


def _shape_trade_ids(shape: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("trade_id", "entry_trade_id", "exit_trade_id", "close_trade_id"):
        value = _safe_text(shape.get(key))
        if value:
            out.add(value)
    return out


def _is_controller_trade_shape(shape: dict[str, Any]) -> bool:
    for key in ("trade_id", "entry_trade_id", "exit_trade_id", "signal_id", "order_id", "position_id"):
        value = _safe_text(shape.get(key))
        if value and "_CTRL_" in value:
            return True
    return False


def _row_by_id(frame: Any, id_column: str, wanted: str | None) -> Any:
    if not wanted or frame is None or not len(frame) or id_column not in getattr(frame, "columns", []):
        return None
    matches = frame[frame[id_column].astype(str) == wanted]
    if matches.empty:
        return None
    return matches.iloc[-1]


def _controller_entry_timestamp(
    shape: dict[str, Any],
    signals: Any,
    orders: Any,
) -> tuple[str | None, str | None]:
    signal_row = _row_by_id(signals, "signal_id", _safe_text(shape.get("signal_id")))
    if signal_row is not None:
        ts = _iso_ts(signal_row.get("source_context_ts"))
        if ts:
            return ts, "paper_signals.source_context_ts"
    order_row = _row_by_id(orders, "paper_order_id", _safe_text(shape.get("order_id")))
    if order_row is not None:
        ts = _iso_ts(order_row.get("candle_timestamp"))
        if ts:
            return ts, "paper_orders.candle_timestamp"
    return _iso_ts(shape.get("source_context_ts") or shape.get("m15_bucket_open_ts") or shape.get("entry_ts")), "raw_overlay_fallback"


def _apply_controller_entry_timestamp(
    shape: dict[str, Any],
    entry_ts: str | None,
    entry_ts_source: str | None,
) -> dict[str, Any]:
    if not entry_ts:
        return shape
    entry_trade_id = _safe_text(shape.get("entry_trade_id") or shape.get("trade_id"))
    shape["trade_id"] = entry_trade_id or shape.get("trade_id")
    shape["entry_trade_id"] = entry_trade_id or shape.get("entry_trade_id")
    shape["entry_ts"] = entry_ts
    shape["paper_action_ts"] = entry_ts
    shape["paper_action_ts_entry"] = entry_ts
    shape["source_context_ts"] = entry_ts
    shape["m15_bucket_open_ts"] = entry_ts
    shape["entry_time_unix"] = _unix(entry_ts)
    shape["entry_ts_source"] = entry_ts_source
    shape["source"] = "controller"
    shape["visual_source"] = "controller_paper_ledger"
    shape["controller_paper_trade_overlay"] = True
    shape["dedupe_key"] = f"controller_trade_id:{shape['trade_id']}" if shape.get("trade_id") else None
    inspector = shape.get("inspector") if isinstance(shape.get("inspector"), dict) else {}
    inspector.update(
        {
            "trade_id": shape.get("trade_id"),
            "entry_trade_id": shape.get("entry_trade_id"),
            "exit_trade_id": shape.get("exit_trade_id"),
            "entry_ts": entry_ts,
            "source_context_ts": entry_ts,
            "entry_ts_source": entry_ts_source,
            "source": "controller",
        }
    )
    shape["inspector"] = inspector
    return shape


def _copy_controller_markers(
    markers: list[dict[str, Any]],
    added_ids: set[str],
    entry_ts_by_trade: dict[str, tuple[str | None, str | None]],
    *,
    marker_type: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for marker in markers:
        marker_ids = _shape_trade_ids(marker)
        if not marker_ids.intersection(added_ids):
            continue
        copy = dict(marker)
        if marker_type == "ENTRY":
            trade_id = _safe_text(copy.get("trade_id") or copy.get("entry_trade_id"))
            entry_ts, entry_ts_source = entry_ts_by_trade.get(trade_id or "", (None, None))
            if entry_ts:
                copy["ts"] = entry_ts
                copy["entry_ts"] = entry_ts
                copy["time_unix"] = _unix(entry_ts)
                copy["entry_ts_source"] = entry_ts_source
        copy["source"] = "controller"
        copy["visual_source"] = "controller_paper_ledger"
        copy["controller_paper_trade_overlay"] = True
        out.append(copy)
    return out


def merge_live_open_positions_into_policy_overlays(
    overlays: dict[str, Any],
    mark_price: float | None,
) -> dict[str, Any]:
    """Keep canonical policy overlays, but add missing controller paper trades by trade id."""
    if not isinstance(overlays, dict):
        return overlays
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_paper_overlays as _build_raw,
    )

    raw = _build_raw(mark_price)
    raw_shapes = [
        dict(shape)
        for shape in (raw.get("trade_shapes") or [])
        if isinstance(shape, dict) and _is_controller_trade_shape(shape)
    ]
    if not raw_shapes:
        return overlays

    signals = load_parquet(PAPER_DIR / "paper_signals.parquet")
    orders = load_parquet(PAPER_DIR / "paper_orders.parquet")
    shapes = list(overlays.get("trade_shapes") or [])
    open_positions = list(overlays.get("open_positions") or [])
    closed_trades = list(overlays.get("closed_trades") or [])
    entries = list(overlays.get("entries") or [])
    exits = list(overlays.get("exits") or [])
    existing = {
        trade_id
        for shape in [*shapes, *open_positions, *closed_trades]
        for trade_id in _shape_trade_ids(shape)
    }
    added_ids: set[str] = set()
    entry_ts_by_trade: dict[str, tuple[str | None, str | None]] = {}
    for shape in raw_shapes:
        entry_trade_id = _safe_text(shape.get("entry_trade_id") or shape.get("trade_id"))
        if not entry_trade_id or entry_trade_id in existing:
            continue
        entry_ts, entry_ts_source = _controller_entry_timestamp(shape, signals, orders)
        shape = _apply_controller_entry_timestamp(shape, entry_ts, entry_ts_source)
        status = str(shape.get("status") or "").upper()
        shapes.append(shape)
        if status == "OPEN":
            open_positions.append(shape)
        else:
            closed_trades.append(shape)
        shape_ids = _shape_trade_ids(shape)
        existing.update(shape_ids)
        added_ids.update(shape_ids)
        entry_ts_by_trade[entry_trade_id] = (entry_ts, entry_ts_source)

    if added_ids:
        entries.extend(
            _copy_controller_markers(raw.get("entries") or [], added_ids, entry_ts_by_trade, marker_type="ENTRY")
        )
        exits.extend(
            _copy_controller_markers(raw.get("exits") or [], added_ids, entry_ts_by_trade, marker_type="EXIT")
        )

    overlays["trade_shapes"] = shapes
    overlays["open_positions"] = open_positions
    overlays["closed_trades"] = closed_trades
    overlays["entries"] = entries
    overlays["exits"] = exits
    counts = dict(overlays.get("counts") or {})
    counts["open_position_overlays"] = len(open_positions)
    counts["closed_trade_overlays"] = len(closed_trades)
    counts["trade_shapes"] = len(shapes)
    counts["entry_markers"] = len(entries)
    counts["exit_markers"] = len(exits)
    counts["live_open_paper_trade_count"] = len(open_positions)
    counts["controller_paper_trade_overlay_count"] = sum(
        1 for shape in shapes if shape.get("controller_paper_trade_overlay") is True
    )
    counts["visible_stop_loss_line_count"] = sum(
        1
        for shape in shapes
        for line in (shape.get("stop_take_lines") or [])
        if line.get("kind") == "STOP_LOSS" and line.get("visible", True)
    )
    counts["visible_take_profit_line_count"] = sum(
        1
        for shape in shapes
        for line in (shape.get("stop_take_lines") or [])
        if line.get("kind") == "TAKE_PROFIT" and line.get("visible", True)
    )
    overlays["counts"] = counts
    overlays["live_controller_trades_merged_from_raw_ledger"] = bool(added_ids)
    overlays["live_controller_trade_merge_key"] = "trade_id"
    return overlays


def build_trade_result_summary(overlays: dict[str, Any]) -> dict[str, Any]:
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_trade_result_summary as _build,
    )

    return _build(overlays)


def build_pnl_summary(overlays: dict[str, Any]) -> dict[str, Any]:
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_pnl_summary as _build,
    )

    return _build(overlays)


def build_trade_context_checks(overlays: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_trade_context_checks as _build,
    )

    return _build(overlays)


def build_controller_cycles() -> dict[str, Any]:
    cycles = load_parquet(PAPER_DIR / "bounded_paper_controller_cycles.parquet")
    actions = load_parquet(PAPER_DIR / "bounded_paper_controller_actions.parquet")
    status = {}
    state = {}
    status_path = PAPER_DIR / "bounded_paper_controller_status.json"
    state_path = PAPER_DIR / "bounded_paper_controller_state.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            status = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    cycle_rows = []
    if len(cycles):
        for _, row in cycles.iterrows():
            cycle_rows.append(
                {
                    "cycle_id": _safe_text(row.get("cycle_id")),
                    "cycle_ts": _iso_ts(row.get("cycle_ts")),
                    "time_unix": _unix(row.get("cycle_ts")),
                    "market_ts": _iso_ts(row.get("market_ts")),
                    "decision_log_ts": _iso_ts(row.get("decision_log_ts")),
                    "context": _safe_text(row.get("context")),
                    "lifecycle_state": _safe_text(row.get("lifecycle_state")),
                    "position_state_before": _safe_text(row.get("position_state_before")),
                    "action_taken": _safe_text(row.get("action_taken")),
                    "cycle_status": _safe_text(row.get("cycle_status")),
                    "reason": _safe_text(row.get("reason")),
                    "execution_enabled": False,
                }
            )
    action_rows = []
    if len(actions):
        for _, row in actions.iterrows():
            action_rows.append(
                {
                    "action_id": _safe_text(row.get("action_id")),
                    "cycle_id": _safe_text(row.get("cycle_id")),
                    "action_ts": _iso_ts(row.get("action_ts")),
                    "time_unix": _unix(row.get("action_ts")),
                    "action_type": _safe_text(row.get("action_type")),
                    "signal_id": _safe_text(row.get("signal_id")),
                    "order_id": _safe_text(row.get("order_id")),
                    "trade_id": _safe_text(row.get("trade_id")),
                    "position_id": _safe_text(row.get("position_id")),
                    "side": _safe_text(row.get("side")),
                    "price": _safe_float(row.get("price")),
                    "reason": _safe_text(row.get("reason")),
                    "execution_enabled": False,
                }
            )
    return {
        "generated_at_utc": _iso_now(),
        "cycles": cycle_rows,
        "actions": action_rows,
        "controller_status": {
            "controller_running": bool(status.get("controller_running")),
            "pid": status.get("pid"),
            "cycle_idx": status.get("cycle_idx"),
            "collecting_paper_data": bool(status.get("collecting_paper_data")),
            "execution_enabled": False,
            "paper_only_mode": True,
        },
        "controller_state_last_cycle_id": state.get("last_cycle_id"),
        "counts": {"cycles": len(cycle_rows), "actions": len(action_rows)},
    }


def build_context_visual(latest: dict[str, Any], overlays: dict[str, Any], cycles: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": _iso_now(),
        "source": "visual_only_refresher",
        "latest": latest,
        "active_market_context": latest.get("active_market_context"),
        "lifecycle_state": latest.get("lifecycle_state"),
        "latest_decision_timestamp": latest.get("timestamp"),
        "paper_overlay_counts": overlays.get("counts"),
        "controller_counts": cycles.get("counts"),
        "paper_only": True,
        "execution_enabled": False,
        "visual_only": True,
    }


def compute_freshness(
    *,
    live_ts: str | None,
    decision_ts: str | None,
    last_visual_refresh_ts: str | None,
    visual_stale_seconds: float,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    live_dt = _parse_ts(live_ts)
    decision_dt = _parse_ts(decision_ts)
    refresh_dt = _parse_ts(last_visual_refresh_ts)

    source_ref = decision_dt or live_dt
    source_lag_minutes = None
    if source_ref is not None:
        source_lag_minutes = round(max(0.0, (now - source_ref.astimezone(timezone.utc)).total_seconds() / 60.0), 2)

    visual_refresh_age_seconds = None
    if refresh_dt is not None:
        visual_refresh_age_seconds = round(
            max(0.0, (now - refresh_dt.astimezone(timezone.utc)).total_seconds()),
            2,
        )

    refresher_fresh = visual_refresh_age_seconds is not None and visual_refresh_age_seconds <= visual_stale_seconds
    if not refresher_fresh:
        visual_data_status = "VISUAL_DATA_STALE"
    elif source_lag_minutes is not None and source_lag_minutes > 30:
        visual_data_status = "SOURCE_WAITING_NO_NEW_BAR"
    else:
        visual_data_status = "LIVE_OK"

    return {
        "latest_live_feed_ts": live_ts,
        "latest_decision_log_ts": decision_ts,
        "last_visual_refresh_ts": last_visual_refresh_ts,
        "source_lag_minutes": source_lag_minutes,
        "visual_refresh_age_seconds": visual_refresh_age_seconds,
        "visual_data_status": visual_data_status,
        "visual_stale_seconds_threshold": visual_stale_seconds,
    }


def refresh_once(*, visual_stale_seconds: float, last_good: dict[str, Any]) -> dict[str, Any]:
    started = _iso_now()
    live_ts = read_latest_ts(LIVE_FEED, "timestamp")
    decision_ts = read_latest_ts(DECISION_LOG, "candle_timestamp", "timestamp", "decision_ts")
    mark = read_latest_close()

    try:
        lifecycle = run_lifecycle_visual_generate()
        latest = lifecycle.get("latest") or {}
        if not decision_ts:
            decision_ts = _iso_ts(latest.get("timestamp"))
        refresh_ts = _iso_now()
        render_layer = build_normalized_trade_render_layer(refresh_ts, mark)
        closed_report = build_closed_trade_report(render_layer)
        overlays = build_overlays_from_trade_render_layer(render_layer)
        cycles = build_controller_cycles()
        reconciliation = build_trade_layer_reconciliation(render_layer, closed_report, overlays)
        trade_result = build_trade_result_summary(overlays)
        pnl_summary = build_pnl_summary(overlays)
        entry_check, exit_check = build_trade_context_checks(overlays)
        context_visual = build_context_visual(latest, overlays, cycles)
        freshness = compute_freshness(
            live_ts=live_ts,
            decision_ts=decision_ts,
            last_visual_refresh_ts=refresh_ts,
            visual_stale_seconds=visual_stale_seconds,
        )
        visual_status = {
            "generated_at_utc": refresh_ts,
            "status": "OK",
            "visual_data_status": freshness["visual_data_status"],
            "last_error": None,
            "last_success_at": refresh_ts,
            "last_run_started_at": started,
            "last_run_finished_at": refresh_ts,
            "visual_only": True,
            "paper_ledger_write_performed": False,
            "decision_log_write_performed": False,
            "live_refresh_performed": False,
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "dashboard_started": False,
            "bounded_paper_controller_touched": False,
            "cache_busting_enabled": True,
            "no_cache_headers_enabled": True,
            "lock_active": True,
            "interval_hint_seconds": DEFAULT_INTERVAL_SECONDS,
            **freshness,
            "overlay_counts": overlays.get("counts"),
            "controller_counts": cycles.get("counts"),
            "entries_count": (overlays.get("counts") or {}).get("entry_markers"),
            "exits_count": (overlays.get("counts") or {}).get("exit_markers"),
            "open_positions_count": (overlays.get("counts") or {}).get("open_position_overlays"),
            "closed_trades_count": (overlays.get("counts") or {}).get("closed_trade_overlays"),
            "last_trade_id": overlays.get("last_trade_id"),
            "last_trade_result": overlays.get("last_trade_result"),
            "normalized_trade_render_layer": {
                "source_closed": render_layer.get("source_closed"),
                "source_open": render_layer.get("source_open"),
                "json_path": render_layer.get("json_path"),
                "parquet_path": render_layer.get("parquet_path"),
                "xlsx_path": render_layer.get("xlsx_path"),
                "closed_trade_count": render_layer.get("closed_trade_count"),
                "open_trade_count": render_layer.get("open_trade_count"),
                "total_render_trade_count": render_layer.get("total_render_trade_count"),
                "renderer_source": render_layer.get("renderer_source"),
            },
            "closed_trade_report": {
                "json_path": closed_report.get("json_path"),
                "parquet_path": closed_report.get("parquet_path"),
                "xlsx_path": closed_report.get("xlsx_path"),
                "closed_report_trade_count": closed_report.get("closed_report_trade_count"),
                "required_columns_present": closed_report.get("required_columns_present"),
            },
            "trade_layer_reconciliation": reconciliation,
            "forbidden_writes": list(FORBIDDEN_WRITE_GLOBS),
        }

        # Canonical timeframe-trader OPEN positions (decision-driving paper books).
        try:
            from trading_truth import (  # type: ignore
                build_trading_truth,
                open_position_overlay_shapes,
                write_trading_truth_artifacts,
            )

            truth = write_trading_truth_artifacts(PUBLIC_DATA, timeframe="ALL")
            tf_open = truth.get("open_positions") or []
            tf_shapes = open_position_overlay_shapes(tf_open)
            overlays["open_positions"] = tf_shapes
            counts = dict(overlays.get("counts") or {})
            counts["open_position_overlays"] = len(tf_shapes)
            counts["live_open_paper_trade_count"] = len(tf_shapes)
            counts["timeframe_trader_open_position_count"] = len(tf_shapes)
            overlays["counts"] = counts
            overlays["open_positions_source"] = "data/trading/timeframe_traders"
            visual_status["open_positions_count"] = len(tf_shapes)
            visual_status["trading_truth"] = {
                "active_episode_id": (truth.get("active_episode") or {}).get("episode_id"),
                "open_position_count": len(tf_shapes),
                "path": "apps/context_visualizer/public/data/trading_truth.json",
            }
        except Exception as exc:
            visual_status["trading_truth_error"] = f"{type(exc).__name__}: {exc}"

        write_json(CONTEXT_VISUAL_OUT, context_visual)
        write_json(PAPER_OVERLAYS_OUT, overlays)
        write_json(
            OPEN_POSITIONS_OUT,
            {
                "generated_at_utc": refresh_ts,
                "source": overlays.get("open_positions_source") or "overlay_shapes",
                "open_positions": overlays.get("open_positions") or [],
                "overlay_shapes": overlays.get("open_positions") or [],
                "count": len(overlays.get("open_positions") or []),
            },
        )
        write_json(
            CLOSED_TRADES_OUT,
            {
                "generated_at_utc": refresh_ts,
                "closed_trades": overlays.get("closed_trades") or [],
                "count": len(overlays.get("closed_trades") or []),
            },
        )
        write_json(CONTROLLER_CYCLES_OUT, cycles)
        write_json(TRADE_RESULT_SUMMARY_OUT, trade_result)
        write_json(PNL_SUMMARY_OUT, pnl_summary)
        write_json(
            RESTATED_TRADES_OUT,
            {
                "generated_at_utc": refresh_ts,
                "accounting_mode": "RESTATED_CONTEXT_EVENT_POLICY",
                "policy_version": overlays.get("policy_version"),
                "restated_trades": overlays.get("restated_trades") or [],
                "count": len(overlays.get("restated_trades") or []),
            },
        )
        write_json(
            SUPERSEDED_TRADES_OUT,
            {
                "generated_at_utc": refresh_ts,
                "status": "SUPERSEDED_BY_CONTEXT_EVENT_RESTATEMENT",
                "superseded_paper_trades": overlays.get("superseded_paper_trades") or [],
                "count": len(overlays.get("superseded_paper_trades") or []),
                "use_in_main_chart": False,
                "use_in_corrected_pnl": False,
            },
        )
        write_json(VISUAL_STATUS_OUT, visual_status)
        write_json(TRADE_ENTRY_CONTEXT_CHECK, entry_check)
        write_json(TRADE_EXIT_CONTEXT_CHECK, exit_check)

        research_payload = {
            "generated_at_utc": refresh_ts,
            "status": "CONTEXT_VISUAL_TRADE_POSITION_OVERLAY_OK",
            "visual_status": visual_status,
            "overlay_counts": overlays.get("counts"),
            "trade_result": trade_result,
            "pnl_summary": pnl_summary,
            "entry_context_check": entry_check,
            "exit_context_check": exit_check,
            "controller_counts": cycles.get("counts"),
            "normalized_trade_render_layer": {
                "source_closed": render_layer.get("source_closed"),
                "source_open": render_layer.get("source_open"),
                "json_path": render_layer.get("json_path"),
                "parquet_path": render_layer.get("parquet_path"),
                "xlsx_path": render_layer.get("xlsx_path"),
                "closed_trade_count": render_layer.get("closed_trade_count"),
                "open_trade_count": render_layer.get("open_trade_count"),
                "total_render_trade_count": render_layer.get("total_render_trade_count"),
            },
            "closed_trade_report": {
                "json_path": closed_report.get("json_path"),
                "parquet_path": closed_report.get("parquet_path"),
                "xlsx_path": closed_report.get("xlsx_path"),
                "closed_report_trade_count": closed_report.get("closed_report_trade_count"),
                "required_columns_present": closed_report.get("required_columns_present"),
            },
            "trade_layer_reconciliation": reconciliation,
            "safety": {
                "paper_ledger_write_performed": False,
                "decision_log_write_performed": False,
                "live_refresh_performed": False,
                "execution_enabled": False,
                "bounded_paper_controller_touched": False,
            },
        }
        stamp = refresh_ts.replace(":", "").replace("-", "")[:15]
        write_json(RESEARCH_DIR / f"visual_trade_overlay_{stamp}.json", research_payload)
        write_json(RESEARCH_DIR / "visual_trade_overlay_latest.json", research_payload)
        write_json(RESEARCH_DIR / f"visual_context_stack_{stamp}.json", research_payload)
        write_json(RESEARCH_DIR / "visual_context_stack_latest.json", research_payload)

        last_good.clear()
        last_good.update(
            {
                "context_visual": context_visual,
                "overlays": overlays,
                "cycles": cycles,
                "visual_status": visual_status,
                "trade_result": trade_result,
                "pnl_summary": pnl_summary,
            }
        )
        log_line(
            f"[pass] visual_status={visual_status['visual_data_status']} "
            f"entries={overlays['counts']['entry_markers']} exits={overlays['counts']['exit_markers']} "
            f"open={overlays['counts']['open_position_overlays']} "
            f"last_result={overlays.get('last_trade_result')}"
        )
        return visual_status
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()[-1500:]}"
        refresh_ts = _iso_now()
        freshness = compute_freshness(
            live_ts=live_ts,
            decision_ts=decision_ts,
            last_visual_refresh_ts=(last_good.get("visual_status") or {}).get("last_visual_refresh_ts")
            or (last_good.get("visual_status") or {}).get("generated_at_utc"),
            visual_stale_seconds=visual_stale_seconds,
        )
        visual_status = {
            "generated_at_utc": refresh_ts,
            "status": "DEGRADED_LAST_GOOD_DATA",
            "visual_data_status": "DEGRADED_LAST_GOOD_DATA",
            "last_error": err[:2000],
            "last_error_at": refresh_ts,
            "last_run_started_at": started,
            "last_run_finished_at": refresh_ts,
            "visual_only": True,
            "paper_ledger_write_performed": False,
            "decision_log_write_performed": False,
            "live_refresh_performed": False,
            "execution_enabled": False,
            "exchange_api_call_used": False,
            "dashboard_started": False,
            "bounded_paper_controller_touched": False,
            "kept_last_good": bool(last_good),
            **freshness,
        }
        # Do not overwrite overlay JSON on failure if last-good exists.
        write_json(VISUAL_STATUS_OUT, visual_status)
        write_json(RESEARCH_DIR / "visual_context_stack_latest.json", {"generated_at_utc": refresh_ts, "status": "DEGRADED", "visual_status": visual_status})
        log_line(f"[degraded] {exc}")
        return visual_status


def run_loop(*, interval_seconds: int, once: bool, visual_stale_seconds: float) -> int:
    if not acquire_lock():
        return 2
    atexit.register(release_lock)
    stopping = {"flag": False}

    def _handle(signum: int, _frame: Any) -> None:
        log_line(f"[signal] {signum}")
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    last_good: dict[str, Any] = {}
    if VISUAL_STATUS_OUT.exists():
        try:
            last_good["visual_status"] = json.loads(VISUAL_STATUS_OUT.read_text(encoding="utf-8"))
        except Exception:
            pass

    log_line(f"[start] pid={os.getpid()} interval={interval_seconds}s visual_only=true")
    exit_code = 0
    while True:
        status = refresh_once(visual_stale_seconds=visual_stale_seconds, last_good=last_good)
        if status.get("status") == "DEGRADED_LAST_GOOD_DATA":
            exit_code = 1
        if once or stopping["flag"]:
            break
        time.sleep(float(interval_seconds))
    release_lock()
    return 0 if not once else exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Visual-only market context + paper trade refresher")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    p.add_argument("--visual-stale-seconds", type=float, default=VISUAL_STALE_SECONDS)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interval = max(15, min(30, int(args.interval_seconds)))
    return run_loop(
        interval_seconds=interval,
        once=bool(args.once),
        visual_stale_seconds=float(args.visual_stale_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
