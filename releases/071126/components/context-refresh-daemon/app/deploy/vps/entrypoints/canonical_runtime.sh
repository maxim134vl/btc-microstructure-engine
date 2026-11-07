#!/bin/sh
# Canonical runtime (run.py) — host model_start parity.
set -eu
cd /app
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:$PYTHONPATH}"
export BTC_ML_REPO_ROOT="${BTC_ML_REPO_ROOT:-/app}"
mkdir -p /app/data/runtime /app/run /app/logs /app/output /app/artifacts /app/reports /app/replays

python /app/run.py &
pid=$!
echo "$pid" >/app/run/canonical_runtime.pid
# Shared volume copy for cross-container OPS process truth.
echo "$pid" >/app/data/runtime/canonical_pipeline.pid
wait "$pid"
rc=$?
rm -f /app/run/canonical_runtime.pid /app/data/runtime/canonical_pipeline.pid
exit "$rc"
