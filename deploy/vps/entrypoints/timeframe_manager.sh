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
wait "$pid"
rc=$?
rm -f /app/run/timeframe_manager.pid
exit "$rc"
