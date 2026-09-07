#!/usr/bin/env python3
"""Causal feature matrix for the canonical Hybrid tick book, keyed on trade entries.

Purpose
-------
One row per closed trade, every column knowable at the entry decision, labelled with
the realised R multiple. This is the input for the CatBoost sizing model.

Causality
---------
The manager decided each entry on `source_bar_close` — the close of the last bar of
that timeframe available at the evaluation stamp. That, not the entry timestamp, is
the correct cutoff: entry happens at the evaluation boundary, but the state behind it
was published at the prior bar close. Every plane is therefore joined backward-asof
against `source_bar_close`, and the script asserts afterwards that no joined row
carries a timestamp beyond it.

Why the manager's own state fields are not features
---------------------------------------------------
On entry rows `timeframe_state`, `lifecycle_phase`, `availability_status` and
`reason_codes` are constant (LONG/SHORT_CONTEXT, ACTIVE, FRESH_EVENT,
TIMEFRAME_DIRECTIONAL_ENTRY) because they *are* the entry condition. They carry zero
information here. The signal has to come from the context planes, from the other
timeframes' states via cross_timeframe_metadata, and from portfolio state.

Synthesis-derived fields (alignment_score, persistence_score, structural_rank,
location_bias, confidence) are populated on 8.8% of commands — the production
synthesis plane only covers 2026-05 onward — so they are dropped rather than fed in
as near-empty columns.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
sys.path.insert(0, str(ROOT))

from calibration_split import assign_segment  # noqa: E402

BOOKS = (
    ROOT
    / "data/research/external_traders/etll_hybrid_eqcorr/paper_repo/data/trading"
    / "intrabar_paper/ETLL_HYBRID_TICK_V1_20260905_092610/books"
)
MANAGER_COMMANDS = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive/"
    "ETLL_HYBRID_TICK_V1_20260905_092610/manager_commands.parquet"
)
PACKS = {
    "M15": ROOT / "data/research/external_traders/market_pack_btc_m15",
    "M30": ROOT / "data/research/external_traders/market_pack_btc_m30",
    "H1": ROOT / "data/research/external_traders/market_pack_btc_h1",
    "H4": ROOT / "data/research/external_traders/market_pack_btc_h4",
}
TIMEFRAMES = ("M15", "M30", "H1", "H4")
OUT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/trade_feature_matrix.parquet"

# Planes joined for the trade's OWN timeframe. Columns are prefixed per plane.
OWN_PLANES: dict[str, tuple[str, ...]] = {
    "candle_structure_memory": (
        "candle_type", "body", "spread", "upper_wick", "lower_wick", "close_position",
        "spread_mean_20", "spread_std_20", "volume_mean_20", "volume_std_20",
        "spread_zscore", "volume_zscore", "delta", "volume", "taker_buy_volume",
        "buy_volume", "sell_volume", "number_of_trades", "close",
    ),
    "volume_response_state": (
        "volume_event", "continuation_quality", "climax_state", "effort_result_state",
        "volume_class", "localized_behavior", "participation_state",
        "relative_volume", "relative_spread", "delta_efficiency", "effort_score",
        "result_score", "normalized_result", "effort_result_ratio",
        "unfinished_auction", "upper_rejection", "lower_rejection",
    ),
    "auction_episode_memory": (
        "bar_event", "volume_event", "climax_state", "volume_effort", "effort_side",
        "auction_location", "price_result", "effort_result", "follow_through",
        "convergence_state", "localized_behavior", "auction_regime", "auction_episode",
        "episode_status",
    ),
    "cognitive_market_state_memory": (
        "cognitive_market_state", "state_direction", "state_status",
        "primary_auction_episode", "primary_episode_status",
    ),
    "final_market_context_memory": (
        "market_context", "context_status", "action_allowed",
    ),
    "market_context_lifecycle_memory": (
        "lifecycle_state", "active_context_age_bars", "state_age_minutes",
        "market_activity_score", "context_distance_bps", "context_favorable_distance_bps",
        "context_adverse_distance_bps", "context_direction", "context_origin_price",
        "invalidation_type", "transition_reason", "challenge_reason",
    ),
    "cognition_triggers_proxy": ("trigger_event", "location_bias"),
}

# For the other three timeframes only the cheap state summary is carried across, to
# describe the wider regime without exploding the column count.
CROSS_PLANES: dict[str, tuple[str, ...]] = {
    "cognitive_market_state_memory": ("cognitive_market_state", "state_direction"),
    "volume_response_state": ("volume_class", "climax_state", "relative_volume", "effort_score"),
    "auction_episode_memory": ("auction_regime", "follow_through", "convergence_state"),
    "market_context_lifecycle_memory": ("lifecycle_state", "active_context_age_bars"),
}

TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}


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


def ts(series: pd.Series) -> pd.Series:
    """Parse to UTC and pin the resolution.

    The book stamps ISO8601 strings (parsed as microseconds) while the pack parquets
    carry milliseconds; merge_asof refuses to join across resolutions, so everything
    is normalised to nanoseconds at the edges.
    """
    return pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601").astype("datetime64[ns, UTC]")


def build_entries() -> pd.DataFrame:
    """Trades joined to their OPEN position and to the manager command behind them."""
    trades = pd.DataFrame(read_jsonl(BOOKS / "trades.jsonl"))
    positions = [r for r in read_jsonl(BOOKS / "positions.jsonl") if str(r.get("status", "")).upper() == "OPEN"]
    pos = pd.DataFrame(positions).drop_duplicates(subset=["position_id"], keep="first")

    keep_pos = [
        "position_id", "timeframe", "side", "context_occurrence_timestamp", "context_event_price",
        "entry_price", "stop_loss_price", "take_profit_price", "stop_distance_usd",
        "quantity", "notional_usd", "risk_amount_usd", "equity_at_entry_usd",
        "manager_command_id", "lifecycle_episode_id",
    ]
    pos = pos[[c for c in keep_pos if c in pos.columns]]
    df = trades[["trade_id", "position_id", "net_pnl_usd", "exit_reason", "context_occurrence_timestamp"]].rename(
        columns={"context_occurrence_timestamp": "exit_ts_raw"}
    )
    df["position_id"] = df["position_id"].astype(str)
    pos["position_id"] = pos["position_id"].astype(str)
    df = df.merge(pos, on="position_id", how="inner", validate="one_to_one")

    cmds = pd.read_parquet(MANAGER_COMMANDS)
    cmds = cmds.loc[cmds["intent"].isin(["OPEN_LONG", "OPEN_SHORT"])].copy()
    cmd_cols = [
        "command_id", "evaluation_timestamp", "source_bar_open", "source_bar_close",
        "source_state_timestamp", "source_event_timestamp", "timeframe_direction",
        "requested_risk_usd", "approved_risk_usd", "portfolio_open_risk_usd",
        "stop_reference", "invalidation_reference", "context_origin_price",
        "context_started_at", "cross_timeframe_metadata", "canonical_episode_id",
        "timeframe_episode_id",
    ]
    cmds = cmds[[c for c in cmd_cols if c in cmds.columns]]
    df = df.merge(cmds, left_on="manager_command_id", right_on="command_id", how="left")

    df["entry_ts"] = ts(df["context_occurrence_timestamp"])
    df["exit_ts"] = ts(df["exit_ts_raw"])
    df["cutoff"] = ts(df["source_bar_close"])
    df["bar_open"] = ts(df["source_bar_open"])
    df["context_started_at_ts"] = ts(df["context_started_at"])

    for c in (
        "net_pnl_usd", "risk_amount_usd", "entry_price", "stop_loss_price", "take_profit_price",
        "stop_distance_usd", "quantity", "notional_usd", "equity_at_entry_usd",
        "context_event_price", "requested_risk_usd", "approved_risk_usd",
        "portfolio_open_risk_usd", "stop_reference", "context_origin_price",
    ):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["R"] = df["net_pnl_usd"] / df["risk_amount_usd"].replace(0, np.nan)
    df["win"] = (df["net_pnl_usd"] > 0).astype(int)
    df["segment"] = assign_segment(df.assign(context_occurrence_timestamp=df["entry_ts"]))
    return df


def parse_cross_tf(df: pd.DataFrame) -> pd.DataFrame:
    """Explode cross_timeframe_metadata into per-timeframe state plus agreement counts.

    This is the only place the wider regime is visible without re-deriving it, and it
    is exactly what the manager itself saw.
    """
    recs: list[dict[str, Any]] = []
    for raw, own_tf, own_dir in zip(
        df["cross_timeframe_metadata"], df["timeframe"], df["timeframe_direction"], strict=True
    ):
        try:
            meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            meta = {}
        row: dict[str, Any] = {}
        agree = disagree = neutral = 0
        n_active = 0
        for tf in TIMEFRAMES:
            slot = meta.get(tf) or {}
            d = slot.get("direction")
            row[f"xtf_{tf}_direction"] = d
            row[f"xtf_{tf}_availability"] = slot.get("availability")
            row[f"xtf_{tf}_phase"] = slot.get("lifecycle_phase")
            if str(slot.get("lifecycle_phase") or "") == "ACTIVE":
                n_active += 1
            if tf == own_tf:
                continue
            if d in (None, "NON_DIRECTIONAL"):
                neutral += 1
            elif d == own_dir:
                agree += 1
            else:
                disagree += 1
        row["xtf_agree_n"] = agree
        row["xtf_disagree_n"] = disagree
        row["xtf_neutral_n"] = neutral
        row["xtf_active_n"] = n_active
        row["xtf_net_agreement"] = agree - disagree
        recs.append(row)
    return pd.DataFrame(recs, index=df.index)


def asof_join(
    left: pd.DataFrame,
    plane: pd.DataFrame,
    *,
    cols: tuple[str, ...],
    prefix: str,
    ts_col: str,
    bar_minutes: int,
) -> pd.DataFrame:
    """As-of join restricted to bars that had FULLY CLOSED by the causal cutoff.

    Every plane in the packs is keyed on the bar's OPEN timestamp: a row stamped T
    describes the bar spanning [T, T+bar_minutes). Joining on `timestamp <= cutoff`
    therefore matches a bar that is still forming at the decision, handing the model
    the price it is about to trade into — verified on this book as a one-bar leak on
    100% of rows, worth a fake AUC of 0.77.

    A bar is knowable at the cutoff only once T + bar_minutes <= cutoff, so the join
    key is shifted back by one bar length. For a plane on the trade's own timeframe
    this selects the bar closing exactly at the cutoff (the one the manager evaluated);
    for a higher timeframe it selects the last bar fully closed before it.
    """
    available = [c for c in cols if c in plane.columns]
    if not available:
        return left
    right = plane[[ts_col, *available]].copy()
    right[ts_col] = pd.to_datetime(right[ts_col], utc=True, errors="coerce").astype("datetime64[ns, UTC]")
    right = right.dropna(subset=[ts_col]).sort_values(ts_col)
    right = right.rename(columns={c: f"{prefix}{c}" for c in available})
    right[f"{prefix}row_ts"] = right[ts_col]

    out = left.sort_values("cutoff").copy()
    out["_key"] = out["cutoff"] - pd.Timedelta(minutes=bar_minutes)
    out = pd.merge_asof(
        out,
        right,
        left_on="_key",
        right_on=ts_col,
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns=["_key"])
    if ts_col in out.columns and ts_col != "cutoff":
        out = out.drop(columns=[ts_col])
    # Age measured to the matched bar's CLOSE, which is when it became knowable.
    out[f"{prefix}age_min"] = (
        out["cutoff"] - (out[f"{prefix}row_ts"] + pd.Timedelta(minutes=bar_minutes))
    ).dt.total_seconds() / 60.0
    return out


def build_matrix() -> pd.DataFrame:
    entries = build_entries()
    entries = pd.concat([entries, parse_cross_tf(entries)], axis=1)

    # Cache planes once; the packs are large and each is read for several timeframes.
    cache: dict[tuple[str, str], pd.DataFrame] = {}

    def plane(tf: str, name: str) -> pd.DataFrame:
        key = (tf, name)
        if key not in cache:
            path = PACKS[tf] / "context" / f"{name}.parquet"
            if not path.exists() and name == "volume_response_state":
                path = PACKS[tf] / "context" / "volume_response_state_proxy.parquet"
            cache[key] = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        return cache[key]

    parts: list[pd.DataFrame] = []
    bar_len: dict[str, int] = {}  # prefix -> bar minutes, for the causality audit
    for tf, group in entries.groupby("timeframe", sort=False):
        block = group.copy()
        own_min = TF_MINUTES[str(tf)]
        for name, cols in OWN_PLANES.items():
            p = plane(str(tf), name)
            if p.empty:
                continue
            pre = f"own_{name[:14]}_"
            bar_len[pre] = own_min
            block = asof_join(block, p, cols=cols, prefix=pre, ts_col="timestamp", bar_minutes=own_min)
        feed = PACKS[str(tf)] / f"feed_{str(tf).lower()}.parquet"
        if feed.exists():
            f = pd.read_parquet(feed)
            bar_len["feed_"] = own_min
            block = asof_join(
                block, f, cols=("open", "high", "low", "close", "volume", "delta", "number_of_trades"),
                prefix="feed_", ts_col="timestamp", bar_minutes=own_min,
            )
        for other in TIMEFRAMES:
            if other == tf:
                continue
            for name, cols in CROSS_PLANES.items():
                p = plane(other, name)
                if p.empty:
                    continue
                pre = f"x{other}_{name[:10]}_"
                bar_len[pre] = TF_MINUTES[other]
                block = asof_join(
                    block, p, cols=cols, prefix=pre, ts_col="timestamp", bar_minutes=TF_MINUTES[other]
                )
        parts.append(block)
    build_matrix.bar_len = bar_len  # type: ignore[attr-defined]

    m = pd.concat(parts, ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    # Derived, all from entry-time quantities only.
    m["f_stop_distance_bps"] = (m["stop_distance_usd"] / m["entry_price"] * 10_000).astype(float)
    m["f_rr_ratio"] = (
        (m["take_profit_price"] - m["entry_price"]).abs() / (m["entry_price"] - m["stop_loss_price"]).abs()
    )
    m["f_entry_vs_context_bps"] = (
        (m["entry_price"] - m["context_event_price"]) / m["context_event_price"] * 10_000
    )
    m["f_is_long"] = (m["side"].astype(str).str.upper() == "LONG").astype(int)
    m["f_portfolio_open_risk_usd"] = m["portfolio_open_risk_usd"]
    m["f_risk_approval_ratio"] = m["approved_risk_usd"] / m["requested_risk_usd"].replace(0, np.nan)
    m["f_context_age_min"] = (m["cutoff"] - m["context_started_at_ts"]).dt.total_seconds() / 60.0
    m["f_context_age_bars"] = m["f_context_age_min"] / m["timeframe"].map(TF_MINUTES)
    m["f_hour_utc"] = m["entry_ts"].dt.hour
    m["f_dow"] = m["entry_ts"].dt.dayofweek
    if "feed_close" in m.columns:
        for c in ("feed_high", "feed_low", "feed_open"):
            if c in m.columns:
                m[f"f_{c[5:]}_vs_close_bps"] = (m[c] - m["feed_close"]) / m["feed_close"] * 10_000
        m["f_entry_vs_bar_close_bps"] = (m["entry_price"] - m["feed_close"]) / m["feed_close"] * 10_000
    if "own_candle_struct_spread" in m.columns and "feed_close" in m.columns:
        m["f_bar_range_bps"] = m["own_candle_struct_spread"] / m["feed_close"] * 10_000
    return m


def audit(m: pd.DataFrame) -> dict[str, Any]:
    """Every joined bar must have CLOSED at or before the causal cutoff.

    Testing the bar's OPEN against the cutoff is the weak check that let the forming-bar
    leak through, so the assertion is on open + bar length. The length is row-dependent:
    an `own_`/`feed_` column carries the trade's own timeframe, while an `xH4_` column is
    always a 4-hour bar regardless of which timeframe the trade fired on.
    """
    own_minutes = m["timeframe"].map(TF_MINUTES).astype("float64")
    violations: dict[str, int] = {}
    for col in [c for c in m.columns if c.endswith("_row_ts")]:
        if col.startswith(("own_", "feed_")):
            minutes = own_minutes
        elif col.startswith("x") and col.split("_")[0][1:] in TF_MINUTES:
            minutes = pd.Series(TF_MINUTES[col.split("_")[0][1:]], index=m.index, dtype="float64")
        else:
            continue
        close = m[col] + pd.to_timedelta(minutes, unit="m")
        bad = int((close > m["cutoff"]).sum())
        if bad:
            violations[col] = bad
    ages = {c: float(m[c].median()) for c in m.columns if c.endswith("_age_min")}
    return {
        "rule": "joined bar must satisfy bar_open + bar_length <= source_bar_close",
        "lookahead_violations": violations,
        "lookahead_ok": not violations,
        "cutoff_before_entry_ok": bool((m["cutoff"] <= m["entry_ts"]).all()),
        "median_bar_close_age_min": dict(sorted(ages.items(), key=lambda kv: kv[1], reverse=True)[:8]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    m = build_matrix()
    a = audit(m)

    feature_cols = [
        c
        for c in m.columns
        if (c.startswith(("own_", "x", "feed_", "f_")) and not c.endswith("_row_ts"))
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(args.out, index=False)

    nn = m[feature_cols].notna().mean()
    dense = [c for c in feature_cols if nn[c] >= 0.90]
    sparse = [c for c in feature_cols if nn[c] < 0.50]
    report = {
        "stage": "HYBRID_TRADE_FEATURE_MATRIX",
        "rows": int(len(m)),
        "feature_columns": len(feature_cols),
        "dense_features_ge_90pct": len(dense),
        "sparse_features_lt_50pct": len(sparse),
        "segments": {k: int(v) for k, v in m["segment"].value_counts().items()},
        "label": {
            "win_rate_pct": round(float(m["win"].mean()) * 100, 2),
            "expectancy_r": round(float(m["R"].mean()), 4),
            "r_std": round(float(m["R"].std()), 4),
        },
        "causality_audit": a,
        "output": str(args.out),
    }
    (args.out.parent / "trade_feature_matrix_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print("\nsparse (<50% populated), candidates to drop:")
    for c in sparse[:25]:
        print(f"   {c:<52}{nn[c]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
