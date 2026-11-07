#!/usr/bin/env python3
"""Roll up Shadow Auction outcomes vs lived trades for prove/refute."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument(
        "--auction-summary",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "output/audits/etll_lived_replay_20260825/shadow_auction_efficiency.json",
    )
    parser.add_argument("--from", dest="from_ts", default="2026-06-01T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-01T00:00:00Z")
    args = parser.parse_args()

    lab = args.pack_dir / "lived_replay" / "shadow_lab"
    summary_path = args.auction_summary or (lab / "reports" / "shadow_auction_summary.json")
    auction_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    lived = pd.read_parquet(args.pack_dir / "lived_replay" / "lived_trades.parquet")
    entry = pd.to_datetime(lived["entry_ts"], utc=True)
    lived = lived[(entry >= pd.Timestamp(args.from_ts)) & (entry < pd.Timestamp(args.to_ts))]

    # Find latest replay outcomes
    outcomes = []
    replay_root = lab / "paper_repo" / "data" / "trading" / "shadow_auction" / "replay"
    if not replay_root.exists():
        # alternate path used by runner
        alt = args.pack_dir / "lived_replay" / "shadow_lab"
        for p in alt.rglob("shadow_outcome_memory.jsonl"):
            replay_root = p.parent.parent
            break
    outcome_files = list(Path(lab).rglob("shadow_outcome_memory.jsonl")) if lab.exists() else []
    for path in outcome_files:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                outcomes.append(json.loads(line))

    verdicts: dict[str, int] = {}
    for o in outcomes:
        v = str(o.get("final_shadow_verdict") or o.get("primary_outcome_label") or "UNKNOWN")
        verdicts[v] = verdicts.get(v, 0) + 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": "SHADOW_AUCTION_EFFICIENCY",
        "status": "DONE" if outcomes or auction_summary else "NO_OUTCOMES",
        "window": {"from": args.from_ts, "to": args.to_ts},
        "n_lived_trades_window": int(len(lived)),
        "lived_net_pnl_usd": float(lived["net_pnl_usd"].sum()) if len(lived) and "net_pnl_usd" in lived else 0.0,
        "auction_summary_status": auction_summary.get("status"),
        "auction_fidelity": auction_summary.get("fidelity"),
        "n_outcomes": len(outcomes),
        "verdict_counts": verdicts,
        "lifecycle_event_count": auction_summary.get("lifecycle_event_count"),
        "gate_verdict": (
            "GO_FULL_SPAN"
            if auction_summary.get("status") in {"AUCTION_REPLAY_DONE", "DONE"} and len(outcomes) > 0
            else "NO_GO_OR_EMPTY"
        ),
        "external_trades_used": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
