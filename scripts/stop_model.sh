#!/usr/bin/env bash
# Full hybrid-model teardown (manager, LIVE1A/B, shadows, run.py). Does not stop dashboard.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/btc_ml" model stop
