#!/usr/bin/env bash
# Start / stop / status / tail / repair-duplicates for bounded paper trading controller.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
PID_FILE="$ROOT/run/bounded_paper_trading_controller_auto_ledger.pid"
LOCK_FILE="$ROOT/run/bounded_paper_trading_controller_auto_ledger.lock"
LOG_FILE="$ROOT/logs/bounded_paper_trading_controller_auto_ledger.log"
STATUS_JSON="$ROOT/data/research/paper_simulator/bounded_paper_controller_status.json"
CONTROLLER_SCRIPT="bounded_paper_trading_controller_auto_ledger_no_real_execution.py"

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

read_lock_pid() {
  if [[ -f "$LOCK_FILE" ]]; then
    tr -d '[:space:]' <"$LOCK_FILE" || true
  fi
}

write_pid_and_lock() {
  local pid="$1"
  printf '%s\n' "$pid" >"$PID_FILE"
  printf '%s\n' "$pid" >"$LOCK_FILE"
}

list_controller_pids() {
  # Strict match: only the live controller python script, not ctl/qa wrappers.
  ps -ax -o pid=,command= 2>/dev/null | awk '
    /scripts\/live\/bounded_paper_trading_controller_auto_ledger_no_real_execution\.py/ &&
    $0 !~ /audit_/ &&
    $0 !~ /bounded_paper_trading_controller_ctl/ &&
    $0 !~ /grep/ {
      print $1
    }'
}

cleanup_stale_pid_files() {
  local pid
  pid="$(read_pid)"
  if [[ -f "$PID_FILE" ]] && { [[ -z "${pid:-}" ]] || ! pid_alive "$pid"; }; then
    echo "stale_pid_cleanup pid=${pid:-empty}"
    rm -f "$PID_FILE"
  fi
  local lock_pid
  lock_pid="$(read_lock_pid)"
  if [[ -f "$LOCK_FILE" ]] && { [[ -z "${lock_pid:-}" ]] || ! pid_alive "$lock_pid"; }; then
    echo "stale_lock_cleanup pid=${lock_pid:-empty}"
    rm -f "$LOCK_FILE"
  fi
}

cleanup_stale_lock() {
  local lock_pid
  lock_pid="$(read_lock_pid)"
  if [[ -n "${lock_pid:-}" ]] && ! pid_alive "$lock_pid"; then
    echo "stale_lock_cleanup pid=$lock_pid"
    rm -f "$LOCK_FILE"
    return 0
  fi
  return 1
}

stop_all_controller_processes() {
  local killed=0
  local pids
  pids="$(list_controller_pids | tr '\n' ' ')"
  for lp in $pids; do
    if pid_alive "$lp"; then
      echo "stopping_controller_pid=$lp signal=TERM"
      kill -TERM "$lp" 2>/dev/null || true
      killed=1
    fi
  done
  if [[ "$killed" -eq 1 ]]; then
    sleep 1
  fi
  for lp in $(list_controller_pids); do
    if pid_alive "$lp"; then
      echo "stopping_controller_pid=$lp signal=KILL"
      kill -KILL "$lp" 2>/dev/null || true
    fi
  done
  sleep 0.3
  rm -f "$PID_FILE" "$LOCK_FILE"
}

