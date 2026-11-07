"""Step-1 loser autopsy: lag of the book vs a dead or fading thesis.

Not a trainer. Does not score allow/block on total R, does not read CatBoost,
does not open the holdout.

Two axes, not one:

- chase: was the book fill already far from context origin? If the same
  distance is gone at context_started_at, that chase is book lag, not a
  misread at birth.
- path from origin: after the origin bar, did price ever pay the thesis
  (MFE on M15, strictly later bars only)?
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CHASE_BPS = 50.0
NEVER_FOLLOWED_MFE_BPS = 25.0
FOLLOWED_MFE_BPS = 50.0

CHASE_LAG = "A_LAG"
CHASE_EVENT = "A_EVENT"
CHASE_NONE = "NO_CHASE"
PATH_NEVER = "B_NEVER"
PATH_WEAK = "WEAK"
PATH_FOLLOWED = "C_FOLLOWED"
PATH_NO_PATH = "NO_PATH"
ENTRY_BIRTH = "FIRST_BIRTH"
ENTRY_LATE = "FIRST_LATE"
ENTRY_REENTRY = "REENTRY"


def utc_ns(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def _utc_i8(ts: Any) -> int:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return int(t.value)


def signed_bps(price: np.ndarray | pd.Series | float, origin: np.ndarray | pd.Series | float, sign: np.ndarray | pd.Series | int) -> np.ndarray:
    price_f = np.asarray(price, dtype=float)
    origin_f = np.asarray(origin, dtype=float)
    sign_f = np.asarray(sign, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (price_f / origin_f - 1.0) * 1e4 * sign_f


def side_sign(side: pd.Series) -> np.ndarray:
    return np.where(side.astype(str).str.upper().eq("LONG"), 1.0, -1.0)


def load_m15_bars(pack_root: Path) -> pd.DataFrame:
    path = Path(pack_root) / "market_pack_btc_m15" / "bars_m15.parquet"
    bars = pd.read_parquet(path, columns=["bar_close", "high", "low", "close"])
    bars["bar_close"] = utc_ns(bars["bar_close"])
    bars["high"] = pd.to_numeric(bars["high"], errors="coerce")
    bars["low"] = pd.to_numeric(bars["low"], errors="coerce")
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["bar_close", "high", "low", "close"]).sort_values("bar_close")
    return bars.reset_index(drop=True)


def m15_path_stats(
    bars: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    entry: float,
    sign: float,
    *,
    ts_i8: np.ndarray | None = None,
) -> dict[str, float]:
    """MFE/MAE on M15 bars with bar_close strictly after start_ts, up to end_ts.

    The start bar itself is excluded so H1/H4 range cannot inflate the path.
    """
    empty = {
        "mfe_bps": np.nan,
        "mae_bps": np.nan,
        "first_close_bps": np.nan,
        "n_bars": 0.0,
    }
    if not np.isfinite(entry) or entry == 0 or sign not in (1.0, -1.0):
        return empty
    if pd.isna(start_ts) or pd.isna(end_ts):
        return empty
    if ts_i8 is None:
        ts_i8 = utc_ns(bars["bar_close"]).astype("int64").to_numpy()
    start_i8 = _utc_i8(start_ts)
    end_i8 = _utc_i8(end_ts)
    i0 = int(np.searchsorted(ts_i8, start_i8, side="right"))
    i1 = int(np.searchsorted(ts_i8, end_i8, side="right"))
    if i1 <= i0:
        return empty
    high = bars["high"].to_numpy()[i0:i1]
    low = bars["low"].to_numpy()[i0:i1]
    close = bars["close"].to_numpy()[i0:i1]
    if sign > 0:
        fav = (high / entry - 1.0) * 1e4
        adv = (low / entry - 1.0) * 1e4
        first = (close[0] / entry - 1.0) * 1e4
    else:
        fav = (1.0 - low / entry) * 1e4
        adv = (1.0 - high / entry) * 1e4
        first = (1.0 - close[0] / entry) * 1e4
    return {
        "mfe_bps": float(np.nanmax(fav)),
        "mae_bps": float(np.nanmin(adv)),
        "first_close_bps": float(first),
        "n_bars": float(i1 - i0),
    }


def classify_chase(book_signed_bps: float, event_signed_bps: float, chase_bps: float = CHASE_BPS) -> str:
    event = np.isfinite(event_signed_bps) and event_signed_bps >= chase_bps
    book = np.isfinite(book_signed_bps) and book_signed_bps >= chase_bps
    if event:
        return CHASE_EVENT
    if book:
        return CHASE_LAG
    return CHASE_NONE


def classify_path(mfe_from_origin_bps: float) -> str:
    if not np.isfinite(mfe_from_origin_bps):
        return PATH_NO_PATH
    if mfe_from_origin_bps < NEVER_FOLLOWED_MFE_BPS:
        return PATH_NEVER
    if mfe_from_origin_bps >= FOLLOWED_MFE_BPS:
        return PATH_FOLLOWED
    return PATH_WEAK


def classify_entry_kind(age_bars: float, open_index: int) -> str:
    if int(open_index) > 1:
        return ENTRY_REENTRY
    if np.isfinite(age_bars) and float(age_bars) > 1.0:
        return ENTRY_LATE
    return ENTRY_BIRTH


def primary_loser_bucket(chase_axis: str, path_axis: str) -> str:
    if chase_axis == CHASE_EVENT:
        return CHASE_EVENT
    if chase_axis == CHASE_LAG:
        return CHASE_LAG
    if path_axis == PATH_NEVER:
        return PATH_NEVER
    if path_axis == PATH_FOLLOWED:
        return PATH_FOLLOWED
    if path_axis == PATH_WEAK:
        return PATH_WEAK
    return PATH_NO_PATH


def attach_origin_audit(events: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    origin = pd.to_numeric(out["context_origin_price"], errors="coerce").to_numpy()
    entry = pd.to_numeric(out["entry_price"], errors="coerce").to_numpy()
    event_px = pd.to_numeric(out.get("context_event_price"), errors="coerce").to_numpy()
    event_px = np.where(np.isfinite(event_px), event_px, origin)
    sign = side_sign(out["side"])
    out["sign"] = sign
    out["signed_fill_origin_bps"] = signed_bps(entry, origin, sign)
    out["signed_event_origin_bps"] = signed_bps(event_px, origin, sign)
    out["chase_fill"] = pd.to_numeric(out["signed_fill_origin_bps"], errors="coerce") >= CHASE_BPS
    out["chase_event"] = pd.to_numeric(out["signed_event_origin_bps"], errors="coerce") >= CHASE_BPS

    started = utc_ns(out["context_started_at"])
    fill_ts = utc_ns(out["source_bar_close_ts"] if "source_bar_close_ts" in out.columns else out["source_bar_close"])
    exit_ts = utc_ns(out["exit_ts"])
    out["lag_minutes"] = (fill_ts - started).dt.total_seconds() / 60.0

    ordered = out.sort_values(["timeframe", "lifecycle_episode_id", "entry_ts"], kind="mergesort")
    open_index = ordered.groupby(["timeframe", "lifecycle_episode_id"], sort=False).cumcount() + 1
    out["episode_open_index"] = open_index.reindex(out.index)

    ts_i8 = utc_ns(m15["bar_close"]).astype("int64").to_numpy()
    fill_mfe: list[float] = []
    fill_mae: list[float] = []
    fill_first: list[float] = []
    origin_mfe: list[float] = []
    origin_mae: list[float] = []
    origin_first: list[float] = []
    origin_n: list[float] = []
    for i in range(len(out)):
        fill_path = m15_path_stats(
            m15, fill_ts.iloc[i], exit_ts.iloc[i], float(entry[i]), float(sign[i]), ts_i8=ts_i8
        )
        origin_path = m15_path_stats(
            m15, started.iloc[i], exit_ts.iloc[i], float(origin[i]), float(sign[i]), ts_i8=ts_i8
        )
        fill_mfe.append(fill_path["mfe_bps"])
        fill_mae.append(fill_path["mae_bps"])
        fill_first.append(fill_path["first_close_bps"])
        origin_mfe.append(origin_path["mfe_bps"])
        origin_mae.append(origin_path["mae_bps"])
        origin_first.append(origin_path["first_close_bps"])
        origin_n.append(origin_path["n_bars"])
    out["mfe_from_fill_bps"] = fill_mfe
    out["mae_from_fill_bps"] = fill_mae
    out["first_m15_from_fill_bps"] = fill_first
    out["mfe_from_origin_bps"] = origin_mfe
    out["mae_from_origin_bps"] = origin_mae
    out["first_m15_from_origin_bps"] = origin_first
    out["origin_path_bars"] = origin_n

    out["chase_axis"] = [
        classify_chase(b, e) for b, e in zip(out["signed_fill_origin_bps"], out["signed_event_origin_bps"])
    ]
    out["path_axis"] = [classify_path(v) for v in out["mfe_from_origin_bps"]]
    out["entry_kind"] = [
        classify_entry_kind(a, n) for a, n in zip(out["age_bars"], out["episode_open_index"])
    ]
    out["loser"] = pd.to_numeric(out["R"], errors="coerce") < 0
    out["primary_loser_bucket"] = [
        primary_loser_bucket(c, p) if lose else "WINNER_OR_FLAT"
        for c, p, lose in zip(out["chase_axis"], out["path_axis"], out["loser"])
    ]
    return out


def _counts(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).items()}


def _frac(mask: pd.Series) -> float | None:
    if len(mask) == 0:
        return None
    return round(float(mask.mean()), 4)


def summarize_train(frame: pd.DataFrame) -> dict[str, Any]:
    n = len(frame)
    losers = frame.loc[frame["loser"]].copy()
    n_lose = int(len(losers))
    a_lag_c = int(((losers["chase_axis"] == CHASE_LAG) & (losers["path_axis"] == PATH_FOLLOWED)).sum())
    a_lag_b = int(((losers["chase_axis"] == CHASE_LAG) & (losers["path_axis"] == PATH_NEVER)).sum())
    no_chase_b = int(((losers["chase_axis"] == CHASE_NONE) & (losers["path_axis"] == PATH_NEVER)).sum())
    no_chase_c = int(((losers["chase_axis"] == CHASE_NONE) & (losers["path_axis"] == PATH_FOLLOWED)).sum())
    fill_path = losers["mfe_from_fill_bps"].map(classify_path)
    a_lag_fill = losers.loc[losers["chase_axis"] == CHASE_LAG, "mfe_from_fill_bps"].map(classify_path)
    no_chase_fill = losers.loc[losers["chase_axis"] == CHASE_NONE, "mfe_from_fill_bps"].map(classify_path)
    return {
        "segment": "train",
        "holdout": "sealed",
        "n": n,
        "losers": n_lose,
        "wr": round(float((pd.to_numeric(frame["R"], errors="coerce") > 0).mean()), 4),
        "thresholds": {
            "chase_bps": CHASE_BPS,
            "never_followed_mfe_bps": NEVER_FOLLOWED_MFE_BPS,
            "followed_mfe_bps": FOLLOWED_MFE_BPS,
            "path": "M15 bars strictly after context_started_at (origin) or source_bar_close (fill)",
        },
        "chase_all": _counts(frame["chase_axis"]),
        "chase_losers": _counts(losers["chase_axis"]),
        "path_from_origin_losers": _counts(losers["path_axis"]),
        "path_after_fill_losers": _counts(fill_path),
        "entry_kind_losers": _counts(losers["entry_kind"]),
        "primary_loser_bucket": _counts(losers["primary_loser_bucket"]),
        "cross_chase_x_path_losers": {
            f"{chase}|{path}": int(((losers["chase_axis"] == chase) & (losers["path_axis"] == path)).sum())
            for chase in (CHASE_LAG, CHASE_EVENT, CHASE_NONE)
            for path in (PATH_NEVER, PATH_WEAK, PATH_FOLLOWED, PATH_NO_PATH)
        },
        "cross_entry_x_chase_losers": {
            f"{kind}|{chase}": int(((losers["entry_kind"] == kind) & (losers["chase_axis"] == chase)).sum())
            for kind in (ENTRY_BIRTH, ENTRY_LATE, ENTRY_REENTRY)
            for chase in (CHASE_LAG, CHASE_EVENT, CHASE_NONE)
        },
        "rates": {
            "p_loss_if_chase_fill": _frac(frame.loc[frame["chase_fill"], "loser"]),
            "p_loss_if_not_chase_fill": _frac(frame.loc[~frame["chase_fill"], "loser"]),
            "p_loss_if_reentry": _frac(frame.loc[frame["entry_kind"].eq(ENTRY_REENTRY), "loser"]),
            "p_loss_if_first_birth": _frac(frame.loc[frame["entry_kind"].eq(ENTRY_BIRTH), "loser"]),
            "p_loss_if_first_late": _frac(frame.loc[frame["entry_kind"].eq(ENTRY_LATE), "loser"]),
            "mean_R_chase_fill": round(float(frame.loc[frame["chase_fill"], "R"].mean()), 4) if frame["chase_fill"].any() else None,
            "mean_R_not_chase_fill": round(float(frame.loc[~frame["chase_fill"], "R"].mean()), 4) if (~frame["chase_fill"]).any() else None,
        },
        "by_timeframe_losers": {
            str(tf): {
                "n": int(len(g)),
                "primary": _counts(g["primary_loser_bucket"]),
                "chase": _counts(g["chase_axis"]),
                "entry_kind": _counts(g["entry_kind"]),
            }
            for tf, g in losers.groupby("timeframe", sort=False)
        },
        "overlap": {
            "A_LAG_and_C_followed_from_origin": a_lag_c,
            "A_LAG_and_B_never_from_origin": a_lag_b,
            "A_LAG_path_after_fill": _counts(a_lag_fill),
            "no_chase_and_B_never": no_chase_b,
            "no_chase_and_C_followed": no_chase_c,
            "no_chase_path_after_fill": _counts(no_chase_fill),
            "origin_C_given_A_LAG_is_tautological": (
                "Chase ≥50bps from origin already is ≥50bps of origin-path MFE. "
                "Use path_after_fill, not origin-path C, for A_LAG trades."
            ),
        },
        "reading": {
            "A_EVENT_empty_means": (
                "context_event_price is the origin close, so chase at the event is ~0 by construction. "
                "H1/H4 'birth' fills that are already 50bps past origin are still A_LAG: "
                "one TF bar after the painted start, not a chase at CONTEXT_START."
            ),
            "A_LAG": (
                "Book fill already ≥50bps past origin. Live journal START/FLIP fills at origin, "
                "and live does not re-enter the same episode after TP/SL."
            ),
            "B_without_chase": "Opened near origin and the thesis never paid. This is the actual misread at birth.",
            "C_without_chase": "Opened near origin, impulse existed, then died. Not an OPEN misread of ACTIVE.",
            "REENTRY": "Same episode, second+ OPEN. Live journal emits START/FLIP once; these book fills would not fire again.",
        },
        "n_note": n_lose,
    }
