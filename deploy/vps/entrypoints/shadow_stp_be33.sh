#!/bin/sh
# STP_BE33 shadow runner (position management, observe-only).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p \
  /app/data/trading/shadow_structural_protection \
  /app/run \
  /app/run/logs

exec python /app/scripts/live/run_shadow_stp_be33.py \
  --poll-ms "${STP_BE33_POLL_MS:-1000}"
