#!/usr/bin/env bash
# Dedicated context refresher control (Patch 2A / 2A.1).
# Default: DISABLED. Does not start unless BTC_ML_CONTEXT_REFRESH_DAEMON=1.
#
# Commands: start | stop | restart | status | foreground
# Production macOS activation: start (background via nohup, logs to file + stdout tee).
# Docker-future: foreground (PID1-friendly, stdout structured JSON lines).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
DAEMON_SCRIPT="$ROOT/scripts/live/run_context_refresh_daemon.py"
PID_FILE="$ROOT/run/context_refresh_daemon.pid"
LOCK_FILE="$ROOT/run/context_refresh_daemon.lock"
LOG_FILE="$ROOT/logs/context_refresh_daemon.log"
INTERVAL_S="${CONTEXT_REFRESH_INTERVAL_SECONDS:-900}"
FLAG="${BTC_ML_CONTEXT_REFRESH_DAEMON:-0}"

_require_flag() {
  if [[ "$FLAG" != "1" ]]; then
    echo "REFUSED: set BTC_ML_CONTEXT_REFRESH_DAEMON=1 to enable (default OFF)"
    exit 2
  fi
}

_require_interpreter() {
  if [[ ! -x "$PYTHON" ]]; then
    echo "REFUSED: canonical interpreter missing/not executable: $PYTHON"
    exit 2
  fi
  case "$PYTHON" in
    "$ROOT/venv/"*) ;;
    *)
      echo "REFUSED: interpreter must be under $ROOT/venv/: got $PYTHON"
      exit 2
      ;;
  esac
  if [[ ! -f "$DAEMON_SCRIPT" ]]; then
    echo "REFUSED: daemon entrypoint missing: $DAEMON_SCRIPT"
    exit 2
  fi
}

_pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # Reject zombies via ps state
  local st
  st="$(/bin/ps -p "$pid" -o state= 2>/dev/null | tr -d '[:space:]' || true)"
  [[ "$st" == Z* ]] && return 1
  return 0
}

_running_pid() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(tr -d '[:space:]' <"$PID_FILE")"
    if _pid_alive "$pid"; then
      # Confirm command identity
      local cmd
      cmd="$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)"
      if [[ "$cmd" == *"run_context_refresh_daemon.py"* ]]; then
        echo "$pid"
        return 0
      fi
    fi
  fi
  return 1
}

cmd="${1:-status}"
case "$cmd" in
  start)
    _require_flag
    _require_interpreter
    if pid="$(_running_pid)"; then
      echo "already running pid=$pid"
      exit 0
    fi
    mkdir -p "$ROOT/run" "$ROOT/logs"
    rm -f "$LOCK_FILE"
    # Background for macOS ops in a new session so agent/shell teardown does not
    # SIGTERM the daemon. Logs append to $LOG_FILE (not /dev/null).
    ROOT="$ROOT" PYTHON="$PYTHON" DAEMON_SCRIPT="$DAEMON_SCRIPT" \
      PID_FILE="$PID_FILE" LOCK_FILE="$LOCK_FILE" LOG_FILE="$LOG_FILE" \
      INTERVAL_S="$INTERVAL_S" \
      BTC_ML_CONTINUATION_PROGRESSION="${BTC_ML_CONTINUATION_PROGRESSION:-0}" \
      PRICE_GATE="${PRICE_GATE:-OFF}" \
      "$PYTHON" - <<'PY'
import os
import subprocess
import time
from pathlib import Path

root = Path(os.environ["ROOT"])
python = os.environ["PYTHON"]
script = os.environ["DAEMON_SCRIPT"]
pid_file = Path(os.environ["PID_FILE"])
lock_file = Path(os.environ["LOCK_FILE"])
log_file = Path(os.environ["LOG_FILE"])
interval = os.environ["INTERVAL_S"]
env = os.environ.copy()
env["BTC_ML_CONTEXT_REFRESH_DAEMON"] = "1"
env["CONTEXT_REFRESH_INTERVAL_SECONDS"] = interval
log_file.parent.mkdir(parents=True, exist_ok=True)
with log_file.open("a", encoding="utf-8") as log_handle:
    proc = subprocess.Popen(
        [
            python,
            "-u",
            script,
            "--foreground",
            "--interval-s",
            interval,
            "--pid-path",
            str(pid_file),
            "--lock-path",
            str(lock_file),
        ],
        cwd=str(root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
time.sleep(0.4)
alive = True
try:
    os.kill(proc.pid, 0)
except OSError:
    alive = False
print(f"spawned pid={proc.pid} alive={alive}")
if not alive:
    raise SystemExit(1)
PY
    sleep 0.2
    if pid="$(_running_pid)"; then
      echo "started pid=$pid interval=${INTERVAL_S}s python=$PYTHON log=$LOG_FILE"
    else
      echo "ERROR: daemon failed to stay up; see $LOG_FILE"
      exit 1
    fi
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      pid="$(tr -d '[:space:]' <"$PID_FILE")"
      if _pid_alive "$pid"; then
        kill -TERM "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
          _pid_alive "$pid" || break
          sleep 0.5
        done
        if _pid_alive "$pid"; then
          kill -KILL "$pid" 2>/dev/null || true
        fi
      fi
      rm -f "$PID_FILE" "$LOCK_FILE"
      echo "stopped $pid"
    else
      echo "not running"
    fi
    ;;
  restart)
    "$0" stop || true
    FLAG="${BTC_ML_CONTEXT_REFRESH_DAEMON:-0}" exec "$0" start
    ;;
  foreground)
    _require_flag
    _require_interpreter
    if pid="$(_running_pid)"; then
      echo "REFUSED: background daemon already running pid=$pid"
      exit 1
    fi
    exec env \
      BTC_ML_CONTEXT_REFRESH_DAEMON=1 \
      BTC_ML_CONTINUATION_PROGRESSION="${BTC_ML_CONTINUATION_PROGRESSION:-0}" \
      PRICE_GATE="${PRICE_GATE:-OFF}" \
      CONTEXT_REFRESH_INTERVAL_SECONDS="$INTERVAL_S" \
      "$PYTHON" -u "$DAEMON_SCRIPT" --foreground \
      --interval-s "$INTERVAL_S" \
      --pid-path "$PID_FILE" \
      --lock-path "$LOCK_FILE"
    ;;
  status)
    echo "flag_BTC_ML_CONTEXT_REFRESH_DAEMON=${FLAG}"
    echo "interval_s=${INTERVAL_S}"
    echo "python=${PYTHON}"
    echo "entrypoint=${DAEMON_SCRIPT}"
    if pid="$(_running_pid)"; then
      echo "status=RUNNING pid=$pid"
      /bin/ps -p "$pid" -o pid=,ppid=,state=,command= 2>/dev/null || true
    else
      echo "status=STOPPED"
    fi
    if [[ -f "$LOCK_FILE" ]]; then
      echo "lock=$(tr -d '[:space:]' <"$LOCK_FILE")"
    else
      echo "lock=absent"
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|foreground}"
    exit 1
    ;;
esac
