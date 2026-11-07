#!/usr/bin/env python3
"""Aggregate ETLL EQCORR lived summaries across timeframes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "output/audits/etll_eqcorr_verdict.json")
    args = parser.parse_args()

    rows = []
    for tf in ("M15", "M30", "H1", "H4"):
        slug = tf.lower()
        pack = ROOT / f"data/research/external_traders/market_pack_btc_{slug}"
        summary_path = pack / "lived_replay/shadow_lab/reports" / f"shadow_eqcorr_summary_{slug}.json"
        if tf == "M15" and not summary_path.exists():
            summary_path = pack / "lived_replay/shadow_lab/reports/shadow_eqcorr_summary.json"
        s = _load(summary_path)
        if not s:
            rows.append({"timeframe": tf, "status": "MISSING"})
            continue
        b = s.get("overall_baseline") or {}
        br = s.get("policy_action_rates") or {}
        rows.append(
            {
                "timeframe": tf,
                "status": s.get("status"),
                "lived_trades": s.get("lived_trades"),
                "candidates": s.get("candidates"),
                "policy_decisions": s.get("policy_decisions"),
                "joined": s.get("joined_with_candidate"),
                "baseline_wr": b.get("wr"),
                "baseline_pnl": b.get("net_pnl_usd"),
                "baseline_policy_block": (br.get("BASELINE_ALL_ELIGIBLE") or {}).get("block_rate"),
                "max1_same_dir_block": (br.get("MAX_1_SAME_DIRECTION") or {}).get("block_rate"),
                "risk_cap_100_block": (br.get("DIRECTION_RISK_CAP_100_BLOCK") or {}).get("block_rate"),
                f"{tf.lower()}_only_full": (br.get(f"{tf}_ONLY") or {}).get("execute_full_rate"),
                "summary_path": str(summary_path),
            }
        )

    done = [r for r in rows if r.get("status") == "EQCORR_BATCH_DONE"]
    verdict = {
        "stage": "ETLL_EQCORR_VERDICT",
        "timeframes_done": len(done),
        "timeframes_total": 4,
        "rows": rows,
        "note": (
            "Single-TF ETLL replay: cluster/correlation policies mostly block; "
            "BASELINE_ALL_ELIGIBLE = canonical book. Multi-TF filter eval needs combined books."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if len(done) == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
