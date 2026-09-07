#!/bin/sh
# Context refresh daemon — foreground runner (Docker-friendly).
# Bypasses ctl.sh venv gate; sets BTC_ML_CONTEXT_REFRESH_DAEMON=1.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
export BTC_ML_CONTEXT_REFRESH_DAEMON=1
export CONTEXT_REFRESH_INTERVAL_SECONDS="${CONTEXT_REFRESH_INTERVAL_SECONDS:-900}"
export BTC_ML_CONTINUATION_PROGRESSION="${BTC_ML_CONTINUATION_PROGRESSION:-0}"
export PRICE_GATE="${PRICE_GATE:-OFF}"

INTERVAL_S="${CONTEXT_REFRESH_INTERVAL_SECONDS}"
mkdir -p /app/run /app/logs /app/data/runtime

exec python -u /app/scripts/live/run_context_refresh_daemon.py \
  --foreground \
  --interval-s "${INTERVAL_S}" \
  --pid-path /app/data/runtime/context_refresher.pid \
  --lock-path /app/run/context_refresh_daemon.lock
