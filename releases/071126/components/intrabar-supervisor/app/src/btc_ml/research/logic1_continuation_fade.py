"""Step 5: continuation fade among near-origin OPENs that did pay.

Not a trainer. These losers are not a misread of ACTIVE at OPEN.
The impulse existed (MFE from origin ≥ 50bps), then died.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.logic1_loser_origin import (
    CHASE_NONE,
    FOLLOWED_MFE_BPS,
    PATH_FOLLOWED,
    _utc_i8,
    utc_ns,
)


def fade_timing(
    bars: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    origin: float,
    sign: float,
    *,
    ts_i8: np.ndarray | None = None,
) -> dict[str, float]:
    empty = {
        "mfe_bps": np.nan,
        "mae_bps": np.nan,
        "bars_to_mfe": np.nan,
        "bars_to_back_through_origin": np.nan,
        "gave_back_after_mfe": np.nan,
        "n_bars": 0.0,
        "peak_bar_close": pd.NaT,
        "giveback_bar_close": pd.NaT,
    }
    if not np.isfinite(origin) or origin == 0 or sign not in (1.0, -1.0):
        return empty
    if pd.isna(start_ts) or pd.isna(end_ts):
        return empty
    if ts_i8 is None:
        ts_i8 = utc_ns(bars["bar_close"]).astype("int64").to_numpy()
    i0 = int(np.searchsorted(ts_i8, _utc_i8(start_ts), side="right"))
    i1 = int(np.searchsorted(ts_i8, _utc_i8(end_ts), side="right"))
    if i1 <= i0:
        return empty
    high = bars["high"].to_numpy()[i0:i1]
    low = bars["low"].to_numpy()[i0:i1]
    close = bars["close"].to_numpy()[i0:i1]
    if sign > 0:
        fav = (high / origin - 1.0) * 1e4
        adv = (low / origin - 1.0) * 1e4
        signed_close = (close / origin - 1.0) * 1e4
    else:
        fav = (1.0 - low / origin) * 1e4
        adv = (1.0 - high / origin) * 1e4
        signed_close = (1.0 - close / origin) * 1e4
    running_mfe = np.maximum.accumulate(fav)
    mfe = float(running_mfe[-1])
    mae = float(np.nanmin(adv))
    peak_i = int(np.nanargmax(fav))
    back = np.where(signed_close[peak_i:] <= 0)[0]
    bars_back = float(peak_i + int(back[0])) if len(back) else np.nan
    peak_ts = bars["bar_close"].iloc[i0 + peak_i]
    giveback_ts = bars["bar_close"].iloc[i0 + int(bars_back)] if np.isfinite(bars_back) else pd.NaT
    return {
        "mfe_bps": mfe,
        "mae_bps": mae,
        "bars_to_mfe": float(peak_i + 1),
        "bars_to_back_through_origin": bars_back,
        "gave_back_after_mfe": float(mfe >= FOLLOWED_MFE_BPS and np.isfinite(bars_back)),
        "n_bars": float(i1 - i0),
        "peak_bar_close": peak_ts,
        "giveback_bar_close": giveback_ts,
    }


def attach_fade_timing(events: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    origin = pd.to_numeric(out["context_origin_price"], errors="coerce").to_numpy()
    sign = np.where(out["side"].astype(str).str.upper().eq("LONG"), 1.0, -1.0)
    started = utc_ns(out["context_started_at"])
    exit_ts = utc_ns(out["exit_ts"] if "exit_ts" in out.columns else out.get("source_bar_close"))
    ts_i8 = utc_ns(m15["bar_close"]).astype("int64").to_numpy()
    rows = [fade_timing(m15, started.iloc[i], exit_ts.iloc[i], float(origin[i]), float(sign[i]), ts_i8=ts_i8) for i in range(len(out))]
    timed = pd.DataFrame(rows)
    for col in timed.columns:
        out[col] = timed[col].to_numpy()
    return out


def summarize_continuation_fade(frame: pd.DataFrame) -> dict[str, Any]:
    no_chase = frame["chase_axis"].astype(str).eq(CHASE_NONE)
    c_loss = no_chase & frame["loser"].astype(bool) & frame["path_axis"].astype(str).eq(PATH_FOLLOWED)
    c_win = no_chase & (pd.to_numeric(frame["R"], errors="coerce") > 0) & (
        pd.to_numeric(frame["mfe_from_origin_bps"], errors="coerce") >= FOLLOWED_MFE_BPS
    )
    losers = frame.loc[c_loss]
    winners = frame.loc[c_win]

    def _med(series: pd.Series) -> float | None:
        s = pd.to_numeric(series, errors="coerce")
        return round(float(s.median()), 4) if s.notna().any() else None

    def _mean(series: pd.Series) -> float | None:
        s = pd.to_numeric(series, errors="coerce")
        return round(float(s.mean()), 4) if s.notna().any() else None

    return {
        "segment": "train",
        "holdout": "sealed",
        "universe": "NO_CHASE trades whose origin path followed (≥50bps MFE)",
        "n_c_losers": int(c_loss.sum()),
        "n_c_winners": int(c_win.sum()),
        "loser_exit": {str(k): int(v) for k, v in losers["exit_reason"].value_counts().items()} if len(losers) else {},
        "loser_by_tf": {str(k): int(v) for k, v in losers["timeframe"].value_counts().items()} if len(losers) else {},
        "timing_losers": {
            "median_mfe_bps": _med(losers.get("mfe_bps", losers.get("mfe_from_origin_bps"))),
            "median_mae_bps": _med(losers.get("mae_bps", losers.get("mae_from_origin_bps"))),
            "median_bars_to_mfe": _med(losers["bars_to_mfe"]) if "bars_to_mfe" in losers.columns else None,
            "median_bars_to_back_through_origin": _med(losers["bars_to_back_through_origin"])
            if "bars_to_back_through_origin" in losers.columns
            else None,
            "frac_gave_back_after_mfe": _mean(losers["gave_back_after_mfe"]) if "gave_back_after_mfe" in losers.columns else None,
            "frac_first_m15_against": round(
                float((pd.to_numeric(losers["first_m15_from_origin_bps"], errors="coerce") < 0).mean()), 4
            )
            if "first_m15_from_origin_bps" in losers.columns and len(losers)
            else None,
        },
        "timing_winners": {
            "median_mfe_bps": _med(winners.get("mfe_bps", winners.get("mfe_from_origin_bps"))),
            "median_mae_bps": _med(winners.get("mae_bps", winners.get("mae_from_origin_bps"))),
            "median_bars_to_mfe": _med(winners["bars_to_mfe"]) if "bars_to_mfe" in winners.columns else None,
            "frac_first_m15_against": round(
                float((pd.to_numeric(winners["first_m15_from_origin_bps"], errors="coerce") < 0).mean()), 4
            )
            if "first_m15_from_origin_bps" in winners.columns and len(winners)
            else None,
        },
        "reading": {
            "not_an_open_misread": (
                "ACTIVE paid from origin. The error is continuation, not the birth label."
            ),
            "do_not_mix_with_B": "Dead-birth (B) is 20 first-open never-followed trades. Do not share a gate.",
            "do_not_wait_one_bar_to_enter": "First M15 against is a path fact, not an OPEN filter.",
        },
    }
