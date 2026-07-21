#!/usr/bin/env python3
"""Market Context Stage Review — consolidated read-only quality / latency / readiness audit.

Does NOT rewrite model / auction / cognitive / final / lifecycle / visual / runtime artifacts.
Does NOT enable execution. Does NOT change action_allowed / shadow_only semantics.

Answers:
  1. Context quality after auction/lifecycle fixes
  2. LONG/SHORT stability
  3. OBSERVE correctness
  4. CHALLENGED usefulness vs lag
  5. Formation → confirmation delay
  6. Premature / late termination
  7. Lifecycle parameter calibration
  8. Model vs technical refresh lag
  9. Execution readiness blockers
  10. Primary next step
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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
VISUAL_DIR = ROOT / "apps" / "context_visualizer" / "public" / "data"
VISUAL_LATEST = VISUAL_DIR / "lifecycle_latest.json"
VISUAL_EPISODES = VISUAL_DIR / "lifecycle_context_episodes.json"
VISUAL_CANDLES = VISUAL_DIR / "lifecycle_candles.json"
LIFECYCLE_BUILDER_PATH = ROOT / "scripts" / "research" / "build_market_context_lifecycle_memory.py"
REPORT_PATH = ROOT / "docs" / "MARKET_CONTEXT_STAGE_REVIEW_AUDIT.md"

# Decision-log / readiness probe paths (expected absent today).
DECISION_LOG_CANDIDATES = [
    ROOT / "data" / "cognition" / "market_context_decision_log.jsonl",
    ROOT / "data" / "cognition" / "append_only_context_decision_log.jsonl",
    ROOT / "logs" / "market_context_decision_log.jsonl",
]
DECISION_LATENCY_AUDIT_CANDIDATES = [
    ROOT / "docs" / "DECISION_LATENCY_AUDIT.md",
    ROOT / "scripts" / "research" / "audit_decision_latency.py",
]
NO_REPAINT_AUDIT_CANDIDATES = [
    ROOT / "docs" / "NO_REPAINT_AUDIT.md",
    ROOT / "scripts" / "research" / "audit_no_repaint.py",
]
PAPER_SIM_CANDIDATES = [
    ROOT / "scripts" / "research" / "paper_execution_simulator.py",
    ROOT / "scripts" / "paper_execution_simulator.py",
    ROOT / "sandbox" / "paper_execution_simulator",
]
SETUP_RISK_GATE_CANDIDATES = [
    ROOT / "scripts" / "research" / "setup_risk_gate.py",
    ROOT / "config" / "setup_risk_gate.yaml",
]

CUTOVER_10JUL = pd.Timestamp("2026-07-10T00:00:00Z")
# Documented proxy: lifecycle persistence fix deployed / rebuilt around 2026-07-14.
POST_PERSISTENCE_FIX = pd.Timestamp("2026-07-14T00:00:00Z")
POST_PERSISTENCE_NOTE = (
    "POST_PERSISTENCE_FIX uses documented proxy cutover 2026-07-14T00:00:00Z "
    "(lifecycle persistence fix + shadow-chain rebuild). Exact git/deploy timestamp "
    "is not encoded in parquet rows."
)
CYCLE_THRESHOLD = 50_000
MIN_USEFUL_ROWS = 20
BAR_MINUTES = 15
DIRECTIONAL = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
PIPELINE_CYCLE_RE = re.compile(r"PIPELINE CYCLE:\s*(\d+)")
FT_YES_MOVE = 0.001
FT_YES_EXTENT = 0.002
CURRENT_NEUT_BARS = 2
CURRENT_HOLD_BARS = 3


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


def pct(numer: float, denom: float) -> float | None:
    if denom <= 0:
        return None
    return round(100.0 * float(numer) / float(denom), 2)


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


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "median": None, "p75": None, "p90": None, "max": None}
    s = pd.Series(values, dtype=float)
    return {
        "avg": round(float(s.mean()), 3),
        "median": round(float(s.median()), 3),
        "p75": round(float(s.quantile(0.75)), 3),
        "p90": round(float(s.quantile(0.90)), 3),
        "max": round(float(s.max()), 3),
    }


def analysis_windows(now: pd.Timestamp | None = None) -> list[tuple[str, pd.Timestamp | None, pd.Timestamp | None]]:
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    # Latest live segment: last 24h of available memory / feed.
    return [
        ("FULL", None, None),
        ("SINCE_10JUL", CUTOVER_10JUL, None),
        ("LAST_7D", now - pd.Timedelta(days=7), None),
        ("LAST_48H", now - pd.Timedelta(hours=48), None),
        ("POST_PERSISTENCE_FIX", POST_PERSISTENCE_FIX, None),
        ("LATEST_LIVE_SEGMENT", now - pd.Timedelta(hours=24), None),
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


# ---------------------------------------------------------------------------
# Section 1 — runtime cycles
# ---------------------------------------------------------------------------


def parse_runtime_cycles(log_path: Path = RUNTIME_LOG) -> dict[str, Any]:
    empty = {
        "total_runtime_log_cycles": 0,
        "current_run_cycle": 0,
        "runtime_segments": 0,
        "latest_5_cycles": [],
        "cycles_to_50k": CYCLE_THRESHOLD,
        "threshold_50k_reached": False,
        "runtime_log_mtime_utc": None,
        "log_exists": False,
        "max_cycle_seen": 0,
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
                "runtime_log_mtime_utc": mtime.isoformat().replace("+00:00", "Z"),
            }
        )
        return empty
    total = len(cycles)
    return {
        "total_runtime_log_cycles": total,
        "current_run_cycle": cycles[-1],
        "runtime_segments": segments,
        "latest_5_cycles": cycles[-5:],
        "cycles_to_50k": max(0, CYCLE_THRESHOLD - total),
        "threshold_50k_reached": total >= CYCLE_THRESHOLD,
        "runtime_log_mtime_utc": mtime.isoformat().replace("+00:00", "Z"),
        "log_exists": True,
        "max_cycle_seen": max(cycles),
        "first_cycle_seen": cycles[0],
        "note": "Parsed from runtime.log PIPELINE CYCLE lines; ops_stability.json is not authoritative.",
    }


# ---------------------------------------------------------------------------
# Section 2 — freshness / lag
# ---------------------------------------------------------------------------


def _mtime_utc(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_ts(frame: pd.DataFrame, cols: tuple[str, ...] = ("timestamp", "start_time", "end_time")) -> pd.Timestamp | None:
    for col in cols:
        if col in frame.columns and len(frame):
            ts = frame[col].dropna()
            if len(ts):
                return pd.Timestamp(ts.max())
    return None


def _json_latest_ts(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    candidates: list[Any] = []
    if isinstance(payload, dict):
        for key in ("timestamp", "generated_at", "as_of", "latest_timestamp"):
            if key in payload:
                candidates.append(payload[key])
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            last = rows[-1]
            if isinstance(last, dict):
                candidates.append(last.get("timestamp"))
        if "end_time" in payload:
            candidates.append(payload.get("end_time"))
    elif isinstance(payload, list) and payload:
        last = payload[-1]
        if isinstance(last, dict):
            candidates.extend([last.get("timestamp"), last.get("end_time"), last.get("start_time")])
    for raw in candidates:
        if raw is None:
            continue
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.notna(ts):
            return pd.Timestamp(ts)
    return None


def lag_minutes(a: pd.Timestamp | None, b: pd.Timestamp | None) -> float | None:
    if a is None or b is None:
        return None
    return round((pd.Timestamp(a) - pd.Timestamp(b)).total_seconds() / 60.0, 2)


def artifact_freshness(
    live: pd.DataFrame,
    auction: pd.DataFrame,
    cognitive: pd.DataFrame,
    final: pd.DataFrame,
    lifecycle: pd.DataFrame,
    episodes: pd.DataFrame,
) -> dict[str, Any]:
    live_ts = _latest_ts(live)
    items = {
        "live_feed": (LIVE_FEED, live_ts, len(live)),
        "auction_episode_memory": (AUCTION_PATH, _latest_ts(auction), len(auction)),
        "cognitive_market_state_memory": (COGNITIVE_PATH, _latest_ts(cognitive), len(cognitive)),
        "final_market_context_memory": (FINAL_PATH, _latest_ts(final), len(final)),
        "market_context_lifecycle_memory": (LIFECYCLE_PATH, _latest_ts(lifecycle), len(lifecycle)),
        "market_context_lifecycle_episodes": (EPISODES_PATH, _latest_ts(episodes), len(episodes)),
        "visual_latest": (VISUAL_LATEST, _json_latest_ts(VISUAL_LATEST), None),
        "visual_episodes": (VISUAL_EPISODES, _json_latest_ts(VISUAL_EPISODES), None),
        "visual_candles": (VISUAL_CANDLES, _json_latest_ts(VISUAL_CANDLES), None),
    }
    rows: dict[str, Any] = {}
    for name, (path, latest, count) in items.items():
        rows[name] = {
            "path": str(path),
            "exists": path.exists(),
            "rows": count,
            "latest_timestamp": latest.isoformat().replace("+00:00", "Z") if latest is not None else None,
            "file_mtime_utc": _mtime_utc(path),
            "lag_vs_live_min": lag_minutes(live_ts, latest) if live_ts is not None else None,
        }
    # Positive lag_vs_live_min means live is ahead of artifact.
    interpretation = []
    life_lag = rows["market_context_lifecycle_memory"]["lag_vs_live_min"]
    visual_lag = rows["visual_latest"]["lag_vs_live_min"]
    if life_lag is not None and life_lag > BAR_MINUTES:
        interpretation.append(
            f"TECHNICAL_REFRESH_LAG: lifecycle lags live feed by {life_lag} min "
            "(not automatically a model failure; rebuild can catch up)."
        )
    if visual_lag is not None and visual_lag > BAR_MINUTES:
        interpretation.append(
            f"TECHNICAL_REFRESH_LAG: visual latest lags live feed by {visual_lag} min "
            "(visual JSON must not be used as execution source)."
        )
    if not interpretation:
        interpretation.append("No material technical refresh lag detected vs live feed timestamps.")
    return {
        "artifacts": rows,
        "live_to_auction_lag_min": rows["auction_episode_memory"]["lag_vs_live_min"],
        "live_to_cognitive_lag_min": rows["cognitive_market_state_memory"]["lag_vs_live_min"],
        "live_to_final_context_lag_min": rows["final_market_context_memory"]["lag_vs_live_min"],
        "live_to_lifecycle_lag_min": life_lag,
        "live_to_visual_lag_min": visual_lag,
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# Section 3 — context distribution
# ---------------------------------------------------------------------------


def context_distribution(lifecycle: pd.DataFrame) -> dict[str, Any]:
    n = len(lifecycle)
    if n == 0:
        return {
            "rows": 0,
            "sample_large_enough": False,
            "raw_context": {},
            "active_context": {},
            "lifecycle_state": {},
            "directional_active_pct": None,
            "observe_pct": None,
            "challenged_pct": None,
            "candidate_pct": None,
            "invalidated_pct": None,
        }
    raw = lifecycle["raw_market_context"].map(lambda x: _clean(x)) if "raw_market_context" in lifecycle.columns else pd.Series(dtype=str)
    active = lifecycle["active_market_context"].map(lambda x: _clean(x)) if "active_market_context" in lifecycle.columns else pd.Series(dtype=str)
    life = lifecycle["lifecycle_state"].map(lambda x: _clean(x)) if "lifecycle_state" in lifecycle.columns else pd.Series(dtype=str)
    return {
        "rows": n,
        "sample_large_enough": n >= MIN_USEFUL_ROWS,
        "raw_context": value_counts_dict(raw),
        "active_context": value_counts_dict(active),
        "lifecycle_state": value_counts_dict(life),
        "directional_active_pct": pct(int(active.isin(DIRECTIONAL).sum()), n),
        "observe_pct": pct(int((active == "OBSERVE").sum()), n),
        "challenged_pct": pct(int((life == "CHALLENGED").sum()), n),
        "candidate_pct": pct(int((life == "CANDIDATE").sum()), n),
        "invalidated_pct": pct(int((life == "INVALIDATED").sum()), n),
    }


# ---------------------------------------------------------------------------
# Section 4 — directional episode quality
# ---------------------------------------------------------------------------


def directional_episode_quality(episodes: pd.DataFrame) -> dict[str, Any]:
    empty = {
        "directional_episodes": 0,
        "by_context": {},
        "one_bar_directional_episode_pct": None,
        "short_lived_episode_pct": None,
        "long_lived_episode_pct": None,
        "duration_buckets": duration_buckets([]),
        "avg_bars": None,
        "median_bars": None,
        "max_bars": None,
        "start_reason_counts": {},
        "end_reason_counts": {},
    }
    if episodes is None or len(episodes) == 0:
        return empty
    ctx_col = "active_market_context" if "active_market_context" in episodes.columns else "context"
    ctx = episodes[ctx_col].map(lambda x: _clean(x))
    directional = episodes.loc[ctx.isin(DIRECTIONAL)].copy()
    if len(directional) == 0:
        return empty

    def _side(side: str) -> dict[str, Any]:
        sub = directional.loc[directional[ctx_col].map(lambda x: _clean(x)) == side]
        bars = [int(v) for v in sub.get("bars_count", pd.Series(dtype=float)).fillna(0).tolist()]
        return {
            "episode_count": len(sub),
            "avg_bars": round(float(pd.Series(bars).mean()), 3) if bars else None,
            "median_bars": float(pd.Series(bars).median()) if bars else None,
            "max_bars": int(max(bars)) if bars else None,
            "duration_buckets": duration_buckets(bars),
            "one_bar_count": sum(1 for b in bars if b <= 1),
            "one_bar_pct": pct(sum(1 for b in bars if b <= 1), len(bars)) if bars else None,
            "two_bar_count": sum(1 for b in bars if b == 2),
            "two_bar_pct": pct(sum(1 for b in bars if b == 2), len(bars)) if bars else None,
            "start_reason_counts": value_counts_dict(sub["start_reason"]) if "start_reason" in sub.columns else {},
            "end_reason_counts": value_counts_dict(sub["end_reason"]) if "end_reason" in sub.columns else {},
        }

    all_bars = [int(v) for v in directional.get("bars_count", pd.Series(dtype=float)).fillna(0).tolist()]
    return {
        "directional_episodes": len(directional),
        "by_context": {
            "LONG_CONTEXT": _side("LONG_CONTEXT"),
            "SHORT_CONTEXT": _side("SHORT_CONTEXT"),
        },
        "one_bar_directional_episode_pct": pct(sum(1 for b in all_bars if b <= 1), len(all_bars)) if all_bars else None,
        "short_lived_episode_pct": pct(sum(1 for b in all_bars if b <= 2), len(all_bars)) if all_bars else None,
        "long_lived_episode_pct": pct(sum(1 for b in all_bars if b > 8), len(all_bars)) if all_bars else None,
        "duration_buckets": duration_buckets(all_bars),
        "avg_bars": round(float(pd.Series(all_bars).mean()), 3) if all_bars else None,
        "median_bars": float(pd.Series(all_bars).median()) if all_bars else None,
        "max_bars": int(max(all_bars)) if all_bars else None,
        "start_reason_counts": value_counts_dict(directional["start_reason"]) if "start_reason" in directional.columns else {},
        "end_reason_counts": value_counts_dict(directional["end_reason"]) if "end_reason" in directional.columns else {},
    }


# ---------------------------------------------------------------------------
# Section 5 — CHALLENGED streaks
# ---------------------------------------------------------------------------


def forward_returns_from_closes(closes: list[float | None], index: int) -> dict[str, float | None]:
    if index < 0 or index >= len(closes):
        return {"return_1": None, "return_2": None, "return_4": None, "return_8": None, "mfe_8": None, "mae_8": None}
    base = closes[index]
    if base is None or base == 0:
        return {"return_1": None, "return_2": None, "return_4": None, "return_8": None, "mfe_8": None, "mae_8": None}

    def ret(h: int) -> float | None:
        j = index + h
        if j >= len(closes) or closes[j] is None:
            return None
        return (closes[j] - base) / abs(base)

    future = [c for c in closes[index + 1 : index + 9] if c is not None]
    mfe = ((max(future) - base) / abs(base)) if future else None
    mae = ((min(future) - base) / abs(base)) if future else None
    return {
        "return_1": ret(1),
        "return_2": ret(2),
        "return_4": ret(4),
        "return_8": ret(8),
        "mfe_8": mfe,
        "mae_8": mae,
    }


def movement_during(closes: list[float | None], start_i: int, end_i: int) -> float | None:
    if start_i < 0 or end_i >= len(closes) or start_i > end_i:
        return None
    a = closes[start_i]
    b = closes[end_i]
    if a is None or b is None or a == 0:
        return None
    return (b - a) / abs(a)


def classify_challenged_streak(
    *,
    context: str,
    streak_len: int,
    move_during: float | None,
    move_after: float | None,
    next_state: str,
    next_context: str,
    still_open: bool,
) -> str:
    if still_open or next_state in {"", "UNKNOWN"} and move_after is None:
        return "UNRESOLVED"
    ctx = _clean(context)
    against = None
    if move_during is not None:
        if ctx == "LONG_CONTEXT":
            against = move_during <= -FT_YES_EXTENT
        elif ctx == "SHORT_CONTEXT":
            against = move_during >= FT_YES_EXTENT
    if against and streak_len >= 3:
        return "STALE_CONTEXT"
    if next_state == "INVALIDATED" or (
        next_context in DIRECTIONAL and next_context != ctx and _clean(next_state) == "ACTIVE"
    ):
        return "EARLY_WARNING"
    if next_state == "ACTIVE" and next_context == ctx:
        return "HEALTHY_DOUBT"
    if streak_len <= 3 and not against:
        return "HEALTHY_DOUBT"
    if against:
        return "STALE_CONTEXT"
    return "UNRESOLVED"


def challenged_streak_analysis(lifecycle: pd.DataFrame) -> dict[str, Any]:
    if lifecycle is None or len(lifecycle) == 0 or "lifecycle_state" not in lifecycle.columns:
        return {
            "streaks": [],
            "total_challenged_bars": 0,
            "challenged_bars_pct_of_directional": None,
            "average_challenged_streak": None,
            "median_challenged_streak": None,
            "max_challenged_streak": None,
            "classification_counts": {},
        }
    work = lifecycle.sort_values("timestamp").reset_index(drop=True)
    states = work["lifecycle_state"].map(lambda x: _clean(x)).tolist()
    actives = work["active_market_context"].map(lambda x: _clean(x)).tolist()
    closes = [_safe_float(v) for v in work["close"].tolist()] if "close" in work.columns else [None] * len(work)
    timestamps = work["timestamp"].tolist()

    streaks: list[dict[str, Any]] = []
    i = 0
    while i < len(work):
        if states[i] != "CHALLENGED":
            i += 1
            continue
        start = i
        while i < len(work) and states[i] == "CHALLENGED":
            i += 1
        end = i - 1
        prev_state = states[start - 1] if start > 0 else "NONE"
        prev_ctx = actives[start - 1] if start > 0 else "NONE"
        next_state = states[end + 1] if end + 1 < len(work) else "NONE"
        next_ctx = actives[end + 1] if end + 1 < len(work) else "NONE"
        still_open = end == len(work) - 1
        move_during = movement_during(closes, start, end)
        after = forward_returns_from_closes(closes, end)
        move_after = after.get("return_4")
        context = actives[start]
        streak_len = end - start + 1
        klass = classify_challenged_streak(
            context=context,
            streak_len=streak_len,
            move_during=move_during,
            move_after=move_after,
            next_state=next_state,
            next_context=next_ctx,
            still_open=still_open,
        )
        streaks.append(
            {
                "start_timestamp": pd.Timestamp(timestamps[start]).isoformat().replace("+00:00", "Z"),
                "end_timestamp": pd.Timestamp(timestamps[end]).isoformat().replace("+00:00", "Z"),
                "context": context,
                "streak_length_bars": streak_len,
                "previous_state": prev_state,
                "previous_context": prev_ctx,
                "next_state": next_state,
                "next_context": next_ctx,
                "price_move_during": move_during,
                "price_move_after_4": move_after,
                "classification": klass,
                "still_open": still_open,
            }
        )

    lengths = [s["streak_length_bars"] for s in streaks]
    challenged_bars = sum(lengths)
    directional_bars = int(pd.Series(actives).isin(DIRECTIONAL).sum())
    class_counts = Counter(s["classification"] for s in streaks)
    return {
        "streaks": streaks[:50],  # cap detail in payload; aggregates use all
        "streak_count": len(streaks),
        "total_challenged_bars": challenged_bars,
        "challenged_bars_pct_of_directional": pct(challenged_bars, directional_bars),
        "average_challenged_streak": round(float(pd.Series(lengths).mean()), 3) if lengths else None,
        "median_challenged_streak": float(pd.Series(lengths).median()) if lengths else None,
        "max_challenged_streak": int(max(lengths)) if lengths else None,
        "classification_counts": dict(class_counts),
        "stale_context_count": int(class_counts.get("STALE_CONTEXT", 0)),
        "healthy_doubt_count": int(class_counts.get("HEALTHY_DOUBT", 0)),
        "early_warning_count": int(class_counts.get("EARLY_WARNING", 0)),
        "unresolved_count": int(class_counts.get("UNRESOLVED", 0)),
    }


# ---------------------------------------------------------------------------
# Section 6 — premature / late termination
# ---------------------------------------------------------------------------


def continuation_favorable(context: str, fwd: dict[str, float | None]) -> bool:
    r4 = fwd.get("return_4")
    mfe = fwd.get("mfe_8")
    mae = fwd.get("mae_8")
    ctx = _clean(context).upper()
    if ctx == "LONG_CONTEXT":
        if r4 is not None and r4 >= FT_YES_MOVE:
            return True
        if mfe is not None and mfe >= FT_YES_EXTENT and (r4 is None or r4 >= 0):
            return True
        return False
    if ctx == "SHORT_CONTEXT":
        if r4 is not None and r4 <= -FT_YES_MOVE:
            return True
        if mae is not None and mae <= -FT_YES_EXTENT and (r4 is None or r4 <= 0):
            return True
        return False
    return False


def adverse_move(context: str, fwd: dict[str, float | None]) -> bool:
    r4 = fwd.get("return_4")
    mfe = fwd.get("mfe_8")
    mae = fwd.get("mae_8")
    ctx = _clean(context).upper()
    if ctx == "LONG_CONTEXT":
        if r4 is not None and r4 <= -FT_YES_MOVE:
            return True
        if mae is not None and mae <= -FT_YES_EXTENT:
            return True
        return False
    if ctx == "SHORT_CONTEXT":
        if r4 is not None and r4 >= FT_YES_MOVE:
            return True
        if mfe is not None and mfe >= FT_YES_EXTENT:
            return True
        return False
    return False


def classify_termination(
    *,
    context: str,
    bars_count: int,
    end_reason: str,
    next_rows: list[dict[str, Any]],
    fwd: dict[str, float | None],
) -> str:
    reason = _clean(end_reason).lower()
    fav = continuation_favorable(context, fwd)
    adv = adverse_move(context, fwd)
    first = next_rows[0] if next_rows else {}

    if "latest open" in reason:
        return "UNKNOWN"

    if "opposite confirmed" in reason or _clean(first.get("invalidation_type")).upper() == "OPPOSITE_CONTEXT_REPLACEMENT":
        return "OPPOSITE_REPLACEMENT"

    if "auction neutralization" in reason or _clean(first.get("invalidation_type")).upper() == "AUCTION_NEUTRALIZATION":
        single_balance = _clean(first.get("raw_market_context")).upper() == "OBSERVE"
        if bars_count <= 2 and single_balance and not adv:
            return "NEUTRALIZATION_TOO_FAST"
        if fav and not adv:
            return "NEUTRALIZATION_TOO_FAST"
        if bars_count > 8 and not fav and not adv:
            return "TOO_SLOW_TERMINATION"
        if adv:
            return "CORRECT_TERMINATION"
        return "NEUTRALIZATION_TOO_FAST" if bars_count <= 2 else "CORRECT_TERMINATION"

    if "thesis rejection" in reason or _clean(first.get("invalidation_type")).upper() == "THESIS_REJECTION":
        if fav and not adv:
            return "THESIS_REJECTION_TOO_FAST"
        if bars_count > 8 and not fav and not adv:
            return "TOO_SLOW_TERMINATION"
        if adv:
            return "CORRECT_TERMINATION"
        return "THESIS_REJECTION_TOO_FAST" if bars_count <= 2 else "CORRECT_TERMINATION"

    if bars_count > 8 and not fav and not adv:
        return "TOO_SLOW_TERMINATION"
    if fav and not adv:
        return "PREMATURE_TERMINATION"
    if adv:
        return "CORRECT_TERMINATION"
    if bars_count <= 2 and fav:
        return "PREMATURE_TERMINATION"
    return "UNKNOWN"


def termination_analysis(episodes: pd.DataFrame, lifecycle: pd.DataFrame) -> dict[str, Any]:
    if episodes is None or len(episodes) == 0 or lifecycle is None or len(lifecycle) == 0:
        return {"classified": 0, "counts": {}, "pct": {}, "examples": []}
    life = lifecycle.sort_values("timestamp").reset_index(drop=True)
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(life["timestamp"].tolist())}
    closes = [_safe_float(v) for v in life["close"].tolist()] if "close" in life.columns else [None] * len(life)
    ctx_col = "active_market_context" if "active_market_context" in episodes.columns else "context"
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for _, ep in episodes.iterrows():
        ctx = _clean(ep.get(ctx_col))
        if ctx not in DIRECTIONAL:
            continue
        end_ts = pd.Timestamp(ep.get("end_time"))
        if end_ts not in ts_to_idx:
            # nearest prior
            prior = life.loc[life["timestamp"] <= end_ts]
            if len(prior) == 0:
                counts["UNKNOWN"] += 1
                continue
            idx = int(prior.index[-1])
        else:
            idx = ts_to_idx[end_ts]
        fwd = forward_returns_from_closes(closes, idx)
        next_rows = []
        for j in range(idx + 1, min(idx + 5, len(life))):
            row = life.iloc[j]
            next_rows.append(
                {
                    "raw_market_context": _clean(row.get("raw_market_context"), default="OBSERVE"),
                    "invalidation_type": _clean(row.get("invalidation_type"), default="NONE"),
                    "auction_episode": _clean(row.get("raw_auction_episode"), default="UNKNOWN"),
                    "active_market_context": _clean(row.get("active_market_context"), default="OBSERVE"),
                    "lifecycle_state": _clean(row.get("lifecycle_state"), default="UNKNOWN"),
                }
            )
        klass = classify_termination(
            context=ctx,
            bars_count=int(ep.get("bars_count") or 0),
            end_reason=_clean(ep.get("end_reason"), default=""),
            next_rows=next_rows,
            fwd=fwd,
        )
        counts[klass] += 1
        if len(examples) < 25:
            examples.append(
                {
                    "context": ctx,
                    "start_time": str(ep.get("start_time")),
                    "end_time": str(ep.get("end_time")),
                    "bars_count": int(ep.get("bars_count") or 0),
                    "end_reason": _clean(ep.get("end_reason")),
                    "classification": klass,
                    **fwd,
                }
            )

    total = sum(counts.values())
    return {
        "classified": total,
        "counts": dict(counts),
        "pct": {k: pct(v, total) for k, v in counts.items()},
        "examples": examples,
        "premature_termination_count": int(counts.get("PREMATURE_TERMINATION", 0)),
        "premature_termination_pct": pct(counts.get("PREMATURE_TERMINATION", 0), total),
        "neutralization_too_fast_count": int(counts.get("NEUTRALIZATION_TOO_FAST", 0)),
        "thesis_rejection_too_fast_count": int(counts.get("THESIS_REJECTION_TOO_FAST", 0)),
        "too_slow_termination_count": int(counts.get("TOO_SLOW_TERMINATION", 0)),
        "opposite_replacement_count": int(counts.get("OPPOSITE_REPLACEMENT", 0)),
        "correct_termination_count": int(counts.get("CORRECT_TERMINATION", 0)),
    }


# ---------------------------------------------------------------------------
# Section 7 — formation → confirmation delay
# ---------------------------------------------------------------------------


def formation_confirmation_delay(lifecycle: pd.DataFrame) -> dict[str, Any]:
    """Measure DEVELOPING directional → first ACTIVE lifecycle activation lag."""
    result: dict[str, Any] = {"by_context": {}, "note": "Model confirmation delay (bars/minutes), not execution lag."}
    if lifecycle is None or len(lifecycle) == 0:
        return result
    work = lifecycle.sort_values("timestamp").reset_index(drop=True)
    for side in ("LONG_CONTEXT", "SHORT_CONTEXT"):
        lags_bars: list[float] = []
        formations = 0
        confirmed = 0
        never = 0
        i = 0
        while i < len(work):
            raw = _clean(work.iloc[i].get("raw_market_context"))
            status = _clean(work.iloc[i].get("raw_context_status")).upper()
            # start of a developing directional formation while not already active same side
            active = _clean(work.iloc[i].get("active_market_context"))
            if raw == side and status == "DEVELOPING" and active != side:
                formations += 1
                start_i = i
                found = None
                j = i
                while j < len(work):
                    r = work.iloc[j]
                    if _clean(r.get("active_market_context")) == side and _clean(r.get("lifecycle_state")) in {
                        "ACTIVE",
                        "CHALLENGED",
                    }:
                        found = j
                        break
                    # abandoned if opposite becomes active or long gap of observe without activation
                    if _clean(r.get("active_market_context")) in DIRECTIONAL - {side}:
                        break
                    if j > start_i + 40:
                        break
                    j += 1
                if found is None:
                    never += 1
                else:
                    confirmed += 1
                    lags_bars.append(float(found - start_i))
                i = max(i + 1, (found + 1) if found is not None else i + 1)
                continue
            i += 1
        q = quantiles(lags_bars)
        lag_min = [b * BAR_MINUTES for b in lags_bars]
        qm = quantiles(lag_min)
        result["by_context"][side] = {
            "formations": formations,
            "confirmed": confirmed,
            "never_confirmed": never,
            "median_lag_bars": q["median"],
            "average_lag_bars": q["avg"],
            "p75_lag_bars": q["p75"],
            "p90_lag_bars": q["p90"],
            "median_lag_minutes": qm["median"],
            "average_lag_minutes": qm["avg"],
            "p75_lag_minutes": qm["p75"],
            "p90_lag_minutes": qm["p90"],
            "confirmed_after_gt_1_bar": sum(1 for b in lags_bars if b > 1),
            "confirmed_after_gt_2_bars": sum(1 for b in lags_bars if b > 2),
            "confirmed_after_gt_3_bars": sum(1 for b in lags_bars if b > 3),
        }
    return result


# ---------------------------------------------------------------------------
# Section 8 — parameter sensitivity (exact in-memory replay)
# ---------------------------------------------------------------------------


def _load_lifecycle_builder():
    spec = importlib.util.spec_from_file_location("mctx_lifecycle_builder_stage_review", LIFECYCLE_BUILDER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Avoid colliding with other loaders of the same file.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def parameter_grid() -> list[tuple[int, int]]:
    neutrals = [1, 2, 3]
    holds = [1, 2, 3, 4]
    return [(n, h) for n in neutrals for h in holds]


def score_sensitivity_row(row: dict[str, Any]) -> float:
    """Higher is better. Conservative heuristic for ranking only."""
    score = 0.0
    one_bar = row.get("one_bar_episode_count") or 0
    short = row.get("le_2_bar_episode_count") or 0
    premature = row.get("premature_neutralization_count") or 0
    too_slow = row.get("too_slow_termination_count") or 0
    stale = row.get("stale_challenged_count") or 0
    raw_drop = row.get("raw_active_to_final_observe") or 0
    avg_bars = row.get("avg_episode_bars") or 0
    directional_pct = row.get("active_directional_pct") or 0
    score -= one_bar * 3.0
    score -= short * 1.5
    score -= premature * 4.0
    score -= too_slow * 2.0
    score -= stale * 2.5
    score -= raw_drop * 10.0
    # Prefer moderate duration and some directional presence.
    if 3.5 <= avg_bars <= 8.0:
        score += 5.0
    score += min(directional_pct, 40.0) * 0.1
    return round(score, 3)


def run_parameter_sensitivity(
    final: pd.DataFrame,
    auction: pd.DataFrame,
    live_closes: pd.DataFrame | None = None,
    *,
    max_rows: int = 1200,
) -> dict[str, Any]:
    """Exact in-memory lifecycle replay with patched constants. Never writes artifacts."""
    if final is None or len(final) == 0:
        return {"mode": "exact_in_memory_replay", "rows": [], "note": "No final context rows."}
    # Focus sensitivity on post-10jul / recent segment for speed & relevance.
    work = final.copy()
    if "timestamp" in work.columns:
        work = work.loc[work["timestamp"] >= CUTOVER_10JUL].copy()
    if len(work) > max_rows:
        work = work.tail(max_rows).copy()
    auction_slice = auction
    if auction is not None and len(auction) and "timestamp" in auction.columns:
        auction_slice = auction.loc[auction["timestamp"] >= work["timestamp"].min()].copy()

    builder = _load_lifecycle_builder()
    original_n = builder.NEUTRALIZATION_CONFIRM_BARS
    original_h = builder.MIN_ACTIVE_CONTEXT_HOLD_BARS
    rows: list[dict[str, Any]] = []
    try:
        for neut, hold in parameter_grid():
            builder.NEUTRALIZATION_CONFIRM_BARS = neut
            builder.MIN_ACTIVE_CONTEXT_HOLD_BARS = hold
            memory = builder.build_lifecycle_memory(work, auction_frame=auction_slice)
            episodes = builder.build_lifecycle_episodes(memory)
            dist = context_distribution(memory)
            epq = directional_episode_quality(episodes)
            challenged = challenged_streak_analysis(memory)
            term = termination_analysis(episodes, memory)
            # conversion drop
            conv_drop = 0
            if "raw_market_context" in memory.columns and "raw_context_status" in memory.columns:
                raw = memory["raw_market_context"].map(lambda x: _clean(x))
                status = memory["raw_context_status"].map(lambda x: _clean(x).upper())
                active = memory["active_market_context"].map(lambda x: _clean(x))
                conv_drop = int(((raw.isin(DIRECTIONAL)) & (status == "ACTIVE") & (active == "OBSERVE")).sum())
            bars = []
            if len(episodes):
                ctx_col = "active_market_context" if "active_market_context" in episodes.columns else "context"
                d = episodes.loc[episodes[ctx_col].map(lambda x: _clean(x)).isin(DIRECTIONAL)]
                bars = [int(v) for v in d.get("bars_count", pd.Series(dtype=float)).fillna(0).tolist()]
            row = {
                "NEUTRALIZATION_CONFIRM_BARS": neut,
                "MIN_ACTIVE_CONTEXT_HOLD_BARS": hold,
                "is_current": neut == CURRENT_NEUT_BARS and hold == CURRENT_HOLD_BARS,
                "directional_episode_count": epq.get("directional_episodes"),
                "active_directional_pct": dist.get("directional_active_pct"),
                "observe_pct": dist.get("observe_pct"),
                "avg_episode_bars": epq.get("avg_bars"),
                "median_episode_bars": epq.get("median_bars"),
                "one_bar_episode_count": sum(1 for b in bars if b <= 1),
                "le_2_bar_episode_count": sum(1 for b in bars if b <= 2),
                "challenged_bar_count": challenged.get("total_challenged_bars"),
                "stale_challenged_count": challenged.get("stale_context_count"),
                "premature_neutralization_count": term.get("neutralization_too_fast_count"),
                "too_slow_termination_count": term.get("too_slow_termination_count"),
                "opposite_replacement_count": term.get("opposite_replacement_count"),
                "raw_active_to_final_observe": conv_drop,
            }
            row["score"] = score_sensitivity_row(row)
            rows.append(row)
    finally:
        builder.NEUTRALIZATION_CONFIRM_BARS = original_n
        builder.MIN_ACTIVE_CONTEXT_HOLD_BARS = original_h

    ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    current = next((r for r in ranked if r["is_current"]), None)
    top = ranked[0] if ranked else None

    # Verdict policy:
    # - BLOCKER_FOUND only for hard regressions (raw ACTIVE→OBSERVE drops, or one-bar chatter explosion)
    # - ADJUST_LATER when current is mid-pack / elevated premature neutralization but otherwise stable
    # - KEEP_CURRENT when current ranks near the top and one-bar/raw-drop stay controlled
    if current and (
        (current.get("raw_active_to_final_observe") or 0) > 0
        or (current.get("one_bar_episode_count") or 0) >= 15
    ):
        param_verdict = "BLOCKER_FOUND"
    elif current and top and current["rank"] <= 3 and (current.get("one_bar_episode_count") or 0) <= 5:
        param_verdict = "KEEP_CURRENT"
    elif current and top and abs((current.get("score") or 0) - (top.get("score") or 0)) <= 8:
        param_verdict = "KEEP_CURRENT"
    else:
        param_verdict = "ADJUST_LATER"

    return {
        "mode": "exact_in_memory_replay",
        "window_note": f"Sensitivity replay on final_context rows since {CUTOVER_10JUL.date()} (tail max {max_rows}).",
        "current_parameters": {
            "NEUTRALIZATION_CONFIRM_BARS": CURRENT_NEUT_BARS,
            "MIN_ACTIVE_CONTEXT_HOLD_BARS": CURRENT_HOLD_BARS,
        },
        "rows": ranked,
        "parameter_verdict": param_verdict,
        "best": top,
        "current": current,
    }


# ---------------------------------------------------------------------------
# Section 9 — volume climax context check
# ---------------------------------------------------------------------------


def volume_climax_context_check(auction: pd.DataFrame, lifecycle: pd.DataFrame) -> dict[str, Any]:
    if auction is None or len(auction) == 0:
        return {"BUYING_CLIMAX": {}, "SELLING_CLIMAX": {}, "note": "No auction rows."}
    work = auction.copy()
    if "bar_event" not in work.columns:
        return {"BUYING_CLIMAX": {}, "SELLING_CLIMAX": {}, "note": "bar_event missing."}
    if "timestamp" in work.columns:
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce").astype(
            "datetime64[ns, UTC]"
        )
    life = pd.DataFrame()
    if lifecycle is not None and len(lifecycle):
        life = lifecycle.copy()
        if "timestamp" in life.columns:
            life["timestamp"] = pd.to_datetime(life["timestamp"], utc=True, errors="coerce").astype(
                "datetime64[ns, UTC]"
            )
        life = life.sort_values("timestamp")
    out: dict[str, Any] = {}
    for event in ("BUYING_CLIMAX", "SELLING_CLIMAX"):
        sub = work.loc[work["bar_event"].map(lambda x: _clean(x).upper()) == event].copy()
        if len(sub) == 0:
            out[event] = {"count": 0}
            continue
        # asof join lifecycle fields
        if len(life):
            merged = pd.merge_asof(
                sub.sort_values("timestamp"),
                life[
                    [
                        c
                        for c in (
                            "timestamp",
                            "active_market_context",
                            "lifecycle_state",
                            "raw_market_context",
                            "invalidation_type",
                        )
                        if c in life.columns
                    ]
                ].sort_values("timestamp"),
                on="timestamp",
                direction="backward",
                tolerance=pd.Timedelta("2h"),
            )
        else:
            merged = sub
        closes = [_safe_float(v) for v in merged["close"].tolist()] if "close" in merged.columns else [None] * len(merged)
        fwds = [forward_returns_from_closes(closes, i) for i in range(len(merged))]
        # next-state probes within +4 bars using lifecycle index
        precedes = Counter()
        if len(life):
            life_idx = life.reset_index(drop=True)
            ts_map = {pd.Timestamp(t): i for i, t in enumerate(life_idx["timestamp"].tolist())}
            for _, row in merged.iterrows():
                ts = pd.Timestamp(row["timestamp"])
                if ts not in ts_map:
                    prior = life_idx.loc[life_idx["timestamp"] <= ts]
                    if len(prior) == 0:
                        continue
                    i0 = int(prior.index[-1])
                else:
                    i0 = ts_map[ts]
                window = life_idx.iloc[i0 : i0 + 5]
                if (window["lifecycle_state"].map(lambda x: _clean(x)) == "ACTIVE").any() and (
                    window["active_market_context"].map(lambda x: _clean(x)).isin(DIRECTIONAL)
                ).any():
                    precedes["context_activation"] += 1
                if (window["lifecycle_state"].map(lambda x: _clean(x)) == "CHALLENGED").any():
                    precedes["challenged_state"] += 1
                if (window["lifecycle_state"].map(lambda x: _clean(x)) == "INVALIDATED").any():
                    precedes["invalidation"] += 1
                if (window["invalidation_type"].map(lambda x: _clean(x)) == "OPPOSITE_CONTEXT_REPLACEMENT").any():
                    precedes["opposite_replacement"] += 1

        def avg_ret(key: str) -> float | None:
            vals = [f.get(key) for f in fwds if f.get(key) is not None]
            return round(float(sum(vals) / len(vals)), 5) if vals else None

        out[event] = {
            "count": len(merged),
            "by_active_context": value_counts_dict(merged["active_market_context"]) if "active_market_context" in merged.columns else {},
            "by_lifecycle_state": value_counts_dict(merged["lifecycle_state"]) if "lifecycle_state" in merged.columns else {},
            "avg_return_1": avg_ret("return_1"),
            "avg_return_2": avg_ret("return_2"),
            "avg_return_4": avg_ret("return_4"),
            "avg_return_8": avg_ret("return_8"),
            "precedes_within_4_bars": dict(precedes),
        }
    return out


# ---------------------------------------------------------------------------
# Section 10 / 11 — limitations + execution readiness
# ---------------------------------------------------------------------------


def _any_exists(paths: list[Path]) -> bool:
    return any(p.exists() for p in paths)


def live_postfactum_limitations(freshness: dict[str, Any]) -> dict[str, Any]:
    decision_log = _any_exists(DECISION_LOG_CANDIDATES)
    return {
        "append_only_decision_log_present": decision_log,
        "strict_live_decision_proof": False if not decision_log else True,
        "current_artifacts_rebuildable_from_live_candles": True,
        "visual_json_must_not_be_used_as_execution_source": True,
        "context_refresh_lag_is_technical_not_automatically_model_failure": True,
        "snapshot_no_repaint_proof_present": False,
        "notes": [
            "Append-only decision log does not exist yet → strict no-repaint / live-decision proof unavailable.",
            "Artifacts can be rebuilt from live candles; rebuilt history is not a live decision transcript.",
            "Visual JSON is display-only and must not be used as an execution source.",
            *freshness.get("interpretation", []),
        ],
    }


def execution_readiness(lifecycle: pd.DataFrame) -> dict[str, Any]:
    action_all_false = True
    shadow_all_true = True
    if lifecycle is not None and len(lifecycle):
        if "action_allowed" in lifecycle.columns:
            action_all_false = not bool(lifecycle["action_allowed"].fillna(False).astype(bool).any())
        if "shadow_only" in lifecycle.columns:
            shadow_all_true = bool(lifecycle["shadow_only"].fillna(False).astype(bool).all())
    decision_log = _any_exists(DECISION_LOG_CANDIDATES)
    decision_latency = _any_exists(DECISION_LATENCY_AUDIT_CANDIDATES)
    no_repaint = _any_exists(NO_REPAINT_AUDIT_CANDIDATES)
    paper = _any_exists(PAPER_SIM_CANDIDATES)
    setup_gate = _any_exists(SETUP_RISK_GATE_CANDIDATES)
    blockers = []
    if not decision_log:
        blockers.append("append-only context decision log missing")
    if not decision_latency:
        blockers.append("decision latency audit missing")
    if not no_repaint:
        blockers.append("no-repaint audit missing")
    if not paper:
        blockers.append("paper execution simulator missing")
    if not setup_gate:
        blockers.append("setup/risk gate missing")
    blockers.append("execution must not read visual JSON")
    return {
        "action_allowed_all_false": action_all_false,
        "shadow_only_all_true": shadow_all_true,
        "execution_enabled": False,
        "visual_json_used_for_execution": False,
        "append_only_decision_log_present": decision_log,
        "decision_latency_audit_present": decision_latency,
        "no_repaint_audit_present": no_repaint,
        "paper_execution_simulator_present": paper,
        "setup_risk_gate_present": setup_gate,
        "execution_readiness": "BLOCKED",
        "blockers": blockers,
        "required_statement": (
            "Execution must remain disabled until decision latency and append-only "
            "no-repaint logging are implemented."
        ),
    }


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def decide_recommendations(
    *,
    freshness: dict[str, Any],
    windows: dict[str, dict[str, Any]],
    sensitivity: dict[str, Any],
    readiness: dict[str, Any],
    limitations: dict[str, Any],
) -> dict[str, Any]:
    focus = windows.get("POST_PERSISTENCE_FIX") or windows.get("LAST_7D") or windows.get("FULL") or {}
    ep = focus.get("episodes", {})
    term = focus.get("termination", {})
    delay = focus.get("formation_delay", {})
    life_lag = freshness.get("live_to_lifecycle_lag_min")
    visual_lag = freshness.get("live_to_visual_lag_min")

    recs: list[str] = []
    primary = "KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION"
    param_verdict = sensitivity.get("parameter_verdict")

    if param_verdict == "BLOCKER_FOUND":
        primary = "RUN_TARGETED_LIFECYCLE_FIX"
        recs.append("RUN_TARGETED_LIFECYCLE_FIX")
    elif param_verdict == "ADJUST_LATER":
        recs.append("KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION")
        recs.append("RUN_TARGETED_LIFECYCLE_FIX")
    else:
        recs.append("KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION")

    # Confirmation delay investigation if median lag large.
    med_lags = []
    for side in ("LONG_CONTEXT", "SHORT_CONTEXT"):
        side_stats = (delay.get("by_context") or {}).get(side) or {}
        if side_stats.get("median_lag_bars") is not None:
            med_lags.append(side_stats["median_lag_bars"])
    if med_lags and max(med_lags) >= 4:
        recs.append("RUN_CONFIRMATION_DELAY_INVESTIGATION")

    # Material technical refresh lag ( > 1 hour ) is a pipeline issue, not model failure.
    if (life_lag is not None and life_lag > 60) or (visual_lag is not None and visual_lag > 60):
        recs.append("FIX_LIVE_CONTEXT_REFRESH")
        if primary == "KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION":
            primary = "FIX_LIVE_CONTEXT_REFRESH"

    # When context quality is not a hard blocker, the next execution-path step is decision logging.
    if not limitations.get("append_only_decision_log_present"):
        recs.append("IMPLEMENT_DECISION_LOGGER_NEXT")
        if param_verdict != "BLOCKER_FOUND" and primary in {
            "KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION",
            "FIX_LIVE_CONTEXT_REFRESH",
        }:
            # Prefer decision logger as primary next engineering step once params are usable.
            if param_verdict in {"KEEP_CURRENT", "ADJUST_LATER"}:
                primary = "IMPLEMENT_DECISION_LOGGER_NEXT"

    if readiness.get("execution_readiness") == "BLOCKED":
        recs.append("BUILD_PAPER_EXECUTION_SIMULATOR_NEXT")

    if not recs:
        recs = ["KEEP_CURRENT_PARAMETERS_AND_CONTINUE_OBSERVATION"]

    seen: set[str] = set()
    ordered: list[str] = []
    for r in [primary] + recs:
        if r not in seen:
            seen.add(r)
            ordered.append(r)

    classified = int(term.get("classified") or 0)
    neut_fast = int(term.get("neutralization_too_fast_count") or 0)
    premature = int(term.get("premature_termination_count") or 0)
    one_bar = ep.get("one_bar_directional_episode_pct")
    quality_ok = True
    if one_bar is not None and one_bar > 15:
        quality_ok = False
    if classified and neut_fast > max(3, int(0.35 * classified)):
        quality_ok = False
    if classified and premature > max(3, int(0.25 * classified)):
        quality_ok = False

    return {
        "primary": ordered[0],
        "all": ordered,
        "quality_acceptable_after_fixes": bool(quality_ok),
        "parameter_verdict": param_verdict,
        "notes": [
            "Quality assessment is observational; remaining ~4k cycles to 50k are not expected to materially change the picture.",
            "Execution remains blocked regardless of context quality until decision-log / latency / no-repaint / paper-sim exist.",
        ],
    }


# ---------------------------------------------------------------------------
# Orchestration + report
# ---------------------------------------------------------------------------


def build_window_bundle(
    name: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    lifecycle: pd.DataFrame,
    episodes: pd.DataFrame,
) -> dict[str, Any]:
    life_w = slice_window(lifecycle, start, end, "timestamp")
    ep_w = slice_window(episodes, start, end, "start_time")
    return {
        "window": name,
        "start": str(start) if start is not None else None,
        "end": str(end) if end is not None else None,
        "distribution": context_distribution(life_w),
        "episodes": directional_episode_quality(ep_w),
        "challenged": challenged_streak_analysis(life_w),
        "termination": termination_analysis(ep_w, life_w),
        "formation_delay": formation_confirmation_delay(life_w),
    }


def render_report(payload: dict[str, Any]) -> str:
    cyc = payload["runtime_cycles"]
    fresh = payload["freshness"]
    rec = payload["recommendations"]
    sens = payload["sensitivity"]
    ready = payload["execution_readiness"]
    lim = payload["limitations"]
    lines: list[str] = [
        "# Market Context Stage Review Audit",
        "",
        "Read-only stage review. No model / lifecycle / visual / runtime / execution changes.",
        "",
        f"**Generated:** `{payload['generated_at']}`  ",
        f"**Primary recommendation:** `{rec['primary']}`  ",
        f"**Parameter verdict:** `{sens.get('parameter_verdict')}`  ",
        f"**Execution readiness:** `{ready.get('execution_readiness')}`  ",
        "",
        "## 1. Executive summary",
        "",
        f"- Runtime cycles: **{cyc.get('total_runtime_log_cycles')}** total "
        f"(current run **{cyc.get('current_run_cycle')}**, segments **{cyc.get('runtime_segments')}**).",
        f"- 50k threshold reached: **{cyc.get('threshold_50k_reached')}** "
        f"(remaining **{cyc.get('cycles_to_50k')}**). Analysis proceeds without waiting.",
        f"- Quality acceptable after auction/lifecycle fixes (focus window heuristic): "
        f"**{rec.get('quality_acceptable_after_fixes')}**.",
        f"- Lifecycle params currently `NEUTRALIZATION_CONFIRM_BARS={CURRENT_NEUT_BARS}`, "
        f"`MIN_ACTIVE_CONTEXT_HOLD_BARS={CURRENT_HOLD_BARS}` → **{sens.get('parameter_verdict')}**.",
        f"- {POST_PERSISTENCE_NOTE}",
        f"- **{ready.get('required_statement')}**",
        "",
        "### Recommendations",
        "",
        f"- **Primary:** `{rec['primary']}`",
    ]
    for r in rec.get("all", []):
        if r != rec["primary"]:
            lines.append(f"- Secondary: `{r}`")
    lines.extend(["", "## 2. Runtime cycle summary", "", "```text"])
    for key in (
        "total_runtime_log_cycles",
        "current_run_cycle",
        "runtime_segments",
        "latest_5_cycles",
        "cycles_to_50k",
        "threshold_50k_reached",
        "runtime_log_mtime_utc",
        "max_cycle_seen",
        "note",
    ):
        lines.append(f"{key}: {cyc.get(key)}")
    lines.extend(["```", "", "## 3. Freshness / lag summary", "", "```text"])
    for key in (
        "live_to_auction_lag_min",
        "live_to_cognitive_lag_min",
        "live_to_final_context_lag_min",
        "live_to_lifecycle_lag_min",
        "live_to_visual_lag_min",
    ):
        lines.append(f"{key}: {fresh.get(key)}")
    lines.append("interpretation:")
    for note in fresh.get("interpretation", []):
        lines.append(f"  - {note}")
    lines.append("artifacts:")
    for name, info in (fresh.get("artifacts") or {}).items():
        lines.append(
            f"  {name}: exists={info.get('exists')} rows={info.get('rows')} "
            f"latest={info.get('latest_timestamp')} mtime={info.get('file_mtime_utc')} "
            f"lag_vs_live_min={info.get('lag_vs_live_min')}"
        )
    lines.extend(["```", "", "## 4. Context distribution", ""])
    lines.append("| window | rows | enough | directional% | observe% | challenged% | candidate% | invalidated% |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for name, bundle in payload["windows"].items():
        d = bundle["distribution"]
        lines.append(
            f"| `{name}` | {d.get('rows')} | {'yes' if d.get('sample_large_enough') else 'no'} | "
            f"{d.get('directional_active_pct')} | {d.get('observe_pct')} | {d.get('challenged_pct')} | "
            f"{d.get('candidate_pct')} | {d.get('invalidated_pct')} |"
        )
    for name, bundle in payload["windows"].items():
        d = bundle["distribution"]
        lines.append(f"\n### `{name}` detail\n")
        lines.append("```text")
        lines.append(f"raw_context: {d.get('raw_context')}")
        lines.append(f"active_context: {d.get('active_context')}")
        lines.append(f"lifecycle_state: {d.get('lifecycle_state')}")
        lines.append("```")

    lines.extend(["", "## 5. Directional episode quality", ""])
    lines.append("| window | dir_eps | avg | median | max | one_bar% | <=2bar% | >8bar% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, bundle in payload["windows"].items():
        e = bundle["episodes"]
        lines.append(
            f"| `{name}` | {e.get('directional_episodes')} | {e.get('avg_bars')} | {e.get('median_bars')} | "
            f"{e.get('max_bars')} | {e.get('one_bar_directional_episode_pct')} | "
            f"{e.get('short_lived_episode_pct')} | {e.get('long_lived_episode_pct')} |"
        )
    for name, bundle in payload["windows"].items():
        e = bundle["episodes"]
        lines.append(f"\n### `{name}` by side / reasons\n")
        lines.append("```text")
        lines.append(f"duration_buckets: {e.get('duration_buckets')}")
        lines.append(f"by_context: {e.get('by_context')}")
        lines.append(f"top_end_reasons: {dict(list((e.get('end_reason_counts') or {}).items())[:8])}")
        lines.append("```")

    lines.extend(["", "## 6. CHALLENGED behavior", ""])
    for name, bundle in payload["windows"].items():
        ch = bundle["challenged"]
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append("```text")
        for key in (
            "streak_count",
            "total_challenged_bars",
            "challenged_bars_pct_of_directional",
            "average_challenged_streak",
            "median_challenged_streak",
            "max_challenged_streak",
            "classification_counts",
        ):
            lines.append(f"{key}: {ch.get(key)}")
        lines.append("```")
        lines.append("")

    lines.extend(["", "## 7. Premature / late termination", ""])
    lines.append(
        "| window | classified | correct | premature | neut_fast | thesis_fast | too_slow | opposite |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, bundle in payload["windows"].items():
        t = bundle["termination"]
        lines.append(
            f"| `{name}` | {t.get('classified')} | {t.get('correct_termination_count')} | "
            f"{t.get('premature_termination_count')} | {t.get('neutralization_too_fast_count')} | "
            f"{t.get('thesis_rejection_too_fast_count')} | {t.get('too_slow_termination_count')} | "
            f"{t.get('opposite_replacement_count')} |"
        )

    lines.extend(["", "## 8. Formation → confirmation delay", ""])
    for name, bundle in payload["windows"].items():
        fd = bundle["formation_delay"]
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append("```text")
        lines.append(json.dumps(fd.get("by_context") or {}, indent=2, default=str)[:4000])
        lines.append("```")
        lines.append("")

    lines.extend(
        [
            "## 9. Lifecycle parameter sensitivity",
            "",
            f"Mode: `{sens.get('mode')}`  ",
            f"{sens.get('window_note')}",
            "",
            f"**Verdict:** `{sens.get('parameter_verdict')}`",
            "",
            "| rank | neut | hold | current | dir_eps | dir% | obs% | avg | 1bar | <=2 | stale_ch | neut_fast | too_slow | raw→OBS | score |",
            "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sens.get("rows") or []:
        lines.append(
            "| {rank} | {n} | {h} | {cur} | {de} | {dp} | {op} | {avg} | {ob} | {le2} | {st} | {nf} | {ts} | {ra} | {sc} |".format(
                rank=row.get("rank"),
                n=row.get("NEUTRALIZATION_CONFIRM_BARS"),
                h=row.get("MIN_ACTIVE_CONTEXT_HOLD_BARS"),
                cur="yes" if row.get("is_current") else "",
                de=row.get("directional_episode_count"),
                dp=row.get("active_directional_pct"),
                op=row.get("observe_pct"),
                avg=row.get("avg_episode_bars"),
                ob=row.get("one_bar_episode_count"),
                le2=row.get("le_2_bar_episode_count"),
                st=row.get("stale_challenged_count"),
                nf=row.get("premature_neutralization_count"),
                ts=row.get("too_slow_termination_count"),
                ra=row.get("raw_active_to_final_observe"),
                sc=row.get("score"),
            )
        )

    lines.extend(["", "## 10. Volume climax context check", "", "```text"])
    lines.append(json.dumps(payload.get("volume_climax") or {}, indent=2, default=str)[:6000])
    lines.extend(["```", "", "## 11. Live / postfactum limitation", "", "```text"])
    for k, v in lim.items():
        lines.append(f"{k}: {v}")
    lines.extend(["```", "", "## 12. Execution readiness implication", "", "```text"])
    for k, v in ready.items():
        lines.append(f"{k}: {v}")
    lines.extend(
        [
            "```",
            "",
            "## 13. Final recommendation",
            "",
            f"**Primary:** `{rec['primary']}`",
            "",
        ]
    )
    for r in rec.get("all", []):
        lines.append(f"- `{r}`")
    for note in rec.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "### Answers to stage questions",
            "",
            f"1. Context quality after fixes: **{rec.get('quality_acceptable_after_fixes')}**",
            "2. LONG/SHORT stability: see directional episode quality (one-bar / short-lived rates).",
            "3. OBSERVE usage: see active/raw distributions; raw ACTIVE→OBSERVE drops should stay 0.",
            "4. CHALLENGED usefulness: see classification counts (HEALTHY_DOUBT vs STALE_CONTEXT).",
            "5. Formation→confirmation delay: see section 8 (model delay, not execution lag).",
            "6. Termination timing: see premature / too-fast / too-slow counts.",
            f"7. Lifecycle params calibrated: **{sens.get('parameter_verdict')}**",
            "8. Model vs technical lag: see freshness interpretation.",
            f"9. Execution blocked by: {ready.get('blockers')}",
            f"10. Exact next step: **{rec['primary']}**",
            "",
            "## Scope confirmation",
            "",
            "- model / auction / cognitive / final / lifecycle logic unchanged",
            "- visualization / runtime / feed / dashboard / execution unchanged",
            "- action_allowed remains False; shadow_only remains True",
            "- no commits; read-only analysis only",
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(*, write_report: bool = True, sensitivity_max_rows: int = 1200) -> dict[str, Any]:
    now = pd.Timestamp.now(tz="UTC")
    cycles = parse_runtime_cycles(RUNTIME_LOG)

    live = load_parquet(LIVE_FEED)
    auction = load_parquet(AUCTION_PATH)
    cognitive = load_parquet(COGNITIVE_PATH)
    final = load_parquet(FINAL_PATH)
    lifecycle = load_parquet(LIFECYCLE_PATH)
    episodes = load_parquet(EPISODES_PATH)

    freshness = artifact_freshness(live, auction, cognitive, final, lifecycle, episodes)
    windows: dict[str, dict[str, Any]] = {}
    for name, start, end in analysis_windows(now):
        windows[name] = build_window_bundle(name, start, end, lifecycle, episodes)

    sensitivity = run_parameter_sensitivity(final, auction, max_rows=sensitivity_max_rows)
    climax = volume_climax_context_check(auction, lifecycle)
    limitations = live_postfactum_limitations(freshness)
    readiness = execution_readiness(lifecycle)
    recommendations = decide_recommendations(
        freshness=freshness,
        windows=windows,
        sensitivity=sensitivity,
        readiness=readiness,
        limitations=limitations,
    )

    # Optional status snapshots (must not fail if missing).
    shadow = None
    visual = None
    try:
        if SHADOW_STATUS.exists():
            shadow = json.loads(SHADOW_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        shadow = None
    try:
        if VISUAL_LATEST.exists():
            visual = json.loads(VISUAL_LATEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        visual = None

    payload = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "read_only": True,
        "post_persistence_note": POST_PERSISTENCE_NOTE,
        "runtime_cycles": cycles,
        "freshness": freshness,
        "windows": windows,
        "sensitivity": sensitivity,
        "volume_climax": climax,
        "limitations": limitations,
        "execution_readiness": readiness,
        "recommendations": recommendations,
        "shadow_status_present": shadow is not None,
        "visual_latest_present": visual is not None,
        "artifact_rows": {
            "live_market_feed": len(live),
            "auction_episode_memory": len(auction),
            "cognitive_market_state_memory": len(cognitive),
            "final_market_context_memory": len(final),
            "market_context_lifecycle_memory": len(lifecycle),
            "market_context_lifecycle_episodes": len(episodes),
        },
    }
    if write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
        payload["report_path"] = str(REPORT_PATH)
    return payload


def print_summary(payload: dict[str, Any]) -> None:
    cyc = payload["runtime_cycles"]
    rec = payload["recommendations"]
    print("======== MARKET CONTEXT STAGE REVIEW (read-only) ========")
    print(f"total_runtime_log_cycles: {cyc.get('total_runtime_log_cycles')}")
    print(f"current_run_cycle: {cyc.get('current_run_cycle')}")
    print(f"runtime_segments: {cyc.get('runtime_segments')}")
    print(f"cycles_to_50k: {cyc.get('cycles_to_50k')}")
    print(f"threshold_50k_reached: {cyc.get('threshold_50k_reached')}")
    print("--- focus POST_PERSISTENCE_FIX ---")
    focus = payload["windows"].get("POST_PERSISTENCE_FIX", {})
    print(f"rows: {focus.get('distribution', {}).get('rows')}")
    print(f"directional%: {focus.get('distribution', {}).get('directional_active_pct')}")
    print(f"one_bar%: {focus.get('episodes', {}).get('one_bar_directional_episode_pct')}")
    print(f"termination: {focus.get('termination', {}).get('counts')}")
    print(f"challenged classes: {focus.get('challenged', {}).get('classification_counts')}")
    print("--- sensitivity ---")
    print(f"parameter_verdict: {payload['sensitivity'].get('parameter_verdict')}")
    print(f"current: {payload['sensitivity'].get('current')}")
    print("--- readiness ---")
    print(f"execution_readiness: {payload['execution_readiness'].get('execution_readiness')}")
    print(f"blockers: {payload['execution_readiness'].get('blockers')}")
    print("--- recommendation ---")
    print(f"primary: {rec.get('primary')}")
    print(f"all: {rec.get('all')}")
    if payload.get("report_path"):
        print(f"report: {payload['report_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only market context stage review audit")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--sensitivity-max-rows", type=int, default=1200)
    args = parser.parse_args(argv)
    payload = run_audit(write_report=not args.no_report, sensitivity_max_rows=args.sensitivity_max_rows)
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
