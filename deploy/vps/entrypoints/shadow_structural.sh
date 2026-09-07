#!/bin/sh
# Structural Stop/Take shadow — cold-volume tolerant (strict_epoch=False).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/trading/shadow_structural_protection /app/run

exec python /app/deploy/vps/entrypoints/shadow_structural.py \
  --poll-ms "${STRUCTURAL_POLL_MS:-1000}" \
  --health-every-s "${STRUCTURAL_HEALTH_EVERY_S:-2.0}"
