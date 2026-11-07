"""Step 6: zombie active context. Not a trainer. Not an entry fix.

The object is the context, not the fill. A LONG that is still active after
price has already gone through the 100bps stop, while the next context is
already SHORT, is a misread. Split it:

- RAW_STALE: at the stop bar, raw_market_context is still the old direction.
  Cognition still believes the dead thesis.
- LIFECYCLE_LAG: at the stop bar, raw is already opposite or OBSERVE, but
  active_market_context has not released yet (neutralization / opposite confirm).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from build_market_context_lifecycle_memory import (  # noqa: E402
    BUILDER_VERSION,
    attach_context_origin_fields,
    step_lifecycle,
)

from btc_ml.research.logic1_loser_origin import utc_ns

DIRECTIONAL = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
OPPOSITE = {"LONG_CONTEXT": "SHORT_CONTEXT", "SHORT_CONTEXT": "LONG_CONTEXT"}
STOP_BPS = 100.0
IMMEDIATE_BARS = 1
MIN_N_TO_KEEP_DIGGING = 80
TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}

RAW_STALE = "RAW_STALE"
LIFECYCLE_LAG = "LIFECYCLE_LAG"
NOT_THIS = "NOT_THIS"

AUCTION_AGAINST = {
    "LONG_CONTEXT": frozenset({"UPPER_DISTRIBUTION", "ACCEPTANCE_LOWER"}),
    "SHORT_CONTEXT": frozenset({"LOWER_ABSORPTION", "ACCEPTANCE_HIGHER"}),
}
COGNITIVE_AGAINST = {
    "LONG_CONTEXT": frozenset({"UPPER_DISTRIBUTION", "ACCEPTANCE_LOWER", "SELLER_CONTROL"}),
    "SHORT_CONTEXT": frozenset({"LOWER_ABSORPTION", "ACCEPTANCE_HIGHER", "BUYER_CONTROL"}),
}
DIRECTION_AGAINST = {
    "LONG_CONTEXT": frozenset({"SELLER_CONTROL", "SELLER_PRESSURE"}),
    "SHORT_CONTEXT": frozenset({"BUYER_CONTROL", "BUYER_SUPPORT"}),
}

DEFAULT_LIFECYCLE = (
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders")
    / "etll_hybrid_tick"
    / "context"
    / "market_context_lifecycle_memory.parquet"
)


def _clean(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def load_tf_ohlc(pack_root: Path, timeframe: str) -> pd.DataFrame:
    tf = str(timeframe).upper()
    path = Path(pack_root) / f"market_pack_btc_{tf.lower()}" / f"bars_{tf.lower()}.parquet"
    bars = pd.read_parquet(path)
    ts_col = "bar_close" if "bar_close" in bars.columns else "timestamp"
    out = pd.DataFrame(
        {
            "_k": utc_ns(bars[ts_col]),
            "high": pd.to_numeric(bars["high"], errors="coerce"),
            "low": pd.to_numeric(bars["low"], errors="coerce"),
            "close": pd.to_numeric(bars["close"], errors="coerce"),
        }
    )
    return out.dropna(subset=["_k", "high", "low"]).sort_values("_k").drop_duplicates("_k", keep="last")


def load_tf_volume(pack_root: Path, timeframe: str) -> pd.DataFrame:
    tf = str(timeframe).upper()
    path = Path(pack_root) / f"market_pack_btc_{tf.lower()}" / "context" / "volume_response_state.parquet"
    vol = pd.read_parquet(path)
    keep = [
        "timestamp",
        "volume_event",
        "continuation_quality",
        "effort_result_state",
        "localized_behavior",
        "climax_state",
    ]
    have = [c for c in keep if c in vol.columns]
    out = vol[have].copy()
    out["_open"] = utc_ns(out["timestamp"])
    return out.drop(columns=["timestamp"]).dropna(subset=["_open"]).sort_values("_open")


def attach_stop_volume(episodes: pd.DataFrame, pack_root: Path) -> pd.DataFrame:
    """Volume row is stamped on bar OPEN; lifecycle stop_time is bar CLOSE."""
    if episodes is None or len(episodes) == 0:
        return episodes
    parts: list[pd.DataFrame] = []
    for tf, group in episodes.groupby("timeframe", sort=False):
        tf_u = str(tf).upper()
        minutes = float(TF_MINUTES.get(tf_u, 15))
        vol = load_tf_volume(pack_root, tf_u)
        left = group.copy()
        left["_open"] = utc_ns(left["stop_time"]) - pd.Timedelta(minutes=minutes)
        right = vol.rename(columns={c: f"stop_{c}" for c in vol.columns if c != "_open"})
        clash = [c for c in right.columns if c in left.columns and c != "_open"]
        right = right.drop(columns=clash, errors="ignore")
        ok = left["_open"].notna()
        if not ok.any():
            parts.append(left.drop(columns=["_open"], errors="ignore"))
            continue
        merged_ok = pd.merge_asof(
            left.loc[ok].sort_values("_open"),
            right.sort_values("_open"),
            on="_open",
            direction="backward",
            allow_exact_matches=True,
            tolerance=pd.Timedelta(minutes=minutes),
        )
        rest = left.loc[~ok].drop(columns=["_open"], errors="ignore")
        parts.append(pd.concat([merged_ok.drop(columns=["_open"], errors="ignore"), rest], ignore_index=True))
    out = pd.concat(parts, ignore_index=True)
    cq = out.get("stop_continuation_quality", pd.Series("", index=out.index)).astype(str)
    ve = out.get("stop_volume_event", pd.Series("", index=out.index)).astype(str)
    out["stop_passive_or_absorption"] = cq.eq("PASSIVE_DEFENSE") | ve.eq("ABSORPTION_VOLUME")
    out["stop_exhaustion"] = ve.eq("EXHAUSTION_VOLUME")
    out["stop_stopping"] = ve.eq("STOPPING_VOLUME")
    return out


def _counts(series: pd.Series, n: int) -> dict[str, Any]:
    vc = series.fillna("").astype(str).replace({"": "MISSING", "nan": "MISSING"}).value_counts()
    return {str(k): {"n": int(v), "frac": round(int(v) / n, 4) if n else None} for k, v in vc.items()}


def _frac(mask: pd.Series) -> float | None:
    if mask is None or len(mask) == 0:
        return None
    return round(float(mask.mean()), 4)


def summarize_stop_bar(frame: pd.DataFrame) -> dict[str, Any]:
    """RAW_STALE stop bar vs through-stop that did not immediately flip."""
    stale = frame.loc[frame["layer"].astype(str).eq(RAW_STALE)].copy()
    control = frame.loc[frame["through_stop"].astype(bool) & ~frame["user_pattern"].astype(bool)].copy()
    slices = {"raw_stale": stale, "stop_no_immediate_opposite": control}

    def one(sub: pd.DataFrame) -> dict[str, Any]:
        n = int(len(sub))
        if n == 0:
            return {"n": 0}
        def col(name: str, default=False) -> pd.Series:
            if name in sub.columns:
                return sub[name]
            return pd.Series([default] * n, index=sub.index)

        out: dict[str, Any] = {
            "n": n,
            "close_through_stop_frac": _frac(col("close_through_stop").astype(bool)),
            "wick_only_stop_frac": _frac(col("wick_only_stop").astype(bool)),
            "auction_against_frac": _frac(col("auction_against").astype(bool)),
            "cognitive_against_frac": _frac(col("cognitive_against").astype(bool)),
            "direction_against_frac": _frac(col("direction_against").astype(bool)),
            "cognitive_neutral_frac": _frac(col("cognitive_neutral").astype(bool)),
            "status": _counts(col("stop_bar_status", ""), n),
            "auction": _counts(col("stop_bar_auction", ""), n),
            "cognitive": _counts(col("stop_bar_cognitive", ""), n),
            "state_direction": _counts(col("stop_bar_direction", ""), n),
        }
        if "stop_volume_event" in sub.columns:
            out["volume_event"] = _counts(sub["stop_volume_event"], n)
            out["continuation_quality"] = _counts(sub["stop_continuation_quality"], n)
            out["passive_or_absorption_frac"] = _frac(sub["stop_passive_or_absorption"].astype(bool))
            out["exhaustion_frac"] = _frac(sub["stop_exhaustion"].astype(bool))
            out["stopping_frac"] = _frac(sub["stop_stopping"].astype(bool))
        close_and_same = (
            col("close_through_stop").astype(bool)
            & ~col("auction_against").astype(bool)
            & ~col("cognitive_against").astype(bool)
        )
        out["close_dead_auction_still_with_thesis_frac"] = _frac(close_and_same)
        out["n_close_dead_auction_still_with_thesis"] = int(close_and_same.sum())
        return out

    stale_rep = one(stale)
    ctrl_rep = one(control)
    n_stale = int(stale_rep.get("n") or 0)
    wick_dom = bool(n_stale and (stale_rep.get("wick_only_stop_frac") or 0) >= 0.6)
    close_blind = int(stale_rep.get("n_close_dead_auction_still_with_thesis") or 0)
    if wick_dom:
        decision = (
            "Most RAW_STALE stops are wick-only: cognition still reads close as the old thesis "
            "while the 100bps SL is a wick. Do not train. Do not change entries."
        )
    elif close_blind >= MIN_N_TO_KEEP_DIGGING:
        decision = (
            "Close already through 100bps and auction/cognitive still with the old thesis. "
            "This is a raw cognition miss. Keep digging there. Do not train Optuna."
        )
    else:
        decision = (
            "RAW_STALE is real but the stop-bar auction/volume split is not a live gate. "
            "Do not train. Holdout stays sealed."
        )
    return {
        "raw_stale": stale_rep,
        "stop_no_immediate_opposite": ctrl_rep,
        "decision": decision,
        "not_a_trainer": True,
        "holdout": "SEALED",
    }


def replay_v3(memory: pd.DataFrame) -> pd.DataFrame:
    """Rebuild active context with live v3 rules from frozen raw_* columns."""
    if memory is None or len(memory) == 0:
        return pd.DataFrame()
    pieces: list[pd.DataFrame] = []
    for tf, part in memory.groupby("timeframe", sort=False):
        pieces.append(_replay_one_tf(part, str(tf).upper()))
    out = pd.concat(pieces, ignore_index=True)
    out["builder_version_replay"] = BUILDER_VERSION
    return out


def _replay_one_tf(part: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    work = part.sort_values("timestamp").reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for src in work.itertuples(index=False):
        ts = pd.Timestamp(src.timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        step = step_lifecycle(
            raw_market_context=_clean(getattr(src, "raw_market_context", None), "OBSERVE"),
            raw_context_status=_clean(getattr(src, "raw_context_status", None), "UNKNOWN"),
            raw_context_reason=_clean(getattr(src, "raw_context_reason", None), "UNKNOWN"),
            raw_cognitive_market_state=_clean(getattr(src, "raw_cognitive_market_state", None), "UNKNOWN"),
            raw_state_direction=_clean(getattr(src, "raw_state_direction", None), "UNKNOWN"),
            auction_episode=_clean(getattr(src, "raw_auction_episode", None), "UNKNOWN"),
            timestamp=ts,
            prev=prev,
        )
        row = {
            "timestamp": ts,
            "close": getattr(src, "close", None),
            "raw_market_context": _clean(getattr(src, "raw_market_context", None), "OBSERVE"),
            "raw_context_status": _clean(getattr(src, "raw_context_status", None), "UNKNOWN"),
            "raw_cognitive_market_state": _clean(getattr(src, "raw_cognitive_market_state", None), "UNKNOWN"),
            "raw_state_direction": _clean(getattr(src, "raw_state_direction", None), "UNKNOWN"),
            "raw_context_reason": _clean(getattr(src, "raw_context_reason", None), "UNKNOWN"),
            "raw_auction_episode": _clean(getattr(src, "raw_auction_episode", None), "UNKNOWN"),
            "timeframe": timeframe,
            "_timeframe": timeframe,
            **step,
        }
        rows.append(row)
        prev = row
    frame = pd.DataFrame(rows)
    return attach_context_origin_fields(frame)


def close_adverse_bps(direction: str, origin: float, close: float) -> float:
    if not np.isfinite(origin) or origin == 0 or not np.isfinite(close):
        return float("nan")
    if direction == "LONG_CONTEXT":
        return float((origin - close) / origin * 1e4)
    if direction == "SHORT_CONTEXT":
        return float((close - origin) / origin * 1e4)
    return float("nan")


def wick_adverse_bps(direction: str, origin: float, high: float, low: float) -> float:
    if not np.isfinite(origin) or origin == 0 or not np.isfinite(high) or not np.isfinite(low):
        return float("nan")
    if direction == "LONG_CONTEXT":
        return float((origin - low) / origin * 1e4)
    if direction == "SHORT_CONTEXT":
        return float((high - origin) / origin * 1e4)
    return float("nan")


def classify_episode(
    bars: pd.DataFrame,
    *,
    next_direction: str | None,
    next_gap_bars: int | None,
    stop_bps: float = STOP_BPS,
    immediate_bars: int = IMMEDIATE_BARS,
) -> dict[str, Any]:
    """One directional episode. `bars` must already be that episode only."""
    empty = {
        "user_pattern": False,
        "layer": NOT_THIS,
        "through_stop": False,
        "through_origin": False,
        "immediate_opposite": False,
        "bars_after_stop": None,
        "stop_bar_raw": None,
        "stop_bar_lifecycle": None,
        "stop_bar_status": None,
        "stop_bar_cognitive": None,
        "stop_bar_direction": None,
        "stop_bar_auction": None,
        "stop_time": None,
        "stop_wick_adverse_bps": None,
        "stop_close_adverse_bps": None,
        "close_through_stop": False,
        "wick_only_stop": False,
        "auction_against": False,
        "cognitive_against": False,
        "direction_against": False,
        "cognitive_neutral": False,
        "n_bars": int(len(bars)),
        "next_direction": next_direction,
        "next_gap_bars": next_gap_bars,
    }
    if bars is None or len(bars) == 0:
        return empty
    direction = _clean(bars.iloc[0].get("active_market_context"))
    if direction not in DIRECTIONAL:
        return empty
    origin = float(bars.iloc[0].get("context_origin_price") or bars.iloc[0].get("close") or np.nan)
    opposite = OPPOSITE[direction]
    stop_i: int | None = None
    origin_i: int | None = None
    for i, row in enumerate(bars.itertuples(index=False)):
        high = float(getattr(row, "high", np.nan))
        low = float(getattr(row, "low", np.nan))
        close = float(getattr(row, "close", np.nan))
        if not np.isfinite(high):
            high = close
        if not np.isfinite(low):
            low = close
        adv = wick_adverse_bps(direction, origin, high, low)
        if origin_i is None and np.isfinite(adv) and adv >= 0 and i > 0:
            # through origin: LONG low<=origin, SHORT high>=origin
            if direction == "LONG_CONTEXT" and low <= origin:
                origin_i = i
            elif direction == "SHORT_CONTEXT" and high >= origin:
                origin_i = i
        if stop_i is None and np.isfinite(adv) and adv >= stop_bps:
            stop_i = i
    through_stop = stop_i is not None
    immediate = bool(
        next_direction == opposite and next_gap_bars is not None and int(next_gap_bars) <= immediate_bars
    )
    user_pattern = bool(through_stop and immediate)
    layer = NOT_THIS
    stop_raw = None
    stop_life = None
    stop_status = None
    stop_cog = None
    stop_dir = None
    stop_auc = None
    stop_time = None
    wick_adv = None
    close_adv = None
    close_hit = False
    wick_only = False
    auc_against = False
    cog_against = False
    dir_against = False
    cog_neutral = False
    bars_after = None
    if through_stop:
        stop_row = bars.iloc[int(stop_i)]
        stop_raw = _clean(stop_row.get("raw_market_context"))
        stop_life = _clean(stop_row.get("lifecycle_state"))
        stop_status = _clean(stop_row.get("raw_context_status"))
        stop_cog = _clean(stop_row.get("raw_cognitive_market_state"))
        stop_dir = _clean(stop_row.get("raw_state_direction"))
        stop_auc = _clean(stop_row.get("raw_auction_episode"))
        stop_time = stop_row.get("timestamp")
        high = float(stop_row.get("high") if pd.notna(stop_row.get("high")) else stop_row.get("close") or np.nan)
        low = float(stop_row.get("low") if pd.notna(stop_row.get("low")) else stop_row.get("close") or np.nan)
        close = float(stop_row.get("close") or np.nan)
        wick_adv = wick_adverse_bps(direction, origin, high, low)
        close_adv = close_adverse_bps(direction, origin, close)
        close_hit = bool(np.isfinite(close_adv) and close_adv >= stop_bps)
        wick_only = bool(through_stop and not close_hit)
        auc_against = stop_auc in AUCTION_AGAINST[direction]
        cog_against = stop_cog in COGNITIVE_AGAINST[direction]
        dir_against = stop_dir in DIRECTION_AGAINST[direction]
        cog_neutral = stop_cog in {"BALANCE", "UNCERTAIN"} or stop_dir == "NEUTRAL"
        bars_after = int(len(bars) - 1 - int(stop_i))
        if user_pattern:
            if stop_raw == direction:
                layer = RAW_STALE
            elif stop_raw in {opposite, "OBSERVE"}:
                layer = LIFECYCLE_LAG
            else:
                layer = LIFECYCLE_LAG
    return {
        "user_pattern": user_pattern,
        "layer": layer,
        "through_stop": through_stop,
        "through_origin": origin_i is not None,
        "immediate_opposite": immediate,
        "bars_after_stop": bars_after,
        "stop_bar_raw": stop_raw,
        "stop_bar_lifecycle": stop_life,
        "stop_bar_status": stop_status,
        "stop_bar_cognitive": stop_cog,
        "stop_bar_direction": stop_dir,
        "stop_bar_auction": stop_auc,
        "stop_time": stop_time,
        "stop_wick_adverse_bps": wick_adv,
        "stop_close_adverse_bps": close_adv,
        "close_through_stop": close_hit,
        "wick_only_stop": wick_only,
        "auction_against": auc_against,
        "cognitive_against": cog_against,
        "direction_against": dir_against,
        "cognitive_neutral": cog_neutral,
        "n_bars": int(len(bars)),
        "next_direction": next_direction,
        "next_gap_bars": next_gap_bars,
        "direction": direction,
        "stop_bar_index": stop_i,
    }


def episode_table(memory: pd.DataFrame, ohlc_by_tf: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """One row per directional v3 episode, with next-context gap."""
    if memory is None or len(memory) == 0:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for tf, part in memory.groupby("timeframe", sort=False):
        tf_u = str(tf).upper()
        work = part.sort_values("timestamp").reset_index(drop=True)
        work["timestamp"] = utc_ns(work["timestamp"])
        if ohlc_by_tf and tf_u in ohlc_by_tf:
            ohlc = ohlc_by_tf[tf_u]
            work = work.copy()
            work["_k"] = work["timestamp"]
            work = work.merge(ohlc, on="_k", how="left", suffixes=("", "_ohlc"))
            if "high" not in work.columns:
                work["high"] = np.nan
            if "low" not in work.columns:
                work["low"] = np.nan
        else:
            work = work.copy()
            work["high"] = np.nan
            work["low"] = np.nan
        changed = work["active_market_context"].astype(str) != work["active_market_context"].astype(str).shift(1)
        if len(changed):
            changed.iloc[0] = True
        work["_ep"] = changed.cumsum()
        groups = list(work.groupby("_ep", sort=True))
        directional = []
        for _, g in groups:
            active = _clean(g.iloc[0].get("active_market_context"))
            if active in DIRECTIONAL:
                directional.append(g)
        for i, g in enumerate(directional):
            nxt = directional[i + 1] if i + 1 < len(directional) else None
            next_dir = _clean(nxt.iloc[0].get("active_market_context")) if nxt is not None else None
            if nxt is None:
                gap = None
            else:
                # bars in this TF between this episode's last row and next start,
                # inclusive of the next start bar as gap=0 if adjacent.
                last_ts = g["timestamp"].iloc[-1]
                next_ts = nxt["timestamp"].iloc[0]
                between = work.loc[(work["timestamp"] > last_ts) & (work["timestamp"] < next_ts)]
                gap = int(len(between))
            labeled = classify_episode(g, next_direction=next_dir, next_gap_bars=gap)
            labeled.update(
                {
                    "timeframe": tf_u,
                    "episode_id": int(g.iloc[0].get("context_episode_id") or i + 1),
                    "start_time": g["timestamp"].iloc[0],
                    "end_time": g["timestamp"].iloc[-1],
                    "origin_price": g.iloc[0].get("context_origin_price"),
                }
            )
            rows.append(labeled)
    return pd.DataFrame(rows)


def summarize_train(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or len(frame) == 0:
        return {"n_episodes": 0, "enough_to_keep_digging": False}
    n = int(len(frame))
    pattern = frame["user_pattern"].astype(bool)
    n_pattern = int(pattern.sum())
    stale = frame.loc[pattern & (frame["layer"] == RAW_STALE)]
    lag = frame.loc[pattern & (frame["layer"] == LIFECYCLE_LAG)]
    by_tf = (
        frame.loc[pattern]
        .groupby("timeframe")
        .agg(n=("user_pattern", "size"), raw_stale=("layer", lambda s: int((s == RAW_STALE).sum())), lifecycle_lag=("layer", lambda s: int((s == LIFECYCLE_LAG).sum())))
        .reset_index()
        .to_dict(orient="records")
        if n_pattern
        else []
    )
    after = pd.to_numeric(frame.loc[pattern, "bars_after_stop"], errors="coerce")
    return {
        "n_episodes": n,
        "n_through_stop": int(frame["through_stop"].astype(bool).sum()),
        "n_user_pattern": n_pattern,
        "user_pattern_frac": round(n_pattern / n, 4) if n else 0.0,
        "raw_stale": int(len(stale)),
        "lifecycle_lag": int(len(lag)),
        "enough_to_keep_digging": bool(n_pattern >= MIN_N_TO_KEEP_DIGGING),
        "median_bars_after_stop_on_pattern": (None if after.empty else float(np.nanmedian(after))),
        "by_timeframe": by_tf,
        "decision": (
            "Keep digging on context quality. Do not change entries. "
            "Do not train Optuna. Holdout stays sealed."
        ),
        "builder_version": BUILDER_VERSION,
        "not_a_trainer": True,
        "stop_bar": summarize_stop_bar(frame),
    }
