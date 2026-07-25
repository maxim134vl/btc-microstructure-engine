#!/usr/bin/env python3
"""Patch 4.3 §5 — preflight capture before trade visual parity activation.

Read-only: records runtime identity, payload hashes and source inventory so the
activation can be rolled back from a proven baseline.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "data" / "research"
PUBLIC_DATA = ROOT / "apps" / "context_visualizer" / "public" / "data"

HASHED_FILES = [
    "scripts/live/run_market_context_visual_refresher.py",
    "scripts/live/visual_paper_trade_overlay_builder.py",
    "apps/context_visualizer/generate_lifecycle_context_data.py",
    "apps/context_visualizer/public/index.html",
    "apps/context_visualizer/public/lifecycle.css",
    "apps/context_visualizer/public/styles.css",
    "apps/context_visualizer/public/lifecycle_app.js",
    "dashboard/frontend/src/index.css",
    "apps/context_visualizer/public/data/paper_trade_overlays.json",
    "apps/context_visualizer/public/data/normalized_trade_render_layer.json",
    "apps/context_visualizer/public/data/pnl_summary.json",
    "data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet",
    "data/research/paper_simulator/normalized_trade_render_layer.parquet",
    "data/research/paper_simulator/closed_trade_report.parquet",
]

SEMANTIC_DATASETS = [
    "data/cognition/final_market_context_memory.parquet",
    "data/cognition/market_context_lifecycle_memory.parquet",
    "data/trading/manager/timeframe_command_memory.parquet",
]

PROCESS_PATTERNS = {
    "live_feed": "live_binance_intrabar_feed.py",
    "canonical_pipeline": "run.py",
    "context_refresher": "run_context_refresh_daemon.py",
    "visual_refresher": "run_market_context_visual_refresher.py",
    "ops_backend": "run_api.py",
    "timeframe_manager": "timeframe_manager_daemon.py",
    "trader_M15": "timeframe_trader_daemon.py --timeframe M15",
    "trader_M30": "timeframe_trader_daemon.py --timeframe M30",
    "trader_H1": "timeframe_trader_daemon.py --timeframe H1",
    "trader_H4": "timeframe_trader_daemon.py --timeframe H4",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_of(path: Path) -> str | None:
    if not path.exists() or path.is_dir():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    return {
        "path": rel,
        "exists": path.exists(),
        "sha256": sha256_of(path),
        "mtime": path.stat().st_mtime if path.exists() else None,
        "size": path.stat().st_size if path.exists() else None,
    }


def ps_table() -> list[tuple[int, str]]:
    out = subprocess.run(
        ["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=20
    ).stdout
    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        head, _, rest = line.partition(" ")
        try:
            rows.append((int(head), rest.strip()))
        except ValueError:
            continue
    return rows


def inspect_processes() -> dict[str, Any]:
    table = ps_table()
    result: dict[str, Any] = {}
    for role, needle in PROCESS_PATTERNS.items():
        matches = [
            {"pid": pid, "command": cmd}
            for pid, cmd in table
            if needle in cmd and "ps -ax" not in cmd
        ]
        result[role] = {
            "pattern": needle,
            "pids": [m["pid"] for m in matches],
            "running": bool(matches),
            "command": matches[0]["command"] if matches else None,
        }
    return result


def source_inventory() -> dict[str, Any]:
    import pandas as pd

    inv: dict[str, Any] = {}

    policy = ROOT / "data/research/paper_simulator/policy_context_canonical_bar_policy_trades.parquet"
    if policy.exists():
        frame = pd.read_parquet(policy)
        inv["policy_context_source"] = {
            "path": str(policy.relative_to(ROOT)),
            "rows": int(len(frame)),
            "unique_trade_ids": int(frame["trade_id"].astype(str).nunique()),
            "context_episode_ids": sorted(
                {str(v) for v in frame.get("context_episode_id", pd.Series(dtype=str)).tolist()}
            ),
        }

    archive = ROOT / "data/archive/legacy_global_paper_ledger_20260724_202010"
    positions = archive / "paper_positions.parquet"
    if positions.exists():
        frame = pd.read_parquet(positions)
        ids = frame["position_id"].astype(str)
        inv["legacy_archive"] = {
            "dir": str(archive.relative_to(ROOT)),
            "positions": int(len(frame)),
            "closed": int((frame["status"].astype(str).str.upper() == "CLOSED").sum()),
            "open": int((frame["status"].astype(str).str.upper() == "OPEN").sum()),
            "controller_positions": int(ids.str.contains("_CTRL_").sum()),
            "one_shot_positions": int(ids.str.contains("_ONE_SHOT_").sum()),
            "read_only": all(
                not (path.stat().st_mode & 0o200)
                for path in sorted(archive.glob("*.parquet"))
            ),
        }

    books: dict[str, Any] = {}
    for timeframe in ("M15", "M30", "H1", "H4"):
        book = ROOT / "data/trading/timeframe_traders" / timeframe
        trades = book / "trades.parquet"
        positions_path = book / "positions.parquet"
        books[timeframe] = {
            "dir": str(book.relative_to(ROOT)),
            "exists": book.exists(),
            "trades": int(len(pd.read_parquet(trades))) if trades.exists() else 0,
            "positions": int(len(pd.read_parquet(positions_path)))
            if positions_path.exists()
            else 0,
        }
    inv["s4_books"] = books

    activation = ROOT / "data/trading/manager/activation.json"
    if activation.exists():
        payload = json.loads(activation.read_text(encoding="utf-8"))
        inv["s4_activation_timestamp"] = payload.get("activation_timestamp")
    return inv


def visual_state() -> dict[str, Any]:
    state: dict[str, Any] = {}
    overlays = PUBLIC_DATA / "paper_trade_overlays.json"
    if overlays.exists():
        payload = json.loads(overlays.read_text(encoding="utf-8"))
        state["paper_trade_overlays"] = {
            "generated_at_utc": payload.get("generated_at_utc"),
            "keys": sorted(payload.keys()),
            "source_closed": payload.get("source_closed"),
            "renderer_source": payload.get("renderer_source"),
            "controller_ledger_used_for_render": payload.get(
                "controller_ledger_used_for_render"
            ),
            "counts": payload.get("counts"),
        }
    pnl = PUBLIC_DATA / "pnl_summary.json"
    if pnl.exists():
        payload = json.loads(pnl.read_text(encoding="utf-8"))
        state["pnl_summary"] = {
            "pnl_mode": payload.get("pnl_mode"),
            "accounting_mode": payload.get("accounting_mode"),
            "legacy_layers_hidden_from_main": payload.get("legacy_layers_hidden_from_main"),
        }
    return state


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": utc_now(),
        "stage": "PATCH4_3_VISUAL_PARITY_PREFLIGHT",
        "stamp": stamp,
        "read_only": True,
        "branch": subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "git_status_short": subprocess.run(
            ["git", "status", "--short"], cwd=str(ROOT), capture_output=True, text=True
        ).stdout.splitlines(),
        "interpreter": sys.executable,
        "cwd": str(ROOT),
        "processes": inspect_processes(),
        "hashed_files": {rel: file_record(rel) for rel in HASHED_FILES},
        "semantic_datasets": {rel: file_record(rel) for rel in SEMANTIC_DATASETS},
        "source_inventory": source_inventory(),
        "visual_state": visual_state(),
        "flags_frozen": {
            "real_execution": False,
            "exchange_enabled": False,
            "BTC_ML_CONTINUATION_PROGRESSION": "0",
            "PRICE_GATE": "OFF",
        },
    }
    RESEARCH.mkdir(parents=True, exist_ok=True)
    out = RESEARCH / f"patch4_3_preflight_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (RESEARCH / "patch4_3_visual_parity_active_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(out.relative_to(ROOT)), "stamp": stamp}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
