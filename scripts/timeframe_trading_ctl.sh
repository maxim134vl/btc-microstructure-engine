#!/usr/bin/env bash
# Start / stop / status / tail for the S4.1 manager and the four timeframe traders.
# PAPER ONLY. No real execution, no exchange calls.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

TIMEFRAMES=(M15 M30 H1 H4)
ROLES=(timeframe_manager trader_M15 trader_M30 trader_H1 trader_H4)
INTERVAL="${INTERVAL_SECONDS:-60}"

mkdir -p "$ROOT/run" "$ROOT/logs"

pid_file() { printf '%s/run/%s.pid' "$ROOT" "$1"; }
lock_file() { printf '%s/run/%s.lock' "$ROOT" "$1"; }
log_file() { printf '%s/logs/%s.log' "$ROOT" "$1"; }

pid_alive() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

read_pid() {
  local f
  f="$(pid_file "$1")"
  [[ -f "$f" ]] && tr -d '[:space:]' <"$f" || true
}

script_for() {
  case "$1" in
    timeframe_manager) printf 'scripts/live/timeframe_manager_daemon.py' ;;
    trader_*) printf 'scripts/live/timeframe_trader_daemon.py' ;;
  esac
}

list_pids() {
  local role="$1" pattern
  case "$role" in
    timeframe_manager) pattern='scripts/live/timeframe_manager_daemon\.py' ;;
    trader_*) pattern="scripts/live/timeframe_trader_daemon\.py --timeframe ${role#trader_}( |$)" ;;
  esac
  ps -ax -o pid=,command= 2>/dev/null | awk -v pat="$pattern" '$0 ~ pat && $0 !~ /timeframe_trading_ctl/ && $0 !~ /awk/ { print $1 }'
}

cleanup_stale() {
  local role="$1" pid
  pid="$(read_pid "$role")"
  if [[ -n "${pid:-}" ]] && ! pid_alive "$pid"; then
    echo "stale_pid_cleanup role=$role pid=$pid"
    rm -f "$(pid_file "$role")" "$(lock_file "$role")"
  fi
  if [[ -z "${pid:-}" ]]; then
    rm -f "$(lock_file "$role")" 2>/dev/null || true
  fi
}

start_role() {
  local role="$1"
  cleanup_stale "$role"
  local existing
  existing="$(list_pids "$role" | head -n 1 || true)"
  if [[ -n "${existing:-}" ]]; then
    echo "already_running role=$role pid=$existing"
    return 0
  fi
  local log
  log="$(log_file "$role")"
  if [[ "$role" == "timeframe_manager" ]]; then
    nohup "$PYTHON" "$ROOT/scripts/live/timeframe_manager_daemon.py" \
      --approved-timeframe-manager --paper-only --no-real-execution \
      --interval-seconds "$INTERVAL" >>"$log" 2>&1 &
  else
    local tf="${role#trader_}"
    nohup "$PYTHON" "$ROOT/scripts/live/timeframe_trader_daemon.py" \
      --timeframe "$tf" \
      --approved-timeframe-trader --paper-only --no-real-execution \
      --interval-seconds "$INTERVAL" >>"$log" 2>&1 &
  fi
  local pid=$!
  sleep 2
  if pid_alive "$pid"; then
    echo "started role=$role pid=$pid"
  else
    echo "start_failed role=$role (see $log)"
    return 1
  fi
}

stop_role() {
  local role="$1" pids
  pids="$(list_pids "$role" || true)"
  if [[ -z "${pids:-}" ]]; then
    cleanup_stale "$role"
    echo "not_running role=$role"
    return 0
  fi
  local pid
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  local waited=0
  while [[ $waited -lt 20 ]]; do
    pids="$(list_pids "$role" || true)"
    [[ -z "${pids:-}" ]] && break
    sleep 1
    waited=$((waited + 1))
  done
  pids="$(list_pids "$role" || true)"
  if [[ -n "${pids:-}" ]]; then
    for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
    echo "force_stopped role=$role pids=$pids"
  else
    echo "stopped role=$role"
  fi
  rm -f "$(pid_file "$role")" "$(lock_file "$role")"
}

status_role() {
  local role="$1" pid pids count
  pid="$(read_pid "$role")"
  pids="$(list_pids "$role" | tr '\n' ' ' || true)"
  count="$(list_pids "$role" | wc -l | tr -d ' ')"
  local alive="false"
  pid_alive "${pid:-}" && alive="true"
  local zombie="false"
  [[ "$count" -gt 1 ]] && zombie="true"
  printf 'role=%s pid_file=%s alive=%s process_pids=[%s] duplicate_writers=%s\n' \
    "$role" "${pid:-none}" "$alive" "${pids% }" "$zombie"
}

resolve_roles() {
  if [[ $# -eq 0 || "${1:-}" == "all" ]]; then
    printf '%s\n' "${ROLES[@]}"
    return
  fi
  local arg
  for arg in "$@"; do
    case "$arg" in
      manager) printf 'timeframe_manager\n' ;;
      traders) printf 'trader_M15\ntrader_M30\ntrader_H1\ntrader_H4\n' ;;
      M15|M30|H1|H4) printf 'trader_%s\n' "$arg" ;;
      D1) echo "refused role=trader_D1 reason=TIMEFRAME_NOT_LIVE/NO_LIVE_STAGE2_WRITER" >&2 ;;
      *) printf '%s\n' "$arg" ;;
    esac
  done
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  start)
    while read -r role; do start_role "$role"; done < <(resolve_roles "$@")
    ;;
  stop)
    while read -r role; do stop_role "$role"; done < <(resolve_roles "$@")
    ;;
  restart)
    while read -r role; do stop_role "$role"; start_role "$role"; done < <(resolve_roles "$@")
    ;;
  status)
    while read -r role; do status_role "$role"; done < <(resolve_roles "$@")
    ;;
  tail)
    role="$(resolve_roles "${1:-timeframe_manager}" | head -n 1)"
    tail -n "${LINES:-60}" "$(log_file "$role")"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|tail} [all|manager|traders|M15|M30|H1|H4]" >&2
    exit 2
    ;;
esac
