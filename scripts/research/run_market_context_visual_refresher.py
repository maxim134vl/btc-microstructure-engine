#!/usr/bin/env python3
"""Market Context Visual Auto-Refresh (shadow-only).

Periodically runs build_market_context_shadow_chain.py so the Lifecycle
Context Viewer JSON stays near live_market_feed.

Not pipeline. Not execution. Not model/retrain/benchmark.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

BUILDER_SCRIPT = ROOT / "scripts" / "research" / "build_market_context_shadow_chain.py"
STATUS_PATH = ROOT / "data" / "cognition" / "market_context_visual_refresher_status.json"
LOG_PATH = ROOT / "logs" / "market_context_visual_refresher.log"
PID_PATH = ROOT / "runtime_context_visual_refresher.pid"
LOCK_PATH = ROOT / "runtime_context_visual_refresher.lock"
LIVE_FEED_CANDIDATES = (
    ROOT / "data" / "live" / "live_market_feed.parquet",
)
LIFECYCLE_LATEST = (
    ROOT
    / "apps"
    / "context_visualizer"
    / "public"
    / "data"
    / "lifecycle_latest.json"
)

DEFAULT_INTERVAL_SECONDS = 180
DEFAULT_STALE_THRESHOLD_MINUTES = 30

REQUIRED_STATUS_FIELDS = (
    "generated_at",
    "status",
    "last_run_started_at",
    "last_run_finished_at",
    "last_success_at",
    "last_error_at",
    "last_error",
    "interval_seconds",
    "runs_total",
    "runs_success",
    "runs_failed",
    "latest_live_timestamp",
    "latest_visual_timestamp",
    "live_to_visual_lag_minutes",
    "visual_data_stale",
    "stale_threshold_minutes",
    "shadow_only",
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
        if not text:
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


def compute_visual_stale(
    live_ts: Any,
    visual_ts: Any,
    *,
    stale_threshold_minutes: float = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> tuple[float | None, bool]:
    """Return (lag_minutes, is_stale). Lag = live - visual; stale when lag > threshold."""
    live = _parse_ts(live_ts)
    visual = _parse_ts(visual_ts)
    if live is None or visual is None:
        return None, True
    lag_minutes = (live - visual).total_seconds() / 60.0
    # Boundary-safe: exactly at threshold is not stale.
    return round(lag_minutes, 2), lag_minutes > float(stale_threshold_minutes)


def read_latest_live_timestamp() -> str | None:
    candidates = list(LIVE_FEED_CANDIDATES)
    try:
        sys.path.insert(0, str(ROOT))
        from storage.path_registry import resolve_read  # type: ignore

        candidates.insert(0, Path(resolve_read("live_market_feed.parquet")))
    except Exception:
        pass
    for path in candidates:
        if not path.exists():
            continue
        try:
            import pandas as pd

            frame = pd.read_parquet(path, columns=["timestamp"])
            if frame.empty:
                continue
            return _iso_ts(frame["timestamp"].iloc[-1])
        except Exception:
            try:
                import pandas as pd

                frame = pd.read_parquet(path)
                for col in ("timestamp", "ts", "time", "event_time"):
                    if col in frame.columns and len(frame):
                        return _iso_ts(frame[col].iloc[-1])
            except Exception:
                continue
    return None


def read_latest_visual_timestamp(path: Path | None = None) -> str | None:
    target = path or LIFECYCLE_LATEST
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _iso_ts(payload.get("timestamp") or payload.get("generated_at") or payload.get("as_of"))


def default_status(
    *,
    interval_seconds: int,
    stale_threshold_minutes: int,
) -> dict[str, Any]:
    return {
        "generated_at": _iso_now(),
        "status": "RUNNING",
        "last_run_started_at": None,
        "last_run_finished_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
        "interval_seconds": int(interval_seconds),
        "runs_total": 0,
        "runs_success": 0,
        "runs_failed": 0,
        "latest_live_timestamp": None,
        "latest_visual_timestamp": None,
        "live_to_visual_lag_minutes": None,
        "visual_data_stale": True,
        "stale_threshold_minutes": int(stale_threshold_minutes),
        "shadow_only": True,
    }


def load_status(
    *,
    interval_seconds: int,
    stale_threshold_minutes: int,
) -> dict[str, Any]:
    if STATUS_PATH.exists():
        try:
            data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = default_status(
                    interval_seconds=interval_seconds,
                    stale_threshold_minutes=stale_threshold_minutes,
                )
                base.update(data)
                base["interval_seconds"] = int(interval_seconds)
                base["stale_threshold_minutes"] = int(stale_threshold_minutes)
                base["shadow_only"] = True
                return base
        except Exception:
            pass
    return default_status(
        interval_seconds=interval_seconds,
        stale_threshold_minutes=stale_threshold_minutes,
    )


def write_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["generated_at"] = _iso_now()
    payload["shadow_only"] = True
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATUS_PATH)


def log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_iso_now()} {message}"
    print(line, flush=True)
    # When runtime_stack redirects stdout into LOG_PATH, print already wrote the line.
    # Only mirror to the log file for interactive (TTY) runs.
    if sys.stdout.isatty():
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def get_refresher_logger():
    """Stable logger factory — handlers are attached once (test contract)."""
    import logging

    logger = logging.getLogger("market_context_visual_refresher")
    if not getattr(logger, "_btc_ml_handlers_configured", False):
        logger.setLevel(logging.INFO)
        # Prefer a single StreamHandler; avoid stacking duplicates on re-import.
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        logger.propagate = False
        logger._btc_ml_handlers_configured = True  # type: ignore[attr-defined]
    return logger


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock() -> bool:
    """Return True if this process owns the lock. False if another live refresher holds it."""
    if LOCK_PATH.exists():
        try:
            existing = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            existing = 0
        if _pid_alive(existing) and existing != os.getpid():
            log_line(f"[lock] refresher already running pid={existing}")
            return False
        log_line(f"[lock] replacing stale lock pid={existing}")
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    LOCK_PATH.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    PID_PATH.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        if LOCK_PATH.exists():
            existing = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
            if existing == os.getpid():
                LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        if PID_PATH.exists():
            existing = int(PID_PATH.read_text(encoding="utf-8").strip() or "0")
            if existing == os.getpid():
                PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def run_builder(
    builder: Callable[[], int] | None = None,
    *,
    timeout_seconds: int | None = None,
) -> tuple[bool, str | None]:
    if builder is not None:
        try:
            code = int(builder())
            return code == 0, None if code == 0 else f"builder exit code {code}"
        except Exception as exc:
            return False, str(exc)

    if not BUILDER_SCRIPT.exists():
        return False, f"missing builder: {BUILDER_SCRIPT}"

    cmd = [str(PYTHON), str(BUILDER_SCRIPT)]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return False, f"builder timeout: {exc}"
    except Exception as exc:
        return False, str(exc)

    if completed.returncode == 0:
        return True, None
    err = (completed.stderr or completed.stdout or "").strip()
    if not err:
        err = f"builder exit code {completed.returncode}"
    return False, err[-2000:]


def refresh_once(
    status: dict[str, Any],
    *,
    stale_threshold_minutes: int,
    builder: Callable[[], int] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    status = dict(status)
    status["last_run_started_at"] = _iso_now()
    status["status"] = "RUNNING"
    status["runs_total"] = int(status.get("runs_total") or 0) + 1
    write_status(status)
    log_line("[run] starting build_market_context_shadow_chain.py")

    ok, error = run_builder(builder, timeout_seconds=timeout_seconds)
    status["last_run_finished_at"] = _iso_now()

    live_ts = read_latest_live_timestamp()
    visual_ts = read_latest_visual_timestamp()
    lag, stale = compute_visual_stale(
        live_ts,
        visual_ts,
        stale_threshold_minutes=stale_threshold_minutes,
    )
    status["latest_live_timestamp"] = live_ts
    status["latest_visual_timestamp"] = visual_ts
    status["live_to_visual_lag_minutes"] = lag
    status["visual_data_stale"] = bool(stale)
    status["stale_threshold_minutes"] = int(stale_threshold_minutes)

    if ok:
        status["status"] = "PASS"
        status["last_success_at"] = status["last_run_finished_at"]
        status["last_error"] = None
        status["runs_success"] = int(status.get("runs_success") or 0) + 1
        log_line(
            f"[pass] visual={visual_ts} live={live_ts} lag_min={lag} stale={stale}"
        )
    else:
        status["status"] = "FAIL"
        status["last_error_at"] = status["last_run_finished_at"]
        status["last_error"] = error
        status["runs_failed"] = int(status.get("runs_failed") or 0) + 1
        log_line(f"[fail] {error}")

    write_status(status)
    return status


def run_loop(
    *,
    interval_seconds: int,
    stale_threshold_minutes: int,
    once: bool,
    builder: Callable[[], int] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_iterations: int | None = None,
    timeout_seconds: int | None = None,
) -> int:
    if not acquire_lock():
        return 2

    atexit.register(release_lock)

    stopping = {"flag": False}

    def _handle_signal(signum: int, _frame: Any) -> None:
        log_line(f"[signal] received {signum}; stopping after current cycle")
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    status = load_status(
        interval_seconds=interval_seconds,
        stale_threshold_minutes=stale_threshold_minutes,
    )
    status["status"] = "RUNNING"
    write_status(status)
    log_line(
        f"[start] pid={os.getpid()} interval={interval_seconds}s "
        f"stale_threshold={stale_threshold_minutes}m once={once}"
    )

    iterations = 0
    exit_code = 0
    while True:
        status = refresh_once(
            status,
            stale_threshold_minutes=stale_threshold_minutes,
            builder=builder,
            timeout_seconds=timeout_seconds,
        )
        if status.get("status") == "FAIL":
            exit_code = 1
        iterations += 1
        if once or stopping["flag"]:
            break
        if max_iterations is not None and iterations >= max_iterations:
            break
        # Keep status RUNNING between cycles so stack status shows live process intent.
        status["status"] = "RUNNING"
        write_status(status)
        sleep_fn(float(interval_seconds))

    release_lock()
    return 0 if once is False else exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-refresh Market Context Viewer shadow visual JSON.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single refresh and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Loop interval seconds (default {DEFAULT_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--stale-threshold-minutes",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_MINUTES,
        help=f"Lag threshold for visual_data_stale (default {DEFAULT_STALE_THRESHOLD_MINUTES}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interval = max(15, int(args.interval_seconds))
    threshold = max(1, int(args.stale_threshold_minutes))
    return run_loop(
        interval_seconds=interval,
        stale_threshold_minutes=threshold,
        once=bool(args.once),
    )


if __name__ == "__main__":
    raise SystemExit(main())
