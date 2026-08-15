#!/usr/bin/env bash
# Full dashboard teardown (OPS API, UI, chart :8765, visual refresher). Does not stop the model.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/btc_ml" dashboard stop
