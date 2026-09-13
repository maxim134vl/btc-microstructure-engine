#!/usr/bin/env python3
"""Pre-start guard for the Binance KZ executor. Isolated from paper-only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app")).resolve()
CONTRACT_PATH = REPO / "data" / "deployment" / "binance_kz_contract.json"


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO))
    from btc_ml.trading.binance_kz.guard import evaluate_start

    cfg_path = Path(os.environ.get("BINANCE_KZ_CONFIG") or (REPO / "config" / "binance_kz_live.json"))
    result = evaluate_start(
        config_path=cfg_path,
        repo_root=REPO,
        environ=dict(os.environ),
        contract_path=CONTRACT_PATH,
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result.get("status") == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
