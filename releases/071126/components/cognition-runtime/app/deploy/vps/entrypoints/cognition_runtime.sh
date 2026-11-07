#!/bin/sh
# VPS cognition-runtime (LIVE1A): public market WS + journal + context events.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"

mkdir -p \
  /app/data/raw_market_events_v2 \
  /app/data/cognition/intrabar_context_events \
  /app/data/runtime \
  /app/run

exec python /app/scripts/live/run_intrabar_cognition_service.py \
  --journal-root /app/data/raw_market_events_v2 \
  --context-root /app/data/cognition/intrabar_context_events \
  --health-path /app/data/runtime/intrabar_cognition_health.json \
  --pid-file /app/run/intrabar_cognition.pid \
  --symbol "${MARKET_SYMBOL:-BTCUSDT}"
