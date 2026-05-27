#!/usr/bin/env bash
# Unified canonical runtime launcher — Phase 4A
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
exec "${PYTHON:-venv/bin/python3}" run.py "$@"
