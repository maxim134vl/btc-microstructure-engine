#!/usr/bin/env bash
# Start / stop / status / tail / healthcheck / restart for paper-only Binance intrabar feed.
# Start uses Python --daemonize (os.fork + os.setsid). Does NOT use shell setsid.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
PID_FILE="$ROOT/run/live_binance_intrabar_feed.pid"
LOCK_FILE="$ROOT/run/live_binance_intrabar_feed.lock"
LOG_FILE="$ROOT/logs/live_binance_intrabar_feed.log"
STATUS_JSON="$ROOT/data/live/intrabar_feed_status.json"
FEED_SCRIPT="$ROOT/scripts/live/live_binance_intrabar_feed.py"
FEED_PARQUET="$ROOT/data/live/live_market_intrabar_feed.parquet"

mkdir -p "$ROOT/run" "$ROOT/logs" "$ROOT/data/live"

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' <"$PID_FILE" || true
  fi
}

list_feed_pids() {
  ps -ax -o pid=,command= 2>/dev/null | awk '
    /scripts\/live\/live_binance_intrabar_feed\.py/ &&
    $0 !~ /intrabar_feed_ctl/ &&
    $0 !~ /grep/ &&
    $0 !~ /check_intrabar_feed/ &&
    $0 !~ /pytest/ {
      print $1
    }'
}

classify_status() {
  local pid alive live_count live_pids orphan_count duplicate_count
  pid="$(read_pid)"
  alive=false
  if pid_alive "$pid"; then
    alive=true
  fi
  live_count=0
  live_pids=""
  orphan_count=0
  for lp in $(list_feed_pids); do
    if pid_alive "$lp"; then
      live_count=$((live_count + 1))
      live_pids="${live_pids},${lp}"
      if [[ -z "${pid:-}" ]] || [[ "$lp" != "$pid" ]]; then
        # live process not matching pid file → orphan (or duplicate sibling)
        if [[ -z "${pid:-}" ]] || [[ "$alive" != "true" ]]; then
          orphan_count=$((orphan_count + 1))
        elif [[ "$lp" != "$pid" ]]; then
          orphan_count=$((orphan_count + 1))
        fi
      fi
    fi
  done
  live_pids="${live_pids#,}"
  if [[ "$live_count" -eq 0 ]] && [[ "$alive" == "true" ]]; then
    live_count=1
    live_pids="${pid}"
    orphan_count=0
  fi
  duplicate_count=0
  if [[ "$live_count" -gt 1 ]]; then
    duplicate_count=$((live_count - 1))
  fi

  echo "pid_file_exists=$([[ -f $PID_FILE ]] && echo true || echo false)"
  echo "pid_file_pid=${pid:-}"
  echo "pid_file_alive=$alive"
  echo "live_intrabar_feed_count=$live_count"
  echo "live_intrabar_feed_pids=[${live_pids}]"
  echo "duplicate_count=$duplicate_count"
  echo "orphan_count=$orphan_count"

  if [[ "$live_count" -gt 1 ]]; then
    echo "status=DUPLICATE_RUNNING"
  elif [[ "$live_count" -eq 1 ]] && [[ "$alive" != "true" ]]; then
    echo "status=ORPHAN_RUNNING"
  elif [[ "$live_count" -eq 1 ]] && [[ "$alive" == "true" ]]; then
    echo "status=RUNNING"
  elif [[ -n "${pid:-}" ]] && [[ "$alive" != "true" ]]; then
    echo "status=STALE_PID"
  else
    echo "status=STOPPED"
  fi
}

