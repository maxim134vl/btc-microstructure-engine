#!/usr/bin/env python3
"""Paper-only Binance public intrabar/minute feed (does NOT alter canonical M15 feed).

Polls public market data about every 60s and appends to:
  data/live/live_market_intrabar_feed.parquet

No order APIs. No execution. No cognition writes.

Daemon mode (macOS-safe):
  When launched with --daemonize, double-fork + os.setsid happens in a stdlib-only
  prelude BEFORE pandas/numpy are imported, then the final child re-execs with
  --foreground (fresh interpreter). This avoids macOS crashes from forking after
  multi-threaded native libs have started.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = ROOT / "logs" / "live_binance_intrabar_feed.log"
DEFAULT_PID_PATH = ROOT / "run" / "live_binance_intrabar_feed.pid"
POLL_INTERVAL_SECONDS = 60


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{pid}\n", encoding="utf-8")
    tmp.replace(path)


def _early_wants_daemonize(argv: list[str]) -> bool:
    return (
        "--daemonize" in argv
        and "--foreground" not in argv
        and "--once" not in argv
        and "--help" not in argv
        and "-h" not in argv
    )


def _early_path_arg(argv: list[str], flag: str, default: Path) -> Path:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            p = Path(argv[i + 1])
            return p if p.is_absolute() else ROOT / p
    return default


def daemonize_reexec(*, pid_file: Path, log_file: Path, argv: list[str], wait_seconds: float = 10.0) -> None:
    """POSIX/macOS double-fork then re-exec --foreground in the final child.

    Parent exits only after final child pid file exists and is alive.
    Uses Python os.fork + os.setsid only (no shell setsid).
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    if pid_file.exists():
        try:
            old = int(pid_file.read_text(encoding="utf-8").strip())
            if not _pid_alive(old):
                pid_file.unlink(missing_ok=True)
        except Exception:
            pid_file.unlink(missing_ok=True)

    first = os.fork()
    if first > 0:
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if pid_file.exists():
                try:
                    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                except Exception:
                    child_pid = -1
                if child_pid > 0 and child_pid != first and _pid_alive(child_pid):
                    raise SystemExit(0)
            time.sleep(0.1)
        sys.stderr.write(f"daemonize_timeout: pid file not ready after {wait_seconds}s\n")
        raise SystemExit(1)

    os.setsid()
    second = os.fork()
    if second > 0:
        raise SystemExit(0)

    os.chdir(str(ROOT))
    os.umask(0)

    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    log_fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if devnull > 2:
        os.close(devnull)
    if log_fd > 2:
        os.close(log_fd)

    # Same PID survives execv.
    _write_pid_file(pid_file, os.getpid())

    script = str(Path(__file__).resolve())
    new_argv = [sys.executable, script, "--foreground"]
    skip_next = False
    for tok in argv:
        if skip_next:
            skip_next = False
            continue
        if tok == "--daemonize":
            continue
        if tok == "--foreground":
            continue
        new_argv.append(tok)
    if "--pid-file" not in new_argv:
        new_argv.extend(["--pid-file", str(pid_file)])
    if "--log-file" not in new_argv:
        new_argv.extend(["--log-file", str(log_file)])
    os.execv(sys.executable, new_argv)


def daemonize(*, pid_file: Path, log_file: Path, wait_seconds: float = 10.0) -> None:
    """Compat wrapper used by tests."""
    daemonize_reexec(
        pid_file=Path(pid_file),
        log_file=Path(log_file),
        argv=["--daemonize", "--pid-file", str(pid_file), "--log-file", str(log_file)],
        wait_seconds=wait_seconds,
    )


# ---------------------------------------------------------------------------
# Stdlib-only daemon prelude when executed as __main__ with --daemonize.
# Must run BEFORE pandas/numpy import.
# ---------------------------------------------------------------------------
if __name__ == "__main__" and _early_wants_daemonize(sys.argv[1:]):
    _argv = sys.argv[1:]
    daemonize_reexec(
        pid_file=_early_path_arg(_argv, "--pid-file", DEFAULT_PID_PATH),
        log_file=_early_path_arg(_argv, "--log-file", DEFAULT_LOG_PATH),
        argv=_argv,
    )


