#!/usr/bin/env python3
"""Single access point for the frozen ETLL Hybrid calibration split.

Every Shadow / Anti-Saw / EQCORR calibration must slice trades through here rather
than hardcoding dates, so that "train" means the same window everywhere and the
holdout stays sealed. Run with --verify to confirm the committed boundaries still
reproduce the recorded trade counts against a book.

  python3 scripts/research/calibration_split.py --verify --trades <trades.jsonl>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SPLIT_PATH = ROOT / "config" / "research" / "etll_hybrid_calibration_split.json"

SEGMENTS = ("train", "validation", "holdout")


def load_split(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or SPLIT_PATH).read_text(encoding="utf-8"))


def market_ts(frame: pd.DataFrame, split: dict[str, Any] | None = None) -> pd.Series:
    """Market-clock exit time. ISO8601 is mandatory; see split.timestamp_parse."""
    cfg = split or load_split()
    col = cfg["timestamp_field"]
    return pd.to_datetime(frame[col], utc=True, errors="coerce", format="ISO8601")


def assign_segment(frame: pd.DataFrame, split: dict[str, Any] | None = None) -> pd.Series:
    """Label each trade train/validation/holdout, or "purged" if it falls in a gap.

    Gaps are not an edge case to be tidied away: a trade landing in one has an
    outcome window straddling two segments, which is exactly what the purge exists
    to keep out of the training set.
    """
    cfg = split or load_split()
    ts = market_ts(frame, cfg)
    out = pd.Series(["purged"] * len(frame), index=frame.index, dtype=object)
    for name in SEGMENTS:
        seg = cfg["segments"][name]
        lo = pd.Timestamp(seg["from"])
        hi = pd.Timestamp(seg["to"])
        out[(ts >= lo) & (ts < hi)] = name
    return out


def load_trades(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    frame = pd.DataFrame(rows)
    frame["net_pnl"] = pd.to_numeric(frame.get("net_pnl_usd"), errors="coerce").fillna(0.0)
    risk = pd.to_numeric(frame.get("risk_amount_usd"), errors="coerce").replace(0, pd.NA)
    frame["r_multiple"] = frame["net_pnl"] / risk
    return frame


def verify(trades_path: Path) -> dict[str, Any]:
    cfg = load_split()
    frame = load_trades(trades_path)
    frame["segment"] = assign_segment(frame, cfg)

    report: dict[str, Any] = {"trades_in_book": int(len(frame)), "segments": {}, "mismatches": []}
    for name in SEGMENTS:
        seg = cfg["segments"][name]
        got = frame.loc[frame.segment == name]
        expected_n = int(seg["trades"])
        entry = {
            "expected_trades": expected_n,
            "actual_trades": int(len(got)),
            "expected_expectancy_r": seg["expectancy_r"],
            "actual_expectancy_r": round(float(got["r_multiple"].mean()), 3),
        }
        report["segments"][name] = entry
        if int(len(got)) != expected_n:
            report["mismatches"].append(f"{name}: expected {expected_n} trades, got {len(got)}")
        if abs(entry["actual_expectancy_r"] - float(seg["expectancy_r"])) > 0.001:
            report["mismatches"].append(
                f"{name}: expectancy {entry['actual_expectancy_r']} vs recorded {seg['expectancy_r']}"
            )

    purged = int((frame.segment == "purged").sum())
    report["purged_trades"] = purged
    if purged != int(cfg["trades_sacrificed_to_purge"]):
        report["mismatches"].append(
            f"purged: expected {cfg['trades_sacrificed_to_purge']}, got {purged}"
        )
    report["status"] = "OK" if not report["mismatches"] else "MISMATCH"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--trades", type=Path, default=None)
    args = parser.parse_args()

    if args.verify:
        if args.trades is None:
            parser.error("--verify needs --trades")
        print(json.dumps(verify(args.trades), indent=2, ensure_ascii=False))
        return 0

    print(json.dumps(load_split(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
