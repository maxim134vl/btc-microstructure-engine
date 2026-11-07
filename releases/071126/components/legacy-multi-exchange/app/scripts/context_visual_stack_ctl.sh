#!/usr/bin/env bash
# Context visual stack ctl: viewer (8765) + visual-only refresher.
# macOS-safe: no setsid. Uses nohup + $! pid files.
# Does NOT touch bounded paper controller / paper ledgers / decision log.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

VIEWER_SCRIPT="$ROOT/scripts/live/run_context_visual_viewer_server.py"
REFRESHER_SCRIPT="$ROOT/scripts/live/run_market_context_visual_refresher.py"
VIEWER_PID_FILE="$ROOT/runtime_context_viewer.pid"
REFRESHER_PID_FILE="$ROOT/runtime_context_visual_refresher.pid"
REFRESHER_LOCK="$ROOT/runtime_context_visual_refresher.lock"
VIEWER_LOG="$ROOT/logs/context_viewer_8765.log"
REFRESHER_LOG="$ROOT/logs/context_visual_refresher.log"
VISUAL_STATUS_JSON="$ROOT/apps/context_visualizer/public/data/visual_status.json"
PORT="${CONTEXT_VISUAL_PORT:-8765}"
INTERVAL="${CONTEXT_VISUAL_INTERVAL_SECONDS:-20}"

mkdir -p "$ROOT/logs" "$ROOT/apps/context_visualizer/public/data" "$ROOT/data/research"

read_pid() {
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }
  tr -d '[:space:]' <"$f" || true
}

write_pid() {
  local f="$1" pid="$2"
  printf '%s\n' "$pid" >"$f"
}

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

clear_pid() {
  rm -f "$1"
}

list_viewer_pids() {
  ps -ax -o pid=,command= 2>/dev/null | awk '
    $0 ~ /[Pp]ython/ && $0 ~ /run_context_visual_viewer_server\.py/ && $0 !~ /awk/ && $0 !~ /git / { print $1 }
  '
}

list_refresher_pids() {
  ps -ax -o pid=,command= 2>/dev/null | awk '
    $0 ~ /[Pp]ython/ && $0 ~ /scripts\/live\/run_market_context_visual_refresher\.py/ && $0 !~ /awk/ && $0 !~ /git / { print $1 }
  '
}

port_pids() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2}' | sort -u
}

is_our_viewer_pid() {
  local pid="$1" managed cmd
  managed="$(read_pid "$VIEWER_PID_FILE")"
  [[ -n "$pid" ]] || return 1
  if [[ -n "$managed" && "$pid" == "$managed" ]]; then
    return 0
  fi
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$cmd" == *run_context_visual_viewer_server.py* ]]
}

# macOS-safe background launch: nohup + $! (never setsid).
nohup_start() {
  local pid_file="$1"
  local log_file="$2"
  shift 2
  : >>"$log_file"
  nohup "$@" >>"$log_file" 2>&1 </dev/null &
  local pid=$!
  write_pid "$pid_file" "$pid"
  echo "$pid"
}

stop_pid() {
  local label="$1" pid="$2"
  if pid_alive "$pid"; then
    echo "  [stop] $label pid=$pid"
    kill "$pid" 2>/dev/null || true
    local _
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      pid_alive "$pid" || return 0
      sleep 0.2
    done
    if pid_alive "$pid"; then
      echo "  [kill] $label pid=$pid"
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
}

assert_port_free_or_ours() {
  local listener managed
  listener="$(port_pids | head -1 || true)"
  [[ -n "$listener" ]] || return 0
  managed="$(read_pid "$VIEWER_PID_FILE")"
  if is_our_viewer_pid "$listener"; then
    return 0
  fi
  echo "ERROR: port ${PORT} is occupied by foreign pid=${listener} (not our viewer pid file=${managed:-none})" >&2
  echo "  Refusing to kill foreign process. Free the port manually or stop that service." >&2
  return 1
}

