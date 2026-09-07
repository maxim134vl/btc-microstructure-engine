#!/bin/sh
# Host-parity collector watchdog (required collectors only).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/live /app/data/runtime /app/run /app/logs

python /app/collector_watchdog.py --required-only &
pid=$!
echo "$pid" >/app/run/collector_watchdog.pid
wait "$pid"
rc=$?
rm -f /app/run/collector_watchdog.pid
exit "$rc"
