#!/usr/bin/env python3
"""Autopsy of toxic Hybrid-book entries (train only).

Question
--------
Losers are not "trades to forbid". They are moments when S4.1 treated
LONG/SHORT_CONTEXT + ACTIVE as a true reading of the market, then the trade
died at full stop. This script asks what the stack already knew at that OPEN.

It does not train CatBoost, does not open the holdout, and does not score
allow/block on total R.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from btc_ml.research.logic1_open_gate import (  # noqa: E402
    DEFAULT_ARCHIVE,
    build_open_events,
    resolve_pack_root,
)
from calibration_split import assign_segment, load_split  # noqa: E402

OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1"


def ns(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def attach_atr_and_volume(frame: pd.DataFrame, pack_root: Path) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for tf, group in frame.groupby("timeframe", sort=False):
        feed = pd.read_parquet(
            pack_root / f"market_pack_btc_{str(tf).lower()}" / f"feed_{str(tf).lower()}.parquet",
            columns=["timestamp", "high", "low", "close"],
        )
        feed["timestamp"] = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
        feed = feed.sort_values("timestamp")
        feed["atr14"] = (feed["high"] - feed["low"]).rolling(14, min_periods=5).median()
        left = group.copy()
        left["_k"] = ns(left["source_bar_open_ts"])
        right = pd.DataFrame(
            {
                "_k": feed["timestamp"].astype("datetime64[ns, UTC]"),
                "atr14": feed["atr14"].to_numpy(),
                "atr_close": feed["close"].to_numpy(),
            }
        ).dropna(subset=["_k"]).sort_values("_k")
        left = pd.merge_asof(
            left.dropna(subset=["_k"]).sort_values("_k"),
            right,
            on="_k",
            direction="backward",
            allow_exact_matches=True,
        )
        vol_path = pack_root / f"market_pack_btc_{str(tf).lower()}" / "context" / "volume_response_state.parquet"
        vol = pd.read_parquet(
            vol_path,
            columns=["timestamp", "volume_event", "continuation_quality", "localized_behavior"],
        )
        vol["_k"] = ns(vol["timestamp"])
        vol = vol.drop(columns=["timestamp"]).dropna(subset=["_k"]).sort_values("_k")
        left = pd.merge_asof(left, vol, on="_k", direction="backward", allow_exact_matches=True)
        parts.append(left)
    out = pd.concat(parts, ignore_index=True)
    out["stop_bps"] = 100.0
    out["atr_bps"] = (pd.to_numeric(out["atr14"], errors="coerce") / pd.to_numeric(out["atr_close"], errors="coerce")) * 1e4
    out["stop_vs_atr"] = out["stop_bps"] / out["atr_bps"].replace(0, np.nan)
    out["signed_origin_bps"] = pd.to_numeric(out["price_vs_origin_bps"], errors="coerce") * np.where(
        out["side"].astype(str).str.upper() == "LONG", 1.0, -1.0
    )
    loc = out["localized_behavior"].astype(str).str.lower()
    side = out["side"].astype(str).str.upper()
    out["absorption_or_passive"] = out["continuation_quality"].astype(str).eq("PASSIVE_DEFENSE") | out[
        "volume_event"
    ].astype(str).eq("ABSORPTION_VOLUME")
    out["localized_against"] = ((side == "LONG") & loc.str.contains("distribution")) | (
        (side == "SHORT") & loc.str.contains("absorption")
    )
    out["stop_inside_bar"] = out["stop_vs_atr"] < 1.0
    out["late_vs_origin"] = out["signed_origin_bps"] >= 50.0
    out["sl"] = out["exit_reason"].astype(str).str.upper().eq("SL")
    out["hold_hours"] = (out["exit_ts"] - out["entry_ts"]).dt.total_seconds() / 3600.0
    return out


def catch(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    m = mask.fillna(False)
    sl = frame["sl"]
    win = frame["R"] > 0
    n_flag = int(m.sum())
    return {
        "flagged": n_flag,
        "catch_sl": int((m & sl).sum()),
        "catch_sl_frac": round(float((m & sl).sum() / sl.sum()), 4) if sl.any() else None,
        "also_winners": int((m & win).sum()),
        "also_winners_frac": round(float((m & win).sum() / win.sum()), 4) if win.any() else None,
        "p_sl_if_flag": round(float(frame.loc[m, "sl"].mean()), 4) if n_flag else None,
        "p_sl_if_not": round(float(frame.loc[~m, "sl"].mean()), 4) if (~m).any() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--pack-root", type=Path, default=None)
    args = parser.parse_args()
    pack = resolve_pack_root(args.pack_root, ROOT)
    if pack is None:
        raise SystemExit("market packs not found")

    events = build_open_events(args.archive, pack_root=pack)
    events["segment"] = assign_segment(events, load_split())
    train = events.loc[events["segment"] == "train"].copy()
    train = attach_atr_and_volume(train, pack)

    sl = train.loc[train["sl"]]
    report: dict[str, Any] = {
        "segment": "train",
        "holdout": "sealed",
        "n": int(len(train)),
        "sl": int(train["sl"].sum()),
        "scratch_loss_not_sl": int(((train["R"] < 0) & ~train["sl"]).sum()),
        "wr": round(float((train["R"] > 0).mean()), 4),
        "exit_reasons": train["exit_reason"].value_counts().to_dict(),
        "sl_is_minus_one_r": round(float(sl["R"].median()), 4) if len(sl) else None,
        "sl_rate_by_tf": {k: round(float(v), 4) for k, v in train.groupby("timeframe")["sl"].mean().items()},
        "stop_vs_atr_median_by_tf": {
            k: round(float(v), 3) for k, v in train.groupby("timeframe")["stop_vs_atr"].median().items()
        },
        "sl_hold_hours_median_by_tf": {
            k: round(float(v), 3) for k, v in sl.groupby("timeframe")["hold_hours"].median().items()
        } if len(sl) else {},
        "perception_errors": {
            "stop_tighter_than_one_atr": catch(train, train["stop_inside_bar"]),
            "entry_already_50bps_past_origin": catch(train, train["late_vs_origin"]),
            "volume_absorption_still_labeled_active": catch(train, train["absorption_or_passive"]),
            "late_and_absorbed": catch(train, train["late_vs_origin"] & train["absorption_or_passive"]),
            "h4": catch(train, train["timeframe"].eq("H4")),
        },
        "reading": {
            "stop_is_100bps_on_every_tf": True,
            "sl_never_got_a_context_close": "measured separately in research notes: 0% of SL rows had a CLOSE command on the same episode before exit",
            "meaning": (
                "ACTIVE was still the lifecycle's belief when price hit the 100bps stop. "
                "On H4 that stop is ~0.7 of one bar, so the context was never given time to invalidate. "
                "The misread is treating a multi-hour regime as if the next 100bps of price must agree."
            ),
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "toxic_entry_autopsy_train.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
