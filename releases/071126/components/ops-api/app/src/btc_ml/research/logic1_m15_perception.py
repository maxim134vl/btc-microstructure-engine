"""M15 OPEN perception: ACTIVE is necessary, a contested push is not tradable.

Footprint at the closed bar is the reading. CatBoost is not used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.logic1_open_gate import DEFAULT_ARCHIVE, build_open_events, utc_iso

DEFAULT_FOOTPRINT_DIR = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_full_etll")
MIN_KEEP_FRAC = 0.70

ALLOW_ALL: dict[str, Any] = {
    "reject_fp_opp": False,
    "reject_rejection": False,
    "reject_cluster": False,
    "cluster_vol_share": 0.12,
    "reject_trapped": False,
    "reject_fade": False,
    "poc_against_max": 0.0,
}


def ns(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def load_footprint_bars(footprint_dir: Path) -> pd.DataFrame:
    features = pd.read_parquet(footprint_dir / "m15_footprint_features.parquet")
    features["timestamp"] = ns(features["timestamp"])
    numeric = (
        "fp_delta",
        "fp_buy_volume",
        "fp_sell_volume",
        "fp_volume",
        "fp_poc_position",
        "fp_vol_at_high_share",
        "fp_vol_at_low_share",
        "fp_delta_at_high",
        "fp_delta_at_low",
        "fp_delta_efficiency",
        "body",
        "upper_wick",
        "lower_wick",
        "close_position",
    )
    for col in numeric:
        if col in features.columns:
            features[col] = pd.to_numeric(features[col], errors="coerce")
    features = features.sort_values("timestamp").reset_index(drop=True)
    features["fp_delta_l1"] = features["fp_delta"].shift(1)
    features["upper_wick_l1"] = features["upper_wick"].shift(1)
    features["lower_wick_l1"] = features["lower_wick"].shift(1)
    features["body_l1"] = features["body"].shift(1)
    vr_path = footprint_dir / "volume_response_state_footprint.parquet"
    if vr_path.exists():
        vr = pd.read_parquet(
            vr_path,
            columns=[
                "timestamp",
                "effort_result_state",
                "continuation_quality",
                "volume_event",
                "effort_score",
                "result_score",
                "effort_result_ratio",
            ],
        )
        vr["timestamp"] = ns(vr["timestamp"])
        vr = vr.rename(columns={c: f"fvr_{c}" for c in vr.columns if c != "timestamp"})
        features = features.merge(vr, on="timestamp", how="left")
    return features


def attach_perception(events: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Causal: footprint row timestamp is bar OPEN, matching source_bar_open."""
    m15 = events.loc[events["timeframe"].astype(str).str.upper() == "M15"].copy()
    if m15.empty:
        return m15
    left = m15.copy()
    left["_k"] = ns(
        left["source_bar_open_ts"] if "source_bar_open_ts" in left.columns else utc_iso(left["source_bar_open"])
    )
    right = bars.copy()
    right["fp_bar_open"] = ns(right["timestamp"])
    right["_k"] = right["fp_bar_open"]
    clash = [c for c in right.columns if c in left.columns and c not in {"_k", "fp_bar_open"}]
    right = right.drop(columns=clash, errors="ignore").dropna(subset=["_k"]).sort_values("_k")
    out = pd.merge_asof(
        left.dropna(subset=["_k"]).sort_values("_k"),
        right,
        on="_k",
        direction="backward",
        allow_exact_matches=True,
    )
    out["fp_exact_bar"] = ns(out["fp_bar_open"]).astype("datetime64[ns, UTC]") == out["_k"].astype("datetime64[ns, UTC]")
    out = out.loc[out["fp_exact_bar"]].copy()
    side = out["side"].astype(str).str.upper()
    sign = np.where(side == "LONG", 1.0, -1.0)
    out["fp_signed_delta"] = pd.to_numeric(out["fp_delta"], errors="coerce") * sign
    out["fp_signed_delta_l1"] = pd.to_numeric(out["fp_delta_l1"], errors="coerce") * sign
    out["fp_opp"] = out["fp_signed_delta"] < 0
    out["fp_push"] = (out["fp_signed_delta"] > 0) & (out["fp_signed_delta_l1"] > 0)
    out["fp_fade"] = out["fp_push"] & (out["fp_signed_delta"] < out["fp_signed_delta_l1"])
    out["wick_against"] = np.where(side == "LONG", out["upper_wick"] > out["body"], out["lower_wick"] > out["body"])
    out["fp_trapped"] = (out["fp_signed_delta"] > 0) & out["wick_against"].fillna(False)
    out["fp_rej_against"] = np.where(
        side == "LONG",
        out["fp_upper_rejection"].fillna(False),
        out["fp_lower_rejection"].fillna(False),
    ).astype(bool)
    out["vol_against"] = np.where(side == "LONG", out["fp_vol_at_high_share"], out["fp_vol_at_low_share"])
    out["delta_at_against"] = np.where(side == "LONG", out["fp_delta_at_high"], out["fp_delta_at_low"])
    out["cluster_against"] = np.where(
        side == "LONG",
        (out["fp_vol_at_high_share"] >= 0.12) & (out["fp_delta_at_high"] < 0),
        (out["fp_vol_at_low_share"] >= 0.12) & (out["fp_delta_at_low"] > 0),
    )
    poc = pd.to_numeric(out["fp_poc_position"], errors="coerce")
    out["poc_against"] = np.where(side == "LONG", poc <= 0.35, poc >= 0.65)
    out["loss"] = pd.to_numeric(out["R"], errors="coerce") < 0
    out["win"] = pd.to_numeric(out["R"], errors="coerce") > 0
    return out.reset_index(drop=True)


