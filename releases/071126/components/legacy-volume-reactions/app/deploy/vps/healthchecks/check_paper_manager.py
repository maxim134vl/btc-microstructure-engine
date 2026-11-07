#!/usr/bin/env python3
"""Paper manager readiness: active epoch + paper-only contract + health artifact."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app"))


def main() -> int:
    contract = REPO / "data" / "deployment" / "paper_only_contract.json"
    active = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    if not contract.is_file():
        print("UNHEALTHY: missing paper_only_contract.json")
        return 1
    c = json.loads(contract.read_text(encoding="utf-8"))
    if c.get("status") != "PASSED" or c.get("real_execution_enabled") is not False:
        print(f"UNHEALTHY: contract={c.get('status')}")
        return 1
    if not active.is_file():
        print("UNHEALTHY: missing active epoch")
        return 1
    ep = json.loads(active.read_text(encoding="utf-8"))
    if ep.get("epoch_status") != "ACTIVE":
        print(f"UNHEALTHY: epoch_status={ep.get('epoch_status')}")
        return 1
    # Health file written by IntrabarPaperEngine.write_health()
    epoch_id = ep["paper_epoch_id"]
    candidates = [
        REPO / "data" / "trading" / "intrabar_paper" / epoch_id / "health.json",
        REPO / "data" / "trading" / "intrabar_paper" / epoch_id / "books" / "health.json",
        REPO / "data" / "runtime" / "intrabar_paper_health.json",
    ]
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        print("STARTING: waiting for paper health artifact")
        return 1
    print(f"HEALTHY: epoch={epoch_id} health={found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
