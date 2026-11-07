"""Step 4: dead-at-birth losers among near-origin OPENs.

Not a trainer. Label is never-followed from origin (B_NEVER), not SL.
Universe is NO_CHASE only so A_LAG does not leak into the reading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.logic1_loser_origin import (
    CHASE_NONE,
    PATH_NEVER,
    utc_ns,
)

MIN_B_TO_TRAIN = 80
BIRTH_FLAGS = (
    "origin_bar_against",
    "wick_against",
    "trapped",
    "fade",
    "absorption_or_passive",
    "localized_against",
    "balanced_response",
)


def load_tf_birth_bars(pack_root: Path, timeframe: str) -> pd.DataFrame:
    tf = str(timeframe).upper()
    base = Path(pack_root) / f"market_pack_btc_{tf.lower()}" / "context"
    candle = pd.read_parquet(base / "candle_structure_memory.parquet")
    vol = pd.read_parquet(base / "volume_response_state.parquet")
    candle["timestamp"] = utc_ns(candle["timestamp"])
    vol["timestamp"] = utc_ns(vol["timestamp"])
    vol = vol.rename(columns={c: f"vr_{c}" for c in vol.columns if c != "timestamp"})
    bars = candle.merge(vol, on="timestamp", how="left").sort_values("timestamp")
    for col in ("delta", "body", "upper_wick", "lower_wick"):
        if col in bars.columns:
            bars[col] = pd.to_numeric(bars[col], errors="coerce")
    if "delta" in bars.columns:
        bars["delta_l1"] = bars["delta"].shift(1)
    return bars.reset_index(drop=True)


def attach_birth_bar(events: pd.DataFrame, pack_root: Path) -> pd.DataFrame:
    """Join the origin bar (context_started_at = that bar's open)."""
    parts: list[pd.DataFrame] = []
    for tf, group in events.groupby("timeframe", sort=False):
        bars = load_tf_birth_bars(pack_root, str(tf))
        left = group.copy()
        left["_k"] = utc_ns(left["context_started_at"])
        right = bars.copy()
        right["_k"] = utc_ns(right["timestamp"])
        right["birth_timestamp"] = right["_k"]
        clash = [c for c in right.columns if c in left.columns and c not in {"_k"}]
        right = right.drop(columns=clash, errors="ignore").dropna(subset=["_k"]).sort_values("_k")
        merged = pd.merge_asof(
            left.dropna(subset=["_k"]).sort_values("_k"),
            right,
            on="_k",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["birth_bar_exact"] = utc_ns(merged["_k"]) == utc_ns(merged["birth_timestamp"])
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    side = out["side"].astype(str).str.upper()
    sign = np.where(side.eq("LONG"), 1.0, -1.0)
    delta = pd.to_numeric(out.get("delta"), errors="coerce")
    delta_l1 = pd.to_numeric(out.get("delta_l1"), errors="coerce")
    out["signed_delta"] = delta * sign
    out["signed_delta_l1"] = delta_l1 * sign
    out["origin_bar_against"] = out["signed_delta"] < 0
    out["wick_against"] = np.where(
        side.eq("LONG"),
        pd.to_numeric(out.get("upper_wick"), errors="coerce") > pd.to_numeric(out.get("body"), errors="coerce"),
        pd.to_numeric(out.get("lower_wick"), errors="coerce") > pd.to_numeric(out.get("body"), errors="coerce"),
    )
    out["trapped"] = (out["signed_delta"] > 0) & out["wick_against"].fillna(False)
    out["fade"] = (out["signed_delta"] > 0) & (out["signed_delta_l1"] > 0) & (out["signed_delta"] < out["signed_delta_l1"])
    loc = out.get("vr_localized_behavior", pd.Series("", index=out.index)).astype(str).str.lower()
    out["absorption_or_passive"] = out.get("vr_continuation_quality", pd.Series("", index=out.index)).astype(str).eq(
        "PASSIVE_DEFENSE"
    ) | out.get("vr_volume_event", pd.Series("", index=out.index)).astype(str).eq("ABSORPTION_VOLUME")
    out["localized_against"] = ((side == "LONG") & loc.str.contains("distribution")) | (
        (side == "SHORT") & loc.str.contains("absorption")
    )
    out["balanced_response"] = out.get("vr_effort_result_state", pd.Series("", index=out.index)).astype(str).eq(
        "BALANCED_RESPONSE"
    )
    out["dead_birth"] = (
        out["chase_axis"].astype(str).eq(CHASE_NONE)
        & out["path_axis"].astype(str).eq(PATH_NEVER)
        & out["loser"].astype(bool)
        & out["entry_kind"].astype(str).eq("FIRST_BIRTH")
    )
    out["no_chase_winner"] = out["chase_axis"].astype(str).eq(CHASE_NONE) & (
        pd.to_numeric(out["R"], errors="coerce") > 0
    )
    return out


def _flag_table(frame: pd.DataFrame, b_mask: pd.Series, win_mask: pd.Series) -> dict[str, Any]:
    n_b = int(b_mask.sum())
    n_win = int(win_mask.sum())
    out: dict[str, Any] = {}
    for name in BIRTH_FLAGS:
        flag = frame[name].fillna(False).astype(bool)
        catch = int((flag & b_mask).sum())
        win_hit = int((flag & win_mask).sum())
        out[name] = {
            "catch_b": catch,
            "catch_b_frac": round(catch / n_b, 4) if n_b else None,
            "winners_hit": win_hit,
            "winners_hit_frac": round(win_hit / n_win, 4) if n_win else None,
            "p_b_if_flag": round(float(b_mask[flag].mean()), 4) if flag.any() else None,
            "p_b_if_not": round(float(b_mask[~flag].mean()), 4) if (~flag).any() else None,
        }
    return out


def summarize_dead_birth(frame: pd.DataFrame) -> dict[str, Any]:
    no_chase = frame["chase_axis"].astype(str).eq(CHASE_NONE)
    b = frame["dead_birth"].astype(bool)
    wins = frame["no_chase_winner"].astype(bool)
    n_b = int(b.sum())
    return {
        "segment": "train",
        "holdout": "sealed",
        "universe": "NO_CHASE first-birth never-followed losers vs NO_CHASE winners",
        "n_no_chase": int(no_chase.sum()),
        "n_dead_birth": n_b,
        "n_no_chase_winners": int(wins.sum()),
        "min_b_to_train": MIN_B_TO_TRAIN,
        "enough_to_train": n_b >= MIN_B_TO_TRAIN,
        "b_by_tf": {str(k): int(v) for k, v in frame.loc[b, "timeframe"].value_counts().items()},
        "b_exit": {str(k): int(v) for k, v in frame.loc[b, "exit_reason"].value_counts().items()},
        "first_m15_against_b": round(float((pd.to_numeric(frame.loc[b, "first_m15_from_origin_bps"], errors="coerce") < 0).mean()), 4)
        if n_b
        else None,
        "first_m15_against_winners": round(
            float((pd.to_numeric(frame.loc[wins, "first_m15_from_origin_bps"], errors="coerce") < 0).mean()), 4
        )
        if wins.any()
        else None,
        "birth_flags": _flag_table(frame, b, wins),
        "decision": (
            "Do not train a dead-birth OPEN gate. n is below MIN_B_TO_TRAIN and first-M15-against "
            "is not a live feature (waiting one bar restores the 45-minute lag)."
            if n_b < MIN_B_TO_TRAIN
            else "n clears MIN_B_TO_TRAIN; still do not Optuna total R and do not open holdout."
        ),
    }