def build_m15_open_matrix(
    archive: Path | None = None,
    *,
    footprint_dir: Path | None = None,
    pack_root: Path | None = None,
) -> pd.DataFrame:
    events = build_open_events(archive or DEFAULT_ARCHIVE, pack_root=pack_root)
    bars = load_footprint_bars(footprint_dir or DEFAULT_FOOTPRINT_DIR)
    return attach_perception(events, bars)


def contested_mask(frame: pd.DataFrame, policy: dict[str, Any]) -> np.ndarray:
    """True = push is already contested, OPEN would be a misread."""
    n = len(frame)
    hit = np.zeros(n, dtype=bool)
    if bool(policy.get("reject_fp_opp")):
        hit |= frame["fp_opp"].fillna(False).to_numpy(dtype=bool)
    if bool(policy.get("reject_rejection")):
        hit |= frame["fp_rej_against"].fillna(False).to_numpy(dtype=bool)
    if bool(policy.get("reject_cluster")):
        share = float(policy.get("cluster_vol_share") or 0.12)
        side = frame["side"].astype(str).str.upper()
        vol = pd.to_numeric(frame["vol_against"], errors="coerce").to_numpy()
        delta_ext = pd.to_numeric(frame["delta_at_against"], errors="coerce").to_numpy()
        long = (side == "LONG").to_numpy()
        cluster = (np.isfinite(vol) & (vol >= share) & np.where(long, delta_ext < 0, delta_ext > 0)).astype(bool)
        hit |= cluster
    if bool(policy.get("reject_trapped")):
        hit |= frame["fp_trapped"].fillna(False).to_numpy(dtype=bool)
    if bool(policy.get("reject_fade")):
        hit |= frame["fp_fade"].fillna(False).to_numpy(dtype=bool)
    poc_max = float(policy.get("poc_against_max") or 0.0)
    if poc_max > 0:
        poc = pd.to_numeric(frame["fp_poc_position"], errors="coerce").to_numpy()
        side = frame["side"].astype(str).str.upper()
        long = (side == "LONG").to_numpy()
        against = np.isfinite(poc) & np.where(long, poc <= poc_max, poc >= (1.0 - poc_max))
        hit |= against.astype(bool)
    return hit


def tradable_mask(frame: pd.DataFrame, policy: dict[str, Any]) -> np.ndarray:
    return ~contested_mask(frame, policy)


def score_policy(
    frame: pd.DataFrame,
    policy: dict[str, Any],
    *,
    min_keep_frac: float = MIN_KEEP_FRAC,
) -> dict[str, Any]:
    kept = tradable_mask(frame, policy)
    n = int(len(frame))
    n_kept = int(kept.sum())
    frac = (n_kept / n) if n else 0.0
    loss = frame["loss"].fillna(False).to_numpy(dtype=bool)
    win = frame["win"].fillna(False).to_numpy(dtype=bool)
    if n == 0 or frac < float(min_keep_frac):
        return {
            "n": n,
            "n_kept": n_kept,
            "keep_frac": round(frac, 4),
            "remaining_losers": None,
            "losers_caught": int((~kept & loss).sum()),
            "winners_dropped": int((~kept & win).sum()),
            "p_loss_kept": None,
            "rejected": "keep_frac_below_floor",
        }
    remaining = int((kept & loss).sum())
    caught = int((~kept & loss).sum())
    dropped_win = int((~kept & win).sum())
    return {
        "n": n,
        "n_kept": n_kept,
        "keep_frac": round(frac, 4),
        "remaining_losers": remaining,
        "losers_caught": caught,
        "winners_dropped": dropped_win,
        "p_loss_kept": round(float(remaining / n_kept), 4) if n_kept else None,
        "p_loss_all": round(float(loss.mean()), 4),
        "rejected": None,
    }


def mean_fold_remaining_losers(
    frame: pd.DataFrame,
    policy: dict[str, Any],
    folds: list[tuple[np.ndarray, np.ndarray]],
    *,
    min_keep_frac: float = MIN_KEEP_FRAC,
) -> tuple[float, list[float]]:
    per: list[float] = []
    for _, score_idx in folds:
        result = score_policy(frame.iloc[score_idx], policy, min_keep_frac=min_keep_frac)
        if result["rejected"] or result["remaining_losers"] is None:
            return float("inf"), per + [float("inf")]
        per.append(float(result["remaining_losers"]))
    if not per:
        return float("inf"), per
    return float(np.mean(per)), per
