#!/usr/bin/env bash
# Start / stop / status / restart for paper-only intrabar feed supervisor.
# Does NOT touch paper controller or runtime-stack.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
PID_FILE="$ROOT/run/live_binance_intrabar_feed_supervisor.pid"
STATE_JSON="$ROOT/run/live_binance_intrabar_feed_supervisor.json"
LOG_FILE="$ROOT/logs/live_binance_intrabar_feed_supervisor.log"
SCRIPT="$ROOT/scripts/live/intrabar_feed_supervisor.py"

mkdir -p "$ROOT/run" "$ROOT/logs"

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' <"$PID_FILE" || true
  fi
}

list_supervisor_pids() {
  ps -ax -o pid=,command= 2>/dev/null | awk '
    /scripts\/live\/intrabar_feed_supervisor\.py/ &&
    $0 !~ /intrabar_feed_supervisor_ctl/ &&
    $0 !~ /grep/ &&
    $0 !~ /pytest/ {
      print $1
    }'
}

cmd="${1:-status}"

case "$cmd" in
  start)
    pid="$(read_pid)"
    if pid_alive "$pid"; then
      echo "already_running pid=$pid"
      exit 0
    fi
    rm -f "$PID_FILE"
    "$PYTHON" "$SCRIPT" --daemonize
    sleep 1
    pid="$(read_pid)"
    if pid_alive "$pid"; then
      echo "started pid=$pid"
      exit 0
    fi
    echo "start_failed"
    exit 1
    ;;
  stop)
    pid="$(read_pid)"
    if pid_alive "$pid"; then
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5; do
        pid_alive "$pid" || break
        sleep 1
      done
      if pid_alive "$pid"; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    for lp in $(list_supervisor_pids); do
      kill "$lp" 2>/dev/null || true
    done
    rm -f "$PID_FILE"
    echo "stopped"
    ;;
  status)
    pid="$(read_pid)"
    alive=false
    if pid_alive "$pid"; then
      alive=true
    fi
    live_count=0
    live_pids=""
    for lp in $(list_supervisor_pids); do
      if pid_alive "$lp"; then
        live_count=$((live_count + 1))
        live_pids="${live_pids},${lp}"
      fi
    done
    live_pids="${live_pids#,}"
    if [[ "$live_count" -ge 1 ]] && [[ "$alive" == "true" ]]; then
      echo "status=RUNNING"
    elif [[ "$live_count" -ge 1 ]]; then
      echo "status=ORPHAN_RUNNING"
    elif [[ -n "${pid:-}" ]] && [[ "$alive" != "true" ]]; then
      echo "status=STALE_PID"
    else
      echo "status=STOPPED"
    fi
    echo "pid_file_pid=${pid:-}"
    echo "pid_file_alive=$alive"
    echo "live_supervisor_count=$live_count"
    echo "live_supervisor_pids=[${live_pids}]"
    if [[ -f "$STATE_JSON" ]]; then
      echo "--- supervisor_state ---"
      cat "$STATE_JSON"
    fi
    ;;
  restart)
    "$0" stop || true
    sleep 1
    "$0" start
    "$0" status
    ;;
  *)
    echo "usage: $0 {start|stop|status|restart}"
    exit 2
    ;;
esac
