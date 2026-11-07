#!/bin/sh
# Existing service roles only; no second executor or descriptor auto-discovery.
set -eu
cd /app
export PYTHONPATH=/app:/app/src
export BTC_ML_REPO_ROOT=/app
case "${1:-}" in
  context-refresh-daemon)
    exec /bin/sh /app/deploy/vps/entrypoints/context_refresh_daemon.sh ;;
  timeframe-manager)
    python -m btc_ml.runtime.container_preflight --role timeframe-manager
    exec /bin/sh /app/deploy/vps/entrypoints/timeframe_manager.sh ;;
  paper-manager)
    python -m btc_ml.runtime.container_preflight --role paper-manager
    python /app/deploy/vps/entrypoints/paper_only_guard.py
    # The native launcher reads the descriptor's pinned observation config.
    # Do not select an unrelated data/deployment overlay or an old launcher.
    exec python -m btc_ml.runtime.paper_hang_watchdog -- \
      python /app/scripts/live/run_intrabar_paper_manager.py \
      --poll-ms "${PAPER_POLL_MS:-250}" \
      --health-every-s "${PAPER_HEALTH_EVERY_S:-2.0}" ;;
  *) echo 'EXISTING_FINANCIAL_TREND_SERVICE_ROLE_REQUIRED' >&2; exit 2 ;;
esac
