#!/usr/bin/env python3
"""All-TF autopsy of losing Hybrid entries (train+validation, holdout sealed).

Uses candle delta/wicks plus M15 footprint clusters. Does not score allow/block
on total R and does not train CatBoost.
"""

from __future__ import annotations

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

OUT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1/loser_volume_autopsy.json"
FOOTPRINT = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_full_etll/m15_footprint_features.parquet")


def ns(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def rate(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    m = mask.fillna(False).astype(bool)
    loss = frame["loss"]
    if not m.any() or not (~m).any() or not loss.any():
        return {"n": int(m.sum())}
    p1 = float(frame.loc[m, "loss"].mean())
    p0 = float(frame.loc[~m, "loss"].mean())
    return {
        "n": int(m.sum()),
        "p_loss": round(p1, 4),
        "p_loss_if_not": round(p0, 4),
        "lift": round(p1 / p0, 3) if p0 else None,
        "catch_losers": round(float((m & loss).sum() / loss.sum()), 4),
    }


def load_candles(pack: Path, tf: str) -> pd.DataFrame:
    candle = pd.read_parquet(pack / f"market_pack_btc_{tf.lower()}" / "context" / "candle_structure_memory.parquet")
    vol = pd.read_parquet(pack / f"market_pack_btc_{tf.lower()}" / "context" / "volume_response_state.parquet")
    candle["timestamp"] = ns(candle["timestamp"])
    vol["timestamp"] = ns(vol["timestamp"])
    vol = vol.rename(columns={c: f"vr_{c}" for c in vol.columns if c != "timestamp"})
    bars = candle.merge(vol, on="timestamp", how="left").sort_values("timestamp")
    for col in ("delta", "body", "upper_wick", "lower_wick", "spread", "close_position"):
        bars[col] = pd.to_numeric(bars[col], errors="coerce")
    bars["delta_l1"] = bars["delta"].shift(1)
    bars["spread_l1"] = bars["spread"].shift(1)
    bars["result_l1"] = pd.to_numeric(bars.get("vr_result_score"), errors="coerce").shift(1)
    return bars


def main() -> int:
    pack = resolve_pack_root(None, ROOT)
    events = build_open_events(DEFAULT_ARCHIVE, pack_root=pack)
    events["segment"] = assign_segment(events, load_split())
    book_loss = int((events["R"] < 0).sum())
    frame = events.loc[events["segment"].isin(["train", "validation"])].copy()
    frame["loss"] = frame["R"] < 0

    parts: list[pd.DataFrame] = []
    for tf, group in frame.groupby("timeframe"):
        bars = load_candles(pack, str(tf))
        left = group.copy()
        left["_k"] = ns(left["source_bar_open_ts"])
        right = bars.rename(columns={"timestamp": "_k"})
        clash = [c for c in right.columns if c in left.columns and c != "_k"]
        right = right.drop(columns=clash, errors="ignore").dropna(subset=["_k"]).sort_values("_k")
        parts.append(
            pd.merge_asof(
                left.dropna(subset=["_k"]).sort_values("_k"),
                right,
                on="_k",
                direction="backward",
                allow_exact_matches=True,
            )
        )
    t = pd.concat(parts, ignore_index=True)
    sign = np.where(t["side"].astype(str).str.upper() == "LONG", 1.0, -1.0)
    t["signed_delta"] = t["delta"] * sign
    t["signed_delta_l1"] = t["delta_l1"] * sign
    t["push_already"] = (t["signed_delta"] > 0) & (t["signed_delta_l1"] > 0)
    t["fade"] = t["push_already"] & (t["signed_delta"] < t["signed_delta_l1"])
    t["wick_against"] = np.where(
        t["side"].astype(str).str.upper() == "LONG",
        t["upper_wick"] > t["body"],
        t["lower_wick"] > t["body"],
    )
    t["trapped"] = (t["signed_delta"] > 0) & t["wick_against"]
    t["efficient"] = t["vr_effort_result_state"].astype(str).eq("EFFICIENT_CONTINUATION")
    t["balanced"] = t["vr_effort_result_state"].astype(str).eq("BALANCED_RESPONSE")
    t["spread_up_result_down"] = (
        (t["spread"] >= t["spread_l1"])
        & (pd.to_numeric(t["vr_result_score"], errors="coerce") < t["result_l1"])
        & (t["signed_delta"] > 0)
    )
    t["late_and_trapped"] = t["push_already"] & t["trapped"]

    flags = [
        "fade",
        "wick_against",
        "trapped",
        "late_and_trapped",
        "balanced",
        "efficient",
        "spread_up_result_down",
    ]
    by_tf: dict[str, Any] = {}
    for tf, group in t.groupby("timeframe"):
        by_tf[str(tf)] = {
            "n": int(len(group)),
            "losers": int(group["loss"].sum()),
            "p_loss": round(float(group["loss"].mean()), 4),
            "flags": {name: rate(group, group[name]) for name in flags},
        }

    fp_report: dict[str, Any] | None = None
    if FOOTPRINT.exists():
        fp = pd.read_parquet(FOOTPRINT)
        fp["timestamp"] = ns(fp["timestamp"])
        m15 = t.loc[t["timeframe"].eq("M15")].copy()
        left = m15.copy()
        left["_k"] = ns(left["source_bar_open_ts"])
        right = fp.rename(columns={"timestamp": "_k"})
        clash = [c for c in right.columns if c in left.columns and c != "_k"]
        right = right.drop(columns=clash, errors="ignore").dropna(subset=["_k"]).sort_values("_k")
        f = pd.merge_asof(
            left.dropna(subset=["_k"]).sort_values("_k"),
            right,
            on="_k",
            direction="backward",
            allow_exact_matches=True,
        )
        fsign = np.where(f["side"].astype(str).str.upper() == "LONG", 1.0, -1.0)
        f["fp_opp"] = (f["fp_delta"] * fsign) < 0
        f["fp_rej_against"] = np.where(
            f["side"].astype(str).str.upper() == "LONG",
            f["fp_upper_rejection"].fillna(False),
            f["fp_lower_rejection"].fillna(False),
        ).astype(bool)
        f["cluster_against"] = (
            (f["side"].astype(str).str.upper() == "LONG")
            & (f["fp_vol_at_high_share"] >= 0.12)
            & (f["fp_delta_at_high"] < 0)
        ) | (
            (f["side"].astype(str).str.upper() == "SHORT")
            & (f["fp_vol_at_low_share"] >= 0.12)
            & (f["fp_delta_at_low"] > 0)
        )
        fp_report = {
            "coverage": "M15 full book span, not used by the Hybrid context writer",
            "n": int(len(f)),
            "flags": {
                "fp_delta_against_side": rate(f, f["fp_opp"]),
                "fp_rejection_against_side": rate(f, f["fp_rej_against"]),
                "fp_cluster_at_opposing_extreme": rate(f, f["cluster_against"]),
            },
        }

    report = {
        "segment": "train+validation",
        "holdout": "sealed",
        "book_losers_all_segments": book_loss,
        "window_n": int(len(t)),
        "window_losers": int(t["loss"].sum()),
        "all_tf": {name: rate(t, t[name]) for name in flags},
        "by_tf": by_tf,
        "m15_footprint": fp_report,
        "reading": (
            "Garbage entries are ACTIVE while the push is already being contested: "
            "delta still with us, opposite wick/rejection/cluster inside the same bar, "
            "or the delta is shrinking. Efficient continuation is the healthy reading. "
            "The book writer never saw M15 footprint clusters."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
