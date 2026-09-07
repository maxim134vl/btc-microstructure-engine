#!/bin/sh
# Shadow Auction AES0–AES5 observer (always on in VPS full model).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/trading/shadow_auction /app/run /app/run/logs

exec python /app/scripts/live/run_shadow_auction.py \
  --poll-s "${AUCTION_POLL_S:-1.0}" \
  --health-every-s "${AUCTION_HEALTH_EVERY_S:-2.0}"
