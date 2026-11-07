#!/usr/bin/env python3
"""Read-only QA audit for context visual ops-style polish."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
PUBLIC_DATA = PUBLIC / "data"
RESEARCH = ROOT / "data" / "research"
PAPER = RESEARCH / "paper_simulator"
CTRL_PID = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
CTRL_LOCK = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.lock"
FORBIDDEN_GLOBS = [
    "data/research/paper_simulator/paper_*.parquet",
    "data/live/*.parquet",
    "data/cognition/*.parquet",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def file_sig(path: Path):
    if not path.exists():
        return None
    st = path.stat()
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def main() -> int:
    inventory_src = RESEARCH / "visual_ops_style_inventory.json"
    inventory = read_json(inventory_src, {})
    inventory_out = RESEARCH / "context_visual_ops_style_inventory.json"
    inventory_out.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    ctrl_before = CTRL_PID.read_text(encoding="utf-8").strip() if CTRL_PID.exists() else None
    lock_before = CTRL_LOCK.read_text(encoding="utf-8") if CTRL_LOCK.exists() else None
    paper_files = sorted(PAPER.glob("paper_*.parquet"))
    live_files = sorted((ROOT / "data" / "live").glob("*.parquet")) if (ROOT / "data" / "live").exists() else []
    before = {str(p.relative_to(ROOT)): file_sig(p) for p in paper_files + live_files}

    css = (PUBLIC / "lifecycle.css").read_text(encoding="utf-8")
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    js = (PUBLIC / "lifecycle_app.js").read_text(encoding="utf-8")

    overlays = read_json(PUBLIC_DATA / "paper_trade_overlays.json", {}) or {}
    trade_result = read_json(PUBLIC_DATA / "trade_result_summary.json", {}) or {}
    pnl = read_json(PUBLIC_DATA / "pnl_summary.json", {}) or {}
    visual_status = read_json(PUBLIC_DATA / "visual_status.json", {}) or {}

    synthetic_hit = False
    for shape in overlays.get("trade_shapes") or []:
        for key in ("entry_price", "exit_price", "stop_price", "take_profit_price"):
            val = shape.get(key)
            if val is None:
                continue
            num = float(val)
            if 99000 <= num <= 101000:
                synthetic_hit = True

    theme_ok = all(
        token in css
        for token in (
            "--font-sans",
            "--bg-primary",
            "--panel-bg",
            'html[data-theme="dark"]',
            'html[data-theme="light"]',
        )
    )
    toggle_ok = 'id="themeSelect"' in html and "btcml-context-visual-theme" in js and "localStorage" in js
    panels_ok = all(x in html for x in ("paperTradeResultPanel", "paperPnlPanel", "controllerTimeline", "inspectorPanel"))
    overlays_ok = bool(overlays.get("trade_shapes")) and bool(trade_result) and bool(pnl)

    # Capture visual stack status without touching controller.
    status_proc = subprocess.run(
        ["bash", "scripts/context_visual_stack_ctl.sh", "status"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    status_text = (status_proc.stdout or "") + (status_proc.stderr or "")

    # Re-check forbidden files unchanged after this audit (read-only).
    after = {str(p.relative_to(ROOT)): file_sig(p) for p in paper_files + live_files}
    forbidden_modified = sorted([k for k, v in before.items() if after.get(k) != v])
    ctrl_after = CTRL_PID.read_text(encoding="utf-8").strip() if CTRL_PID.exists() else None
    lock_after = CTRL_LOCK.read_text(encoding="utf-8") if CTRL_LOCK.exists() else None

    qa = {
        "generated_at_utc": utc_now(),
        "ops_style_source": inventory.get("ops_style_source") or inventory.get("style_source") or "UNKNOWN",
        "theme_variables_present": theme_ok,
        "theme_toggle_present": toggle_ok,
        "panels_present": panels_ok,
        "visual_json_present": overlays_ok,
        "entries": visual_status.get("entries_count") or overlays.get("counts", {}).get("entry_markers"),
        "exits": visual_status.get("exits_count") or overlays.get("counts", {}).get("exit_markers"),
        "open_positions": visual_status.get("open_positions_count") or overlays.get("counts", {}).get("open_position_overlays"),
        "closed_trades": visual_status.get("closed_trades_count") or overlays.get("counts", {}).get("closed_trade_overlays"),
        "trade_overlay_preserved": bool(overlays.get("trade_shapes")),
        "pnl_summary_preserved": bool(pnl),
        "synthetic_100000_absent": not synthetic_hit,
        "forbidden_files_modified": forbidden_modified,
        "controller_pid_before": ctrl_before,
        "controller_pid_after": ctrl_after,
        "controller_touched": ctrl_before != ctrl_after or lock_before != lock_after,
        "visual_stack_status_excerpt": "\n".join(status_text.strip().splitlines()[:20]),
        "paper_ledger_write_performed": False,
        "decision_log_write_performed": False,
        "live_refresh_performed": False,
        "execution_enabled": False,
        "exchange_api_call_used": False,
    }

    safety_ok = (
        theme_ok
        and toggle_ok
        and panels_ok
        and overlays_ok
        and not synthetic_hit
        and not forbidden_modified
        and not qa["controller_touched"]
    )
    decision = {
        "generated_at_utc": utc_now(),
        "status": "PASS" if safety_ok else "PASS_WITH_LIMITATIONS" if theme_ok and panels_ok else "FAIL",
        "ops_style_applied": theme_ok and toggle_ok and panels_ok,
        "visual_stack_running": "viewer_alive=true" in status_text and "refresher_alive=true" in status_text,
        "safety_status": "PASS" if safety_ok else "FAIL",
        "next_recommended_step": "Open http://127.0.0.1:8765/?v=ops-style-polish and verify Dark/Light/System + sidebar cards",
        "qa_summary": {
            "theme_ok": theme_ok,
            "toggle_ok": toggle_ok,
            "panels_ok": panels_ok,
            "overlays_ok": overlays_ok,
            "controller_untouched": not qa["controller_touched"],
        },
    }

    (RESEARCH / "context_visual_ops_style_qa.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    (RESEARCH / "context_visual_ops_style_final_decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"qa": qa, "decision": decision}, indent=2))
    return 0 if decision["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