cmd_stop() {
  echo "context-visual-stack stop"
  local pid listener

  # Stop only managed viewer (pid file), then any remaining our-script viewers.
  pid="$(read_pid "$VIEWER_PID_FILE")"
  stop_pid "viewer" "$pid"
  clear_pid "$VIEWER_PID_FILE"
  for pid in $(list_viewer_pids); do
    stop_pid "viewer" "$pid"
  done

  # Do NOT kill foreign listeners on :PORT.
  listener="$(port_pids | head -1 || true)"
  if [[ -n "$listener" ]]; then
    if is_our_viewer_pid "$listener"; then
      stop_pid "viewer-port" "$listener"
    else
      echo "  [warn] port ${PORT} still held by foreign pid=${listener} (left untouched)"
    fi
  fi

  pid="$(read_pid "$REFRESHER_PID_FILE")"
  stop_pid "refresher" "$pid"
  clear_pid "$REFRESHER_PID_FILE"
  for pid in $(list_refresher_pids); do
    stop_pid "refresher" "$pid"
  done

  if [[ -f "$REFRESHER_LOCK" ]]; then
    local lock_pid
    lock_pid="$(read_pid "$REFRESHER_LOCK")"
    if ! pid_alive "$lock_pid"; then
      rm -f "$REFRESHER_LOCK"
      echo "  [lock] cleared stale lock"
    else
      # After stop, holder should be gone; clear if dead.
      if ! pid_alive "$lock_pid"; then
        rm -f "$REFRESHER_LOCK"
      else
        # Our stop may have killed refresher that owned the lock.
        rm -f "$REFRESHER_LOCK"
      fi
    fi
  fi
  echo "  note: bounded paper controller NOT touched"
}

