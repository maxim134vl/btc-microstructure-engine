#!/bin/sh
# S4.1 TimeframeManager daemon (4 TF + Anti-Saw rails). Traders stay STOPPED.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/runtime /app/run /app/logs

python /app/scripts/live/timeframe_manager_daemon.py \
  --approved-timeframe-manager \
  --paper-only \
  --no-real-execution \
  --interval-seconds "${TF_MANAGER_INTERVAL_S:-60}" &
pid=$!
echo "$pid" >/app/run/timeframe_manager.pid
# Forward the container stop signal and reap the child before removing its PID.
stop_child() {
  trap '' TERM INT
  kill -TERM "$pid" 2>/dev/null || true
}
trap stop_child TERM INT
rc=0
wait "$pid" || rc=$?
if kill -0 "$pid" 2>/dev/null; then
  wait "$pid" || rc=$?
fi
rm -f /app/run/timeframe_manager.pid
exit "$rc"
