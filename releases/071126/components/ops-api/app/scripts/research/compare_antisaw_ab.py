#!/usr/bin/env python3
"""ARCHIVED comparator for the dead bar-count anti-saw A/B.

The rails themselves are archived. Do not use this to revive min-hold/cooldown.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _load_summary(path: Path) -> dict:
    if path.is_dir():
        path = path / "lived_replay_summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _trades(path: Path) -> pd.DataFrame:
    if path.is_dir():
        path = path / "lived_trades.parquet"
    return pd.read_parquet(path)


def _anti_saw_counts(commands_path: Path) -> dict:
    if not commands_path.exists():
        return {"present": False}
    df = pd.read_parquet(commands_path)
    col = None
    for c in ("reason", "no_action_reason", "decision_reason", "detail"):
        if c in df.columns:
            col = c
            break
    if col is None:
        # search any string column
        hits = 0
        for c in df.columns:
            if df[c].dtype == object:
                s = df[c].astype(str)
                hits += int(s.str.contains("ANTI_SAW", na=False).sum())
        return {"present": True, "anti_saw_hits": hits}
    s = df[col].astype(str)
    return {
        "present": True,
        "anti_saw_hits": int(s.str.contains("ANTI_SAW", na=False).sum()),
        "entry_cooldown": int(s.str.contains("ANTI_SAW_ENTRY_COOLDOWN", na=False).sum()),
        "min_hold": int(s.str.contains("ANTI_SAW_MIN_HOLD", na=False).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on-dir", type=Path, required=True)
    parser.add_argument("--off-dir", type=Path, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "output/audits/etll_lived_replay_20260825/antisaw_ab_summary.json",
    )
    args = parser.parse_args()

    on_sum = _load_summary(args.on_dir)
    off_sum = _load_summary(args.off_dir)
    on_tr = _trades(args.on_dir)
    off_tr = _trades(args.off_dir)

    def metrics(df: pd.DataFrame) -> dict:
        if df is None or df.empty:
            return {"n": 0, "net_pnl": 0.0, "wr": 0.0}
        n = len(df)
        wins = int((df["net_pnl_usd"] > 0).sum()) if "net_pnl_usd" in df.columns else 0
        return {
            "n": n,
            "net_pnl": float(df["net_pnl_usd"].sum()) if "net_pnl_usd" in df.columns else 0.0,
            "wr": wins / max(n, 1),
            "avg_pnl": float(df["net_pnl_usd"].mean()) if "net_pnl_usd" in df.columns else 0.0,
        }

    on_m = metrics(on_tr)
    off_m = metrics(off_tr)
    on_cmd = _anti_saw_counts(args.on_dir / "manager_commands.parquet")
    off_cmd = _anti_saw_counts(args.off_dir / "manager_commands.parquet")

    delta_pnl = on_m["net_pnl"] - off_m["net_pnl"]
    verdict = "INCONCLUSIVE"
    if on_m["n"] and off_m["n"]:
        if delta_pnl > 0 and on_m["wr"] >= off_m["wr"] * 0.98:
            verdict = "PROVE_LEAN_ON_HELPS"
        elif delta_pnl < 0 and off_m["n"] > on_m["n"]:
            verdict = "REFUTE_LEAN_ON_HURTS_OR_BLOCKS_EDGE"
        else:
            verdict = "MIXED_REVIEW"

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": "ANTI_SAW_AB",
        "status": "ANTI_SAW_AB_DONE",
        "on": {"dir": str(args.on_dir), "metrics": on_m, "commands": on_cmd, "summary_keys": list(on_sum)[:12]},
        "off": {"dir": str(args.off_dir), "metrics": off_m, "commands": off_cmd, "summary_keys": list(off_sum)[:12]},
        "delta": {
            "net_pnl_on_minus_off": delta_pnl,
            "trades_on_minus_off": on_m["n"] - off_m["n"],
            "wr_on_minus_off": on_m["wr"] - off_m["wr"],
        },
        "gate_verdict": verdict,
        "note_ru": (
            "ON должен иметь ANTI_SAW_* hits; OFF — около нуля. "
            "Положительный delta PnL при сопоставимом WR → lean prove."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
