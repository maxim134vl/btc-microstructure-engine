#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Starting cognition control center backend on :8080"
(cd backend && PYTHONPATH=".:../.." ../../venv/bin/python3 run_api.py) &
BACK_PID=$!

if [[ "${1:-}" != "--backend-only" ]]; then
  echo "Starting frontend on :5173"
  (cd frontend && npm install && npm run dev) &
  FRONT_PID=$!
fi

trap 'kill $BACK_PID ${FRONT_PID:-} 2>/dev/null || true' EXIT
wait
