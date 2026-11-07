"""LOGIC1 S4.1 OPEN gate: interpretable allow/block policy on the Hybrid tick book.

This is trading logic, not sizing. It never imports CatBoost and never reads
config/trading/hybrid_sizing/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
TF_RANK = {"M15": 0, "M30": 1, "H1": 2, "H4": 3}
HIGHER_TF = {"H1", "H4"}
OPEN_INTENTS = {"OPEN_LONG", "OPEN_SHORT"}
RET_LOOKBACKS = (4, 8, 16, 32)

ALLOW_ALL: dict[str, Any] = {
    "min_age_bars": 0,
    "min_xtf_same": 0,
    "block_higher_tf_opposite": False,
    "block_long_below_origin_bps": 0,
    "block_short_above_origin_bps": 0,
    "ret_lookback_bars": 0,
    "block_adverse_ret_bps": 0,
}

DEFAULT_ARCHIVE = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive/"
    "ETLL_HYBRID_TICK_V1_20260905_092610"
)
DEFAULT_PACK_ROOTS = (
    Path("data/research/external_traders"),
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders"),
)


def utc_iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_xtf(meta: Any) -> dict[str, str]:
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return {}
    if not isinstance(meta, dict):
        return {}
    out: dict[str, str] = {}
    for tf, state in meta.items():
        if isinstance(state, dict):
            out[str(tf).upper()] = str(state.get("direction") or "").upper()
        else:
            out[str(tf).upper()] = str(state or "").upper()
    return out


def xtf_features(meta: Any, own_tf: str, side: str) -> tuple[int, int, bool]:
    """Same-side count (other TFs), opposite count, H1/H4 opposite."""
    dirs = parse_xtf(meta)
    own_tf_u = str(own_tf).upper()
    side_u = str(side).upper()
    same = 0
    opposite = 0
    higher_opposite = False
    for tf, direction in dirs.items():
        if tf == own_tf_u:
            continue
        if direction not in {"LONG", "SHORT"}:
            continue
        if direction == side_u:
            same += 1
        else:
            opposite += 1
            if tf in HIGHER_TF:
                higher_opposite = True
    return same, opposite, higher_opposite


def resolve_pack_root(explicit: Path | None = None, repo_root: Path | None = None) -> Path | None:
    if explicit is not None and (explicit / "market_pack_btc_m15").exists():
        return explicit
    roots: list[Path] = []
    if repo_root is not None:
        roots.append(repo_root / "data/research/external_traders")
    roots.extend(DEFAULT_PACK_ROOTS)
    for root in roots:
        if (root / "market_pack_btc_m15").exists():
            return root
    return None


def load_feed(pack_root: Path, timeframe: str) -> pd.DataFrame:
    tf = str(timeframe).upper()
    path = pack_root / f"market_pack_btc_{tf.lower()}" / f"feed_{tf.lower()}.parquet"
    if not path.exists():
        return pd.DataFrame()
    feed = pd.read_parquet(path, columns=["timestamp", "close"])
    feed["timestamp"] = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
    feed = feed.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
    close = pd.to_numeric(feed["close"], errors="coerce")
    for n in RET_LOOKBACKS:
        feed[f"ret_{n}_bps"] = (close / close.shift(int(n)) - 1.0) * 1e4
    return feed.reset_index(drop=True)


def attach_price_features(events: pd.DataFrame, pack_root: Path | None) -> pd.DataFrame:
    """Bar-close price and lookback returns. Causal: only bars at or before source_bar_open."""
    out = events.copy()
    out["bar_close"] = pd.to_numeric(out.get("entry_price"), errors="coerce")
    for n in RET_LOOKBACKS:
        out[f"ret_{n}_bps"] = np.nan
    if pack_root is None:
        origin = pd.to_numeric(out["context_origin_price"], errors="coerce")
        out["price_vs_origin_bps"] = (out["bar_close"] / origin - 1.0) * 1e4
        return out

    parts: list[pd.DataFrame] = []
    for tf, group in out.groupby("timeframe", sort=False):
        feed = load_feed(pack_root, str(tf))
        if feed.empty:
            parts.append(group)
            continue
        left = group.copy()
        left["_open_ns"] = pd.to_datetime(left["source_bar_open_ts"], utc=True)
        feed = feed.copy()
        feed["_open_ns"] = pd.to_datetime(feed["timestamp"], utc=True)
        merged = left.merge(
            feed[["_open_ns", "close", *[f"ret_{n}_bps" for n in RET_LOOKBACKS]]],
            on="_open_ns",
            how="left",
        )
        close = pd.to_numeric(merged["close"], errors="coerce")
        merged["bar_close"] = close.fillna(pd.to_numeric(merged["entry_price"], errors="coerce"))
        merged = merged.drop(columns=["_open_ns", "close"], errors="ignore")
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    origin = pd.to_numeric(out["context_origin_price"], errors="coerce")
    out["price_vs_origin_bps"] = (out["bar_close"] / origin - 1.0) * 1e4
    return out


def build_open_events(
    archive: Path,
    *,
    pack_root: Path | None = None,
) -> pd.DataFrame:
    """One row per executed OPEN, joined to the command that created it and to realised R."""
    books = archive / "books"
    positions = pd.DataFrame(read_jsonl(books / "positions.jsonl"))
    opens = positions.loc[positions["status"].astype(str).str.upper() == "OPEN"].copy()
    opens = opens.drop_duplicates(subset=["position_id"], keep="first")
    trades = pd.DataFrame(read_jsonl(books / "trades.jsonl"))
    trades["position_id"] = trades["position_id"].astype(str)
    opens["position_id"] = opens["position_id"].astype(str)

    keep_pos = [
        "position_id",
        "timeframe",
        "side",
        "manager_command_id",
        "lifecycle_episode_id",
        "entry_price",
        "context_occurrence_timestamp",
        "context_event_price",
        "stop_loss_price",
        "risk_amount_usd",
    ]
    opens = opens[[c for c in keep_pos if c in opens.columns]]
    trade_keep = ["trade_id", "position_id", "net_pnl_usd", "exit_reason", "context_occurrence_timestamp"]
    closed = trades[[c for c in trade_keep if c in trades.columns]].rename(
        columns={"context_occurrence_timestamp": "exit_ts_raw"}
    )
    events = closed.merge(opens, on="position_id", how="inner", validate="one_to_one")
    events["R"] = pd.to_numeric(events["net_pnl_usd"], errors="coerce") / pd.to_numeric(
        events["risk_amount_usd"], errors="coerce"
    ).replace(0, np.nan)
    events["entry_ts"] = utc_iso(events["context_occurrence_timestamp"])
    events["exit_ts"] = utc_iso(events["exit_ts_raw"])
    events["win"] = (events["R"] > 0).astype(int)

    cmd_path = archive / "manager_commands.parquet"
    cmds = pd.read_parquet(cmd_path)
    cmds = cmds.loc[cmds["intent"].astype(str).isin(OPEN_INTENTS)].copy()
    cmd_keep = [
        "command_id",
        "intent",
        "timeframe",
        "lifecycle_phase",
        "timeframe_state",
        "timeframe_direction",
        "source_bar_open",
        "source_bar_close",
        "evaluation_timestamp",
        "context_origin_price",
        "context_started_at",
        "cross_timeframe_metadata",
        "lifecycle_episode_id",
    ]
    cmds = cmds[[c for c in cmd_keep if c in cmds.columns]]
    events["manager_command_id"] = events["manager_command_id"].astype(str)
    cmds["command_id"] = cmds["command_id"].astype(str)
    events = events.merge(
        cmds,
        left_on="manager_command_id",
        right_on="command_id",
        how="left",
        suffixes=("", "_cmd"),
    )
    if "timeframe_cmd" in events.columns:
        events["timeframe"] = events["timeframe"].fillna(events["timeframe_cmd"])
    events["source_bar_open_ts"] = utc_iso(events["source_bar_open"])
    events["source_bar_close_ts"] = utc_iso(events["source_bar_close"])
    started = utc_iso(events["context_started_at"])
    minutes = events["timeframe"].map(lambda tf: float(TF_MINUTES.get(str(tf).upper(), 15)))
    age_seconds = (events["source_bar_close_ts"] - started).dt.total_seconds()
    events["age_bars"] = (age_seconds / (minutes * 60.0)).clip(lower=0)
    events["side"] = events["side"].astype(str).str.upper()
    xtf_same: list[int] = []
    xtf_opp: list[int] = []
    higher_opp: list[bool] = []
    for row in events.itertuples(index=False):
        same, opp, higher = xtf_features(
            getattr(row, "cross_timeframe_metadata", None),
            getattr(row, "timeframe"),
            getattr(row, "side"),
        )
        xtf_same.append(same)
        xtf_opp.append(opp)
        higher_opp.append(higher)
    events["xtf_same"] = xtf_same
    events["xtf_opposite"] = xtf_opp
    events["higher_tf_opposite"] = higher_opp
    events = attach_price_features(events, pack_root)
    events["context_occurrence_timestamp"] = events["exit_ts_raw"]
    return events.reset_index(drop=True)


def allow_mask(frame: pd.DataFrame, policy: dict[str, Any]) -> np.ndarray:
    """Causal OPEN filter. Threshold 0 on a bps gate means that gate is off."""
    kept = np.ones(len(frame), dtype=bool)
    min_age = int(policy.get("min_age_bars") or 0)
    if min_age > 0:
        kept &= pd.to_numeric(frame["age_bars"], errors="coerce").to_numpy() >= min_age
    min_xtf = int(policy.get("min_xtf_same") or 0)
    if min_xtf > 0:
        kept &= pd.to_numeric(frame["xtf_same"], errors="coerce").fillna(0).to_numpy() >= min_xtf
    if bool(policy.get("block_higher_tf_opposite")):
        kept &= ~frame["higher_tf_opposite"].fillna(False).to_numpy(dtype=bool)

    side = frame["side"].astype(str).str.upper()
    vs_origin = pd.to_numeric(frame["price_vs_origin_bps"], errors="coerce").to_numpy()
    long_bps = float(policy.get("block_long_below_origin_bps") or 0)
    if long_bps > 0:
        long_block = (side == "LONG").to_numpy() & np.isfinite(vs_origin) & (vs_origin <= -long_bps)
        kept &= ~long_block
    short_bps = float(policy.get("block_short_above_origin_bps") or 0)
    if short_bps > 0:
        short_block = (side == "SHORT").to_numpy() & np.isfinite(vs_origin) & (vs_origin >= short_bps)
        kept &= ~short_block

    lookback = int(policy.get("ret_lookback_bars") or 0)
    adverse = float(policy.get("block_adverse_ret_bps") or 0)
    col = f"ret_{lookback}_bps"
    if lookback > 0 and adverse > 0 and col in frame.columns:
        ret = pd.to_numeric(frame[col], errors="coerce").to_numpy()
        long_adv = (side == "LONG").to_numpy() & np.isfinite(ret) & (ret <= -adverse)
        short_adv = (side == "SHORT").to_numpy() & np.isfinite(ret) & (ret >= adverse)
        kept &= ~(long_adv | short_adv)
    return kept


def score_policy(
    frame: pd.DataFrame,
    policy: dict[str, Any],
    *,
    min_keep_frac: float = 0.35,
) -> dict[str, Any]:
    r = pd.to_numeric(frame["R"], errors="coerce").to_numpy()
    baseline_total = float(np.nansum(r))
    kept = allow_mask(frame, policy)
    n = int(len(frame))
    n_kept = int(kept.sum())
    frac = (n_kept / n) if n else 0.0
    if n == 0 or frac < float(min_keep_frac):
        return {
            "n": n,
            "n_kept": n_kept,
            "keep_frac": round(frac, 4),
            "total_r": float("-inf"),
            "delta_total_r": float("-inf"),
            "mean_r": None,
            "wr": None,
            "blocked_mean_r": None,
            "rejected": "keep_frac_below_floor",
        }
    kept_r = r[kept]
    blocked_r = r[~kept]
    total = float(np.nansum(kept_r))
    return {
        "n": n,
        "n_kept": n_kept,
        "keep_frac": round(frac, 4),
        "total_r": round(total, 4),
        "delta_total_r": round(total - baseline_total, 4),
        "mean_r": round(float(np.nanmean(kept_r)), 4) if n_kept else None,
        "wr": round(float(np.mean(kept_r > 0)), 4) if n_kept else None,
        "blocked_mean_r": round(float(np.nanmean(blocked_r)), 4) if (~kept).any() else None,
        "rejected": None,
    }


def purged_folds(
    entry: pd.Series,
    n_folds: int,
    *,
    purge_days: int = 7,
    min_fit: int = 200,
    min_score: int = 80,
) -> list[tuple[np.ndarray, np.ndarray]]:
    order = np.argsort(entry.values)
    ts = entry.values[order]
    bounds = np.linspace(0, len(ts), n_folds + 2, dtype=int)[1:]
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_folds):
        lo, hi = int(bounds[k]), int(bounds[k + 1])
        score_idx = order[lo:hi]
        cut = pd.Timestamp(ts[lo]) - pd.Timedelta(days=purge_days)
        fit_ts = entry.values[order[:lo]]
        fit_idx = order[:lo][fit_ts < cut.to_numpy()]
        if len(fit_idx) < int(min_fit) or len(score_idx) < int(min_score):
            continue
        folds.append((fit_idx, score_idx))
    return folds


def mean_fold_total_r(
    frame: pd.DataFrame,
    policy: dict[str, Any],
    folds: list[tuple[np.ndarray, np.ndarray]],
    *,
    min_keep_frac: float = 0.35,
) -> tuple[float, list[float]]:
    """Score only the score-window of each fold (no fit step: the policy is a rule)."""
    per: list[float] = []
    for _, score_idx in folds:
        chunk = frame.iloc[score_idx]
        result = score_policy(chunk, policy, min_keep_frac=min_keep_frac)
        per.append(float(result["total_r"]))
    if not per or any(not np.isfinite(v) for v in per):
        return float("-inf"), per
    return float(np.mean(per)), per
