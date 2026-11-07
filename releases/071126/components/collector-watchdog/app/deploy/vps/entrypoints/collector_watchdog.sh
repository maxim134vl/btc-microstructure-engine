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
rm -f /app/run/collector_watchdog.pid
exit "$rc"
