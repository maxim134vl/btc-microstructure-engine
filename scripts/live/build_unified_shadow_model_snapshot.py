#!/usr/bin/env python3
"""One-shot builder for Unified Shadow Model snapshot (SHADOW-MODEL1).

Read-only: does not restart processes, rewrite journals, or enable enforcement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.model_assurance.shadow.unified_snapshot import (  # noqa: E402
    ShadowModelBlocker,
    build_unified_shadow_model_snapshot,
    persist_unified_snapshot,
    unified_paths,
)


def _pid_snapshot(repo: Path) -> dict[str, int | None]:
    paths = unified_paths(repo)
    out: dict[str, int | None] = {}
    for name, key in (
        ("LIVE1A", "live1a_pid"),
        ("LIVE1B", "live1b_pid"),
        ("EQCORR", "eqcorr_pid"),
        ("STP2.1", "stp_pid"),
    ):
        p = paths[key]
        try:
            out[name] = int(p.read_text(encoding="utf-8").strip()) if p.exists() else None
        except ValueError:
            out[name] = None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--json", action="store_true", help="Print full snapshot JSON")
    args = parser.parse_args()
    repo = args.repo.resolve()

    pids_before = _pid_snapshot(repo)
    try:
        snapshot = build_unified_shadow_model_snapshot(repo_root=repo)
        result = persist_unified_snapshot(snapshot, repo_root=repo)
    except ShadowModelBlocker as exc:
        print(json.dumps(exc.payload, indent=2, sort_keys=True))
        return 2

    pids_after = _pid_snapshot(repo)
    if pids_before != pids_after:
        print(
            json.dumps(
                {
                    "status": "SHADOW_MODEL_RUNTIME_BOUNDARY_VIOLATION",
                    "missing_or_conflicting_field": "process_pids",
                    "source_path": "run/*.pid",
                    "expected": pids_before,
                    "actual": pids_after,
                    "minimum_required_fix": "Builder must remain read-only; do not restart processes",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3

    summary = {
        "status": result["status"],
        "snapshot_id": result["snapshot_id"],
        "immutable_path": result["immutable_path"],
        "latest_path": result["latest_path"],
        "wrote_immutable": result["wrote_immutable"],
        "operational_status": snapshot.get("operational_status"),
        "evidence_status": snapshot.get("evidence_status"),
        "promotion_eligible": snapshot.get("promotion_eligible"),
        "coverage": snapshot.get("coverage"),
        "pids_unchanged": True,
        "pids": pids_after,
        "runtime_safety": snapshot.get("runtime_safety"),
    }
    if args.json:
        summary["snapshot"] = snapshot
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == "SHADOW_MODEL_ACTIVE_EQCORR_STP21_UNIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
