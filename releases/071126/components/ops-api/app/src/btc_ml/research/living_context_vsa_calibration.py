"""Causal living-process + VSA entry calibration.

Features are known at bar close. Labels look forward. Do not use FALSE_BREAK
on the break bar — confirmation is stamped on the next close.
Does not write live cognition. Holdout stays sealed unless the caller opens it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.vsa_patterns import PATTERN_IDS, detect_vsa_patterns, load_vsa_config

ROOT = Path(__file__).resolve().parents[3]
LOCAL_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"
MAKSTIGER_PACK = Path(
    "/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders/market_pack_btc_m15"
)
CFG_PATH = ROOT / "config/research/living_context_vsa_calibration.json"
SPLIT_PATH = ROOT / "config/research/etll_hybrid_calibration_split.json"


def resolve_pack_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    for candidate in (LOCAL_PACK, MAKSTIGER_PACK):
        if (candidate / "feed_m15.parquet").exists():
            return candidate
    return LOCAL_PACK


DEFAULT_PACK = resolve_pack_dir()

LONG = "LONG"
SHORT = "SHORT"
PATTERN_ALLOW = {
    "ACCUMULATION_REGIME": "allow_accumulation",
    "DISTRIBUTION_REGIME": "allow_distribution",
    "TEST": "allow_test",
    "NO_EFFORT": "allow_no_effort",
    "ABSORPTION": "allow_absorption",
    "SHOCK": "allow_shock",
    "NR7_HIGH_VOL": "allow_nr7",
    "FALSE_BREAK": "allow_false_break",
}


def load_cfg(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CFG_PATH).read_text(encoding="utf-8"))


def load_split(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or SPLIT_PATH).read_text(encoding="utf-8"))


def assign_bar_segment(ts: pd.Series, split: dict[str, Any] | None = None) -> pd.Series:
    cfg = split or load_split()
    stamps = pd.to_datetime(ts, utc=True, errors="coerce")
    out = pd.Series(["purged"] * len(ts), index=ts.index, dtype=object)
    for name in ("train", "validation", "holdout"):
        seg = cfg["segments"][name]
        lo = pd.Timestamp(seg["from"])
        hi = pd.Timestamp(seg["to"])
        if lo.tzinfo is None:
            lo = lo.tz_localize("UTC")
        else:
            lo = lo.tz_convert("UTC")
        if hi.tzinfo is None:
            hi = hi.tz_localize("UTC")
        else:
            hi = hi.tz_convert("UTC")
        out[(stamps >= lo) & (stamps < hi)] = name
    return out


def _side_from_context(ctx: str) -> str | None:
    text = str(ctx or "").upper()
    if text in {"LONG", "LONG_CONTEXT"}:
        return LONG
    if text in {"SHORT", "SHORT_CONTEXT"}:
        return SHORT
    return None


def _side_from_vsa(pattern: str, signal: str, ctx_side: str | None) -> str | None:
    pattern_u = str(pattern or "").upper()
    signal_u = str(signal or "").upper()
    if pattern_u == "ACCUMULATION_REGIME" or signal_u == "BUY":
        return LONG
    if pattern_u == "DISTRIBUTION_REGIME" or signal_u == "SELL":
        return SHORT
    if signal_u in {"TREND_CONTINUATION", "HOLD_OR_TREND"}:
        return ctx_side
    if signal_u in {"REVERSAL", "REVERSAL_TO_RANGE", "WAIT_RETRACE"}:
        if ctx_side == LONG:
            return SHORT
        if ctx_side == SHORT:
            return LONG
        return None
    if signal_u == "BREAKOUT_PREP":
        return ctx_side
    return None


def build_feature_frame(
    *,
    pack_dir: Path,
    horizon_bars: int = 4,
) -> pd.DataFrame:
    """One row per closed bar. Label uses future close; features do not."""
    ctx_dir = pack_dir / "context"
    final_path = ctx_dir / "final_market_context_memory.parquet"
    candle_path = ctx_dir / "candle_structure_memory.parquet"
    volume_path = ctx_dir / "volume_response_state.parquet"
    if not final_path.exists() or not candle_path.exists():
        raise FileNotFoundError(f"missing context under {ctx_dir}")
    final = pd.read_parquet(final_path)
    candle = pd.read_parquet(candle_path)
    volume = pd.read_parquet(volume_path) if volume_path.exists() else None
    final["timestamp"] = pd.to_datetime(final["timestamp"], utc=True, errors="coerce")
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True, errors="coerce")
    flags = detect_vsa_patterns(candle, volume, load_vsa_config())
    flags["timestamp"] = pd.to_datetime(flags["timestamp"], utc=True, errors="coerce")
    keep_final = [
        c
        for c in (
            "timestamp",
            "close",
            "market_context",
            "living_process",
            "process_strength",
            "timeframe",
            "cognitive_market_state",
        )
        if c in final.columns
    ]
    work = final[keep_final].merge(flags, on="timestamp", how="inner", suffixes=("", "_vsa"))
    if "close" not in work.columns and "close_vsa" in work.columns:
        work["close"] = work["close_vsa"]
    work = work.sort_values("timestamp").reset_index(drop=True)
    close = pd.to_numeric(work["close"], errors="coerce")
    atr = pd.to_numeric(work.get("atr"), errors="coerce").replace(0, np.nan)
    future = close.shift(-int(horizon_bars))
    raw_ret = (future - close) / atr
    work["fwd_atr_return"] = raw_ret
    work["horizon_bars"] = int(horizon_bars)
    work["segment"] = assign_bar_segment(work["timestamp"])
    return work


def policy_side(row: pd.Series, policy: dict[str, Any]) -> str | None:
    ctx_side = _side_from_context(row.get("market_context"))
    strength = float(row.get("process_strength") or 0.0)
    min_strength = float(policy.get("min_process_strength") or 0.0)
    mode = str(policy.get("mode") or "both_agree")
    pattern = str(row.get("primary_pattern") or "NONE")
    signal = str(row.get("signal") or "NONE")
    vsa_side = _side_from_vsa(pattern, signal, ctx_side)
    allow_key = PATTERN_ALLOW.get(pattern)
    pattern_ok = True if allow_key is None else bool(policy.get(allow_key, True))
    if pattern == "NONE":
        pattern_ok = False
        vsa_side = None
    if mode == "context_only":
        return ctx_side if strength >= min_strength else None
    if mode == "vsa_only":
        if not pattern_ok or vsa_side is None:
            return None
        if min_strength > 0 and strength < min_strength:
            return None
        return vsa_side
    if not pattern_ok or ctx_side is None or vsa_side is None:
        return None
    if strength < min_strength:
        return None
    return ctx_side if ctx_side == vsa_side else None


def score_policy(frame: pd.DataFrame, policy: dict[str, Any], *, min_keep_frac: float) -> dict[str, Any]:
    y = pd.to_numeric(frame["fwd_atr_return"], errors="coerce").to_numpy()
    sides = [policy_side(row, policy) for row in frame.to_dict("records")]
    signed = np.array(
        [
            (val if side == LONG else -val if side == SHORT else np.nan)
            for side, val in zip(sides, y)
        ],
        dtype=float,
    )
    taken = np.isfinite(signed)
    n = int(np.isfinite(y).sum())
    n_kept = int(taken.sum())
    frac = (n_kept / n) if n else 0.0
    if n == 0 or frac < float(min_keep_frac):
        return {
            "n": n,
            "n_kept": n_kept,
            "keep_frac": round(frac, 4),
            "mean": float("-inf"),
            "hit_rate": None,
            "rejected": "keep_frac_below_floor",
        }
    kept = signed[taken]
    return {
        "n": n,
        "n_kept": n_kept,
        "keep_frac": round(frac, 4),
        "mean": round(float(np.mean(kept)), 6),
        "hit_rate": round(float(np.mean(kept > 0)), 4),
        "rejected": None,
    }


def purged_folds(
    ts: pd.Series,
    n_folds: int = 4,
    *,
    purge_days: int = 7,
    min_fit: int = 400,
    min_score: int = 200,
) -> list[tuple[np.ndarray, np.ndarray]]:
    entry = pd.to_datetime(ts, utc=True, errors="coerce")
    order = np.argsort(entry.values)
    stamps = entry.values[order]
    bounds = np.linspace(0, len(stamps), n_folds + 2, dtype=int)[1:]
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_folds):
        lo, hi = int(bounds[k]), int(bounds[k + 1])
        score_idx = order[lo:hi]
        cut = pd.Timestamp(stamps[lo]) - pd.Timedelta(days=purge_days)
        fit_ts = entry.values[order[:lo]]
        fit_idx = order[:lo][fit_ts < np.datetime64(cut)]
        if len(fit_idx) < int(min_fit) or len(score_idx) < int(min_score):
            continue
        folds.append((fit_idx, score_idx))
    return folds


def mean_fold_score(
    frame: pd.DataFrame,
    policy: dict[str, Any],
    folds: list[tuple[np.ndarray, np.ndarray]],
    *,
    min_keep_frac: float,
) -> tuple[float, list[float]]:
    per: list[float] = []
    for _, score_idx in folds:
        result = score_policy(frame.iloc[score_idx], policy, min_keep_frac=min_keep_frac)
        per.append(float(result["mean"]))
    if not per:
        return float("-inf"), []
    return float(np.mean(per)), per


FEATURE_COLS = [
    "process_strength",
    "relative_volume",
    "relative_spread",
    *PATTERN_IDS,
]


def encode_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    out["process_strength"] = pd.to_numeric(frame.get("process_strength"), errors="coerce").fillna(0.0)
    out["relative_volume"] = pd.to_numeric(frame.get("relative_volume"), errors="coerce").fillna(1.0)
    out["relative_spread"] = pd.to_numeric(frame.get("relative_spread"), errors="coerce").fillna(1.0)
    living = frame.get("living_process", pd.Series(["NONE"] * len(frame), index=frame.index)).astype(str).str.upper()
    out["living_buyer"] = (living == "BUYER").astype(float)
    out["living_seller"] = (living == "SELLER").astype(float)
    ctx = frame.get("market_context", pd.Series([""] * len(frame), index=frame.index)).astype(str).str.upper()
    out["ctx_long"] = ctx.isin({"LONG", "LONG_CONTEXT"}).astype(float)
    out["ctx_short"] = ctx.isin({"SHORT", "SHORT_CONTEXT"}).astype(float)
    for pid in PATTERN_IDS:
        if pid in frame.columns:
            out[pid] = frame[pid].fillna(False).astype(bool).astype(float)
        else:
            out[pid] = 0.0
    return out


def rf_signed_pred(model: Any, features: pd.DataFrame, min_abs_pred: float) -> np.ndarray:
    pred = np.asarray(model.predict(features.to_numpy()), dtype=float)
    out = np.full(len(pred), np.nan)
    strong = np.isfinite(pred) & (np.abs(pred) >= float(min_abs_pred))
    out[strong] = pred[strong]
    return out


def score_signed(y: np.ndarray, pred: np.ndarray, *, min_keep_frac: float) -> dict[str, Any]:
    taken = np.isfinite(y) & np.isfinite(pred)
    n = int(np.isfinite(y).sum())
    n_kept = int(taken.sum())
    frac = (n_kept / n) if n else 0.0
    if n == 0 or frac < float(min_keep_frac):
        return {
            "n": n,
            "n_kept": n_kept,
            "keep_frac": round(frac, 4),
            "mean": float("-inf"),
            "hit_rate": None,
            "rejected": "keep_frac_below_floor",
        }
    signed = np.sign(pred[taken]) * y[taken]
    return {
        "n": n,
        "n_kept": n_kept,
        "keep_frac": round(frac, 4),
        "mean": round(float(np.mean(signed)), 6),
        "hit_rate": round(float(np.mean(signed > 0)), 4),
        "rejected": None,
    }