# ---------------------------------------------------------------------------
# Runtime (safe after re-exec --foreground / --once / module import for tests)
# ---------------------------------------------------------------------------
import atexit  # noqa: E402
import json  # noqa: E402
import signal  # noqa: E402
import ssl  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402

OUT_PATH = ROOT / "data" / "live" / "live_market_intrabar_feed.parquet"
STATUS_PATH = ROOT / "data" / "live" / "intrabar_feed_status.json"
LOG_PATH = DEFAULT_LOG_PATH
PID_PATH = DEFAULT_PID_PATH
HEARTBEAT_PATH = ROOT / "run" / "live_binance_intrabar_feed_heartbeat.json"

SYMBOL = "BTCUSDT"
MAX_ROWS = 50_000
REST_BASE = "https://api.binance.com"

_STOP = False


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _log(msg: str) -> None:
    line = f"{_iso_now()} {msg}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
    try:
        if sys.stdout.isatty():
            print(line, flush=True)
    except Exception:
        pass


def _handle_sig(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    _log("signal_received_stopping")


def _ssl_contexts() -> list[ssl.SSLContext]:
    contexts: list[ssl.SSLContext] = []
    try:
        import certifi  # type: ignore

        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    contexts.append(ssl.create_default_context())
    contexts.append(ssl._create_unverified_context())
    return contexts


def _http_json(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "btc-ml-intrabar-feed/1.0"})
    last_err: Exception | None = None
    for ctx in _ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def m15_bucket(now: datetime | None = None) -> tuple[str, str]:
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    minute = (ts.minute // 15) * 15
    open_ts = ts.replace(minute=minute, second=0, microsecond=0)
    close_ts = open_ts + pd.Timedelta(minutes=15)
    return (
        open_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def fetch_snapshot() -> dict[str, Any]:
    t0 = time.time()
    price_payload = _http_json(f"{REST_BASE}/api/v3/ticker/price?symbol={SYMBOL}")
    book_payload = _http_json(f"{REST_BASE}/api/v3/ticker/bookTicker?symbol={SYMBOL}")
    kline_payload = _http_json(
        f"{REST_BASE}/api/v3/klines?symbol={SYMBOL}&interval=15m&limit=1"
    )
    latency_ms = int((time.time() - t0) * 1000)
    observed = _iso_now()
    open_ts, close_ts = m15_bucket()
    price = float(price_payload["price"])
    bid = float(book_payload.get("bidPrice") or 0) or None
    ask = float(book_payload.get("askPrice") or 0) or None
    k = kline_payload[0] if kline_payload else None
    kline_start = None
    kline_close = None
    if k:
        kline_start_dt = datetime.fromtimestamp(int(k[0]) / 1000.0, tz=timezone.utc)
        kline_close_dt = datetime.fromtimestamp(int(k[6]) / 1000.0, tz=timezone.utc)
        kline_start = kline_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        kline_close = kline_close_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        obs_open, obs_close = m15_bucket()
        if kline_start == obs_open:
            open_ts, close_ts = kline_start, obs_close
        else:
            open_ts, close_ts = obs_open, obs_close
    return {
        "observed_at_utc": observed,
        "exchange_event_time_utc": None,
        "symbol": SYMBOL,
        "price": price,
        "bid": bid,
        "ask": ask,
        "last_trade_price": price,
        "m15_bucket_open_ts": open_ts,
        "m15_bucket_close_ts": close_ts,
        "is_closed_candle": False,
        "source": "BINANCE_PUBLIC",
        "feed_type": "INTRABAR",
        "latency_ms": latency_ms,
        "raw_event_id": f"REST_TICKER_{observed}",
        "sequence": None,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "kline_start_ts": kline_start,
        "kline_close_ts": kline_close,
        "kline_is_closed": False,
        "paper_only": True,
        "execution_enabled": False,
    }


def append_row(row: dict[str, Any], path: Path | None = None) -> int:
    path = path or OUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame([row])
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old, new_df], ignore_index=True)
        if len(df) > MAX_ROWS:
            df = df.iloc[-MAX_ROWS:].reset_index(drop=True)
    else:
        df = new_df
    df.to_parquet(path, index=False)
    return int(len(df))


