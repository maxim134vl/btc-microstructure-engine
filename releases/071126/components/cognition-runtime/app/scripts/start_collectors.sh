#!/usr/bin/env bash
# Start market data collectors + watchdog supervisor
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-venv}"

if [ -d "$VENV" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  PYTHON="$VENV/bin/python3"
fi

echo "Starting collector watchdog (supervise mode) ..."
exec "$PYTHON" collector_watchdog.py "$@"