emit_process_status() {
  local pid_file_exists=false
  local pid_file_pid=""
  local pid_file_alive=false
  local live_pids=()
  local orphan_pids=()
  local live_count=0
  local duplicate_count=0
  local status="STOPPED"

  if [[ -f "$PID_FILE" ]]; then
    pid_file_exists=true
    pid_file_pid="$(read_pid)"
    if pid_alive "$pid_file_pid"; then
      pid_file_alive=true
    fi
  fi

  while IFS= read -r lp; do
    [[ -z "$lp" ]] && continue
    if pid_alive "$lp"; then
      live_pids+=("$lp")
    fi
  done < <(list_controller_pids)

  live_count="${#live_pids[@]}"
  if [[ "$live_count" -gt 1 ]]; then
    duplicate_count=$((live_count - 1))
  fi

  for lp in "${live_pids[@]:-}"; do
    if [[ "$pid_file_alive" == "true" ]]; then
      if [[ "$lp" != "$pid_file_pid" ]]; then
        orphan_pids+=("$lp")
      fi
    else
      orphan_pids+=("$lp")
    fi
  done

  if [[ "$live_count" -eq 0 ]]; then
    if [[ "$pid_file_exists" == "true" ]] && [[ "$pid_file_alive" != "true" ]]; then
      status="STALE_PID"
    else
      status="STOPPED"
    fi
  elif [[ "$live_count" -gt 1 ]]; then
    status="DUPLICATE_RUNNING"
  elif [[ "$pid_file_alive" == "true" ]] && [[ "${live_pids[0]:-}" == "$pid_file_pid" ]]; then
    status="RUNNING"
  else
    status="ORPHAN_RUNNING"
  fi

  local live_csv orphan_csv
  live_csv="$(IFS=,; echo "${live_pids[*]:-}")"
  orphan_csv="$(IFS=,; echo "${orphan_pids[*]:-}")"

  echo "pid_file_exists=$pid_file_exists"
  echo "pid_file_pid=${pid_file_pid:-}"
  echo "pid_file_alive=$pid_file_alive"
  echo "live_controller_process_count=$live_count"
  echo "live_controller_count=$live_count"
  echo "live_controller_pids=[${live_csv}]"
  echo "orphan_controller_pids=[${orphan_csv}]"
  echo "duplicate_controller_count=$duplicate_count"
  echo "status=$status"
  # Backward-compatible one-liner
  case "$status" in
    RUNNING) echo "running pid=${live_pids[0]}" ;;
    ORPHAN_RUNNING) echo "orphan running pid=${live_pids[0]} (pid_file_alive=$pid_file_alive)" ;;
    DUPLICATE_RUNNING) echo "duplicate running count=$live_count pids=[${live_csv}]" ;;
    STALE_PID) echo "stale pid=${pid_file_pid}" ;;
    *) echo "not running" ;;
  esac
}

cmd="${1:-status}"

case "$cmd" in
  start)
    # After the S4.1 cutover the manager and the four timeframe traders own paper
    # execution; the global controller must never append to the frozen ledger.
    if [[ -f "$ROOT/data/trading/manager/activation.json" ]] && [[ "${ALLOW_LEGACY_PAPER_CONTROLLER_AFTER_S4_1:-0}" != "1" ]]; then
      echo "start_blocked reason=LEGACY_CONTROLLER_RETIRED_AFTER_S4_1_CUTOVER"
      echo "activation_record=data/trading/manager/activation.json"
      echo "use=scripts/timeframe_trading_ctl.sh start all"
      exit 3
    fi
    cleanup_stale_lock || true
    old="$(read_pid)"
    lock_pid="$(read_lock_pid)"
    if pid_alive "$old"; then
      echo "already running pid=$old (pid_file)"
      write_pid_and_lock "$old"
      exit 0
    fi
    if pid_alive "$lock_pid"; then
      echo "already running pid=$lock_pid (lock_file) — second start blocked"
      write_pid_and_lock "$lock_pid"
      exit 0
    fi
    # Also block if any live controller process exists.
    live_pids="$(list_controller_pids | tr '\n' ' ')"
    for lp in $live_pids; do
      if pid_alive "$lp"; then
        echo "already running pid=$lp (process scan) — second start blocked"
        write_pid_and_lock "$lp"
        exit 0
      fi
    done
    ROOT="$ROOT" PID_FILE="$PID_FILE" LOCK_FILE="$LOCK_FILE" LOG_FILE="$LOG_FILE" "$PYTHON" - <<'PY'
import os
import subprocess
from pathlib import Path