def write_status(row: dict[str, Any], rows: int, *, running: bool = True) -> None:
    try:
        out_rel = str(OUT_PATH.relative_to(ROOT))
    except ValueError:
        out_rel = str(OUT_PATH)
    payload = {
        "generated_at_utc": _iso_now(),
        "running": running,
        "pid": None if not PID_PATH.exists() else PID_PATH.read_text(encoding="utf-8").strip(),
        "latest_observed_at_utc": row.get("observed_at_utc"),
        "latest_price": row.get("price"),
        "rows": rows,
        "latest_m15_bucket_open_ts": row.get("m15_bucket_open_ts"),
        "latest_m15_bucket_close_ts": row.get("m15_bucket_close_ts"),
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "output_path": out_rel,
        "canonical_m15_feed_untouched": True,
        "execution_enabled": False,
        "paper_only": True,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def once() -> dict[str, Any]:
    row = fetch_snapshot()
    n = append_row(row)
    write_status(row, n, running=False)
    return {"row": row, "rows": n}


def _remove_own_pid_file() -> None:
    try:
        if not PID_PATH.exists():
            return
        cur = PID_PATH.read_text(encoding="utf-8").strip()
        if cur == str(os.getpid()):
            PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def write_heartbeat(
    *,
    latest_observed_at_utc: str | None = None,
    latest_price: float | None = None,
    latest_m15_bucket_open_ts: str | None = None,
    rows_written: int = 0,
    consecutive_errors: int = 0,
    last_error: str | None = None,
    last_success_at_utc: str | None = None,
    feed_status: str = "RUNNING",
) -> None:
    payload = {
        "process_pid": os.getpid(),
        "heartbeat_at_utc": _iso_now(),
        "latest_observed_at_utc": latest_observed_at_utc,
        "latest_price": latest_price,
        "latest_m15_bucket_open_ts": latest_m15_bucket_open_ts,
        "rows_written": int(rows_written),
        "consecutive_errors": int(consecutive_errors),
        "last_error": last_error,
        "last_success_at_utc": last_success_at_utc,
        "feed_status": feed_status,
        "source": "BINANCE_PUBLIC",
        "execution_enabled": False,
        "paper_only": True,
    }
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_loop(interval: int = POLL_INTERVAL_SECONDS) -> int:
    global _STOP
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except Exception:
        pass
    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    atexit.register(_remove_own_pid_file)
    _write_pid_file(PID_PATH, os.getpid())
    _log(f"intrabar_feed_start interval={interval}s out={OUT_PATH} pid={os.getpid()}")
    consecutive_errors = 0
    last_error = None
    last_success_at = None
    latest_observed = None
    latest_price = None
    latest_bucket = None
    rows_written = 0
    if OUT_PATH.exists():
        try:
            df = pd.read_parquet(OUT_PATH)
            rows_written = int(len(df))
            if rows_written and "observed_at_utc" in df.columns:
                latest_observed = str(df.iloc[-1]["observed_at_utc"])
                latest_price = float(df.iloc[-1]["price"]) if "price" in df.columns else None
                latest_bucket = (
                    str(df.iloc[-1]["m15_bucket_open_ts"]) if "m15_bucket_open_ts" in df.columns else None
                )
        except Exception:
            pass
    write_heartbeat(
        latest_observed_at_utc=latest_observed,
        latest_price=latest_price,
        latest_m15_bucket_open_ts=latest_bucket,
        rows_written=rows_written,
        consecutive_errors=0,
        last_error=None,
        last_success_at_utc=last_success_at,
        feed_status="RUNNING",
    )
    while not _STOP:
        try:
            row = fetch_snapshot()
            n = append_row(row)
            write_status(row, n, running=True)
            consecutive_errors = 0
            last_error = None
            last_success_at = row["observed_at_utc"]
            latest_observed = row["observed_at_utc"]
            latest_price = float(row["price"])
            latest_bucket = row.get("m15_bucket_open_ts")
            rows_written = n
            _log(f"appended price={row['price']} observed={row['observed_at_utc']} rows={n}")
            write_heartbeat(
                latest_observed_at_utc=latest_observed,
                latest_price=latest_price,
                latest_m15_bucket_open_ts=latest_bucket,
                rows_written=rows_written,
                consecutive_errors=0,
                last_error=None,
                last_success_at_utc=last_success_at,
                feed_status="RUNNING",
            )
            backoff = interval
        except Exception as exc:  # noqa: BLE001 — keep feed alive across transient errors
            consecutive_errors += 1
            last_error = repr(exc)
            _log(f"poll_error={exc!r} consecutive_errors={consecutive_errors}")
            write_heartbeat(
                latest_observed_at_utc=latest_observed,
                latest_price=latest_price,
                latest_m15_bucket_open_ts=latest_bucket,
                rows_written=rows_written,
                consecutive_errors=consecutive_errors,
                last_error=last_error,
                last_success_at_utc=last_success_at,
                feed_status="DEGRADED",
            )
            # Backoff on errors but stay alive.
            backoff = min(interval * max(1, min(consecutive_errors, 5)), interval * 5)
        for _ in range(int(backoff)):
            if _STOP:
                break
            time.sleep(1)
    _remove_own_pid_file()
    write_heartbeat(
        latest_observed_at_utc=latest_observed,
        latest_price=latest_price,
        latest_m15_bucket_open_ts=latest_bucket,
        rows_written=rows_written,
        consecutive_errors=consecutive_errors,
        last_error=last_error,
        last_success_at_utc=last_success_at,
        feed_status="STOPPED",
    )
    _log("intrabar_feed_stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    global LOG_PATH, PID_PATH
    parser = argparse.ArgumentParser(description="Paper-only Binance intrabar feed")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemonize", action="store_true", help="Double-fork + re-exec (stdlib prelude)")
    parser.add_argument("--foreground", action="store_true", help="Run loop in this process")
    parser.add_argument("--pid-file", type=str, default=str(DEFAULT_PID_PATH))
    parser.add_argument("--log-file", type=str, default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--interval-seconds", type=int, default=POLL_INTERVAL_SECONDS)
    parser.add_argument("--paper-only", action="store_true", default=True)
    parser.add_argument("--no-real-execution", action="store_true", default=True)
    args = parser.parse_args(argv)

    PID_PATH = Path(args.pid_file)
    if not PID_PATH.is_absolute():
        PID_PATH = ROOT / PID_PATH
    LOG_PATH = Path(args.log_file)
    if not LOG_PATH.is_absolute():
        LOG_PATH = ROOT / LOG_PATH

    if args.once:
        out = once()
        print(
            json.dumps(
                {
                    "ok": True,
                    "rows": out["rows"],
                    "observed_at_utc": out["row"]["observed_at_utc"],
                    "price": out["row"]["price"],
                },
                indent=2,
            )
        )
        return 0

    # If someone calls main(['--daemonize']) after import, still handle safely
    # by re-execing via a fresh subprocess to avoid fork-after-pandas.
    if args.daemonize and not args.foreground:
        import subprocess

        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--daemonize",
            "--pid-file",
            str(PID_PATH),
            "--log-file",
            str(LOG_PATH),
            "--interval-seconds",
            str(args.interval_seconds),
            "--paper-only",
            "--no-real-execution",
        ]
        return subprocess.call(cmd)

    return run_loop(interval=max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
