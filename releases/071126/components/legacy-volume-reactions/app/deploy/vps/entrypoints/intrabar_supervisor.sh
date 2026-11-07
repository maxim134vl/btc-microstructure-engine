#!/bin/sh
# LIVE1A/LIVE1B process supervisor (intrabar_process_supervisor).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/runtime /app/run /app/run/logs

exec python /app/scripts/live/intrabar_process_supervisor.py
