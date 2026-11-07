#!/usr/bin/env python3
"""Close the active paper epoch and start empty books on a new one.

Public labels restart at M15_1 / M30_1 / H1_1 / H4_1 because ordinals
are assigned inside the active epoch only. Cognition / live feed stay.
Paper-only. Does not start processes.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    from scripts.deploy.bootstrap_vps_environment import main as bootstrap_main
    from btc_ml.trading.command_bus import COMMAND_COLUMNS
    from btc_ml.trading.trader_book import atomic_write_json, atomic_write_parquet
    import pandas as pd

    data = Path("/app/data")
    if not data.exists():
        data = ROOT / "data"
    epochs = data / "trading" / "paper_epochs"
    old_path = epochs / "active.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    old_id = str(old["paper_epoch_id"])
    now = _utc()

    old["epoch_status"] = "CLOSED"
    old["closed_at"] = now
    old["closed_reason"] = "CLEAN_PNL_RESET_NEW_EPOCH"
    (epochs / f"{old_id}.json").write_text(
        json.dumps(old, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    repo = Path("/app") if (Path("/app") / "scripts" / "deploy").exists() else ROOT
    rc = bootstrap_main(
        [
            "--data-root",
            str(data),
            "--repo-root",
            str(repo),
            "--allow-existing",
            "--deployment-tag",
            "VPS_DEPLOY",
        ]
    )
    if rc != 0:
        return rc

    new = json.loads(old_path.read_text(encoding="utf-8"))
    new_id = str(new["paper_epoch_id"])
    if new_id == old_id:
        print(json.dumps({"error": "bootstrap_reused_epoch", "epoch": old_id}))
        return 2

    (epochs / f"{old_id}.json").write_text(
        json.dumps(old, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    mgr = data / "trading" / "manager"
    stamp = now.replace(":", "").replace("-", "")[:15]
    archive = data / "archive" / f"clean_pnl_{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("timeframe_command_memory.parquet", "manager_state.json", "portfolio_summary.json"):
        src = mgr / name
        if src.exists():
            shutil.copy2(src, archive / name)

    atomic_write_parquet(mgr / "timeframe_command_memory.parquet", pd.DataFrame(columns=list(COMMAND_COLUMNS)))
    atomic_write_json(
        mgr / "manager_state.json",
        {
            "cycles": 0,
            "timeframes": {},
            "last_manager_cycle_id": None,
            "last_evaluation_timestamp": None,
            "updated_at": now,
            "clean_pnl_reset": True,
            "previous_paper_epoch_id": old_id,
            "paper_epoch_id": new_id,
        },
    )
    atomic_write_json(
        mgr / "portfolio_summary.json",
        {
            "generated_at": now,
            "manager_cycle_id": None,
            "evaluation_timestamp": None,
            "read_model_only": True,
            "traders": {
                tf: {"timeframe": tf, "open_position": None, "open_risk_usd": 0.0}
                for tf in ("M15", "M30", "H1", "H4")
            },
            "clean_pnl_reset": True,
            "paper_epoch_id": new_id,
        },
    )
    latest = data / "runtime" / "timeframe_manager_latest.json"
    if latest.exists():
        shutil.copy2(latest, archive / latest.name)
    atomic_write_json(
        latest,
        {
            "generated_at": now,
            "clean_pnl_reset": True,
            "paper_epoch_id": new_id,
            "commands": {},
        },
    )

    marker = data / "deployment" / "clean_pnl_reset.json"
    marker.write_text(
        json.dumps(
            {
                "status": "CLEAN_PNL_RESET",
                "at": now,
                "previous_paper_epoch_id": old_id,
                "paper_epoch_id": new_id,
                "archive": str(archive),
                "paper_only": True,
                "real_execution_enabled": False,
                "note": "New empty LIVE1B books. Public labels restart at TF_1. Cognition/live feed kept.",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"previous": old_id, "new": new_id, "archive": str(archive)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
