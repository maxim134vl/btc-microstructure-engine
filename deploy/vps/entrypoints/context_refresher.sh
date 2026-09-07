#!/bin/sh
# Visual market-context refresher (dashboard plane).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
export CONTEXT_REFRESHER_PID_PATH="${CONTEXT_REFRESHER_PID_PATH:-/app/data/runtime/visual_refresher.pid}"
export CONTEXT_REFRESHER_LOCK_PATH="${CONTEXT_REFRESHER_LOCK_PATH:-/app/run/context_visual_refresher.lock}"
mkdir -p /app/data/runtime /app/data/research /app/run /app/logs \
  /app/apps/context_visualizer/public/data

exec python /app/scripts/live/run_market_context_visual_refresher.py \
  --interval-seconds "${VISUAL_REFRESH_INTERVAL_S:-20}"
