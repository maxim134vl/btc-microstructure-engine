"""Practical VSA pattern detectors (VSA_PRACTICAL_V1).

Eight trading patterns from classical Volume Spread Analysis, mapped onto
candle_structure + volume_response_V2 features.

This is a research overlay — does not mutate AES / live cognition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CFG = ROOT / "config/research/vsa_practical_v1.json"

PATTERN_IDS = (
    "ACCUMULATION_REGIME",
    "DISTRIBUTION_REGIME",
    "TEST",
    "NO_EFFORT",
    "ABSORPTION",
    "SHOCK",
    "NR7_HIGH_VOL",
    "FALSE_BREAK",
)


def load_vsa_config(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_CFG
    return json.loads(p.read_text(encoding="utf-8"))


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = pd.Series(tr).rolling(n, min_periods=max(3, n // 2)).mean().to_numpy()
    return np.where(np.isfinite(out) & (out > 0), out, np.nanmedian(tr))


def _prepare_frame(candle: pd.DataFrame, volume_response: pd.DataFrame | None) -> pd.DataFrame:
    c = candle.copy()
    c["timestamp"] = pd.to_datetime(c["timestamp"], utc=True)
    c = c.sort_values("timestamp").reset_index(drop=True)
    if volume_response is not None and len(volume_response):
        vr = volume_response.copy()
        vr["timestamp"] = pd.to_datetime(vr["timestamp"], utc=True)
        cols = [
            x
            for x in (
                "timestamp",
                "relative_volume",
                "relative_spread",
                "volume_zscore",
                "volume_event",
                "participation_state",
                "effort_result_state",
                "upper_rejection",
                "lower_rejection",
            )
            if x in vr.columns
        ]
        c = c.merge(vr[cols], on="timestamp", how="left", suffixes=("", "_vr"))
    if "relative_volume" not in c.columns or c["relative_volume"].isna().all():
        vm = pd.to_numeric(c.get("volume_mean_20"), errors="coerce")
        vol = pd.to_numeric(c["volume"], errors="coerce")
        c["relative_volume"] = (vol / vm.replace(0, np.nan)).fillna(1.0).clip(0.05, 30.0)
    if "relative_spread" not in c.columns or c["relative_spread"].isna().all():
        sm = pd.to_numeric(c.get("spread_mean_20"), errors="coerce")
        sp = pd.to_numeric(c["spread"], errors="coerce")
        c["relative_spread"] = (sp / sm.replace(0, np.nan)).fillna(1.0).clip(0.05, 30.0)
    for col in (
        "open",
        "high",
        "low",
        "close",
        "spread",
        "body",
        "upper_wick",
        "lower_wick",
        "close_position",
        "volume",
        "volume_zscore",
        "spread_zscore",
        "relative_volume",
        "relative_spread",
    ):
        if col in c.columns:
            c[col] = pd.to_numeric(c[col], errors="coerce")
    c["candle_type"] = c.get("candle_type", pd.Series(["unknown"] * len(c))).astype(str)
    atr_n = 14
    c["atr"] = _atr(c["high"].to_numpy(), c["low"].to_numpy(), c["close"].to_numpy(), atr_n)
    return c


def detect_vsa_patterns(
    candle: pd.DataFrame,
    volume_response: pd.DataFrame | None = None,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Return one row per bar with boolean columns for each VSA_PRACTICAL_V1 pattern."""
    cfg = cfg or load_vsa_config()
    th = cfg["thresholds"]
    win = cfg["windows"]
    df = _prepare_frame(candle, volume_response)
    n = len(df)
    if n == 0:
        return df

    rv = df["relative_volume"].fillna(1.0).to_numpy()
    rs = df["relative_spread"].fillna(1.0).to_numpy()
    vz = df["volume_zscore"].fillna(0.0).to_numpy()
    sz = df["spread_zscore"].fillna(0.0).to_numpy()
    cp = df["close_position"].fillna(0.5).to_numpy()
    body = df["body"].fillna(0.0).to_numpy()
    upper = df["upper_wick"].fillna(0.0).to_numpy()
    lower = df["lower_wick"].fillna(0.0).to_numpy()
    spread = df["spread"].fillna(0.0).to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    atr = df["atr"].to_numpy()
    ctype = df["candle_type"].to_numpy()
    up_bar = close > open_
    down_bar = close < open_

    # --- NO_EFFORT: narrow spread + very low volume ---
    no_effort = (rs <= th["narrow_relative_spread"]) & (rv <= th["very_low_relative_volume"])

    # --- NR7_HIGH_VOL ---
    nr = int(win["nr_bars"])
    spread_min7 = pd.Series(spread).rolling(nr, min_periods=nr).min().to_numpy()
    nr7 = (spread > 0) & np.isfinite(spread_min7) & (spread <= spread_min7 * 1.0001)
    nr7_high_vol = nr7 & (rv >= th["high_relative_volume"])

    # --- SHOCK: extreme expansion, close away from extreme ---
    shock = (sz >= th["shock_spread_z"]) & (vz >= th["shock_volume_z"]) & (
        (upper > body * th["wick_vs_body"]) | (lower > body * th["wick_vs_body"]) | ((cp > 0.35) & (cp < 0.65))
    )
    # close away from extreme: not pinned at high after up shock / low after down shock
    shock = shock & ~((cp >= 0.9) & up_bar & (rs > 2.0)) & ~((cp <= 0.1) & down_bar & (rs > 2.0))

    # --- ABSORPTION: wide + extreme vol + mid/reject close near local S/R ---
    roll_hi = pd.Series(high).rolling(int(win["swing_lookback"]), min_periods=3).max().to_numpy()
    roll_lo = pd.Series(low).rolling(int(win["swing_lookback"]), min_periods=3).min().to_numpy()
    near_res = (high >= roll_hi - win["level_tolerance_atr"] * atr) | (
        np.abs(high - roll_hi) <= win["level_tolerance_atr"] * atr
    )
    near_sup = (low <= roll_lo + win["level_tolerance_atr"] * atr) | (
        np.abs(low - roll_lo) <= win["level_tolerance_atr"] * atr
    )
    mid_or_wick = ((cp >= th["close_mid_lo"]) & (cp <= th["close_mid_hi"])) | (
        (upper > body * th["wick_vs_body"]) | (lower > body * th["wick_vs_body"])
    )
    wide_extreme = (rs >= th["wide_relative_spread"]) & (rv >= th["extreme_relative_volume"])
    absorption = wide_extreme & mid_or_wick & (near_res | near_sup)
    # also honor existing STOPPING/ABSORPTION volume_event if present
    if "volume_event" in df.columns:
        ve = df["volume_event"].astype(str).to_numpy()
        absorption = absorption | (
            np.isin(ve, ["STOPPING_VOLUME", "ABSORPTION_VOLUME"]) & (rv >= th["high_relative_volume"])
        )

    # --- ACCUMULATION / DISTRIBUTION regimes (multi-bar ending at i) ---
    rb = int(win["regime_bars"])
    accum = np.zeros(n, dtype=bool)
    distrib = np.zeros(n, dtype=bool)
    hh = pd.Series(high).rolling(rb, min_periods=rb).max()
    ll = pd.Series(low).rolling(rb, min_periods=rb).min()
    hh_prev = hh.shift(rb // 2)
    ll_prev = ll.shift(rb // 2)
    rising = (hh > hh_prev) & (ll > ll_prev)
    falling = (hh < hh_prev) & (ll < ll_prev)
    # volume share on up vs down bars inside window
    vol = df["volume"].fillna(0.0).to_numpy()
    up_vol = np.where(up_bar, vol, 0.0)
    down_vol = np.where(down_bar, vol, 0.0)
    up_vol_sum = pd.Series(up_vol).rolling(rb, min_periods=rb).sum().to_numpy()
    down_vol_sum = pd.Series(down_vol).rolling(rb, min_periods=rb).sum().to_numpy()
    tot = up_vol_sum + down_vol_sum
    with np.errstate(divide="ignore", invalid="ignore"):
        up_share = np.where(tot > 0, up_vol_sum / tot, 0.5)
        down_share = np.where(tot > 0, down_vol_sum / tot, 0.5)
    mean_rs = pd.Series(rs).rolling(rb, min_periods=rb).mean().to_numpy()
    mean_cp = pd.Series(cp).rolling(rb, min_periods=rb // 2).mean().to_numpy()
    accum = (
        rising.fillna(False).to_numpy()
        & (up_share >= th["accumulation_up_vol_share"])
        & (mean_rs >= 1.0)
        & (mean_cp >= 0.55)
        & (cp >= th["close_high"] * 0.85)
    )
    distrib = (
        falling.fillna(False).to_numpy()
        & (down_share >= th["distribution_down_vol_share"])
        & (mean_rs >= 1.0)
        & (mean_cp <= 0.45)
        & (cp <= th["close_low"] * 1.15)
    )

    # --- TEST: return to prior climax/impulse extreme on much thinner volume ---
    test = np.zeros(n, dtype=bool)
    look = int(win["test_lookback"])
    # anchor candidates: prior shock / high RV wide bars
    anchor_score = (rv * rs) + np.where(vz > 1.0, vz, 0.0)
    for i in range(look, n):
        window_scores = anchor_score[i - look : i]
        j_rel = int(np.nanargmax(window_scores))
        j = i - look + j_rel
        if not np.isfinite(anchor_score[j]) or anchor_score[j] < th["high_relative_volume"]:
            continue
        # thinner + narrow + near anchor extreme
        if rv[i] > th["test_volume_ratio_vs_anchor"] * rv[j]:
            continue
        if rs[i] > th["narrow_relative_spread"] * 1.25:
            continue
        tol = win["level_tolerance_atr"] * atr[i]
        near_hi = abs(high[i] - high[j]) <= tol or abs(close[i] - high[j]) <= tol
        near_lo = abs(low[i] - low[j]) <= tol or abs(close[i] - low[j]) <= tol
        has_wick = (upper[i] > body[i] * 0.6) or (lower[i] > body[i] * 0.6)
        if (near_hi or near_lo) and has_wick:
            test[i] = True

    # --- FALSE_BREAK: break local level on high vol, close back; next bar vol drops ---
    false_break = np.zeros(n, dtype=bool)
    for i in range(2, n - 1):
        if rv[i] < th["high_relative_volume"]:
            continue
        prior_hi = float(np.nanmax(high[max(0, i - win["swing_lookback"]) : i]))
        prior_lo = float(np.nanmin(low[max(0, i - win["swing_lookback"]) : i]))
        broke_up = high[i] > prior_hi and close[i] < prior_hi
        broke_dn = low[i] < prior_lo and close[i] > prior_lo
        if not (broke_up or broke_dn):
            continue
        if rv[i + 1] > rv[i] * th["false_break_next_vol_drop"]:
            continue
        # Confirmation is known only at the next bar close.
        false_break[i + 1] = True

    out = df[
        [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "spread",
            "volume",
            "relative_volume",
            "relative_spread",
            "close_position",
            "atr",
            "candle_type",
        ]
    ].copy()
    out["ACCUMULATION_REGIME"] = accum
    out["DISTRIBUTION_REGIME"] = distrib
    out["TEST"] = test
    out["NO_EFFORT"] = no_effort
    out["ABSORPTION"] = absorption
    out["SHOCK"] = shock
    out["NR7_HIGH_VOL"] = nr7_high_vol
    out["FALSE_BREAK"] = false_break
    # primary signal label (priority if several fire)
    priority = [
        "FALSE_BREAK",
        "ABSORPTION",
        "SHOCK",
        "TEST",
        "NR7_HIGH_VOL",
        "ACCUMULATION_REGIME",
        "DISTRIBUTION_REGIME",
        "NO_EFFORT",
    ]
    primary = np.full(n, "NONE", dtype=object)
    for name in reversed(priority):
        primary = np.where(out[name].to_numpy(), name, primary)
    out["primary_pattern"] = primary
    sig_map = cfg.get("signal_map") or {}
    out["signal"] = [sig_map.get(str(p), "NONE") for p in primary]
    # stop reference: extreme of signal bar (high for sellish, low for buyish — both stored)
    out["stop_extreme_high"] = out["high"]
    out["stop_extreme_low"] = out["low"]
    return out


def pattern_event_table(flags: pd.DataFrame) -> pd.DataFrame:
    """Long-form events: one row per (timestamp, pattern)."""
    rows: list[dict] = []
    sig_by_ts = dict(zip(flags["timestamp"], flags["signal"]))
    primary_by_ts = dict(zip(flags["timestamp"], flags["primary_pattern"]))
    for pid in PATTERN_IDS:
        if pid not in flags.columns:
            continue
        sub = flags.loc[
            flags[pid],
            ["timestamp", "high", "low", "close", "relative_volume"],
        ]
        for r in sub.itertuples(index=False):
            rows.append(
                {
                    "timestamp": r.timestamp,
                    "pattern": pid,
                    "is_primary": primary_by_ts.get(r.timestamp) == pid,
                    "signal": sig_by_ts.get(r.timestamp) if primary_by_ts.get(r.timestamp) == pid else "",
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "relative_volume": float(r.relative_volume),
                }
            )
    return pd.DataFrame(rows)


def compute_forward_outcomes(
    flags: pd.DataFrame,
    *,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    """Per-bar forward displacement / volume regime after primary pattern (non-NONE)."""
    horizons = horizons or [1, 2, 4, 8]
    df = flags.reset_index(drop=True)
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr = df["atr"].to_numpy()
    rv = df["relative_volume"].to_numpy()
    n = len(df)
    rows = []
    for i in range(n):
        if str(df.at[i, "primary_pattern"]) == "NONE":
            continue
        base = {
            "timestamp": df.at[i, "timestamp"],
            "pattern": df.at[i, "primary_pattern"],
            "signal": df.at[i, "signal"],
            "close": float(close[i]),
            "atr": float(atr[i]) if np.isfinite(atr[i]) else None,
        }
        for h in horizons:
            j = i + h
            if j >= n:
                base[f"ret_{h}"] = None
                base[f"disp_atr_{h}"] = None
                base[f"mfe_atr_{h}"] = None
                base[f"mae_atr_{h}"] = None
                base[f"mean_rv_{h}"] = None
                continue
            ret = (close[j] - close[i]) / close[i]
            a = atr[i] if atr[i] and np.isfinite(atr[i]) else np.nan
            disp = (close[j] - close[i]) / a if a and a > 0 else np.nan
            path_hi = float(np.nanmax(high[i + 1 : j + 1]))
            path_lo = float(np.nanmin(low[i + 1 : j + 1]))
            mfe = (path_hi - close[i]) / a if a and a > 0 else np.nan
            mae = (close[i] - path_lo) / a if a and a > 0 else np.nan
            base[f"ret_{h}"] = float(ret)
            base[f"disp_atr_{h}"] = float(disp) if np.isfinite(disp) else None
            base[f"mfe_atr_{h}"] = float(mfe) if np.isfinite(mfe) else None
            base[f"mae_atr_{h}"] = float(mae) if np.isfinite(mae) else None
            base[f"mean_rv_{h}"] = float(np.nanmean(rv[i + 1 : j + 1]))
        rows.append(base)
    return pd.DataFrame(rows)


def summarize_outcomes(outcomes: pd.DataFrame, horizons: list[int] | None = None) -> dict[str, Any]:
    horizons = horizons or [1, 2, 4, 8]
    out: dict[str, Any] = {}
    if outcomes.empty:
        return out
    for pattern, g in outcomes.groupby("pattern"):
        block: dict[str, Any] = {"n": int(len(g)), "signal": str(g["signal"].iloc[0])}
        for h in horizons:
            col = f"disp_atr_{h}"
            if col not in g.columns:
                continue
            s = pd.to_numeric(g[col], errors="coerce").dropna()
            rv = pd.to_numeric(g[f"mean_rv_{h}"], errors="coerce").dropna()
            if s.empty:
                continue
            cont_up = float((s > 0.25).mean())
            cont_dn = float((s < -0.25).mean())
            chop = float(((s >= -0.25) & (s <= 0.25)).mean())
            block[f"h{h}"] = {
                "median_disp_atr": round(float(s.median()), 4),
                "p20_disp_atr": round(float(s.quantile(0.2)), 4),
                "p80_disp_atr": round(float(s.quantile(0.8)), 4),
                "pct_up": round(cont_up, 4),
                "pct_down": round(cont_dn, 4),
                "pct_chop": round(chop, 4),
                "median_follow_rv": round(float(rv.median()), 4) if len(rv) else None,
            }
        out[str(pattern)] = block
    return out


def combo_counts(flags: pd.DataFrame) -> dict[str, int]:
    """Co-occurrence of pattern pairs on same bar."""
    counts: dict[str, int] = {}
    mats = {p: flags[p].to_numpy() for p in PATTERN_IDS if p in flags.columns}
    keys = list(mats.keys())
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            n = int(np.sum(mats[a] & mats[b]))
            if n:
                counts[f"{a}+{b}"] = n
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
