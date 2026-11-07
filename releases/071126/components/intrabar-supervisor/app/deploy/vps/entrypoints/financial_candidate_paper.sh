#!/bin/sh
set -eu
cd /app
export PYTHONPATH=/app:/app/src
export BTC_ML_REPO_ROOT=/app
python -m btc_ml.runtime.container_preflight --role paper-manager
python -c "import runpy; g=runpy.run_path('/app/config/qualified_paper_launcher.py'); g['verify_effective_config']()"
python /app/deploy/vps/entrypoints/paper_only_guard.py
# Invocation with continuity args is separately authorized; do not invent a domain.
exec python /app/scripts/live/run_intrabar_paper_manager.py --config /app/config/intrabar_paper_execution.qualified-anti-saw.json "$@"