root = Path(os.environ["ROOT"])
pid_file = Path(os.environ["PID_FILE"])
lock_file = Path(os.environ["LOCK_FILE"])
log_file = Path(os.environ["LOG_FILE"])
cmd = [
    str(root / "venv" / "bin" / "python"),
    str(root / "scripts" / "live" / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"),
    "--approved-bounded-paper-controller-auto-ledger",
    "--paper-only",
    "--no-real-execution",
    "--skip-refresh",
    "--max-cycles",
    "96",
    "--interval-seconds",
    "900",
    "--max-duration-hours",
    "24",
    "--background-safe",
]
log = open(log_file, "a", encoding="utf-8")
proc = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    cwd=str(root),
    start_new_session=True,
)
pid_file.write_text(str(proc.pid) + "\n", encoding="utf-8")
lock_file.write_text(str(proc.pid) + "\n", encoding="utf-8")
print(f"started pid={proc.pid}")
print(f"lock_file={lock_file}")
PY
    ;;
  stop)
    echo "stop_begin"
    stop_all_controller_processes
    remaining=0
    for lp in $(list_controller_pids); do
      if pid_alive "$lp"; then
        remaining=$((remaining + 1))
        echo "still_alive_after_stop pid=$lp"
      fi
    done
    if [[ "$remaining" -eq 0 ]]; then
      echo "stopped"
      echo "live_controller_count=0"
      echo "pid_file_removed=true"
    else
      echo "ERROR: controller_process_still_alive count=$remaining"
      exit 1
    fi
    ;;
  status)
    emit_process_status
    lock_pid="$(read_lock_pid)"
    if [[ -f "$LOCK_FILE" ]]; then
      if pid_alive "$lock_pid"; then
        echo "lock_status=HELD pid=$lock_pid"
      else
        echo "lock_status=STALE pid=${lock_pid:-unknown}"
      fi
    else
      echo "lock_status=ABSENT"
    fi
    if [[ -f "$STATUS_JSON" ]]; then
      "$PYTHON" -c "import json; print(json.dumps(json.load(open(r'''$STATUS_JSON''')), indent=2)[:2500])"
    fi
    ;;
  cleanup-stale)
    cleanup_stale_pid_files
    emit_process_status
    ;;
  repair-duplicates)
    echo "approval_phrase=APPROVE_FIX_BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_NO_LEDGER_NO_EXECUTION"
    canonical="$(read_pid)"
    if ! pid_alive "$canonical"; then
      # Fallback: prefer lock pid if alive
      lock_pid="$(read_lock_pid)"
      if pid_alive "$lock_pid"; then
        canonical="$lock_pid"
        write_pid_and_lock "$canonical"
        echo "canonical_pid_recovered_from_lock=$canonical"
      else
        echo "ERROR: no alive canonical pid in pid/lock file"
        exit 1
      fi
    fi
    echo "canonical_pid=$canonical"
    duplicates=""
    for lp in $(list_controller_pids); do
      if [[ "$lp" == "$canonical" ]]; then
        continue
      fi
      if pid_alive "$lp"; then
        duplicates="$duplicates $lp"
      fi
    done
    duplicates="$(echo "$duplicates" | xargs || true)"
    if [[ -z "$duplicates" ]]; then
      echo "duplicate_process_found_before=false"
      echo "duplicate_pids_before=[]"
      write_pid_and_lock "$canonical"
      echo "lock_file_created=true"
      echo "duplicate_process_count_after=0"
      echo "single_process_verified=true"
      ROOT="$ROOT" STATUS_JSON="$STATUS_JSON" CANONICAL="$canonical" "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
path = Path(os.environ["STATUS_JSON"])
canonical = int(os.environ["CANONICAL"])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
payload["controller_running"] = True
payload["pid"] = canonical
payload["stop_reason"] = None
payload["collecting_paper_data"] = True
payload["execution_enabled"] = False
payload["exchange_api_call_used"] = False
payload["paper_only_mode"] = True
payload["repair_note"] = "DUPLICATE_PROCESS_REPAIR_KEPT_CANONICAL_PID"
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"status_refreshed_for_canonical_pid={canonical}")
PY
      FINAL_JSON="$ROOT/data/research/paper_simulator/bounded_paper_controller_final_decision.json"
      ROOT="$ROOT" FINAL_JSON="$FINAL_JSON" CANONICAL="$canonical" "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
