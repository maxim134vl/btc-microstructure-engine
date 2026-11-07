#!/bin/sh
# TRD-OUTCOME2 dashboard refresh loop.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/output/audits/trd_outcome2 /app/run /app/run/logs

exec python /app/scripts/live/run_trd_outcome2_refresh.py \
  --interval-seconds "${TRD_OUTCOME2_INTERVAL_S:-900}"
