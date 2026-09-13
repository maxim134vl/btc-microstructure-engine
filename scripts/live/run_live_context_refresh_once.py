#!/usr/bin/env python3
"""Manual live context refresh — once mode (shadow-only).

Logic:
  1. Read latest timestamp from live_market_feed.parquet
  2. Read latest timestamp from market_context_lifecycle_memory.parquet
  3. If lifecycle lags live_feed:
       - run build_market_context_shadow_chain.py
       - on success run append_context_decision_log.py
  4. If lifecycle already fresh:
       - run append_context_decision_log.py only
  5. Write status JSON + log file

Settled M15 prefix is immutable. The last 4 closed M15 bars are restated so
auction follow-through can settle UNKNOWN tips. M30/H1/H4 rows are replaced
from the independent closed-bar rebuild (they were OHLCV-proxy). Lifecycle
tail is replayed from production prev; living higher-TF episode ids stay
when the tip direction does not change. M15 episodes stay frozen.

Does NOT:
  - start dashboard or visual server
  - enable execution / create orders
  - change live feed / runtime-stack
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
LIFECYCLE_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
SHADOW_CHAIN_SCRIPT = ROOT / "scripts" / "research" / "build_market_context_shadow_chain.py"
DECISION_LOGGER_SCRIPT = ROOT / "scripts" / "live" / "append_context_decision_log.py"
STATUS_PATH = ROOT / "data" / "live" / "live_context_refresh_status.json"
LOG_PATH = ROOT / "logs" / "live_context_refresh.log"

# Shadow chain may rewrite tip/history; after rebuild we restore immutable production
# prefix and keep only newly observed timestamps (Patch 2A / 2A.1 FINAL contract).
SHADOW_PREFIX_PRESERVE = (
    (ROOT / "data" / "cognition" / "auction_episode_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "final_market_context_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet", "end_time"),
)

REFRESH_VERSION = "live_context_refresh_once_v3_replace_higher_tf"
# Auction follow-through looks ahead up to 4 closed bars. The previous merge
# froze the tip as UNKNOWN forever (existing_wins). Restate that window on M15.
COGNITION_RESTATE_BARS = 4
# Independent higher TFs were OHLCV-proxy. Replace the whole series from the
# closed-bar volume rebuild. Do not copy M15 LONG/SHORT onto them.
INDEPENDENT_REPLACE_TIMEFRAMES = frozenset({"M30", "H1", "H4"})


class RefreshError(RuntimeError):
    """Safe failure for missing sources / failed rebuild."""


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(ts: Any) -> str | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    parsed = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).isoformat().replace("+00:00", "Z")


def latest_parquet_timestamp(path: Path, col: str = "timestamp") -> pd.Timestamp | None:
    if not path.exists():
        raise RefreshError(f"Missing required artifact: {path}")
    frame = pd.read_parquet(path)
    if col not in frame.columns or len(frame) == 0:
        return None
    # Live feed is M15. A mixed lifecycle file must not look fresh because an
    # older/newer higher-TF stamp sits at iloc[-1].
    if col == "timestamp" and "timeframe" in frame.columns:
        m15 = frame.loc[frame["timeframe"].astype(str).str.upper().eq("M15")]
        if len(m15):
            frame = m15
    series = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
    if len(series) == 0:
        return None
    return pd.Timestamp(series.max())


def lag_seconds(live_ts: pd.Timestamp | None, life_ts: pd.Timestamp | None) -> float | None:
    if live_ts is None or life_ts is None:
        return None
    return round((pd.Timestamp(live_ts) - pd.Timestamp(life_ts)).total_seconds(), 3)


def lifecycle_is_stale(live_ts: pd.Timestamp | None, life_ts: pd.Timestamp | None) -> bool:
    if live_ts is None or life_ts is None:
        return True
    return pd.Timestamp(life_ts) < pd.Timestamp(live_ts)


def append_log(message: str, *, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().isoformat().replace("+00:00", "Z")
    line = f"[{stamp}] {message}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def write_status(payload: dict[str, Any], *, status_path: Path = STATUS_PATH) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_path.with_suffix(status_path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, status_path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _timeframe_timestamp_keys(frame: pd.DataFrame, ts_col: str) -> list[tuple[str, str]]:
    tf = frame["timeframe"].astype(str).str.upper()
    ts = pd.to_datetime(frame[ts_col], utc=True, errors="coerce")
    iso = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return list(zip(tf.tolist(), iso.fillna("").tolist()))


def _iso_ts_series(frame: pd.DataFrame, ts_col: str) -> pd.Series:
    ts = pd.to_datetime(frame[ts_col], utc=True, errors="coerce")
    return ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")


def restate_keys_for_frame(
    prod: pd.DataFrame,
    ts_col: str,
    *,
    restate_bars: int = COGNITION_RESTATE_BARS,
    replace_timeframes: frozenset[str] | set[str] | None = None,
) -> set[Any]:
    """Last N timestamps per timeframe (or untagged series) may be restated.

    ``replace_timeframes`` restates every timestamp of those TFs (used to drop
    OHLCV-proxy M30/H1/H4 without touching the M15 settled prefix).
    """
    if prod is None or not len(prod) or ts_col not in prod.columns:
        return set()
    replace = {str(tf).upper() for tf in (replace_timeframes or ())}
    n = max(int(restate_bars), 0)
    work = prod.copy()
    work["_ts"] = pd.to_datetime(work[ts_col], utc=True, errors="coerce")
    work = work.dropna(subset=["_ts"]).sort_values("_ts")
    if "timeframe" in work.columns:
        keys: set[tuple[str, str]] = set()
        tf = work["timeframe"].astype(str).str.upper()
        for name, grp in work.groupby(tf, sort=False):
            iso_all = grp["_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            if str(name).upper() in replace:
                iso = iso_all
            else:
                if n <= 0:
                    continue
                iso = iso_all.tail(n)
            keys.update((str(name), str(stamp)) for stamp in iso.tolist())
        return keys
    if n <= 0:
        return set()
    iso = work["_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tail(n)
    return {str(stamp) for stamp in iso.tolist()}


def tail_merge_existing_wins(
    prod: pd.DataFrame,
    cand: pd.DataFrame,
    ts_col: str,
    *,
    restate_bars: int = COGNITION_RESTATE_BARS,
    replace_timeframes: frozenset[str] | set[str] | None = None,
) -> pd.DataFrame:
    """Immutable settled prefix; candidate restates the last N bars and appends new.

    Auction follow-through needs the next closed bar. Existing-wins on the tip
    froze UNKNOWN forever. Restate ``restate_bars`` (FT horizon) so volume
    classifiers can settle, then keep older M15 rows unchanged.

    ``replace_timeframes`` (M30/H1/H4) takes the candidate series in full and
    drops production rows that the rebuild no longer has.
    """
    if prod is None or len(prod) == 0:
        return cand.copy()
    if cand is None or len(cand) == 0:
        return prod.copy()
    prod = prod.copy()
    cand = cand.copy()
    replace = {str(tf).upper() for tf in (replace_timeframes or ())}
    tagged = "timeframe" in cand.columns or "timeframe" in prod.columns
    if tagged:
        if "timeframe" not in prod.columns:
            prod["timeframe"] = "M15"
        if "timeframe" not in cand.columns:
            cand["timeframe"] = "M15"
        restated = restate_keys_for_frame(
            prod,
            ts_col,
            restate_bars=restate_bars,
            replace_timeframes=replace,
        )
        prod_keys = _timeframe_timestamp_keys(prod, ts_col)
        settled_mask = [key not in restated for key in prod_keys]
        settled = prod.loc[settled_mask].copy()
        settled_keys = set(_timeframe_timestamp_keys(settled, ts_col)) if len(settled) else set()
        cand_keys = _timeframe_timestamp_keys(cand, ts_col)
        keep = [key not in settled_keys for key in cand_keys]
        extra = cand.loc[keep].copy()
        for col in prod.columns:
            if col not in extra.columns:
                extra[col] = None
        extra = extra[list(prod.columns)] if len(extra) else extra
        cand_key_set = set(cand_keys)
        missing_restated = prod.loc[
            [
                key in restated
                and key not in cand_key_set
                and str(key[0]).upper() not in replace
                for key in prod_keys
            ]
        ]
        if len(missing_restated):
            extra = pd.concat([extra, missing_restated], ignore_index=True, sort=False)
        out = pd.concat([settled, extra], ignore_index=True, sort=False)
        out = out.drop_duplicates(subset=["timeframe", ts_col], keep="last")
        out["_sort"] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
        out = out.sort_values(["_sort", "timeframe"]).drop(columns=["_sort"]).reset_index(drop=True)
        return out
    restated = restate_keys_for_frame(prod, ts_col, restate_bars=restate_bars)
    prod_iso = _iso_ts_series(prod, ts_col)
    settled = prod.loc[~prod_iso.isin(restated)].copy()
    cand_iso = _iso_ts_series(cand, ts_col)
    settled_iso = set(_iso_ts_series(settled, ts_col).tolist()) if len(settled) else set()
    extra = cand.loc[~cand_iso.isin(settled_iso)].copy()
    for col in prod.columns:
        if col not in extra.columns:
            extra[col] = None
    extra = extra[list(prod.columns)] if len(extra) else extra
    cand_iso_set = set(cand_iso.tolist())
    missing_restated = prod.loc[prod_iso.isin(restated) & ~prod_iso.isin(cand_iso_set)]
    if len(missing_restated):
        extra = pd.concat([extra, missing_restated], ignore_index=True, sort=False)
    out = pd.concat([settled, extra], ignore_index=True, sort=False)
    out = out.drop_duplicates(subset=[ts_col], keep="last")
    out["_sort"] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    out = out.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    return out


def snapshot_prefix_datasets(
    datasets: tuple[tuple[Path, str], ...] = SHADOW_PREFIX_PRESERVE,
) -> dict[str, dict[str, Any]]:
    """Read production datasets before shadow rewrite."""
    snaps: dict[str, dict[str, Any]] = {}
    for path, ts_col in datasets:
        key = str(path)
        if not path.exists():
            snaps[key] = {"path": path, "ts_col": ts_col, "frame": None, "tip": None, "rows": 0}
            continue
        frame = pd.read_parquet(path)
        tip = None
        if ts_col in frame.columns and len(frame):
            series = pd.to_datetime(frame[ts_col], utc=True, errors="coerce").dropna()
            if len(series):
                tip = pd.Timestamp(series.max())
        snaps[key] = {
            "path": path,
            "ts_col": ts_col,
            "frame": frame,
            "tip": tip,
            "rows": int(len(frame)),
        }
    return snaps


def restep_lifecycle_tail(
    prod: pd.DataFrame,
    merged: pd.DataFrame,
    ts_col: str = "timestamp",
    *,
    restate_bars: int = COGNITION_RESTATE_BARS,
    replace_timeframes: frozenset[str] | set[str] | None = None,
) -> pd.DataFrame:
    """Replay step_lifecycle on the restated tail using production prev.

    Candidate lifecycle rows assumed a full sequential walk that we discarded.
    Raw classifier fields on the merged tail are kept; active state is restepped.
    Fully replaced TFs (M30/H1/H4) are restepped from bar 0; living episode
    ids are kept when the tip direction matches production.
    """
    if merged is None or not len(merged):
        return merged
    if prod is None or not len(prod):
        return merged
    sys.path.insert(0, str(ROOT / "scripts" / "research"))
    from build_market_context_lifecycle_memory import step_lifecycle  # noqa: WPS433

    replace = {str(tf).upper() for tf in (replace_timeframes or ())}
    work = merged.copy()
    if "timeframe" not in work.columns:
        work["timeframe"] = "M15"
    prod_work = prod.copy()
    if "timeframe" not in prod_work.columns:
        prod_work["timeframe"] = "M15"
    restated = restate_keys_for_frame(
        prod_work,
        ts_col,
        restate_bars=restate_bars,
        replace_timeframes=replace,
    )
    parts: list[pd.DataFrame] = []
    tf_col = work["timeframe"].astype(str).str.upper()
    for tf, grp in work.groupby(tf_col, sort=False):
        grp = grp.copy()
        grp["_ts"] = pd.to_datetime(grp[ts_col], utc=True, errors="coerce")
        grp = grp.sort_values("_ts")
        prod_tf = prod_work[prod_work["timeframe"].astype(str).str.upper() == str(tf)].copy()
        if len(prod_tf):
            prod_tf["_ts"] = pd.to_datetime(prod_tf[ts_col], utc=True, errors="coerce")
            prod_tf = prod_tf.sort_values("_ts")
        if str(tf) in replace:
            tail_mask = [True] * len(grp)
        else:
            iso = grp["_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            tail_mask = [(str(tf), str(stamp)) in restated for stamp in iso.tolist()]
            prod_tip = prod_tf["_ts"].max() if len(prod_tf) and "_ts" in prod_tf.columns else None
            if prod_tip is not None:
                tail_mask = [
                    flag or (pd.notna(ts) and ts > prod_tip)
                    for flag, ts in zip(tail_mask, grp["_ts"].tolist())
                ]
        if not any(tail_mask):
            parts.append(grp.drop(columns=["_ts"], errors="ignore"))
            continue
        settled = grp.loc[[not flag for flag in tail_mask]]
        tail = grp.loc[tail_mask]
        prev = None
        if len(settled):
            prev = settled.iloc[-1].to_dict()
        elif len(prod_tf) and str(tf) not in replace:
            prod_iso = prod_tf["_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            kept = prod_tf.loc[[(str(tf), str(stamp)) not in restated for stamp in prod_iso.tolist()]]
            if len(kept):
                prev = kept.iloc[-1].to_dict()
        new_rows: list[dict[str, Any]] = []
        for rec in tail.to_dict("records"):
            ts = rec.get("_ts")
            step = step_lifecycle(
                raw_market_context=str(rec.get("raw_market_context") or rec.get("active_market_context") or "OBSERVE"),
                raw_context_status=str(rec.get("raw_context_status") or "UNKNOWN"),
                raw_context_reason=str(rec.get("raw_context_reason") or "UNKNOWN"),
                raw_cognitive_market_state=str(rec.get("raw_cognitive_market_state") or "UNKNOWN"),
                raw_state_direction=str(rec.get("raw_state_direction") or "UNKNOWN"),
                auction_episode=str(rec.get("raw_auction_episode") or rec.get("auction_episode") or "UNKNOWN"),
                timestamp=ts,
                prev=prev,
            )
            row = dict(rec)
            row.update(step)
            prev_ep = None if prev is None else prev.get("context_episode_id")
            prev_active = None if prev is None else str(prev.get("active_market_context") or "")
            new_active = str(row.get("active_market_context") or "")
            if prev_ep is not None and prev_active == new_active:
                row["context_episode_id"] = prev_ep
            row.pop("_ts", None)
            new_rows.append(row)
            prev = row
        rebuilt = pd.concat(
            [settled.drop(columns=["_ts"], errors="ignore"), pd.DataFrame(new_rows)],
            ignore_index=True,
            sort=False,
        )
        if str(tf) in replace:
            rebuilt = _preserve_living_episode_id(prod_tf, rebuilt, ts_col)
        parts.append(rebuilt)
    out = pd.concat(parts, ignore_index=True, sort=False)
    out["_sort"] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    out = out.sort_values(["_sort", "timeframe"]).drop(columns=["_sort"]).reset_index(drop=True)
    return out


def _preserve_living_episode_id(
    prod_tf: pd.DataFrame,
    rebuilt: pd.DataFrame,
    ts_col: str,
) -> pd.DataFrame:
    """Keep the open higher-TF episode id when tip direction did not change."""
    if rebuilt is None or not len(rebuilt) or prod_tf is None or not len(prod_tf):
        return rebuilt
    if "active_market_context" not in rebuilt.columns or "context_episode_id" not in prod_tf.columns:
        return rebuilt
    prod_work = prod_tf.copy()
    prod_work["_pts"] = pd.to_datetime(prod_work[ts_col], utc=True, errors="coerce")
    prod_work = prod_work.dropna(subset=["_pts"]).sort_values("_pts")
    if not len(prod_work):
        return rebuilt
    rebuilt = rebuilt.copy()
    rebuilt["_rts"] = pd.to_datetime(rebuilt[ts_col], utc=True, errors="coerce")
    order = rebuilt.dropna(subset=["_rts"]).sort_values("_rts")
    if not len(order):
        return rebuilt.drop(columns=["_rts"], errors="ignore")
    prod_tip = prod_work.iloc[-1]
    new_tip = order.iloc[-1]
    old_ctx = str(prod_tip.get("active_market_context") or "")
    new_ctx = str(new_tip.get("active_market_context") or "")
    old_id = prod_tip.get("context_episode_id")
    if old_id is None or (isinstance(old_id, float) and pd.isna(old_id)) or old_ctx != new_ctx or not old_ctx:
        return rebuilt.drop(columns=["_rts"], errors="ignore")
    living: list[Any] = []
    for idx in reversed(order.index.tolist()):
        if str(rebuilt.at[idx, "active_market_context"] or "") != new_ctx:
            break
        living.append(idx)
    if living:
        rebuilt.loc[living, "context_episode_id"] = old_id
    return rebuilt.drop(columns=["_rts"], errors="ignore")


def merge_episodes_keep_m15_rebuild_higher(
    prod: pd.DataFrame,
    lifecycle: pd.DataFrame,
) -> pd.DataFrame:
    """Freeze M15 episode rows; rebuild M30/H1/H4 from restepped lifecycle."""
    if prod is None or not len(prod):
        return prod
    prod_work = prod.copy()
    if "timeframe" not in prod_work.columns:
        prod_work["timeframe"] = "M15"
    m15 = prod_work[prod_work["timeframe"].astype(str).str.upper().eq("M15")].copy()
    parts: list[pd.DataFrame] = [m15] if len(m15) else []
    if lifecycle is None or not len(lifecycle) or "timeframe" not in lifecycle.columns:
        if parts:
            return pd.concat(parts, ignore_index=True, sort=False)
        return prod_work
    sys.path.insert(0, str(ROOT / "scripts" / "research"))
    from build_market_context_lifecycle_memory import build_lifecycle_episodes  # noqa: WPS433

    life = lifecycle.copy()
    life["timeframe"] = life["timeframe"].astype(str).str.upper()
    for tf in ("M30", "H1", "H4"):
        life_tf = life[life["timeframe"].eq(tf)]
        if not len(life_tf):
            continue
        ep_tf = build_lifecycle_episodes(life_tf)
        if ep_tf is None or not len(ep_tf):
            continue
        ep_tf = ep_tf.copy()
        ep_tf["timeframe"] = tf
        if "lifecycle_source" in life_tf.columns:
            ep_tf["lifecycle_source"] = life_tf["lifecycle_source"].iloc[-1]
        parts.append(ep_tf)
    if not parts:
        return prod_work
    out = pd.concat(parts, ignore_index=True, sort=False)
    if "end_time" in out.columns:
        out["_sort"] = pd.to_datetime(out["end_time"], utc=True, errors="coerce")
        out = out.sort_values(["_sort", "timeframe"]).drop(columns=["_sort"]).reset_index(drop=True)
    return out


def restore_prefix_after_shadow(
    snapshots: dict[str, dict[str, Any]],
    *,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    """Settled M15 prefix stays; last N M15 bars restated; higher TFs replaced."""
    report: dict[str, Any] = {"restored": [], "skipped": []}
    lifecycle_path = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    written_lifecycle: pd.DataFrame | None = None
    for key, snap in snapshots.items():
        path: Path = snap["path"]
        ts_col: str = snap["ts_col"]
        prod = snap["frame"]
        if prod is None or not path.exists():
            report["skipped"].append({"path": key, "reason": "missing_before_or_after"})
            continue
        cand = pd.read_parquet(path)
        if path.name == "market_context_lifecycle_episodes.parquet":
            life = written_lifecycle
            if life is None and lifecycle_path.exists():
                life = pd.read_parquet(lifecycle_path)
            merged = merge_episodes_keep_m15_rebuild_higher(prod, life if life is not None else pd.DataFrame())
            replace: set[str] = set()
            merge_restate = 0
        else:
            replace = (
                set(INDEPENDENT_REPLACE_TIMEFRAMES)
                if path.name == "market_context_lifecycle_memory.parquet"
                else set()
            )
            merge_restate = COGNITION_RESTATE_BARS
            merged = tail_merge_existing_wins(
                prod,
                cand,
                ts_col,
                restate_bars=merge_restate,
                replace_timeframes=replace,
            )
            if path.resolve() == lifecycle_path.resolve() or path.name == "market_context_lifecycle_memory.parquet":
                merged = restep_lifecycle_tail(
                    prod,
                    merged,
                    ts_col,
                    restate_bars=merge_restate,
                    replace_timeframes=replace,
                )
                written_lifecycle = merged
        prior_tip = snap["tip"]
        if prior_tip is not None and path.name != "market_context_lifecycle_episodes.parquet":
            restated = restate_keys_for_frame(
                prod,
                ts_col,
                restate_bars=merge_restate,
                replace_timeframes=replace,
            )
            if "timeframe" in merged.columns:
                prod_work = prod.copy()
                if "timeframe" not in prod_work.columns:
                    prod_work["timeframe"] = "M15"
                prod_keys = _timeframe_timestamp_keys(prod_work, ts_col)
                settled_keys = {k for k in prod_keys if k not in restated}
                merged_keys = _timeframe_timestamp_keys(merged, ts_col)
                merged_settled = merged.loc[[key in settled_keys for key in merged_keys]]
                if len(merged_settled) != len(settled_keys):
                    raise RefreshError(
                        f"settled prefix changed after tail_merge for {path.name}: "
                        f"{len(settled_keys)} -> {len(merged_settled)}"
                    )
            else:
                p_iso = _iso_ts_series(prod, ts_col)
                settled = prod.loc[~p_iso.isin(restated)]
                m_iso = _iso_ts_series(merged, ts_col)
                m_settled = merged.loc[m_iso.isin(set(p_iso.loc[~p_iso.isin(restated)].tolist()))]
                if len(m_settled) != len(settled):
                    raise RefreshError(
                        f"settled prefix changed after tail_merge for {path.name}: "
                        f"{len(settled)} -> {len(m_settled)}"
                    )
        elif prior_tip is not None and path.name == "market_context_lifecycle_episodes.parquet":
            prod_m15 = prod
            if "timeframe" in prod.columns:
                prod_m15 = prod[prod["timeframe"].astype(str).str.upper().eq("M15")]
            merged_m15 = merged
            if "timeframe" in merged.columns:
                merged_m15 = merged[merged["timeframe"].astype(str).str.upper().eq("M15")]
            if len(prod_m15) and len(merged_m15) != len(prod_m15):
                raise RefreshError(
                    f"M15 episodes changed after merge: {len(prod_m15)} -> {len(merged_m15)}"
                )
        _write_parquet_atomic(merged, path)
        new_tip = latest_parquet_timestamp(path, col=ts_col)
        entry = {
            "path": key,
            "rows_before": int(snap["rows"]),
            "rows_after": int(len(merged)),
            "added": int(len(merged) - snap["rows"]),
            "tip_before": _iso(prior_tip),
            "tip_after": _iso(new_tip),
        }
        report["restored"].append(entry)
        append_log(
            f"PREFIX_PRESERVE {path.name} added={entry['added']} "
            f"restated={COGNITION_RESTATE_BARS} tip {_iso(prior_tip)} -> {_iso(new_tip)}",
            log_path=log_path,
        )
    return report


def run_python_script(script: Path, *, cwd: Path = ROOT, timeout_s: int | None = None) -> dict[str, Any]:
    if not script.exists():
        raise RefreshError(f"Missing script: {script}")
    if timeout_s is None:
        timeout_s = int(os.environ.get("BTC_ML_REFRESH_SCRIPT_TIMEOUT_S", "1800"))
    python = Path(sys.executable)
    started = _utc_now()
    proc = subprocess.run(
        [str(python), str(script)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    ended = _utc_now()
    return {
        "script": str(script),
        "returncode": int(proc.returncode),
        "ok": proc.returncode == 0,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def run_refresh_once(
    *,
    live_path: Path = LIVE_FEED,
    lifecycle_path: Path = LIFECYCLE_PATH,
    shadow_script: Path = SHADOW_CHAIN_SCRIPT,
    decision_script: Path = DECISION_LOGGER_SCRIPT,
    status_path: Path = STATUS_PATH,
    log_path: Path = LOG_PATH,
    force_rebuild: bool = False,
    skip_rebuild: bool = False,
    run_script=run_python_script,
    prefix_datasets: tuple[tuple[Path, str], ...] = SHADOW_PREFIX_PRESERVE,
) -> dict[str, Any]:
    started = _utc_now()
    append_log("START live_context_refresh_once", log_path=log_path)

    live_ts = latest_parquet_timestamp(live_path)
    # Fresh VPS volumes have a feed before lifecycle exists. Treat a missing
    # lifecycle file as "no tip" so the shadow chain can seed instead of dying.
    if not lifecycle_path.exists():
        life_ts = None
    else:
        life_ts = latest_parquet_timestamp(lifecycle_path)
    lag = lag_seconds(live_ts, life_ts)
    was_stale = lifecycle_is_stale(live_ts, life_ts)
    needs_rebuild = bool(force_rebuild or (was_stale and not skip_rebuild))

    append_log(
        f"live_latest={_iso(live_ts)} lifecycle_latest={_iso(life_ts)} "
        f"lag_seconds={lag} stale={was_stale} needs_rebuild={needs_rebuild}",
        log_path=log_path,
    )

    shadow_result: dict[str, Any] | None = None
    decision_result: dict[str, Any] | None = None
    prefix_report: dict[str, Any] | None = None
    status = "OK"
    error: str | None = None

    try:
        if needs_rebuild:
            snapshots = snapshot_prefix_datasets(prefix_datasets) if prefix_datasets else {}
            append_log(
                f"SNAPSHOT prefix datasets n={len(snapshots)} "
                f"lifecycle_tip={_iso(snapshots.get(str(lifecycle_path), {}).get('tip'))}",
                log_path=log_path,
            )
            append_log("RUN build_market_context_shadow_chain.py", log_path=log_path)
            shadow_result = run_script(shadow_script)
            if not shadow_result["ok"]:
                raise RefreshError(
                    f"Shadow chain rebuild failed (rc={shadow_result['returncode']}): "
                    f"{shadow_result.get('stderr_tail') or shadow_result.get('stdout_tail')}"
                )
            append_log("PASS shadow chain rebuild", log_path=log_path)
            if snapshots:
                prefix_report = restore_prefix_after_shadow(snapshots, log_path=log_path)
                append_log("PASS prefix preserve (settled rows win, tail restated)", log_path=log_path)
            # Re-read lifecycle after rebuild + prefix restore.
            life_ts = latest_parquet_timestamp(lifecycle_path)
            lag = lag_seconds(live_ts, life_ts)
            append_log(
                f"AFTER rebuild+prefix lifecycle_latest={_iso(life_ts)} lag_seconds={lag} "
                f"stale={lifecycle_is_stale(live_ts, life_ts)}",
                log_path=log_path,
            )
        else:
            append_log("SKIP shadow chain rebuild (lifecycle already fresh)", log_path=log_path)

        append_log("RUN append_context_decision_log.py", log_path=log_path)
        decision_result = run_script(decision_script)
        if not decision_result["ok"]:
            raise RefreshError(
                f"Decision logger failed (rc={decision_result['returncode']}): "
                f"{decision_result.get('stderr_tail') or decision_result.get('stdout_tail')}"
            )
        append_log(
            f"PASS decision logger stdout_tail={decision_result.get('stdout_tail', '')[-500:]}",
            log_path=log_path,
        )
    except Exception as exc:  # noqa: BLE001 — once-mode orchestrator must capture and persist status
        status = "ERROR"
        error = str(exc)
        append_log(f"ERROR {error}", log_path=log_path)

    ended = _utc_now()
    payload = {
        "refresh_version": REFRESH_VERSION,
        "mode": "once",
        "status": status,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "live_feed_latest_timestamp": _iso(live_ts),
        "lifecycle_latest_timestamp": _iso(life_ts),
        "live_to_lifecycle_lag_seconds": lag,
        "lifecycle_was_stale": bool(was_stale),
        "lifecycle_still_stale_after": bool(lifecycle_is_stale(live_ts, life_ts)),
        "shadow_chain_rebuild_ran": bool(needs_rebuild and shadow_result is not None),
        "shadow_chain_rebuild_ok": None if shadow_result is None else bool(shadow_result.get("ok")),
        "prefix_preserve_ran": prefix_report is not None,
        "prefix_preserve": prefix_report,
        "decision_logger_ran": decision_result is not None,
        "decision_logger_ok": None if decision_result is None else bool(decision_result.get("ok")),
        "execution_enabled": False,
        "orders_created": False,
        "paper_orders_created": False,
        "action_allowed": False,
        "shadow_only": True,
        "visual_server_started": False,
        "dashboard_started": False,
        "runtime_stack_modified": False,
        "error": error,
        "shadow_result": shadow_result,
        "decision_result": {
            k: decision_result.get(k)
            for k in ("script", "returncode", "ok", "started_at_utc", "ended_at_utc", "stdout_tail")
        }
        if decision_result
        else None,
        "note": (
            "Manual once-mode live context refresh. Shadow-only. "
            "Does not enable execution and must not be used to place orders."
        ),
    }
    write_status(payload, status_path=status_path)
    append_log(f"END status={status}", log_path=log_path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual live context refresh once-mode (shadow-only)")
    parser.add_argument("--force-rebuild", action="store_true", help="Always run shadow chain rebuild")
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Never run shadow chain rebuild (decision logger only)",
    )
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    args = parser.parse_args(argv)

    if args.force_rebuild and args.skip_rebuild:
        print("ERROR: --force-rebuild and --skip-rebuild are mutually exclusive", file=sys.stderr)
        return 2

    payload = run_refresh_once(
        status_path=args.status_path,
        log_path=args.log_path,
        force_rebuild=bool(args.force_rebuild),
        skip_rebuild=bool(args.skip_rebuild),
    )
    print("======== LIVE CONTEXT REFRESH ONCE (shadow-only) ========")
    for key in (
        "status",
        "live_feed_latest_timestamp",
        "lifecycle_latest_timestamp",
        "live_to_lifecycle_lag_seconds",
        "shadow_chain_rebuild_ran",
        "shadow_chain_rebuild_ok",
        "decision_logger_ran",
        "decision_logger_ok",
        "execution_enabled",
        "error",
    ):
        print(f"{key}: {payload.get(key)}")
    print(f"status_json: {args.status_path}")
    print(f"log_file: {args.log_path}")
    print(
        "NOTE: Manual once-mode refresh. Shadow-only. "
        "Does not enable execution and must not be used to place orders."
    )
    return 0 if payload.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
