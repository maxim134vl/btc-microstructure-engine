#!/usr/bin/env python3
"""Prepare (do NOT execute) future paper-epoch activation after risk-delta clone.

TRD-EPOCH1: this script only evaluates the activation gate and prints a plan.
It never creates/activates a production epoch and never restarts LIVE1B.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.intrabar_paper.trading_contract import (  # noqa: E402
    CANONICAL_SOURCE_EPOCH,
    build_trading_contract_manifest,
    clone_trading_epoch_contract,
    prepare_new_epoch_activation_plan,
    risk_delta_overrides_per_tf_equity,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-epoch-id", default=CANONICAL_SOURCE_EPOCH)
    p.add_argument("--new-epoch-id", default="INTRABAR_RULES_V1_PER_TF_EQUITY_PENDING")
    p.add_argument(
        "--output-root",
        type=Path,
        default=REPO / "tmp" / "trading_contract_clones",
    )
    args = p.parse_args()

    source = build_trading_contract_manifest(args.source_epoch_id, repo_root=REPO)
    clone = clone_trading_epoch_contract(
        args.source_epoch_id,
        args.new_epoch_id,
        risk_delta_overrides_per_tf_equity(),
        repo_root=REPO,
        output_root=args.output_root,
        source_manifest=source,
        register_epoch=False,
    )
    plan = prepare_new_epoch_activation_plan(
        source_epoch_id=args.source_epoch_id,
        new_epoch_id=args.new_epoch_id,
        clone=clone,
        repo_root=REPO,
    )
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0 if plan.get("allowed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
