#!/bin/sh
# Trade chart static viewer (apps/context_visualizer/public on :8765).
set -eu
cd /app
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
PUBLIC_DIR="/app/apps/context_visualizer/public"
if [ ! -d "$PUBLIC_DIR" ]; then
  echo "ERROR: missing $PUBLIC_DIR" >&2
  exit 2
fi
mkdir -p /app/run
echo "$$" >/app/run/trade_chart.pid
cd "$PUBLIC_DIR"
exec python -m http.server "${TRADE_CHART_PORT:-8765}" --bind 0.0.0.0
