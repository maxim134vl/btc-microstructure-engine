#!/usr/bin/env python3
"""Generate sandbox visual data from market context lifecycle memory/episodes.

Shadow-only visual layer. Does not touch pipeline / arbitration / execution.
Reads only:
  - data/live/live_market_feed.parquet
  - data/cognition/market_context_lifecycle_memory.parquet
  - data/cognition/market_context_lifecycle_episodes.parquet
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SANDBOX_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = SANDBOX_ROOT / "public" / "data"
BTC_ML_ROOT = Path(os.environ.get("BTC_ML_ROOT", str(SANDBOX_ROOT.parent.parent)))

LIVE_FEED_CANDIDATES = [
    BTC_ML_ROOT / "data" / "live" / "live_market_feed.parquet",
    BTC_ML_ROOT / "data" / "live_market_feed.parquet",
    BTC_ML_ROOT / "live_market_feed.parquet",
]
LIFECYCLE_MEMORY_PATH = BTC_ML_ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES_PATH = BTC_ML_ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"

CANDLES_OUT = OUTPUT_DIR / "lifecycle_candles.json"
EPISODES_OUT = OUTPUT_DIR / "lifecycle_context_episodes.json"
LATEST_OUT = OUTPUT_DIR / "lifecycle_latest.json"


def _find_live_feed() -> Path | None:
    for path in LIVE_FEED_CANDIDATES:
        if path.exists():
            return path
    matches = sorted(BTC_ML_ROOT.glob("**/live_market_feed.parquet"))
    return matches[0] if matches else None


def _to_utc_ts(series: pd.Series) -> pd.Series:
    # Normalize to ns UTC so merge_asof does not fail on ms vs us dtypes.
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, default: str = "UNKNOWN") -> str:
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes"}:
        return True
    if text in {"0", "false", "f", "no"}:
        return False
    return bool(value)


def load_candles(feed_path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(feed_path)
    if "timestamp" not in frame.columns:
        raise ValueError(f"{feed_path} missing timestamp")
    work = frame.copy()
    work["timestamp"] = _to_utc_ts(work["timestamp"])
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        if col not in work.columns:
            raise ValueError(f"{feed_path} missing {col}")
        work[col] = pd.to_numeric(work[col], errors="coerce")
    if "volume" in work.columns:
        work["volume"] = pd.to_numeric(work["volume"], errors="coerce").fillna(0.0)
    else:
        work["volume"] = 0.0
    work = work.dropna(subset=["open", "high", "low", "close"])
    return work


def build_candle_rows(candles: pd.DataFrame, memory: pd.DataFrame) -> list[dict[str, Any]]:
    mem = memory.copy()
    mem["timestamp"] = _to_utc_ts(mem["timestamp"])
    mem = mem.dropna(subset=["timestamp"]).sort_values("timestamp")
    keep = [
        "timestamp",
        "active_market_context",
        "lifecycle_state",
        "raw_market_context",
        "active_context_age_bars",
        "action_allowed",
        "action_reason",
        "transition_reason",
        "challenge_context",
        "candidate_context",
        "previous_active_market_context",
        "invalidation_type",
        "invalidation_reason",
    ]
    keep = [c for c in keep if c in mem.columns]
    merged = pd.merge_asof(
        candles.sort_values("timestamp"),
        mem[keep],
        on="timestamp",
        direction="backward",
        tolerance=pd.Timedelta("2h"),
    )
    rows: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        ts = row["timestamp"]
        rows.append(
            {
                "timestamp": _iso(ts),
                "time": int(pd.Timestamp(ts).timestamp()),
                "open": _safe_float(row["open"]),
                "high": _safe_float(row["high"]),
                "low": _safe_float(row["low"]),
                "close": _safe_float(row["close"]),
                "volume": _safe_float(row["volume"]) or 0.0,
                "active_market_context": _clean_text(row.get("active_market_context"), default="OBSERVE"),
                "lifecycle_state": _clean_text(row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT"),
                "raw_market_context": _clean_text(row.get("raw_market_context"), default="OBSERVE"),
                "active_context_age_bars": _safe_int(row.get("active_context_age_bars"), default=0),
                "action_allowed": _safe_bool(row.get("action_allowed"), default=False),
                "previous_active_market_context": _clean_text(row.get("previous_active_market_context"), default="")
                or None,
                "invalidation_type": _clean_text(row.get("invalidation_type"), default="NONE"),
            }
        )
    return rows


def build_episode_rows(episodes: pd.DataFrame, latest_candle_ts: pd.Timestamp) -> list[dict[str, Any]]:
    work = episodes.copy()
    work["start_time"] = _to_utc_ts(work["start_time"])
    work["end_time"] = _to_utc_ts(work["end_time"])
    work = work.dropna(subset=["start_time", "end_time"]).sort_values("start_time").reset_index(drop=True)

    out: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        bars = max(1, _safe_int(row.get("bars_count"), default=1))
        challenged = _safe_int(row.get("challenged_bars_count"), default=0)
        challenge_ratio = float(challenged) / float(bars)
        end_reason = _clean_text(row.get("end_reason"), default="")
        end_time = row["end_time"]
        # Keep open episode painted through latest candle when memory lags feed.
        if "latest open" in end_reason.lower() and latest_candle_ts is not None and pd.notna(latest_candle_ts):
            if end_time < latest_candle_ts:
                end_time = latest_candle_ts
        context = _clean_text(row.get("active_market_context"), default="OBSERVE")
        out.append(
            {
                "episode_id": _safe_int(row.get("episode_id"), default=0),
                "context": context,
                "start_time": _iso(row["start_time"]),
                "end_time": _iso(end_time),
                "start_time_unix": int(pd.Timestamp(row["start_time"]).timestamp()),
                "end_time_unix": int(pd.Timestamp(end_time).timestamp()),
                "bars_count": bars,
                "duration_minutes": _safe_float(row.get("duration_minutes")) or 0.0,
                "dominant_lifecycle_state": _clean_text(row.get("dominant_lifecycle_state"), default="UNKNOWN"),
                "challenged_bars_count": challenged,
                "challenge_ratio": round(challenge_ratio, 4),
                "start_reason": _clean_text(row.get("start_reason"), default="UNKNOWN"),
                "end_reason": end_reason or "UNKNOWN",
            }
        )
    return out


def build_status_line(latest: pd.Series | dict[str, Any]) -> str:
    active = _clean_text(
        latest.get("active_market_context") if hasattr(latest, "get") else latest["active_market_context"],
        default="OBSERVE",
    )
    lifecycle = _clean_text(
        latest.get("lifecycle_state") if hasattr(latest, "get") else latest["lifecycle_state"],
        default="NO_ACTIVE_CONTEXT",
    )
    action = _safe_bool(
        latest.get("action_allowed") if hasattr(latest, "get") else latest.get("action_allowed"),
        default=False,
    )
    action_text = "action enabled" if action else "action disabled"
    if active == "OBSERVE":
        prev = _clean_text(
            latest.get("previous_active_market_context") if hasattr(latest, "get") else None,
            default="",
        )
        inv_type = _clean_text(
            latest.get("invalidation_type") if hasattr(latest, "get") else None,
            default="NONE",
        )
        if prev and inv_type != "NONE":
            return f"{active} · {lifecycle} · previous {prev} invalidated · {inv_type}"
        return f"{active} · {lifecycle} · no active directional context · {action_text}"
    age = _safe_int(
        latest.get("active_context_age_bars") if hasattr(latest, "get") else 0,
        default=0,
    )
    return f"{active} · {lifecycle} · age {age} bars · {action_text}"


def build_latest(memory: pd.DataFrame, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    if memory is None or len(memory) == 0:
        return {
            "source": "market_context_lifecycle_memory",
            "episodes_source": "market_context_lifecycle_episodes",
            "active_market_context": "OBSERVE",
            "lifecycle_state": "NO_ACTIVE_CONTEXT",
            "active_context_age_bars": 0,
            "action_allowed": False,
            "action_reason": "shadow market context only; execution disabled",
            "status_line": "OBSERVE · NO_ACTIVE_CONTEXT · no active directional context · action disabled",
            "shadow_only": True,
        }
    latest = memory.iloc[-1]
    open_episode = None
    for episode in reversed(episodes):
        if "latest open" in str(episode.get("end_reason", "")).lower():
            open_episode = episode
            break
    if open_episode is None and episodes:
        open_episode = episodes[-1]
    payload = {
        "source": "market_context_lifecycle_memory",
        "episodes_source": "market_context_lifecycle_episodes",
        "timestamp": _iso(latest.get("timestamp")),
        "close": _safe_float(latest.get("close")),
        "raw_market_context": _clean_text(latest.get("raw_market_context"), default="OBSERVE"),
        "active_market_context": _clean_text(latest.get("active_market_context"), default="OBSERVE"),
        "lifecycle_state": _clean_text(latest.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT"),
        "active_context_age_bars": _safe_int(latest.get("active_context_age_bars"), default=0),
        "action_allowed": _safe_bool(latest.get("action_allowed"), default=False),
        "action_reason": _clean_text(latest.get("action_reason"), default="UNKNOWN"),
        "transition_reason": _clean_text(latest.get("transition_reason"), default="UNKNOWN"),
        "challenge_context": _clean_text(latest.get("challenge_context"), default="") or None,
        "previous_active_market_context": _clean_text(latest.get("previous_active_market_context"), default="")
        or None,
        "invalidation_type": _clean_text(latest.get("invalidation_type"), default="NONE"),
        "invalidation_reason": _clean_text(latest.get("invalidation_reason"), default="") or None,
        "invalidated_at": _iso(latest.get("invalidated_at")) if "invalidated_at" in latest.index else None,
        "shadow_only": True,
        "open_episode_id": open_episode.get("episode_id") if open_episode else None,
        "open_episode_context": open_episode.get("context") if open_episode else None,
        "open_episode_challenge_ratio": open_episode.get("challenge_ratio") if open_episode else None,
        "open_episode_challenged_bars_count": open_episode.get("challenged_bars_count") if open_episode else None,
        "context_blocks_count": sum(1 for ep in episodes if ep.get("context") in {"LONG_CONTEXT", "SHORT_CONTEXT"}),
        "episodes_count": len(episodes),
    }
    # Enforce OBSERVE age semantics in visual payload even if upstream is stale.
    if payload["active_market_context"] == "OBSERVE":
        payload["active_context_age_bars"] = 0
    payload["status_line"] = build_status_line(payload)
    return payload

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def main() -> int:
    feed_path = _find_live_feed()
    if feed_path is None:
        print("ERROR: live_market_feed.parquet not found", file=sys.stderr)
        return 1
    if not LIFECYCLE_MEMORY_PATH.exists():
        print(
            f"ERROR: missing {LIFECYCLE_MEMORY_PATH}\n"
            "Run scripts/research/build_market_context_lifecycle_memory.py first.",
            file=sys.stderr,
        )
        return 1
    if not LIFECYCLE_EPISODES_PATH.exists():
        print(
            f"ERROR: missing {LIFECYCLE_EPISODES_PATH}\n"
            "Run scripts/research/build_market_context_lifecycle_memory.py first.",
            file=sys.stderr,
        )
        return 1

    candles = load_candles(feed_path)
    memory = pd.read_parquet(LIFECYCLE_MEMORY_PATH)
    episodes_frame = pd.read_parquet(LIFECYCLE_EPISODES_PATH)

    candle_rows = build_candle_rows(candles, memory)
    latest_candle_ts = candles["timestamp"].iloc[-1] if len(candles) else pd.NaT
    episode_rows = build_episode_rows(episodes_frame, latest_candle_ts)
    latest = build_latest(memory, episode_rows)

    write_json(CANDLES_OUT, {"source": "live_market_feed", "rows": candle_rows})
    write_json(EPISODES_OUT, episode_rows)
    write_json(LATEST_OUT, latest)

    print(f"candles written: {len(candle_rows)}")
    print(f"episodes written: {len(episode_rows)}")
    print(f"context blocks (LONG/SHORT): {latest.get('context_blocks_count')}")
    print(f"latest active_market_context: {latest.get('active_market_context')}")
    print(f"latest lifecycle_state: {latest.get('lifecycle_state')}")
    print(f"latest active_context_age_bars: {latest.get('active_context_age_bars')}")
    print(f"output candles: {CANDLES_OUT}")
    print(f"output episodes: {EPISODES_OUT}")
    print(f"output latest: {LATEST_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
