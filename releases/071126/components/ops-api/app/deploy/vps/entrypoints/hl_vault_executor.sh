#!/bin/sh
# Isolated Hyperliquid vault executor. Never runs paper_only_guard.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
export HL_VAULT_CONFIG="${HL_VAULT_CONFIG:-/app/config/hl_vault_testnet.json}"

python /app/deploy/vps/entrypoints/hl_vault_guard.py

FAKE_ARGS=""
if [ "${HL_VAULT_FAKE:-false}" = "true" ] || [ "${HL_VAULT_FAKE:-0}" = "1" ]; then
  FAKE_ARGS="--fake"
fi

# shellcheck disable=SC2086
exec python /app/scripts/live/run_hl_vault_executor.py \
  --config "${HL_VAULT_CONFIG}" \
  --poll-ms "${HL_VAULT_POLL_MS:-500}" \
  ${FAKE_ARGS}
