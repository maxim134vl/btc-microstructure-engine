#!/usr/bin/env bash
# Unified local runtime stack — start / stop / status
#
# Historical pieces this restores into one command:
#   ./scripts/start_collectors.sh          → collector_watchdog.py
#   ./run.sh / run.py                      → canonical pipeline
#   dashboard/scripts/start_dashboard.sh   → API :8080 + UI :5173
# Docker equivalent (when deploy/ present): make up / make down / make ps
#
# Dashboard API/UI are always refreshed on start (not adopted) so Model Summary
# source-priority code changes load without a separate restart.
#
# Does NOT change engine/runtime logic — orchestration only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/venv/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

STACK_DIR="${STACK_DIR:-$ROOT/logs/runtime_stack}"
mkdir -p "$STACK_DIR"

WATCHDOG_PID_FILE="$STACK_DIR/collector_watchdog.pid"
RUNTIME_PID_FILE="$STACK_DIR/runtime.pid"
RUNTIME_PID_COMPAT="$ROOT/runtime.pid"
API_PID_FILE="$STACK_DIR/dashboard_api.pid"
UI_PID_FILE="$STACK_DIR/dashboard_ui.pid"
CONTEXT_VISUAL_REFRESHER_PID_FILE="$STACK_DIR/context_visual_refresher.pid"
CONTEXT_VISUAL_REFRESHER_PID_COMPAT="$ROOT/runtime_context_visual_refresher.pid"
CONTEXT_VISUAL_REFRESHER_LOCK="$ROOT/runtime_context_visual_refresher.lock"
CONTEXT_VISUAL_VIEWER_PID_FILE="$STACK_DIR/context_visual_viewer.pid"
INTRABAR_SUPERVISOR_PID_FILE="$STACK_DIR/intrabar_process_supervisor.pid"

WATCHDOG_LOG="$STACK_DIR/collector_watchdog.log"
RUNTIME_LOG="$STACK_DIR/runtime.log"
API_LOG="$STACK_DIR/dashboard_api.log"
UI_LOG="$STACK_DIR/dashboard_ui.log"
CONTEXT_VISUAL_REFRESHER_LOG="$ROOT/logs/context_visual_refresher.log"
CONTEXT_VISUAL_VIEWER_LOG="$STACK_DIR/context_visual_viewer.log"
INTRABAR_SUPERVISOR_LOG="$STACK_DIR/intrabar_process_supervisor.log"
CONTEXT_VISUAL_STATUS_JSON="$ROOT/apps/context_visualizer/public/data/visual_status.json"

API_PORT="${DASHBOARD_PORT:-8080}"
UI_PORT="${DASHBOARD_UI_PORT:-5173}"
UI_HOST="${DASHBOARD_UI_HOST:-127.0.0.1}"
CONTEXT_VISUAL_PORT="${CONTEXT_VISUAL_PORT:-8765}"
CONTEXT_VISUAL_INTERVAL_SECONDS="${CONTEXT_VISUAL_INTERVAL_SECONDS:-20}"
CONTEXT_VISUAL_PUBLIC="$ROOT/apps/context_visualizer/public"

usage() {
  cat <<EOF
Usage: $(basename "$0") {start|stop|status|restart}

  start    Start collector watchdog, intrabar supervisor, runtime, dashboard, context visual refresher
  stop     Stop stack processes managed by this launcher
  status   Show process / port / feed / context visual health
  restart  stop + start

Makefile:
  make runtime-stack
  make runtime-stack-stop
  make runtime-stack-status
EOF
}

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d '[:space:]' <"$file" || true
  fi
}

write_pid() {
  printf '%s\n' "$2" >"$1"
}

clear_pid() {
  rm -f "$1"
}

proc_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
}

proc_args() {
  ps -p "$1" -o args= 2>/dev/null || true
}

