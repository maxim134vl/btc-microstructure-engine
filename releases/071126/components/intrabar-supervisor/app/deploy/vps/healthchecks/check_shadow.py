#!/usr/bin/env python3
"""Shadow service readiness (EQCORR, structural, BE33, auction)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app"))


def _active_epoch_id() -> str | None:
    path = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    if not path.is_file():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("paper_epoch_id") or "") or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _health_paths(kind: str) -> list[Path]:
    if kind == "eqcorr":
        paths = [REPO / "data" / "trading" / "shadow_economic_correlation" / "health.json"]
        root = REPO / "data" / "trading" / "shadow_economic_correlation" / "epochs"
        if root.is_dir():
            paths.extend(sorted(root.glob("*/health.json")))
        return paths
    if kind in {"structural", "stp21"}:
        paths = [REPO / "data" / "trading" / "shadow_structural_protection" / "health.json"]
        root = REPO / "data" / "trading" / "shadow_structural_protection" / "epochs"
        if root.is_dir():
            paths.extend(sorted(root.glob("*/health.json")))
        return paths
    if kind == "be33":
        epoch = _active_epoch_id()
        paths: list[Path] = []
        if epoch:
            paths.append(
                REPO
                / "data"
                / "trading"
                / "shadow_structural_protection"
                / "stp_be33"
                / "epochs"
                / epoch
                / "health.json"
            )
        # Fallback glob for early start before active epoch is readable
        root = REPO / "data" / "trading" / "shadow_structural_protection" / "stp_be33" / "epochs"
        if root.is_dir():
            paths.extend(sorted(root.glob("*/health.json")))
        return paths
    if kind == "auction":
        return [
            REPO / "data" / "trading" / "shadow_auction" / "health" / "health.json",
            REPO / "data" / "trading" / "shadow_auction" / "health.json",
        ]
    return []


def _manifest_paths(kind: str) -> list[Path]:
    if kind == "eqcorr":
        paths = [REPO / "data" / "trading" / "shadow_economic_correlation" / "policy_manifest.json"]
        root = REPO / "data" / "trading" / "shadow_economic_correlation" / "epochs"
        if root.is_dir():
            paths.extend(sorted(root.glob("*/policy_manifest.json")))
        return paths
    if kind in {"structural", "stp21"}:
        paths = [REPO / "data" / "trading" / "shadow_structural_protection" / "policy_manifest.json"]
        root = REPO / "data" / "trading" / "shadow_structural_protection" / "epochs"
        if root.is_dir():
            paths.extend(sorted(root.glob("*/policy_manifest.json")))
        return paths
    if kind == "be33":
        epoch = _active_epoch_id()
        if not epoch:
            return []
        return [
            REPO
            / "data"
            / "trading"
            / "shadow_structural_protection"
            / "stp_be33"
            / "epochs"
            / epoch
            / "policy_manifest.json"
        ]
    if kind == "auction":
        return [
            REPO / "data" / "trading" / "shadow_auction" / "policy_manifest.json",
            REPO / "data" / "trading" / "shadow_auction" / "contract" / "policy_manifest.json",
        ]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--kind",
        choices=("eqcorr", "structural", "stp21", "be33", "auction"),
        required=True,
    )
    args = ap.parse_args()

    health_path = next((p for p in _health_paths(args.kind) if p.is_file()), None)
    if health_path is None:
        print(f"STARTING: missing shadow health kind={args.kind}")
        return 1

    # Manifest is required for eqcorr/structural; BE33/auction may start before it.
    if args.kind in {"eqcorr", "structural", "stp21"}:
        manifest_path = next((p for p in _manifest_paths(args.kind) if p.is_file()), None)
        if manifest_path is None:
            print(f"STARTING: missing policy_manifest kind={args.kind}")
            return 1
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if m.get("enforcement_enabled") is True:
            print("UNHEALTHY: enforcement unexpectedly enabled")
            return 1
        mode = m.get("mode") or m.get("enforcement_enabled")
    else:
        mode = "observer"

    h = json.loads(health_path.read_text(encoding="utf-8"))
    status = h.get("status") or h.get("service_status") or "OK"
    if status in {"FAILED", "UNHEALTHY", "CRITICAL", "SHADOW_AUCTION_REFUSED"}:
        print(f"UNHEALTHY: {status}")
        return 1
    print(f"HEALTHY_OR_STARTING: kind={args.kind} status={status} mode={mode} path={health_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
