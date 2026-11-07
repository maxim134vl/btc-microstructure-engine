#!/bin/sh
# VPS paper-manager entrypoint: guard, then hang-watchdog around LIVE1B.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"

python /app/deploy/vps/entrypoints/paper_only_guard.py

CONFIG_ARGS=""
if [ -f /app/data/deployment/intrabar_paper_execution.overlay.json ]; then
  CONFIG_ARGS="--config /app/data/deployment/intrabar_paper_execution.overlay.json"
fi

# Watchdog is PID of the container command. It kills hung paper (stale
# health.json) so compose restart: unless-stopped brings the loop back.
# shellcheck disable=SC2086
exec python -m btc_ml.runtime.paper_hang_watchdog -- \
  python /app/scripts/live/run_intrabar_paper_manager.py \
  --poll-ms "${PAPER_POLL_MS:-250}" \
  --health-every-s "${PAPER_HEALTH_EVERY_S:-2.0}" \
  ${CONFIG_ARGS}
