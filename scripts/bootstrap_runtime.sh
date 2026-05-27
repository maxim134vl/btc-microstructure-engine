#!/usr/bin/env bash
# Reproducible runtime bootstrap — Phase 4B
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-venv}"

echo "BTC-ML runtime bootstrap"
echo "Root: $ROOT"
echo

if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv at $VENV ..."
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "Installing package (editable) ..."
pip install -U pip wheel setuptools
pip install -e .

if [ -f requirements-runtime.txt ]; then
  echo "Installing runtime requirements ..."
  pip install -r requirements-runtime.txt
elif [ -f requirements.txt ]; then
  echo "Installing full requirements lockfile ..."
  pip install -r requirements.txt
fi

echo
echo "Ensuring data/ layout ..."
"$VENV/bin/python3" - <<'PY'
from storage.path_registry import ensure_data_layout, migrate_all_legacy

ensure_data_layout()
migrated = migrate_all_legacy()
if migrated:
    print("Migrated legacy parquets:", migrated)
PY

echo
echo "Running hardening checks ..."
"$VENV/bin/python3" runtime_hardening.py

echo
echo "Bootstrap complete."
echo "Start runtime: ./run.sh"
echo "Verify Phase 4B: ./run.sh --verify-4b"