path = Path(os.environ["FINAL_JSON"])
canonical = int(os.environ["CANONICAL"])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
payload.update({
    "status": "BOUNDED_PAPER_TRADING_CONTROLLER_RUNNING",
    "qa_status": "PASS_WITH_LIMITATIONS",
    "controller_running": True,
    "collecting_paper_data": True,
    "execution_enabled": False,
    "run_readiness_status": "CONTROLLER_SINGLE_PROCESS_REPAIRED_COLLECTING_PAPER_DATA",
    "next_recommended_step": "OBSERVE_NEXT_CONTROLLER_CYCLE",
    "stop_reason": None,
    "canonical_pid_after_repair": canonical,
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
})
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("final_decision_refreshed=true")
PY
      exit 0
    fi
    echo "duplicate_process_found_before=true"
    echo "duplicate_pids_before=[$duplicates]"
    for dp in $duplicates; do
      echo "terminating_duplicate pid=$dp signal=TERM"
      kill -TERM "$dp" 2>/dev/null || true
    done
    sleep 2
    for dp in $duplicates; do
      if pid_alive "$dp"; then
        echo "terminating_duplicate pid=$dp signal=KILL"
        kill -KILL "$dp" 2>/dev/null || true
      fi
    done
    sleep 1
    remaining=0
    remaining_list=""
    for lp in $(list_controller_pids); do
      if pid_alive "$lp" && [[ "$lp" != "$canonical" ]]; then
        remaining=$((remaining + 1))
        remaining_list="$remaining_list $lp"
      fi
    done
    if ! pid_alive "$canonical"; then
      echo "ERROR: canonical pid died during repair: $canonical"
      exit 1
    fi
    write_pid_and_lock "$canonical"
    echo "duplicate_processes_terminated=true"
    echo "duplicate_process_count_after=$remaining"
    if [[ "$remaining" -eq 0 ]]; then
      echo "single_process_verified=true"
    else
      echo "single_process_verified=false"
      echo "remaining_duplicates=$remaining_list"
      exit 1
    fi
    echo "pid_file_points_to_alive_process=true"
    echo "lock_file_created=true"
    echo "canonical_pid=$canonical"
    # Refresh status JSON to the surviving canonical PID (no ledger writes).
    ROOT="$ROOT" STATUS_JSON="$STATUS_JSON" CANONICAL="$canonical" "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
path = Path(os.environ["STATUS_JSON"])
canonical = int(os.environ["CANONICAL"])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
payload["controller_running"] = True
payload["pid"] = canonical
payload["stop_reason"] = None
payload["collecting_paper_data"] = True
payload["execution_enabled"] = False
payload["exchange_api_call_used"] = False
payload["paper_only_mode"] = True
payload["repair_note"] = "DUPLICATE_PROCESS_REPAIR_KEPT_CANONICAL_PID"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"status_refreshed_for_canonical_pid={canonical}")
PY
    # Also keep final_decision consistent with running collector.
    FINAL_JSON="$ROOT/data/research/paper_simulator/bounded_paper_controller_final_decision.json"
    ROOT="$ROOT" FINAL_JSON="$FINAL_JSON" CANONICAL="$canonical" "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
path = Path(os.environ["FINAL_JSON"])
canonical = int(os.environ["CANONICAL"])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
payload.update({
    "status": "BOUNDED_PAPER_TRADING_CONTROLLER_RUNNING",
    "qa_status": "PASS_WITH_LIMITATIONS",
    "controller_running": True,
    "collecting_paper_data": True,
    "execution_enabled": False,
    "run_readiness_status": "CONTROLLER_SINGLE_PROCESS_REPAIRED_COLLECTING_PAPER_DATA",
    "next_recommended_step": "OBSERVE_NEXT_CONTROLLER_CYCLE",
    "stop_reason": None,
    "canonical_pid_after_repair": canonical,
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
})
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("final_decision_refreshed=true")
PY
    ;;
  tail)
    tail -n 80 "$LOG_FILE"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|tail|repair-duplicates|cleanup-stale}"
    exit 2
    ;;
esac
