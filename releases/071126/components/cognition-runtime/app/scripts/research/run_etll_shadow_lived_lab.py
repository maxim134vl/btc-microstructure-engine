#!/usr/bin/env python3
"""ETLL Shadow Lab orchestrator: adapt → auction → EQCORR → first_candidates report.

External trader imports are not used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import ensure_lab_dirs, pack_paths  # noqa: E402

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(cmd: list[str]) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"src:.{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cmd failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    text = proc.stdout.strip()
    try:
        return json.loads(text[text.rfind("{") :])
    except Exception:
        return {"raw_stdout_tail": text[-2000:], "ok": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--limit-trades", type=int, default=None)
    parser.add_argument("--skip-auction", action="store_true")
    parser.add_argument("--from", dest="from_ts", default="2023-12-17T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-25T00:00:00Z")
    args = parser.parse_args()

    paths = pack_paths(args.pack_dir)
    ensure_lab_dirs(paths)
    py = str(ROOT / "venv" / "bin" / "python")

    adapt_cmd = [py, "scripts/research/adapt_lived_books_to_shadow_jsonl.py", "--pack-dir", str(args.pack_dir)]
    if args.limit_trades:
        adapt_cmd += ["--limit-trades", str(args.limit_trades)]
    adapt = _run(adapt_cmd)

    if paths["shadow_eqcorr"].exists():
        shutil.rmtree(paths["shadow_eqcorr"])
    paths["shadow_eqcorr"].mkdir(parents=True, exist_ok=True)

    auction = None
    if not args.skip_auction:
        auction_cmd = [
            py,
            "scripts/research/run_etll_shadow_auction_lived.py",
            "--pack-dir",
            str(args.pack_dir),
            "--skip-adapt",
            "--from",
            args.from_ts,
            "--to",
            args.to_ts,
        ]
        if args.limit_trades:
            auction_cmd += ["--limit-trades", str(args.limit_trades)]
        auction = _run(auction_cmd)

    eqcorr_cmd = [
        py,
        "scripts/research/run_etll_shadow_eqcorr_lived.py",
        "--pack-dir",
        str(args.pack_dir),
        "--skip-adapt",
    ]
    if args.limit_trades:
        eqcorr_cmd += ["--limit-trades", str(args.limit_trades)]
    eqcorr = _run(eqcorr_cmd)

    report = {
        "generated_at": _utc_now(),
        "stage": "ETLL_SHADOW_LIVED_LAB",
        "status": "SHADOW_LIVED_REPLAY_DONE",
        "external_trades_used": False,
        "scope": {
            "shadows": ["AUCTION_AES6", "EQCORR"],
            "deferred": ["STP2", "STP_BE33"],
            "lived_trades_limit": args.limit_trades,
        },
        "adapt": adapt,
        "auction": auction,
        "eqcorr": {
            "candidates": eqcorr.get("candidates"),
            "joined_with_candidate": eqcorr.get("joined_with_candidate"),
            "by_eqcorr_action_baseline": eqcorr.get("by_eqcorr_action_baseline"),
            "policy_action_rates": eqcorr.get("policy_action_rates"),
            "overall": eqcorr.get("overall"),
            "artifacts": eqcorr.get("artifacts"),
        },
        "artifacts": {
            "lab": str(paths["lab"]),
            "reports": str(paths["reports"]),
            "first_candidates": str(paths["reports"] / "first_candidates_summary.json"),
            "shadow_auction": str(paths["shadow_auction"]),
        },
        "next_step_ru": (
            "Первые shadow-кандидаты из наших lived сделок готовы. "
            "Дальше — unify / STP после tick pack. Чужие сделки пока не трогаем."
        ),
    }
    out = paths["reports"] / "first_candidates_summary.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    manifest_path = args.pack_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        manifest["status"] = "SHADOW_LIVED_REPLAY_DONE"
        manifest["shadow_lab"] = {
            "dir": str(paths["lab"]),
            "candidates": eqcorr.get("candidates"),
            "auction_status": None if not auction else auction.get("status"),
            "generated_at": report["generated_at"],
            "external_trades_used": False,
        }
        manifest["next_step_ru"] = report["next_step_ru"]
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
