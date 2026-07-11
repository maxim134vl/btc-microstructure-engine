#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-all}"

if [[ "$MODE" != "all" && "$MODE" != "--backend-only" && "$MODE" != "--frontend-only" ]]; then
  echo "Usage: ./start_dashboard.sh [--backend-only|--frontend-only]"
  echo "Prefer full stack: ../../scripts/runtime_stack.sh start"
  exit 2
fi

PYTHON_BIN="${DASHBOARD_PYTHON_BIN:-../../venv/bin/python3}"

BACK_PID=""
FRONT_PID=""

cleanup() {
  if [[ -n "${BACK_PID}" ]]; then
    kill "$BACK_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONT_PID}" ]]; then
    kill "$FRONT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ "$MODE" != "--frontend-only" ]]; then
  echo "Starting cognition control center backend"
  echo "  health: http://localhost:8080/health"
  (cd backend && PYTHONPATH=".:../.." "$PYTHON_BIN" run_api.py) &
  BACK_PID=$!
fi

if [[ "$MODE" != "--backend-only" ]]; then
  echo "Starting frontend"
  echo "  app: http://localhost:5173"

  (
    cd frontend
    if [[ ! -d node_modules ]]; then
      echo "Installing frontend dependencies"
      if [[ -f package-lock.json ]]; then
        npm ci
      else
        npm install
      fi
    fi
    npm run dev -- --host 127.0.0.1 --port 5173
  ) &
  FRONT_PID=$!
fi

wait