cmd_start() {
  echo "context-visual-stack start"
  echo "  root=$ROOT"
  echo "  launcher=macos_safe_nohup"

  local existing_viewer existing_refresher live_viewers listener
  existing_viewer="$(read_pid "$VIEWER_PID_FILE")"
  existing_refresher="$(read_pid "$REFRESHER_PID_FILE")"
  live_viewers="$(list_viewer_pids | tr '\n' ' ')"
  listener="$(port_pids | head -1 || true)"

  # Plain start never replaces a live managed stack — use restart.
  if pid_alive "$existing_viewer"; then
    echo "ERROR: viewer already running pid=${existing_viewer} (duplicate start blocked)" >&2
    echo "  Use: bash scripts/context_visual_stack_ctl.sh restart" >&2
    return 1
  fi
  if [[ -n "$(list_viewer_pids)" ]]; then
    echo "ERROR: viewer process(es) already running pid(s)=$(list_viewer_pids | tr '\n' ' ')(duplicate start blocked)" >&2
    echo "  Use: bash scripts/context_visual_stack_ctl.sh restart" >&2
    return 1
  fi
  if pid_alive "$existing_refresher"; then
    local rcmd
    rcmd="$(ps -p "$existing_refresher" -o command= 2>/dev/null || true)"
    if [[ "$rcmd" == *run_market_context_visual_refresher.py* ]]; then
      echo "ERROR: refresher already running pid=${existing_refresher} (duplicate start blocked)" >&2
      echo "  Use: bash scripts/context_visual_stack_ctl.sh restart" >&2
      return 1
    fi
  fi
  if [[ -n "$(list_refresher_pids)" ]]; then
    echo "ERROR: refresher process(es) already running pid(s)=$(list_refresher_pids | tr '\n' ' ')(duplicate start blocked)" >&2
    echo "  Use: bash scripts/context_visual_stack_ctl.sh restart" >&2
    return 1
  fi

  # Port occupied by foreign process → refuse (do not kill).
  if [[ -n "$listener" ]]; then
    if is_our_viewer_pid "$listener"; then
      echo "ERROR: port ${PORT} already listening via our viewer pid=${listener} (duplicate start blocked)" >&2
      echo "  Use: bash scripts/context_visual_stack_ctl.sh restart" >&2
      return 1
    fi
    echo "ERROR: port ${PORT} is occupied by foreign pid=${listener}" >&2
    echo "  Refusing to kill foreign process. Free the port manually or stop that service." >&2
    return 1
  fi

  # Clear dead pid / lock leftovers only (no live process kill on plain start).
  if ! pid_alive "$existing_viewer"; then
    clear_pid "$VIEWER_PID_FILE"
  fi
  if ! pid_alive "$existing_refresher"; then
    clear_pid "$REFRESHER_PID_FILE"
  fi
  if [[ -f "$REFRESHER_LOCK" ]] && ! pid_alive "$(read_pid "$REFRESHER_LOCK")"; then
    rm -f "$REFRESHER_LOCK"
  fi

  : >>"$VIEWER_LOG"
  : >>"$REFRESHER_LOG"

  echo "  [refresher] once"
  "$PYTHON" "$REFRESHER_SCRIPT" --once >>"$REFRESHER_LOG" 2>&1 || true

  echo "  [refresher] loop interval=${INTERVAL}s"
  local rpid
  rpid="$(nohup_start "$REFRESHER_PID_FILE" "$REFRESHER_LOG" \
    "$PYTHON" "$REFRESHER_SCRIPT" --interval-seconds "$INTERVAL")"
  sleep 0.3
  if ! pid_alive "$rpid"; then
    echo "ERROR: refresher failed to stay alive pid=${rpid} — see $REFRESHER_LOG" >&2
    return 1
  fi
  echo "  refresher_pid=$rpid alive=true"

  echo "  [viewer] http://127.0.0.1:${PORT}/"
  local vpid
  vpid="$(nohup_start "$VIEWER_PID_FILE" "$VIEWER_LOG" \
    "$PYTHON" "$VIEWER_SCRIPT" --host 127.0.0.1 --port "$PORT")"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
    if pid_alive "$vpid" && [[ -n "$(port_pids)" ]]; then
      echo "  viewer_pid=$vpid port=$PORT listening=true"
      cmd_status
      return 0
    fi
    sleep 0.25
  done
  if ! pid_alive "$vpid"; then
    echo "ERROR: viewer exited early pid=${vpid} — see $VIEWER_LOG" >&2
    return 1
  fi
  if [[ -z "$(port_pids)" ]]; then
    echo "ERROR: viewer pid=${vpid} alive but port ${PORT} not listening — see $VIEWER_LOG" >&2
    return 1
  fi
  cmd_status
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_status() {
  local viewer_pid refresher_pid lock_pid viewer_alive refresher_alive port_listening
  viewer_pid="$(read_pid "$VIEWER_PID_FILE")"
  refresher_pid="$(read_pid "$REFRESHER_PID_FILE")"
  lock_pid="$(read_pid "$REFRESHER_LOCK")"
  viewer_alive=false
  refresher_alive=false
  port_listening=false
  pid_alive "$viewer_pid" && viewer_alive=true
  pid_alive "$refresher_pid" && refresher_alive=true
  [[ -n "$(port_pids)" ]] && port_listening=true

  echo "viewer_pid=${viewer_pid:-none}"
  echo "viewer_alive=${viewer_alive}"
  echo "refresher_pid=${refresher_pid:-none}"
  echo "refresher_alive=${refresher_alive}"
  echo "lock_pid=${lock_pid:-none}"
  echo "lock_active=$(pid_alive "$lock_pid" && echo true || echo false)"
  echo "port_8765_listening=${port_listening}"
  echo "port=${PORT}"

  if [[ -f "$VISUAL_STATUS_JSON" ]]; then
    "$PYTHON" - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("apps/context_visualizer/public/data/visual_status.json")
d = json.loads(p.read_text())
print(f"visual_status={d.get('visual_data_status') or d.get('status')}")
print(f"visual_data_status={d.get('visual_data_status')}")
print(f"visual_refresh_age_seconds={d.get('visual_refresh_age_seconds')}")
print(f"source_lag_minutes={d.get('source_lag_minutes')}")
print(f"last_visual_refresh_ts={d.get('last_visual_refresh_ts')}")
print(f"latest_live_feed_ts={d.get('latest_live_feed_ts')}")
print(f"latest_decision_log_ts={d.get('latest_decision_log_ts')}")
PY
  else
    echo "visual_status=MISSING"
    echo "visual_refresh_age_seconds="
  fi

  if [[ -f "$ROOT/run/bounded_paper_trading_controller_auto_ledger.pid" ]]; then
    local cpid
    cpid="$(read_pid "$ROOT/run/bounded_paper_trading_controller_auto_ledger.pid")"
    echo "bounded_paper_controller_pid=${cpid} alive=$(pid_alive "$cpid" && echo true || echo false) (untouched)"
  fi
}

dedupe_tail() {
  # Collapse adjacent duplicate lines (e.g. historical double-redirect logs).
  local file="$1" n="${2:-40}"
  if [[ ! -f "$file" ]]; then
    echo "(no log)"
    return
  fi
  tail -n "$n" "$file" | awk 'NR==1 || $0 != prev { print; prev=$0 }'
}

cmd_tail() {
  echo "=== refresher ==="
  dedupe_tail "$REFRESHER_LOG" 40
  echo "=== viewer ==="
  dedupe_tail "$VIEWER_LOG" 20
}

usage() {
  cat <<EOF
Usage: $0 {start|stop|restart|status|tail}
Visual stack only. macOS-safe nohup launcher.
Does not stop/start bounded paper controller.
EOF
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  tail) cmd_tail ;;
  *) usage; exit 1 ;;
esac
