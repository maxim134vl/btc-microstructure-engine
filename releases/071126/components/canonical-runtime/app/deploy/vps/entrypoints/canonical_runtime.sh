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
# Forward the container stop signal and reap the child before removing its PID.
stop_child() {
  trap '' TERM INT
  kill -TERM "$pid" 2>/dev/null || true
}
trap stop_child TERM INT
rc=0
wait "$pid" || rc=$?
if kill -0 "$pid" 2>/dev/null; then
  wait "$pid" || rc=$?
fi
rm -f /app/run/canonical_runtime.pid /app/data/runtime/canonical_pipeline.pid
exit "$rc"