# True if pid belongs to this repo (cwd or absolute path in argv).
pid_in_repo() {
  local pid="$1"
  local cwd args
  cwd="$(proc_cwd "$pid")"
  args="$(proc_args "$pid")"
  [[ "$cwd" == "$ROOT" || "$cwd" == "$ROOT"/* ]] && return 0
  [[ "$args" == *"$ROOT"* ]] && return 0
  return 1
}

find_repo_pids() {
  local pattern="$1"
  local pid
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    if pid_in_repo "$pid"; then
      echo "$pid"
    fi
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

first_repo_pid() {
  find_repo_pids "$1" | head -1
}

adopt_or_skip() {
  local name="$1" pid_file="$2" pattern="$3"
  local pid
  pid="$(read_pid "$pid_file")"
  if pid_alive "$pid"; then
    echo "  [skip] $name already running (pid=$pid)"
    return 0
  fi
  pid="$(first_repo_pid "$pattern")"
  if pid_alive "$pid"; then
    write_pid "$pid_file" "$pid"
    echo "  [adopt] $name pid=$pid"
    return 0
  fi
  return 1
}

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true
  fi
}

kill_pid_tree() {
  local pid="$1"
  if ! pid_alive "$pid"; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  sleep 0.4
  if pid_alive "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi
}

# Start a command in a new session so IDE/shell teardown cannot kill the stack.
detach_start() {
  local pid_file="$1"
  local log_file="$2"
  shift 2
  STACK_PID_FILE="$pid_file" STACK_LOG_FILE="$log_file" STACK_CWD="$PWD" \
    "$PYTHON" - "$@" <<'PY'
import os, subprocess, sys

pid_file = os.environ["STACK_PID_FILE"]
log_file = os.environ["STACK_LOG_FILE"]
cwd = os.environ.get("STACK_CWD") or None
cmd = sys.argv[1:]
log = open(log_file, "a", encoding="utf-8")
proc = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    cwd=cwd,
    start_new_session=True,
    env=os.environ.copy(),
)
with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(proc.pid) + "\n")
print(proc.pid)
PY
}

free_port_if_needed() {
  local port="$1" keep_pid="${2:-}"
  local p
  for p in $(port_pids "$port"); do
    if [[ -n "$keep_pid" && "$p" == "$keep_pid" ]]; then
      continue
    fi
    echo "  [port] freeing :$port (pid=$p)"
    kill_pid_tree "$p"
  done
}

stop_pid_file() {
  local name="$1" pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")"
  if pid_alive "$pid"; then
    echo "  [stop] $name pid=$pid"
    kill_pid_tree "$pid"
  else
    echo "  [stop] $name not running"
  fi
  clear_pid "$pid_file"
}

stop_matching() {
  local name="$1" pattern="$2"
  local pid
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    echo "  [stop] $name pid=$pid"
    kill_pid_tree "$pid"
  done < <(find_repo_pids "$pattern")
}

stop_collector_children() {
  if [[ ! -f "$ROOT/data/live/collector_pids.json" ]]; then
    return 0
  fi
  "$PYTHON" - <<'PY' || true
import json, os, signal
path = "data/live/collector_pids.json"
try:
    with open(path, encoding="utf-8") as f:
        pids = json.load(f)
except Exception:
    raise SystemExit(0)
for name, pid in list(pids.items()):
    try:
        pid = int(pid)
        os.kill(pid, signal.SIGTERM)
        print(f"  [stop] collector {name} pid={pid}")
    except Exception:
        pass
PY
}

start_intrabar_supervisor() {
  if adopt_or_skip "intrabar_process_supervisor" "$INTRABAR_SUPERVISOR_PID_FILE" "intrabar_process_supervisor.py"; then
    return 0
  fi
  echo "  [start] intrabar_process_supervisor.py"
  detach_start "$INTRABAR_SUPERVISOR_PID_FILE" "$INTRABAR_SUPERVISOR_LOG" \
    "$PYTHON" scripts/live/intrabar_process_supervisor.py >/dev/null
  sleep 1
}

start_watchdog() {
  if adopt_or_skip "collector_watchdog" "$WATCHDOG_PID_FILE" "collector_watchdog.py"; then
    return 0
  fi
  # Avoid duplicate feed writers left from prior manual starts
  local feed_pid
  while read -r feed_pid; do
    [[ -z "$feed_pid" ]] && continue
    if pid_in_repo "$feed_pid" || [[ "$(proc_cwd "$feed_pid")" == "$ROOT" ]]; then
      echo "  [cleanup] stale live_binance_feed pid=$feed_pid"
      kill_pid_tree "$feed_pid"
    fi
  done < <(pgrep -f "live_binance_feed_v2\\.py" 2>/dev/null || true)

  echo "  [start] collector_watchdog.py --required-only"
  detach_start "$WATCHDOG_PID_FILE" "$WATCHDOG_LOG" \
    "$PYTHON" collector_watchdog.py --required-only >/dev/null
  sleep 1
}

start_runtime() {
  if adopt_or_skip "runtime" "$RUNTIME_PID_FILE" "run\\.py"; then
    write_pid "$RUNTIME_PID_COMPAT" "$(read_pid "$RUNTIME_PID_FILE")"
    return 0
  fi
  # Fallback: plain "run.py" argv with repo cwd
  local pid
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    local args
    args="$(proc_args "$pid")"
    if [[ "$args" == *" run.py"* || "$args" == *"/run.py"* || "$args" == "run.py"* ]]; then
      if pid_in_repo "$pid" || [[ "$(proc_cwd "$pid")" == "$ROOT" ]]; then
        write_pid "$RUNTIME_PID_FILE" "$pid"
        write_pid "$RUNTIME_PID_COMPAT" "$pid"
        echo "  [adopt] runtime pid=$pid"
        return 0
      fi
    fi
  done < <(pgrep -f "run\\.py" 2>/dev/null || true)

  echo "  [start] run.py (persistent_worker)"
  BTC_ML_ENGINE_EXECUTION_MODE=persistent_worker PYTHONUNBUFFERED=1 \
    "$PYTHON" - "$RUNTIME_PID_FILE" "$RUNTIME_LOG" "$ROOT" "$PYTHON" <<'PY'
import os, subprocess, sys
pid_file, log_file, root, python = sys.argv[1:5]
os.chdir(root)
log = open(log_file, "a", encoding="utf-8")
env = os.environ.copy()
env["BTC_ML_ENGINE_EXECUTION_MODE"] = "persistent_worker"
env["PYTHONUNBUFFERED"] = "1"
proc = subprocess.Popen(
    [python, "run.py"],
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    cwd=root,
    start_new_session=True,
    env=env,
)
open(pid_file, "w", encoding="utf-8").write(str(proc.pid) + "\n")
PY
  write_pid "$RUNTIME_PID_COMPAT" "$(read_pid "$RUNTIME_PID_FILE")"
  sleep 0.5
}

start_dashboard_api() {
  # Always refresh API on stack start so dashboard code changes are loaded.
  # Adopting a long-lived :8080 process was keeping Stage 10 payloads in memory
  # after Stage 11 source-priority changes.
  local listener existing
  listener="$(port_pids "$API_PORT" | head -1 || true)"
  if pid_alive "$listener"; then
    echo "  [refresh] stopping existing dashboard_api on :$API_PORT pid=$listener"
    kill_pid_tree "$listener"
  fi
  existing="$(first_repo_pid "run_api\\.py")"
  if pid_alive "$existing"; then
    echo "  [refresh] stopping existing run_api.py pid=$existing"
    kill_pid_tree "$existing"
  fi
  clear_pid "$API_PID_FILE"
  free_port_if_needed "$API_PORT"

  : >"$API_LOG"
  echo "  [start] dashboard API :$API_PORT"
  (
    cd "$ROOT/dashboard/backend"
    STACK_CWD="$PWD" detach_start "$API_PID_FILE" "$API_LOG" \
      env PYTHONPATH=".:../.." "$PYTHON" run_api.py >/dev/null
  )
  # Wait until port is up (or process dies)
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if [[ -n "$(port_pids "$API_PORT")" ]]; then
      write_pid "$API_PID_FILE" "$(port_pids "$API_PORT" | head -1)"
      echo "  [ok] dashboard API listening on :$API_PORT"
      return 0
    fi
    if ! pid_alive "$(read_pid "$API_PID_FILE")"; then
      echo "  [warn] dashboard API exited — see $API_LOG"
      return 1
    fi
    sleep 0.5
  done
  echo "  [warn] dashboard API started but :$API_PORT not listening yet — see $API_LOG"
}

start_dashboard_ui() {
  # Always refresh UI on stack start so Vite serves current src (not a stale process).
  local listener existing
  listener="$(port_pids "$UI_PORT" | head -1 || true)"
  if pid_alive "$listener"; then
    echo "  [refresh] stopping existing dashboard_ui on :$UI_PORT pid=$listener"
    kill_pid_tree "$listener"
  fi
  existing="$(first_repo_pid "vite")"
  if pid_alive "$existing"; then
    echo "  [refresh] stopping existing vite pid=$existing"
    kill_pid_tree "$existing"
  fi
  clear_pid "$UI_PID_FILE"
  free_port_if_needed "$UI_PORT"

  : >"$UI_LOG"
  echo "  [start] dashboard UI http://${UI_HOST}:${UI_PORT}"
  if [[ ! -d "$ROOT/dashboard/frontend/node_modules" ]]; then
    echo "  [npm] installing frontend dependencies"
    (
      cd "$ROOT/dashboard/frontend"
      if [[ -f package-lock.json ]]; then npm ci >>"$UI_LOG" 2>&1; else npm install >>"$UI_LOG" 2>&1; fi
    )
  fi
  (
    cd "$ROOT/dashboard/frontend"
    STACK_CWD="$PWD" detach_start "$UI_PID_FILE" "$UI_LOG" \
      npm run dev -- --host "$UI_HOST" --port "$UI_PORT" >/dev/null
  )
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if [[ -n "$(port_pids "$UI_PORT")" ]]; then
      write_pid "$UI_PID_FILE" "$(port_pids "$UI_PORT" | head -1)"
      echo "  [ok] dashboard UI listening on :$UI_PORT (vite dev / src)"
      return 0
    fi
    if ! pid_alive "$(read_pid "$UI_PID_FILE")"; then
      echo "  [warn] dashboard UI exited — see $UI_LOG"
      return 1
    fi
    sleep 0.5
  done
  echo "  [warn] dashboard UI started but :$UI_PORT not listening yet — see $UI_LOG"
}

stop_context_visual_refresher() {
  local pid
  pid="$(read_pid "$CONTEXT_VISUAL_REFRESHER_PID_FILE")"
  if pid_alive "$pid"; then
    echo "  [stop] context_visual_refresher pid=$pid"
    kill_pid_tree "$pid"
  fi
  pid="$(read_pid "$CONTEXT_VISUAL_REFRESHER_PID_COMPAT")"
  if pid_alive "$pid"; then
    echo "  [stop] context_visual_refresher (compat) pid=$pid"
    kill_pid_tree "$pid"
  fi
  stop_matching "context_visual_refresher" "run_market_context_visual_refresher\\.py"
  clear_pid "$CONTEXT_VISUAL_REFRESHER_PID_FILE"
  clear_pid "$CONTEXT_VISUAL_REFRESHER_PID_COMPAT"
  rm -f "$CONTEXT_VISUAL_REFRESHER_LOCK"
}

start_context_visual_refresher() {
  # Never silently adopt an old refresher — always restart fresh (like dashboard API).
  echo "  [context-visual-refresher] starting"
  stop_context_visual_refresher

  mkdir -p "$ROOT/logs" "$(dirname "$CONTEXT_VISUAL_STATUS_JSON")"
  : >>"$CONTEXT_VISUAL_REFRESHER_LOG"

  # Immediate one-shot so the chart is fresh before the loop settles.
  echo "  [context-visual-refresher] immediate refresh (--once)"
  (
    cd "$ROOT"
    "$PYTHON" scripts/live/run_market_context_visual_refresher.py --once \
      >>"$CONTEXT_VISUAL_REFRESHER_LOG" 2>&1 || true
  )

  detach_start "$CONTEXT_VISUAL_REFRESHER_PID_FILE" "$CONTEXT_VISUAL_REFRESHER_LOG" \
    "$PYTHON" scripts/live/run_market_context_visual_refresher.py \
    --interval-seconds "$CONTEXT_VISUAL_INTERVAL_SECONDS" >/dev/null

  local pid
  pid="$(read_pid "$CONTEXT_VISUAL_REFRESHER_PID_FILE")"
  write_pid "$CONTEXT_VISUAL_REFRESHER_PID_COMPAT" "$pid"
  echo "  [context-visual-refresher] pid=$pid"
  if [[ -f "$CONTEXT_VISUAL_STATUS_JSON" ]]; then
    "$PYTHON" - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("apps/context_visualizer/public/data/visual_status.json")
data = json.loads(p.read_text(encoding="utf-8"))
print(f"  [context-visual-refresher] last_refresh={data.get('last_visual_refresh_ts')}")
print(f"  [context-visual-refresher] source_lag_min={data.get('source_lag_minutes')} status={data.get('visual_data_status')}")
PY
  fi
}

start_context_visual_viewer() {
  # Static sandbox viewer for lifecycle JSON (http://127.0.0.1:8765/).
  local listener existing
  listener="$(port_pids "$CONTEXT_VISUAL_PORT" | head -1 || true)"
  if pid_alive "$listener"; then
    echo "  [refresh] stopping existing context_visual_viewer on :$CONTEXT_VISUAL_PORT pid=$listener"
    kill_pid_tree "$listener"
  fi
  existing="$(first_repo_pid "http\\.server ${CONTEXT_VISUAL_PORT}")"
  if pid_alive "$existing"; then
    echo "  [refresh] stopping existing http.server :$CONTEXT_VISUAL_PORT pid=$existing"
    kill_pid_tree "$existing"
  fi
  clear_pid "$CONTEXT_VISUAL_VIEWER_PID_FILE"
  free_port_if_needed "$CONTEXT_VISUAL_PORT"

  : >"$CONTEXT_VISUAL_VIEWER_LOG"
  echo "  [start] context visual viewer http://127.0.0.1:${CONTEXT_VISUAL_PORT}/"
  (
    cd "$CONTEXT_VISUAL_PUBLIC"
    STACK_CWD="$PWD" detach_start "$CONTEXT_VISUAL_VIEWER_PID_FILE" "$CONTEXT_VISUAL_VIEWER_LOG" \
      "$PYTHON" -m http.server "$CONTEXT_VISUAL_PORT" --bind 127.0.0.1 >/dev/null
  )
  local i
  for i in 1 2 3 4 5 6 7 8; do
    if [[ -n "$(port_pids "$CONTEXT_VISUAL_PORT")" ]]; then
      write_pid "$CONTEXT_VISUAL_VIEWER_PID_FILE" "$(port_pids "$CONTEXT_VISUAL_PORT" | head -1)"
      echo "  [ok] context visual viewer listening on :$CONTEXT_VISUAL_PORT"
      return 0
    fi
    sleep 0.25
  done
  echo "  [warn] context visual viewer not listening yet — see $CONTEXT_VISUAL_VIEWER_LOG"
}

cmd_start() {
  echo "BTC-ML runtime stack — start"
  echo "Root: $ROOT"
  echo "Logs: $STACK_DIR"
  echo
  start_watchdog
  start_intrabar_supervisor
  start_runtime
  start_dashboard_api
  start_dashboard_ui
  start_context_visual_refresher
  start_context_visual_viewer
  echo
  cmd_status
}

cmd_stop() {
  echo "BTC-ML runtime stack — stop"
  echo
  stop_pid_file "context_visual_viewer" "$CONTEXT_VISUAL_VIEWER_PID_FILE"
  stop_matching "context_visual_viewer" "http\\.server ${CONTEXT_VISUAL_PORT}"
  free_port_if_needed "$CONTEXT_VISUAL_PORT"
  stop_context_visual_refresher
  stop_pid_file "dashboard_ui" "$UI_PID_FILE"
  stop_matching "dashboard_ui" "vite"
  stop_pid_file "dashboard_api" "$API_PID_FILE"
  stop_matching "dashboard_api" "run_api\\.py"
  free_port_if_needed "$UI_PORT"
  free_port_if_needed "$API_PORT"
  stop_pid_file "runtime" "$RUNTIME_PID_FILE"
  stop_matching "runtime" "run\\.py"
  clear_pid "$RUNTIME_PID_COMPAT"
  stop_pid_file "intrabar_process_supervisor" "$INTRABAR_SUPERVISOR_PID_FILE"
  stop_matching "intrabar_process_supervisor" "intrabar_process_supervisor\\.py"
  stop_pid_file "collector_watchdog" "$WATCHDOG_PID_FILE"
  stop_matching "collector_watchdog" "collector_watchdog\\.py"
  stop_collector_children
  echo
  echo "Stopped."
}

component_line() {
  local name="$1" pid_file="$2" extra="${3:-}"
  local pid status
  pid="$(read_pid "$pid_file")"
  if pid_alive "$pid"; then
    status="UP  pid=$pid"
  else
    status="DOWN"
  fi
  printf "  %-22s %s%s\n" "$name" "$status" "$extra"
}

feed_age() {
  "$PYTHON" - <<'PY' 2>/dev/null || echo "n/a"
from pathlib import Path
import time
candidates = [Path("data/live/live_market_feed.parquet")]
try:
    from storage.path_registry import resolve_read
    candidates.insert(0, Path(resolve_read("live_market_feed.parquet")))
except Exception:
    pass
for p in candidates:
    if p.exists():
        age = time.time() - p.stat().st_mtime
        print(f"{age:.0f}s ago ({p})")
        break
else:
    print("missing")
PY
}

api_health() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 2 "http://127.0.0.1:${API_PORT}/health" 2>/dev/null || echo "unreachable"
  else
    echo "curl missing"
  fi
}

intrabar_supervision_status() {
  echo "Intrabar supervision:"
  component_line "intrabar_process_supervisor" "$INTRABAR_SUPERVISOR_PID_FILE"
  if [[ -f "$ROOT/data/runtime/intrabar_operational_status.json" ]]; then
    "$PYTHON" - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("data/runtime/intrabar_operational_status.json")
data = json.loads(p.read_text(encoding="utf-8"))
for name, svc in (data.get("services") or {}).items():
    print(
        f"  {name:24} lifecycle={svc.get('lifecycle_state')} "
        f"pid={svc.get('pid')} execution={svc.get('execution_state')}"
    )
alerts = data.get("alerts") or []
if alerts:
    print(f"  alerts: {', '.join(alerts)}")
PY
  else
    echo "  operational_status: missing"
  fi
}

context_visual_status() {
  local pid status="STOPPED"
  pid="$(read_pid "$CONTEXT_VISUAL_REFRESHER_PID_FILE")"
  if ! pid_alive "$pid"; then
    pid="$(read_pid "$CONTEXT_VISUAL_REFRESHER_PID_COMPAT")"
  fi
  if pid_alive "$pid"; then
    status="RUNNING"
  fi
  echo "Context Visual Refresher: $status${pid:+  pid=$pid}"
  if [[ -f "$CONTEXT_VISUAL_STATUS_JSON" ]]; then
    "$PYTHON" - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("apps/context_visualizer/public/data/visual_status.json")
data = json.loads(p.read_text(encoding="utf-8"))
print(f"  last_success_at: {data.get('last_success_at')}")
print(f"  last_visual_refresh_ts: {data.get('last_visual_refresh_ts')}")
print(f"  latest_live_feed_ts: {data.get('latest_live_feed_ts')}")
print(f"  latest_decision_log_ts: {data.get('latest_decision_log_ts')}")
print(f"  source_lag_minutes: {data.get('source_lag_minutes')}")
print(f"  visual_data_status: {data.get('visual_data_status')}")
print(f"  refresher_status: {data.get('status')}")
PY
  else
    echo "  status json: missing"
  fi
}

cmd_status() {
  echo "BTC-ML runtime stack — status"
  echo "Root: $ROOT"
  echo
  component_line "collector_watchdog" "$WATCHDOG_PID_FILE"
  component_line "intrabar_process_supervisor" "$INTRABAR_SUPERVISOR_PID_FILE"
  component_line "runtime (run.py)" "$RUNTIME_PID_FILE"
  component_line "dashboard_api" "$API_PID_FILE" "  :${API_PORT}"
  component_line "dashboard_ui" "$UI_PID_FILE" "  :${UI_PORT}"
  component_line "context_visual_refresher" "$CONTEXT_VISUAL_REFRESHER_PID_FILE"
  component_line "context_visual_viewer" "$CONTEXT_VISUAL_VIEWER_PID_FILE" "  :${CONTEXT_VISUAL_PORT}"

  echo
  intrabar_supervision_status

  echo
  context_visual_status

  echo
  echo "Collectors (data/live/collector_pids.json):"
  if [[ -f "$ROOT/data/live/collector_pids.json" ]]; then
    "$PYTHON" - <<'PY' 2>/dev/null || cat data/live/collector_pids.json
import json, os
with open("data/live/collector_pids.json", encoding="utf-8") as f:
    pids = json.load(f)
for name, pid in pids.items():
    alive = False
    try:
        os.kill(int(pid), 0)
        alive = True
    except Exception:
        pass
    print(f"  {name:22} {'UP' if alive else 'DOWN'}  pid={pid}")
PY
  else
    echo "  (none)"
  fi

  echo
  echo "Ports:"
  local p api_listed=0 ui_listed=0 cv_listed=0
  for p in $(port_pids "$API_PORT"); do echo "  :$API_PORT LISTEN pid=$p"; api_listed=1; done
  for p in $(port_pids "$UI_PORT"); do echo "  :$UI_PORT LISTEN pid=$p"; ui_listed=1; done
  for p in $(port_pids "$CONTEXT_VISUAL_PORT"); do echo "  :$CONTEXT_VISUAL_PORT LISTEN pid=$p"; cv_listed=1; done
  [[ "$api_listed" -eq 0 ]] && echo "  :$API_PORT (free)"
  [[ "$ui_listed" -eq 0 ]] && echo "  :$UI_PORT (free)"
  [[ "$cv_listed" -eq 0 ]] && echo "  :$CONTEXT_VISUAL_PORT (free)"

  echo
  echo "Dashboard API /health: $(api_health)"
  echo "live_market_feed mtime: $(feed_age)"
  echo
  echo "Logs: $STACK_DIR"
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_restart ;;
  -h|--help|help) usage ;;
  "") usage; exit 2 ;;
  *) echo "Unknown command: $1"; usage; exit 2 ;;
esac
