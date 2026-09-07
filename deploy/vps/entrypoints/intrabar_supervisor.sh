#!/bin/sh
# LIVE1A/LIVE1B process supervisor (intrabar_process_supervisor).
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/runtime /app/run /app/run/logs

# Compose already runs dedicated paper/cognition/manager containers.
# Supervisor must not spawn a second writer on the shared data volume.
python - <<'PY'
from pathlib import Path
from btc_ml.runtime.intrabar_supervision import write_stop_intent

for name in ("intrabar_paper_manager", "intrabar_cognition", "timeframe_manager"):
    write_stop_intent(
        Path(f"/app/run/{name}.stop_intent.json"),
        reason="compose_owns_service",
        stopped_by="vps_supervisor",
    )
PY

exec python /app/scripts/live/intrabar_process_supervisor.py
