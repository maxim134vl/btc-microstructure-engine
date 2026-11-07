#!/bin/sh
# VPS paper-manager entrypoint: guard then canonical LIVE1B launcher.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"

python /app/deploy/vps/entrypoints/paper_only_guard.py
exec python /app/scripts/live/run_intrabar_paper_manager.py \
  --poll-ms "${PAPER_POLL_MS:-250}" \
  --health-every-s "${PAPER_HEALTH_EVERY_S:-2.0}"