print_parquet_stats() {
  "$PYTHON" - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
root = Path(r"""$ROOT""")
pq = root / "data/live/live_market_intrabar_feed.parquet"
status = root / "data/live/intrabar_feed_status.json"
now = datetime.now(timezone.utc)
rows = 0
latest = None
price = None
bucket = None
cadence = None
age = None
if pq.exists():
    df = pd.read_parquet(pq)
    rows = len(df)
    if rows and "observed_at_utc" in df.columns:
        ts = pd.to_datetime(df["observed_at_utc"], utc=True, errors="coerce").dropna().sort_values()
        if len(ts):
            latest = ts.iloc[-1]
            age = (now - latest.to_pydatetime()).total_seconds()
            d = ts.diff().dt.total_seconds().dropna()
            cadence = float(d.median()) if len(d) else None
            price = float(df.iloc[-1]["price"]) if "price" in df.columns else None
            bucket = str(df.iloc[-1].get("m15_bucket_open_ts")) if "m15_bucket_open_ts" in df.columns else None
print(f"rows={rows}")
print(f"latest_observed_at_utc={latest.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if latest is not None else ''}")
print(f"latest_price={price if price is not None else ''}")
print(f"latest_m15_bucket={bucket or ''}")
print(f"seconds_since_latest_row={age if age is not None else ''}")
print(f"estimated_cadence_seconds={cadence if cadence is not None else ''}")
if status.exists():
    try:
        payload = json.loads(status.read_text(encoding="utf-8"))
        print(json.dumps(payload, indent=2)[:1200])
    except Exception as exc:
        print(f"status_json_error={exc}")
PY
}

cmd="${1:-status}"

case "$cmd" in
  start)
    # Healthy running → no-op
    status_line="$(classify_status | awk -F= '/^status=/{print $2}')"
    pid="$(read_pid)"
    if [[ "$status_line" == "RUNNING" ]] && pid_alive "$pid"; then
      echo "already running pid=$pid"
      classify_status
      print_parquet_stats
      exit 0
    fi
    # Stale pid → clean
    if [[ "$status_line" == "STALE_PID" ]]; then
      echo "cleaning stale pid file"
      rm -f "$PID_FILE" "$LOCK_FILE"
    fi
    # Orphan / duplicate → stop then start
    if [[ "$status_line" == "ORPHAN_RUNNING" ]] || [[ "$status_line" == "DUPLICATE_RUNNING" ]]; then
      echo "adopting/stopping $status_line"
      bash "$0" stop || true
    fi

    # Synchronous start: Python parent waits for daemon pid file then exits.
    # Detach uses Python os.fork + os.setsid only (no external detach helper).
    set +e
    "$PYTHON" "$FEED_SCRIPT" \
      --daemonize \
      --pid-file "$PID_FILE" \
      --log-file "$LOG_FILE" \
      --paper-only \
      --no-real-execution \
      --interval-seconds 60
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "start_failed rc=$rc (see $LOG_FILE)"
      exit 1
    fi

    # Wait up to 10s for pid + heartbeat/log
    ok=0
    for _ in $(seq 1 20); do
      pid="$(read_pid)"
      if [[ -n "${pid:-}" ]] && pid_alive "$pid"; then
        if [[ -f "$LOG_FILE" ]] && grep -q "intrabar_feed_start" "$LOG_FILE" 2>/dev/null; then
          ok=1
          break
        fi
        # pid alive is enough even before first log flush race
        ok=1
        break
      fi
      sleep 0.5
    done
    if [[ "$ok" -ne 1 ]]; then
      echo "start_failed: no live pid after wait (see $LOG_FILE)"
      exit 1
    fi
    printf '%s\n' "$(read_pid)" >"$LOCK_FILE"
    echo "started pid=$(read_pid)"
    echo "log=$LOG_FILE"
    echo "parquet=$FEED_PARQUET"
    classify_status
    print_parquet_stats
    ;;

  stop)
    for lp in $(list_feed_pids); do
      if pid_alive "$lp"; then
        echo "stopping pid=$lp"
        kill -TERM "$lp" 2>/dev/null || true
      fi
    done
    pid="$(read_pid)"
    if [[ -n "${pid:-}" ]] && pid_alive "$pid"; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
    # graceful wait
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      still=0
      for lp in $(list_feed_pids); do
        if pid_alive "$lp"; then still=1; fi
      done
      if [[ -n "${pid:-}" ]] && pid_alive "$pid"; then still=1; fi
      if [[ "$still" -eq 0 ]]; then
        break
      fi
      sleep 0.5
    done
    for lp in $(list_feed_pids); do
      if pid_alive "$lp"; then
        echo "sigkill pid=$lp"
        kill -KILL "$lp" 2>/dev/null || true
      fi
    done
    pid="$(read_pid)"
    if [[ -n "${pid:-}" ]] && pid_alive "$pid"; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE" "$LOCK_FILE"
    echo "stopped"
    echo "live_intrabar_feed_count=0"
    ;;

  restart)
    bash "$0" stop || true
    bash "$0" start
    bash "$0" status
    count="$(list_feed_pids | wc -l | tr -d ' ')"
    echo "exact_process_count=${count}"
    ;;

  status)
    classify_status
    print_parquet_stats
    ;;

  tail)
    tail -n 80 "$LOG_FILE"
    ;;

  healthcheck)
    status_blob="$(classify_status)"
    echo "$status_blob"
    status_line="$(echo "$status_blob" | awk -F= '/^status=/{print $2}')"
    dup="$(echo "$status_blob" | awk -F= '/^duplicate_count=/{print $2}')"
    orphan="$(echo "$status_blob" | awk -F= '/^orphan_count=/{print $2}')"
    live_count="$(echo "$status_blob" | awk -F= '/^live_intrabar_feed_count=/{print $2}')"
    export HC_STATUS="$status_line"
    export HC_DUP="$dup"
    export HC_ORPHAN="$orphan"
    export HC_LIVE_COUNT="$live_count"
    export HC_ROOT="$ROOT"
    "$PYTHON" - <<'PY'
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

