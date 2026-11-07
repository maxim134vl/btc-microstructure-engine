#!/usr/bin/env python3
"""Read-only audit: live market context quality after auction/lifecycle fixes.

Does NOT rewrite any model / cognition / visual / runtime / lifecycle artifacts.
Does NOT change auction confirmation, lifecycle persistence, or execution behavior.

Purpose:
  - Measure live context quality across analysis windows
  - Track pipeline cycle progress toward the 50,000-cycle decision threshold
  - Produce a preliminary verdict; final decision requires a rerun at 50k+ cycles
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
AUCTION_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
COGNITIVE_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
FINAL_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
LIFECYCLE_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
EPISODES_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
RUNTIME_LOG = ROOT / "logs" / "runtime_stack" / "runtime.log"
SHADOW_STATUS = ROOT / "data" / "cognition" / "market_context_shadow_chain_status.json"
VISUAL_LATEST = (
    ROOT
    / "apps"
    / "context_visualizer"
    / "public"
    / "data"
    / "lifecycle_latest.json"
)
REPORT_PATH = ROOT / "docs" / "LIVE_CONTEXT_QUALITY_AUDIT.md"

CUTOVER_10JUL = pd.Timestamp("2026-07-10T00:00:00Z")
# Live segment after the lifecycle persistence fix was deployed / rebuilt into memory.
POST_PERSISTENCE_FIX = pd.Timestamp("2026-07-14T00:00:00Z")
CYCLE_DECISION_THRESHOLD = 50_000
MIN_USEFUL_ROWS = 20

DIRECTIONAL = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
PIPELINE_CYCLE_RE = re.compile(r"PIPELINE CYCLE:\s*(\d+)")


def _clean(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    for col in ("timestamp", "start_time", "end_time"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce")
    return frame


def value_counts_dict(series: pd.Series | None) -> dict[str, int]:
    if series is None or len(series) == 0:
        return {}
    return {str(k): int(v) for k, v in series.map(lambda x: _clean(x)).value_counts().items()}


def duration_buckets(bars_counts: list[int]) -> dict[str, int]:
    buckets = {"1": 0, "2": 0, "3-4": 0, "5-8": 0, ">8": 0}
    for n in bars_counts:
        if n <= 1:
            buckets["1"] += 1
        elif n == 2:
            buckets["2"] += 1
        elif n <= 4:
            buckets["3-4"] += 1
        elif n <= 8:
            buckets["5-8"] += 1
        else:
            buckets[">8"] += 1
    return buckets


def pct(numer: float, denom: float) -> float | None:
    if denom <= 0:
        return None
    return round(100.0 * float(numer) / float(denom), 2)


def parse_runtime_cycles(log_path: Path = RUNTIME_LOG) -> dict[str, Any]:
    """Parse PIPELINE CYCLE lines from runtime.log (read-only, streaming)."""
    empty = {
        "total_runtime_log_cycles": 0,
        "current_run_cycle": 0,
        "runtime_segments": 0,
        "latest_5_cycles": [],
        "first_cycle_seen": None,
        "last_cycle_seen": None,
        "max_cycle_seen": 0,
        "cycles_still_increasing": None,
        "log_mtime_utc": None,
        "log_exists": False,
        "log_size_bytes": 0,
    }
    if not log_path.exists():
        return empty

    stat = log_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    cycles: list[int] = []
    segments = 0
    prev: int | None = None

    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = PIPELINE_CYCLE_RE.search(line)
            if not match:
                continue
            n = int(match.group(1))
            cycles.append(n)
            if prev is None or n < prev:
                segments += 1
            prev = n

    if not cycles:
        empty.update(
            {
                "log_exists": True,
                "log_size_bytes": int(stat.st_size),
                "log_mtime_utc": mtime.isoformat().replace("+00:00", "Z"),
            }
        )
        return empty

    latest_5 = cycles[-5:]
    current = cycles[-1]
    # Heuristic: if log was modified recently and last cycle > previous, still increasing.
    age_minutes = (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 60.0
    increasing = None
    if len(cycles) >= 2:
        increasing = cycles[-1] > cycles[-2] or age_minutes <= 15.0

    return {
        "total_runtime_log_cycles": len(cycles),
        "current_run_cycle": current,
        "runtime_segments": segments,
        "latest_5_cycles": latest_5,
        "first_cycle_seen": cycles[0],
        "last_cycle_seen": cycles[-1],
        "max_cycle_seen": max(cycles),
        "cycles_still_increasing": increasing,
        "log_mtime_utc": mtime.isoformat().replace("+00:00", "Z"),
        "log_age_minutes": round(age_minutes, 1),
        "log_exists": True,
        "log_size_bytes": int(stat.st_size),
        "threshold": CYCLE_DECISION_THRESHOLD,
        "cycles_to_threshold": max(0, CYCLE_DECISION_THRESHOLD - len(cycles)),
        "threshold_reached": len(cycles) >= CYCLE_DECISION_THRESHOLD,
    }


def analysis_windows(now: pd.Timestamp | None = None) -> list[tuple[str, pd.Timestamp | None, pd.Timestamp | None]]:
    """Return (name, start_inclusive, end_exclusive) windows."""
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    return [
        ("FULL", None, None),
        ("SINCE_10JUL", CUTOVER_10JUL, None),
        ("LAST_7D", now - pd.Timedelta(days=7), None),
        ("LAST_48H", now - pd.Timedelta(hours=48), None),
        ("POST_PERSISTENCE_FIX", POST_PERSISTENCE_FIX, None),
    ]


def slice_window(
    frame: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    ts_col: str = "timestamp",
) -> pd.DataFrame:
    if frame is None or len(frame) == 0 or ts_col not in frame.columns:
        return pd.DataFrame()
    work = frame
    if start is not None:
        work = work.loc[work[ts_col] >= start]
    if end is not None:
        work = work.loc[work[ts_col] < end]
    return work.copy()


def confirmation_rate(status_series: pd.Series) -> float | None:
    if status_series is None or len(status_series) == 0:
        return None
    cleaned = status_series.map(lambda x: _clean(x).upper())
    confirmed = int((cleaned == "CONFIRMED").sum())
    return pct(confirmed, len(cleaned))


def raw_to_active_conversion(lifecycle: pd.DataFrame) -> dict[str, Any]:
    if lifecycle is None or len(lifecycle) == 0:
        return {
            "raw_directional": 0,
            "raw_active_directional": 0,
            "active_directional": 0,
            "raw_to_active_pct": None,
            "raw_active_but_final_observe": 0,
        }
    raw = lifecycle["raw_market_context"].map(lambda x: _clean(x)) if "raw_market_context" in lifecycle.columns else pd.Series(dtype=str)
    raw_status = (
        lifecycle["raw_context_status"].map(lambda x: _clean(x).upper())
        if "raw_context_status" in lifecycle.columns
        else pd.Series([""] * len(lifecycle))
    )
    active = (
        lifecycle["active_market_context"].map(lambda x: _clean(x))
        if "active_market_context" in lifecycle.columns
        else pd.Series([""] * len(lifecycle))
    )
    raw_dir = raw.isin(DIRECTIONAL)
    raw_active_dir = raw_dir & (raw_status == "ACTIVE")
    active_dir = active.isin(DIRECTIONAL)
    raw_active_observe = int((raw_active_dir & (active == "OBSERVE")).sum())
    raw_dir_n = int(raw_dir.sum())
    raw_active_n = int(raw_active_dir.sum())
    return {
        "raw_directional": raw_dir_n,
        "raw_active_directional": raw_active_n,
        "active_directional": int(active_dir.sum()),
        "raw_to_active_pct": pct(raw_active_n, raw_dir_n) if raw_dir_n else None,
        "active_of_raw_active_pct": pct(int((raw_active_dir & active_dir).sum()), raw_active_n)
        if raw_active_n
        else None,
        "raw_active_but_final_observe": raw_active_observe,
    }


def episode_quality(episodes: pd.DataFrame) -> dict[str, Any]:
    if episodes is None or len(episodes) == 0:
        return {
            "directional_episodes": 0,
            "observe_episodes": 0,
            "duration_buckets": duration_buckets([]),
            "avg_bars": None,
            "median_bars": None,
            "max_bars": None,
            "one_bar_pct": None,
            "end_reason_counts": {},
        }
    ctx_col = "active_market_context" if "active_market_context" in episodes.columns else "context"
    ctx = episodes[ctx_col].map(lambda x: _clean(x))
    directional = episodes.loc[ctx.isin(DIRECTIONAL)].copy()
    observe_n = int((ctx == "OBSERVE").sum())
    bars = [
        int(v)
        for v in directional.get("bars_count", pd.Series(dtype=float)).fillna(0).tolist()
    ]
    end_reasons = value_counts_dict(directional["end_reason"]) if "end_reason" in directional.columns else {}
    one_bar = sum(1 for b in bars if b <= 1)
    return {
        "directional_episodes": len(directional),
        "observe_episodes": observe_n,
        "duration_buckets": duration_buckets(bars),
        "avg_bars": round(float(pd.Series(bars).mean()), 3) if bars else None,
        "median_bars": float(pd.Series(bars).median()) if bars else None,
        "max_bars": int(max(bars)) if bars else None,
        "one_bar_count": one_bar,
        "one_bar_pct": pct(one_bar, len(bars)) if bars else None,
        "end_reason_counts": end_reasons,
    }


def termination_aggressiveness(episodes: pd.DataFrame) -> dict[str, Any]:
    """Lightweight end-reason classification (no price rewrite; diagnostic only)."""
    if episodes is None or len(episodes) == 0:
        return {
            "neutralization_ends": 0,
            "thesis_rejection_ends": 0,
            "opposite_replacement_ends": 0,
            "short_neutralization_ends": 0,
            "short_thesis_ends": 0,
        }
    ctx_col = "active_market_context" if "active_market_context" in episodes.columns else "context"
    ctx = episodes[ctx_col].map(lambda x: _clean(x))
    directional = episodes.loc[ctx.isin(DIRECTIONAL)].copy()
    if len(directional) == 0 or "end_reason" not in directional.columns:
        return {
            "neutralization_ends": 0,
            "thesis_rejection_ends": 0,
            "opposite_replacement_ends": 0,
            "short_neutralization_ends": 0,
            "short_thesis_ends": 0,
        }
    reasons = directional["end_reason"].map(lambda x: _clean(x).lower())
    bars = directional["bars_count"].fillna(0).astype(int) if "bars_count" in directional.columns else pd.Series([0] * len(directional))
    neut = reasons.str.contains("neutralization")
    thesis = reasons.str.contains("thesis rejection")
    opposite = reasons.str.contains("opposite")
    return {
        "neutralization_ends": int(neut.sum()),
        "thesis_rejection_ends": int(thesis.sum()),
        "opposite_replacement_ends": int(opposite.sum()),
        "short_neutralization_ends": int((neut & (bars <= 2)).sum()),
        "short_thesis_ends": int((thesis & (bars <= 2)).sum()),
    }


def lifecycle_composition(lifecycle: pd.DataFrame) -> dict[str, Any]:
    if lifecycle is None or len(lifecycle) == 0:
        return {
            "rows": 0,
            "too_few_rows": True,
            "active_counts": {},
            "lifecycle_state_counts": {},
            "invalidation_type_counts": {},
            "directional_share_pct": None,
            "observe_share_pct": None,
            "challenged_share_pct": None,
            "candidate_share_pct": None,
            "action_allowed_any": None,
            "shadow_only_all": None,
        }
    active = lifecycle["active_market_context"].map(lambda x: _clean(x)) if "active_market_context" in lifecycle.columns else pd.Series(dtype=str)
    life = lifecycle["lifecycle_state"].map(lambda x: _clean(x)) if "lifecycle_state" in lifecycle.columns else pd.Series(dtype=str)
    inv = lifecycle["invalidation_type"].map(lambda x: _clean(x)) if "invalidation_type" in lifecycle.columns else pd.Series(dtype=str)
    n = len(lifecycle)
    directional_n = int(active.isin(DIRECTIONAL).sum())
    observe_n = int((active == "OBSERVE").sum())
    challenged_n = int((life == "CHALLENGED").sum())
    candidate_n = int((life == "CANDIDATE").sum())
    action_any = None
    shadow_all = None
    if "action_allowed" in lifecycle.columns:
        action_any = bool(lifecycle["action_allowed"].fillna(False).astype(bool).any())
    if "shadow_only" in lifecycle.columns:
        shadow_all = bool(lifecycle["shadow_only"].fillna(False).astype(bool).all())
    hold_markers = 0
    if "transition_reason" in lifecycle.columns:
        hold_markers = int(
            lifecycle["transition_reason"]
            .astype(str)
            .str.contains("hold protection", case=False, na=False)
            .sum()
        )
    return {
        "rows": n,
        "too_few_rows": n < MIN_USEFUL_ROWS,
        "start": str(lifecycle["timestamp"].min()) if "timestamp" in lifecycle.columns else None,
        "end": str(lifecycle["timestamp"].max()) if "timestamp" in lifecycle.columns else None,
        "active_counts": value_counts_dict(active),
        "lifecycle_state_counts": value_counts_dict(life),
        "invalidation_type_counts": value_counts_dict(inv),
        "directional_share_pct": pct(directional_n, n),
        "observe_share_pct": pct(observe_n, n),
        "challenged_share_pct": pct(challenged_n, n),
        "candidate_share_pct": pct(candidate_n, n),
        "hold_protection_transition_rows": hold_markers,
        "action_allowed_any": action_any,
        "shadow_only_all": shadow_all,
    }


def auction_quality(auction: pd.DataFrame) -> dict[str, Any]:
    if auction is None or len(auction) == 0:
        return {
            "rows": 0,
            "episode_counts": {},
            "status_counts": {},
            "confirmed_pct": None,
            "developing_pct": None,
            "acceptance_confirmed_pct": None,
        }
    episode = auction["auction_episode"].map(lambda x: _clean(x)) if "auction_episode" in auction.columns else pd.Series(dtype=str)
    status_col = "episode_status" if "episode_status" in auction.columns else (
        "auction_episode_status" if "auction_episode_status" in auction.columns else None
    )
    status = auction[status_col].map(lambda x: _clean(x).upper()) if status_col else pd.Series(dtype=str)
    n = len(auction)
    confirmed = int((status == "CONFIRMED").sum()) if len(status) else 0
    developing = int((status == "DEVELOPING").sum()) if len(status) else 0
    acceptance = episode.isin({"ACCEPTANCE_HIGHER", "ACCEPTANCE_LOWER"})
    acc_n = int(acceptance.sum())
    acc_confirmed = int((acceptance & (status == "CONFIRMED")).sum()) if len(status) else 0
    return {
        "rows": n,
        "episode_counts": value_counts_dict(episode),
        "status_counts": value_counts_dict(status),
        "confirmed_pct": pct(confirmed, n) if n else None,
        "developing_pct": pct(developing, n) if n else None,
        "acceptance_rows": acc_n,
        "acceptance_confirmed_pct": pct(acc_confirmed, acc_n) if acc_n else None,
    }


def cognitive_quality(cognitive: pd.DataFrame) -> dict[str, Any]:
    if cognitive is None or len(cognitive) == 0:
        return {"rows": 0, "state_counts": {}, "status_counts": {}, "confirmed_pct": None}
    state = (
        cognitive["cognitive_market_state"].map(lambda x: _clean(x))
        if "cognitive_market_state" in cognitive.columns
        else pd.Series(dtype=str)
    )
    status_col = "state_status" if "state_status" in cognitive.columns else (
        "cognitive_state_status" if "cognitive_state_status" in cognitive.columns else None
    )
    status = cognitive[status_col].map(lambda x: _clean(x).upper()) if status_col else pd.Series(dtype=str)
    n = len(cognitive)
    confirmed = int((status == "CONFIRMED").sum()) if len(status) else 0
    return {
        "rows": n,
        "state_counts": value_counts_dict(state),
        "status_counts": value_counts_dict(status),
        "confirmed_pct": pct(confirmed, n) if n else None,
    }


def window_metrics(
    *,
    name: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    lifecycle: pd.DataFrame,
    episodes: pd.DataFrame,
    auction: pd.DataFrame,
    cognitive: pd.DataFrame,
    final: pd.DataFrame,
) -> dict[str, Any]:
    life_w = slice_window(lifecycle, start, end, "timestamp")
    ep_w = slice_window(episodes, start, end, "start_time")
    auc_w = slice_window(auction, start, end, "timestamp")
    cog_w = slice_window(cognitive, start, end, "timestamp")
    fin_w = slice_window(final, start, end, "timestamp")

    composition = lifecycle_composition(life_w)
    conversion = raw_to_active_conversion(life_w)
    ep_q = episode_quality(ep_w)
    term = termination_aggressiveness(ep_w)
    auc_q = auction_quality(auc_w)
    cog_q = cognitive_quality(cog_w)

    return {
        "window": name,
        "start": str(start) if start is not None else None,
        "end": str(end) if end is not None else None,
        "lifecycle": composition,
        "conversion": conversion,
        "episodes": ep_q,
        "termination": term,
        "auction": auc_q,
        "cognitive": cog_q,
        "final_rows": len(fin_w),
    }


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def decide_verdict(cycles: dict[str, Any], windows: list[dict[str, Any]]) -> dict[str, Any]:
    total = int(cycles.get("total_runtime_log_cycles") or 0)
    threshold = CYCLE_DECISION_THRESHOLD
    post = next((w for w in windows if w["window"] == "POST_PERSISTENCE_FIX"), None)
    since = next((w for w in windows if w["window"] == "SINCE_10JUL"), None)

    notes: list[str] = []
    if total < threshold:
        readiness = "PRELIMINARY"
        notes.append(
            f"total_runtime_log_cycles={total} is below the {threshold} decision threshold; "
            "rerun this audit after 50,000+ cycles before a final quality decision."
        )
    else:
        readiness = "READY_FOR_DECISION"
        notes.append(f"total_runtime_log_cycles={total} meets/exceeds the {threshold} threshold.")

    # Quality signals (preliminary).
    signals: list[str] = []
    focus = post or since
    if focus and not focus["lifecycle"]["too_few_rows"]:
        one_bar = focus["episodes"].get("one_bar_pct")
        raw_obs = focus["conversion"].get("raw_active_but_final_observe")
        short_neut = focus["termination"].get("short_neutralization_ends")
        directional_share = focus["lifecycle"].get("directional_share_pct")
        if raw_obs == 0:
            signals.append("raw ACTIVE → final OBSERVE drops remain 0 (lifecycle not dropping confirmed context)")
        if one_bar is not None and one_bar <= 15:
            signals.append(f"one-bar directional episodes are controlled ({one_bar}%)")
        elif one_bar is not None and one_bar > 25:
            signals.append(f"one-bar directional episodes still elevated ({one_bar}%)")
        if short_neut is not None and short_neut == 0:
            signals.append("no ≤2-bar neutralization endings in focus window")
        elif short_neut:
            signals.append(f"{short_neut} ≤2-bar neutralization endings remain in focus window")
        if directional_share is not None:
            signals.append(f"directional active share={directional_share}%")
        if focus["lifecycle"].get("action_allowed_any") is False:
            signals.append("action_allowed remains False")
        if focus["lifecycle"].get("shadow_only_all") is True:
            signals.append("shadow_only remains True")
    else:
        signals.append("focus window has too few rows for quality judgment")

    quality_label = "INCONCLUSIVE"
    if focus and not focus["lifecycle"]["too_few_rows"]:
        one_bar = focus["episodes"].get("one_bar_pct") or 100
        raw_obs = focus["conversion"].get("raw_active_but_final_observe") or 0
        short_neut = focus["termination"].get("short_neutralization_ends") or 0
        if raw_obs == 0 and one_bar <= 15 and short_neut <= 2:
            quality_label = "IMPROVED_PRELIMINARY"
        elif raw_obs == 0 and one_bar <= 30:
            quality_label = "MIXED_PRELIMINARY"
        else:
            quality_label = "ATTENTION_PRELIMINARY"

    recommendation = (
        "RERUN_AFTER_50K_CYCLES"
        if total < threshold
        else "PROCEED_TO_FINAL_QUALITY_REVIEW"
    )

    return {
        "readiness": readiness,
        "quality_label": quality_label,
        "recommendation": recommendation,
        "notes": notes,
        "signals": signals,
        "focus_window": focus["window"] if focus else None,
    }


def render_report(payload: dict[str, Any]) -> str:
    cycles = payload["runtime_cycles"]
    verdict = payload["verdict"]
    lines: list[str] = [
        "# Live Context Quality Audit",
        "",
        "Read-only analytics. No model / auction / lifecycle / visual / runtime / execution changes.",
        "",
        f"**Generated:** `{payload['generated_at']}`  ",
        f"**Decision threshold:** `{CYCLE_DECISION_THRESHOLD}` pipeline cycles  ",
        f"**Readiness:** `{verdict['readiness']}`  ",
        f"**Quality label:** `{verdict['quality_label']}`  ",
        f"**Recommendation:** `{verdict['recommendation']}`  ",
        "",
        "## 1. Runtime cycle evidence",
        "",
        "```text",
        f"total_runtime_log_cycles: {cycles.get('total_runtime_log_cycles')}",
        f"current_run_cycle: {cycles.get('current_run_cycle')}",
        f"runtime_segments: {cycles.get('runtime_segments')}",
        f"latest_5_cycles: {cycles.get('latest_5_cycles')}",
        f"max_cycle_seen: {cycles.get('max_cycle_seen')}",
        f"cycles_still_increasing: {cycles.get('cycles_still_increasing')}",
        f"log_mtime_utc: {cycles.get('log_mtime_utc')}",
        f"log_age_minutes: {cycles.get('log_age_minutes')}",
        f"cycles_to_threshold: {cycles.get('cycles_to_threshold')}",
        f"threshold_reached: {cycles.get('threshold_reached')}",
        "```",
        "",
        "## 2. Analysis windows",
        "",
        "| window | rows | start | end | too_few | directional% | observe% | one_bar% | avg bars | raw→active% | rawACTIVE→OBSERVE |",
        "|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for w in payload["windows"]:
        life = w["lifecycle"]
        ep = w["episodes"]
        conv = w["conversion"]
        lines.append(
            "| `{win}` | {rows} | {start} | {end} | {few} | {d} | {o} | {ob} | {avg} | {r2a} | {rao} |".format(
                win=w["window"],
                rows=life.get("rows"),
                start=(life.get("start") or w.get("start") or "—")[:19],
                end=(life.get("end") or "latest")[:19],
                few="yes" if life.get("too_few_rows") else "no",
                d=life.get("directional_share_pct"),
                o=life.get("observe_share_pct"),
                ob=ep.get("one_bar_pct"),
                avg=ep.get("avg_bars"),
                r2a=conv.get("raw_to_active_pct"),
                rao=conv.get("raw_active_but_final_observe"),
            )
        )

    lines.extend(["", "## 3. Per-window detail", ""])
    for w in payload["windows"]:
        life = w["lifecycle"]
        ep = w["episodes"]
        term = w["termination"]
        auc = w["auction"]
        cog = w["cognitive"]
        conv = w["conversion"]
        lines.append(f"### `{w['window']}`")
        lines.append("")
        if life.get("too_few_rows"):
            lines.append(f"_Too few rows ({life.get('rows')}) for a stable quality judgment (min={MIN_USEFUL_ROWS})._")
            lines.append("")
        lines.append("**Lifecycle composition**")
        lines.append("")
        lines.append("```text")
        lines.append(f"rows: {life.get('rows')}")
        lines.append(f"active_counts: {life.get('active_counts')}")
        lines.append(f"lifecycle_state_counts: {life.get('lifecycle_state_counts')}")
        lines.append(f"invalidation_type_counts: {life.get('invalidation_type_counts')}")
        lines.append(f"challenged_share_pct: {life.get('challenged_share_pct')}")
        lines.append(f"candidate_share_pct: {life.get('candidate_share_pct')}")
        lines.append(f"hold_protection_transition_rows: {life.get('hold_protection_transition_rows')}")
        lines.append(f"action_allowed_any: {life.get('action_allowed_any')}")
        lines.append(f"shadow_only_all: {life.get('shadow_only_all')}")
        lines.append("```")
        lines.append("")
        lines.append("**Confirmation / conversion**")
        lines.append("")
        lines.append("```text")
        lines.append(f"raw_directional: {conv.get('raw_directional')}")
        lines.append(f"raw_active_directional: {conv.get('raw_active_directional')}")
        lines.append(f"active_directional: {conv.get('active_directional')}")
        lines.append(f"raw_to_active_pct: {conv.get('raw_to_active_pct')}")
        lines.append(f"raw_active_but_final_observe: {conv.get('raw_active_but_final_observe')}")
        lines.append(f"auction_confirmed_pct: {auc.get('confirmed_pct')}")
        lines.append(f"auction_developing_pct: {auc.get('developing_pct')}")
        lines.append(f"acceptance_confirmed_pct: {auc.get('acceptance_confirmed_pct')}")
        lines.append(f"cognitive_confirmed_pct: {cog.get('confirmed_pct')}")
        lines.append("```")
        lines.append("")
        lines.append("**Directional episode duration**")
        lines.append("")
        lines.append("```text")
        lines.append(f"directional_episodes: {ep.get('directional_episodes')}")
        lines.append(f"duration_buckets: {ep.get('duration_buckets')}")
        lines.append(f"avg_bars: {ep.get('avg_bars')}")
        lines.append(f"median_bars: {ep.get('median_bars')}")
        lines.append(f"max_bars: {ep.get('max_bars')}")
        lines.append(f"one_bar_count: {ep.get('one_bar_count')}")
        lines.append(f"one_bar_pct: {ep.get('one_bar_pct')}")
        lines.append("```")
        lines.append("")
        lines.append("**Termination aggressiveness**")
        lines.append("")
        lines.append("```text")
        lines.append(f"neutralization_ends: {term.get('neutralization_ends')}")
        lines.append(f"thesis_rejection_ends: {term.get('thesis_rejection_ends')}")
        lines.append(f"opposite_replacement_ends: {term.get('opposite_replacement_ends')}")
        lines.append(f"short_neutralization_ends(<=2 bars): {term.get('short_neutralization_ends')}")
        lines.append(f"short_thesis_ends(<=2 bars): {term.get('short_thesis_ends')}")
        lines.append(f"top_end_reasons: {dict(list(ep.get('end_reason_counts', {}).items())[:8])}")
        lines.append("```")
        lines.append("")

    lines.extend(
        [
            "## 4. Optional status snapshots",
            "",
            "```text",
            f"shadow_chain_status: {payload.get('shadow_status')}",
            f"visual_latest: {payload.get('visual_latest')}",
            "```",
            "",
            "## 5. Verdict",
            "",
            f"- **Readiness:** `{verdict['readiness']}`",
            f"- **Quality label:** `{verdict['quality_label']}`",
            f"- **Recommendation:** `{verdict['recommendation']}`",
            f"- **Focus window:** `{verdict.get('focus_window')}`",
            "",
            "### Notes",
            "",
        ]
    )
    for note in verdict.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(["", "### Signals", ""])
    for signal in verdict.get("signals", []):
        lines.append(f"- {signal}")
    lines.extend(
        [
            "",
            "## 6. Confirmation of audit scope",
            "",
            "- model logic unchanged",
            "- auction confirmation logic unchanged",
            "- lifecycle logic unchanged",
            "- visualization unchanged",
            "- runtime/feed/execution/dashboard unchanged",
            "- `action_allowed` / `shadow_only` semantics not modified",
            "",
            "This report is analytics-only. Re-run after `total_runtime_log_cycles >= 50000`",
            "for the final live context quality decision.",
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(*, write_report: bool = True) -> dict[str, Any]:
    now = pd.Timestamp.now(tz="UTC")
    cycles = parse_runtime_cycles(RUNTIME_LOG)

    lifecycle = load_parquet(LIFECYCLE_PATH)
    episodes = load_parquet(EPISODES_PATH)
    auction = load_parquet(AUCTION_PATH)
    cognitive = load_parquet(COGNITIVE_PATH)
    final = load_parquet(FINAL_PATH)
    live = load_parquet(LIVE_FEED)

    windows = [
        window_metrics(
            name=name,
            start=start,
            end=end,
            lifecycle=lifecycle,
            episodes=episodes,
            auction=auction,
            cognitive=cognitive,
            final=final,
        )
        for name, start, end in analysis_windows(now)
    ]
    verdict = decide_verdict(cycles, windows)

    shadow = load_optional_json(SHADOW_STATUS)
    visual = load_optional_json(VISUAL_LATEST)
    shadow_summary = None
    if isinstance(shadow, dict):
        shadow_summary = {
            k: shadow.get(k)
            for k in ("chain_status", "status", "latest_active_market_context", "latest_lifecycle_state")
            if k in shadow
        } or {k: shadow[k] for k in list(shadow)[:6]}
    visual_summary = None
    if isinstance(visual, dict):
        visual_summary = {
            k: visual.get(k)
            for k in (
                "timestamp",
                "active_market_context",
                "lifecycle_state",
                "active_context_age_bars",
                "shadow_only",
                "action_allowed",
                "status_line",
            )
            if k in visual
        }

    payload = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "runtime_cycles": cycles,
        "artifact_rows": {
            "live_market_feed": len(live),
            "auction_episode_memory": len(auction),
            "cognitive_market_state_memory": len(cognitive),
            "final_market_context_memory": len(final),
            "market_context_lifecycle_memory": len(lifecycle),
            "market_context_lifecycle_episodes": len(episodes),
        },
        "windows": windows,
        "verdict": verdict,
        "shadow_status": shadow_summary,
        "visual_latest": visual_summary,
        "cutovers": {
            "since_10jul": str(CUTOVER_10JUL),
            "post_persistence_fix": str(POST_PERSISTENCE_FIX),
            "cycle_decision_threshold": CYCLE_DECISION_THRESHOLD,
        },
        "read_only": True,
    }

    if write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
        payload["report_path"] = str(REPORT_PATH)

    return payload


def print_summary(payload: dict[str, Any]) -> None:
    cycles = payload["runtime_cycles"]
    verdict = payload["verdict"]
    print("======== LIVE CONTEXT QUALITY AUDIT (read-only) ========")
    print(f"total_runtime_log_cycles: {cycles.get('total_runtime_log_cycles')}")
    print(f"current_run_cycle: {cycles.get('current_run_cycle')}")
    print(f"runtime_segments: {cycles.get('runtime_segments')}")
    print(f"latest_5_cycles: {cycles.get('latest_5_cycles')}")
    print(f"cycles_to_threshold: {cycles.get('cycles_to_threshold')}")
    print(f"threshold_reached: {cycles.get('threshold_reached')}")
    print("--- windows ---")
    for w in payload["windows"]:
        life = w["lifecycle"]
        ep = w["episodes"]
        flag = " TOO_FEW_ROWS" if life.get("too_few_rows") else ""
        print(
            f"  {w['window']}: rows={life.get('rows')} "
            f"directional%={life.get('directional_share_pct')} "
            f"one_bar%={ep.get('one_bar_pct')} "
            f"avg_bars={ep.get('avg_bars')} "
            f"rawACTIVE→OBSERVE={w['conversion'].get('raw_active_but_final_observe')}{flag}"
        )
    print("--- verdict ---")
    print(f"readiness: {verdict['readiness']}")
    print(f"quality_label: {verdict['quality_label']}")
    print(f"recommendation: {verdict['recommendation']}")
    for note in verdict.get("notes", []):
        print(f"  note: {note}")
    for signal in verdict.get("signals", []):
        print(f"  signal: {signal}")
    if payload.get("report_path"):
        print(f"report: {payload['report_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only live context quality audit")
    parser.add_argument("--no-report", action="store_true", help="Skip writing the markdown report")
    parser.add_argument("--json", action="store_true", help="Also print full JSON payload")
    args = parser.parse_args(argv)

    payload = run_audit(write_report=not args.no_report)
    print_summary(payload)
    if args.json:
        # Avoid dumping huge nested end_reason maps twice; print compact JSON.
        print(json.dumps(payload, default=str, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    # Guard against accidental writes: never call to_parquet / rewrite artifacts.
    raise SystemExit(main())
