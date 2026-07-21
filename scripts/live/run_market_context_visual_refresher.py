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
sys.path.insert(0, str(ROOT / "scripts" / "live"))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

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
OPEN_POSITIONS_OUT = PUBLIC_DATA / "open_positions.json"
CLOSED_TRADES_OUT = PUBLIC_DATA / "closed_trades.json"
CONTROLLER_CYCLES_OUT = PUBLIC_DATA / "controller_cycles.json"
VISUAL_STATUS_OUT = PUBLIC_DATA / "visual_status.json"
TRADE_RESULT_SUMMARY_OUT = PUBLIC_DATA / "trade_result_summary.json"
PNL_SUMMARY_OUT = PUBLIC_DATA / "pnl_summary.json"
TRADE_ENTRY_CONTEXT_CHECK = RESEARCH_DIR / "trade_entry_context_check.json"
TRADE_EXIT_CONTEXT_CHECK = RESEARCH_DIR / "trade_exit_context_check.json"

DEFAULT_INTERVAL_SECONDS = 20
VISUAL_STALE_SECONDS = 90.0
SYNTHETIC_PRICES = {99950.0, 100000.0, 100050.0}

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


def build_paper_overlays(mark_price: float | None) -> dict[str, Any]:
    from visual_paper_trade_overlay_builder import (  # type: ignore
        build_paper_overlays as _build,
    )

    return _build(mark_price)


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
        overlays = build_paper_overlays(mark)
        cycles = build_controller_cycles()
        trade_result = build_trade_result_summary(overlays)
        pnl_summary = build_pnl_summary(overlays)
        entry_check, exit_check = build_trade_context_checks(overlays)
        context_visual = build_context_visual(latest, overlays, cycles)
        refresh_ts = _iso_now()
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
            "forbidden_writes": list(FORBIDDEN_WRITE_GLOBS),
        }

        write_json(CONTEXT_VISUAL_OUT, context_visual)
        write_json(PAPER_OVERLAYS_OUT, overlays)
        write_json(
            OPEN_POSITIONS_OUT,
            {
                "generated_at_utc": refresh_ts,
                "open_positions": overlays.get("open_positions") or [],
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
