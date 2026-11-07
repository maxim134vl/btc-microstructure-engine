#!/usr/bin/env python3
"""HL vault executor readiness: contract PASSED + health artifact."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app"))


def main() -> int:
    contract = REPO / "data" / "deployment" / "hl_vault_contract.json"
    if not contract.is_file():
        print("UNHEALTHY: missing hl_vault_contract.json")
        return 1
    c = json.loads(contract.read_text(encoding="utf-8"))
    if c.get("status") != "PASSED":
        print(f"UNHEALTHY: contract={c.get('status')}")
        return 1
    health = REPO / "data" / "trading" / "hyperliquid_vault" / "health.json"
    if not health.is_file():
        print("STARTING: waiting for hl vault health")
        return 1
    h = json.loads(health.read_text(encoding="utf-8"))
    if h.get("ok") is not True:
        print(f"UNHEALTHY: health ok={h.get('ok')} kill={h.get('kill')}")
        return 1
    print(f"HEALTHY: network={c.get('network')} vault={c.get('vault_address')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
