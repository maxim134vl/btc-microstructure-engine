#!/usr/bin/env bash
# Reproducible host-side dependency install for non-Docker verification.
# The Docker stack does NOT depend on this venv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PY="${PYTHON:-python3}"
ver="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$ver" != "3.11" ]]; then
  echo "ERROR: Python 3.11 required (found $ver). Set PYTHON=python3.11 if needed." >&2
  exit 2
fi

VENV_DIR="${VPS_VENV_DIR:-${CTO_VENV_DIR:-$REPO_ROOT/.venv-vps}}"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PY" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r requirements-runtime.txt
python -m pip install -r dashboard/backend/requirements.txt
python -m pip install -r requirements-test.txt
# websocket client used by LIVE1A/LIVE1B
python -m pip install 'websocket-client==1.7.0'
python -m pip check
echo "OK: dependencies installed in $VENV_DIR"