root = Path(os.environ["HC_ROOT"])
pq = root / "data/live/live_market_intrabar_feed.parquet"
now = datetime.now(timezone.utc)
rows = 0
latest = None
price = None
age = None
if pq.exists():
    df = pd.read_parquet(pq)
    rows = len(df)
    if rows and "observed_at_utc" in df.columns:
        ts = pd.to_datetime(df["observed_at_utc"], utc=True, errors="coerce").dropna().sort_values()
        if len(ts):
            latest = ts.iloc[-1]
            age = (now - latest.to_pydatetime()).total_seconds()
            price = float(df.iloc[-1]["price"]) if "price" in df.columns else None

status = os.environ.get("HC_STATUS") or ""
dup = int(os.environ.get("HC_DUP") or 0)
orphan = int(os.environ.get("HC_ORPHAN") or 0)
live_count = int(os.environ.get("HC_LIVE_COUNT") or 0)
print(f"health_rows={rows}")
print(f"health_latest_observed_at_utc={latest.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if latest is not None else ''}")
print(f"health_latest_price={price if price is not None else ''}")
print(f"health_seconds_since_latest_row={age if age is not None else ''}")
print(f"health_status={status}")
print(f"health_live_count={live_count}")
print(f"health_duplicate_count={dup}")
print(f"health_orphan_count={orphan}")

reason = None
if status != "RUNNING" or live_count < 1:
    reason = status or "NOT_RUNNING"
elif dup:
    reason = "DUPLICATE_PROCESS"
elif orphan:
    reason = "ORPHAN_PROCESS"
elif age is None:
    reason = "NO_ROWS"
elif age >= 150:
    reason = "STALE_DATA"

if reason is None:
    print("healthcheck=PASS")
    sys.exit(0)
print("healthcheck=FAIL")
print(f"healthcheck_reason={reason}")
sys.exit(1)
PY
    ;;

  *)
    echo "Usage: $0 {start|stop|status|tail|healthcheck|restart}"
    exit 2
    ;;
esac
