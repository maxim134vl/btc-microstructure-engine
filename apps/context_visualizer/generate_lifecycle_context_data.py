#!/usr/bin/env python3
"""Generate context visualizer data from market context lifecycle memory/episodes.

Shadow-only visual layer. Does not touch pipeline / arbitration / execution.
Reads only:
  - data/live/live_market_feed.parquet
  - data/cognition/market_context_lifecycle_memory.parquet
  - data/cognition/market_context_lifecycle_episodes.parquet

Writes only under apps/context_visualizer/public/data/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

APP_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = APP_ROOT / "public" / "data"
BTC_ML_ROOT = Path(os.environ.get("BTC_ML_ROOT", str(APP_ROOT.parent.parent)))
# Back-compat alias for older imports/tests
SANDBOX_ROOT = APP_ROOT

LIVE_FEED_CANDIDATES = [
    BTC_ML_ROOT / "data" / "live" / "live_market_feed.parquet",
    BTC_ML_ROOT / "data" / "live_market_feed.parquet",
    BTC_ML_ROOT / "live_market_feed.parquet",
]
LIFECYCLE_MEMORY_PATH = BTC_ML_ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES_PATH = BTC_ML_ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
# Read-only source for the per-bar volume classification (display-only surfacing).
AUCTION_MEMORY_PATH = BTC_ML_ROOT / "data" / "cognition" / "auction_episode_memory.parquet"

CANDLES_OUT = OUTPUT_DIR / "lifecycle_candles.json"
EPISODES_OUT = OUTPUT_DIR / "lifecycle_context_episodes.json"
LATEST_OUT = OUTPUT_DIR / "lifecycle_latest.json"
UNCERTAINTY_OUT = OUTPUT_DIR / "lifecycle_uncertainty_segments.json"
CONTEXT_VISUAL_OUT = OUTPUT_DIR / "context_visual.json"

_DIRECTIONAL = {"LONG_CONTEXT", "SHORT_CONTEXT"}


def _directional(value: Any) -> str | None:
    text = _clean_text(value, default="")
    return text if text in _DIRECTIONAL else None


def _direction_word(direction: str) -> str:
    if direction == "LONG_CONTEXT":
        return "LONG"
    if direction == "SHORT_CONTEXT":
        return "SHORT"
    return "OBSERVE"


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


def load_volume_events() -> pd.DataFrame | None:
    """Load per-bar volume classification (bar_event) verbatim from auction memory.

    Display-only. Does not alter any parquet or volume classification logic — it only
    surfaces the existing ``bar_event`` column so the viewer can highlight climax bars.
    Returns None when the source or column is unavailable (viewer degrades gracefully).
    """
    if not AUCTION_MEMORY_PATH.exists():
        return None
    frame = pd.read_parquet(AUCTION_MEMORY_PATH)
    if "timestamp" not in frame.columns or "bar_event" not in frame.columns:
        return None
    work = frame[["timestamp", "bar_event"]].copy()
    work["timestamp"] = _to_utc_ts(work["timestamp"])
    work = work.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"], keep="last")
    return work.sort_values("timestamp")


def build_candle_rows(
    candles: pd.DataFrame,
    memory: pd.DataFrame,
    volume_events: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    mem = memory.copy()
    mem["timestamp"] = _to_utc_ts(mem["timestamp"])
    mem = mem.dropna(subset=["timestamp"]).sort_values("timestamp")
    keep = [
        "timestamp",
        "active_market_context",
        "lifecycle_state",
        "raw_market_context",
        "raw_context_status",
        "raw_cognitive_market_state",
        "raw_state_direction",
        "raw_auction_episode",
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
    # Exact-timestamp join for the per-bar volume event so climax classification is
    # never carried forward onto neighbouring bars.
    if volume_events is not None and len(volume_events):
        merged = merged.merge(volume_events, on="timestamp", how="left")
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
                # Per-bar volume classification (verbatim, display-only). All events are
                # preserved here; the viewer only *highlights* climax events by default.
                "volume_event": _clean_text(row.get("bar_event"), default="UNKNOWN"),
                "active_market_context": _clean_text(row.get("active_market_context"), default="OBSERVE"),
                "lifecycle_state": _clean_text(row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT"),
                "raw_market_context": _clean_text(row.get("raw_market_context"), default="OBSERVE"),
                "raw_context_status": _clean_text(row.get("raw_context_status"), default="OBSERVE"),
                "active_context_age_bars": _safe_int(row.get("active_context_age_bars"), default=0),
                "action_allowed": _safe_bool(row.get("action_allowed"), default=False),
                "candidate_context": _clean_text(row.get("candidate_context"), default="") or None,
                "challenge_context": _clean_text(row.get("challenge_context"), default="") or None,
                # Inspector fields (display-only; sourced verbatim from lifecycle memory).
                "auction_episode": _clean_text(row.get("raw_auction_episode"), default="UNKNOWN"),
                "auction_episode_status": _clean_text(row.get("raw_context_status"), default="UNKNOWN"),
                "cognitive_market_state": _clean_text(row.get("raw_cognitive_market_state"), default="UNKNOWN"),
                "cognitive_state_status": _clean_text(row.get("raw_state_direction"), default="UNKNOWN"),
                "previous_active_market_context": _clean_text(row.get("previous_active_market_context"), default="")
                or None,
                "invalidation_type": _clean_text(row.get("invalidation_type"), default="NONE"),
            }
        )
    return rows


def _classify_uncertainty(row: dict[str, Any]) -> tuple[str, str] | None:
    """Return (visual_type, direction) for CANDIDATE / CHALLENGED rows, else None.

    Confirmed ACTIVE directional bars return None — they stay on the confirmed
    episode layer and are drawn unchanged.
    """
    active = _clean_text(row.get("active_market_context"), default="OBSERVE")
    lifecycle = _clean_text(row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT")
    raw = _clean_text(row.get("raw_market_context"), default="OBSERVE")
    raw_status = _clean_text(row.get("raw_context_status"), default="OBSERVE")
    candidate = row.get("candidate_context")
    challenge = row.get("challenge_context")

    if lifecycle == "CHALLENGED":
        direction = _directional(active) or _directional(challenge) or _directional(raw) or "OBSERVE"
        return "CHALLENGED", direction
    if lifecycle == "CANDIDATE":
        direction = _directional(candidate) or _directional(raw) or "OBSERVE"
        return "CANDIDATE", direction
    # Developing directional context that has not been confirmed active yet.
    if raw_status == "DEVELOPING" and _directional(raw) and not _directional(active):
        return "CANDIDATE", _directional(raw)
    return None


def _segment_label(visual_type: str, direction: str) -> str:
    word = _direction_word(direction)
    if visual_type == "CANDIDATE":
        return f"CANDIDATE {word}" if word != "OBSERVE" else "CANDIDATE"
    if visual_type == "CHALLENGED":
        return f"CHALLENGED {word}" if word != "OBSERVE" else "CHALLENGED"
    if visual_type == "AUCTION_NEUTRALIZATION":
        return "AUCTION NEUTRALIZATION"
    if visual_type == "INVALIDATED":
        return "INVALIDATED"
    return visual_type


def _segment_from_run(run: list[dict[str, Any]], visual_type: str, direction: str) -> dict[str, Any]:
    head = run[0]
    tail = run[-1]
    return {
        "start_time": head["timestamp"],
        "end_time": tail["timestamp"],
        "start_time_unix": int(head["time"]),
        "end_time_unix": int(tail["time"]),
        "visual_type": visual_type,
        "direction": direction,
        "raw_market_context": head.get("raw_market_context", "OBSERVE"),
        "raw_context_status": head.get("raw_context_status", "OBSERVE"),
        "active_market_context": head.get("active_market_context", "OBSERVE"),
        "lifecycle_state": head.get("lifecycle_state", "NO_ACTIVE_CONTEXT"),
        "invalidation_type": head.get("invalidation_type", "NONE"),
        "previous_active_market_context": head.get("previous_active_market_context"),
        "label": _segment_label(visual_type, direction),
        "bars_count": len(run),
        "shadow_only": True,
    }


def _marker_from_row(row: dict[str, Any]) -> dict[str, Any]:
    inv_type = _clean_text(row.get("invalidation_type"), default="NONE")
    visual_type = "AUCTION_NEUTRALIZATION" if inv_type == "AUCTION_NEUTRALIZATION" else "INVALIDATED"
    return {
        "start_time": row["timestamp"],
        "end_time": row["timestamp"],
        "start_time_unix": int(row["time"]),
        "end_time_unix": int(row["time"]),
        "visual_type": visual_type,
        # Markers are boundary events — never drawn as opposite directional context.
        "direction": "OBSERVE",
        "raw_market_context": row.get("raw_market_context", "OBSERVE"),
        "raw_context_status": row.get("raw_context_status", "OBSERVE"),
        "active_market_context": row.get("active_market_context", "OBSERVE"),
        "lifecycle_state": row.get("lifecycle_state", "NO_ACTIVE_CONTEXT"),
        "invalidation_type": inv_type,
        "previous_active_market_context": row.get("previous_active_market_context"),
        "label": _segment_label(visual_type, "OBSERVE"),
        "shadow_only": True,
    }


def build_uncertainty_segments(candle_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coalesce CANDIDATE/CHALLENGED runs + emit INVALIDATED/NEUTRALIZATION boundary markers.

    Shadow-only visual overlay. Confirmed active context is left to the episode
    layer and is not duplicated here.
    """
    segments: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    marker_times: set[int] = set()

    run: list[dict[str, Any]] = []
    run_type: str | None = None
    run_dir: str | None = None
    prev_inv: str | None = None

    def flush() -> None:
        nonlocal run, run_type, run_dir
        if run and run_type is not None and run_dir is not None:
            segments.append(_segment_from_run(run, run_type, run_dir))
        run = []
        run_type = None
        run_dir = None

    for row in candle_rows:
        classification = _classify_uncertainty(row)
        if classification is None:
            flush()
        else:
            visual_type, direction = classification
            if run and run_type == visual_type and run_dir == direction:
                run.append(row)
            else:
                flush()
                run = [row]
                run_type = visual_type
                run_dir = direction

        # Boundary markers (independent of region runs).
        inv_type = _clean_text(row.get("invalidation_type"), default="NONE")
        lifecycle = _clean_text(row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT")
        is_boundary = lifecycle == "INVALIDATED" or (
            inv_type == "AUCTION_NEUTRALIZATION" and prev_inv != "AUCTION_NEUTRALIZATION"
        )
        if is_boundary:
            t = int(row["time"])
            if t not in marker_times:
                marker_times.add(t)
                markers.append(_marker_from_row(row))
        prev_inv = inv_type

    flush()
    combined = segments + markers
    combined.sort(key=lambda seg: seg["start_time_unix"])
    return combined


def build_episode_rows(episodes: pd.DataFrame, latest_candle_ts: pd.Timestamp) -> list[dict[str, Any]]:
    """Collapse duplicate episode_id carry rows into one continuous visual band."""
    try:
        from trading_truth import collapse_lifecycle_episodes
    except Exception:
        from apps.context_visualizer.trading_truth import collapse_lifecycle_episodes  # type: ignore

    latest = latest_candle_ts
    if latest is not None and pd.notna(latest):
        latest = pd.Timestamp(latest)
        if latest.tzinfo is None:
            latest = latest.tz_localize("UTC")
        else:
            latest = latest.tz_convert("UTC")
    else:
        latest = None
    return collapse_lifecycle_episodes(episodes, latest_evaluation=latest)


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
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    # Patch 1: read-model metadata sidecar only.
    try:
        if path.name == "lifecycle_latest.json":
            repo = Path(__file__).resolve().parents[2]
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            from runtime_dataset_metadata import emit_metadata_for_path

            emit_metadata_for_path(
                "apps/context_visualizer/public/data/lifecycle_latest.json",
                root=repo,
                metadata_origin="LIVE_WRITER",
            )
    except Exception:
        pass


def emit_timeframe_chart_truth_if_enabled() -> Path | None:
    """Atomic timeframe_chart_truth write.

    Always ON under LIVE1B so active charts cannot retain legacy markers.
    Otherwise requires ENABLE_TIMEFRAME_CHART_TRUTH=1 or TIMEFRAME_CHART_TRUTH_OUT.
    """
    try:
        from active_epoch_trade_filter import live1b_paper_active  # type: ignore
    except Exception:
        live1b_paper_active = lambda: False  # type: ignore

    explicit = (os.environ.get("TIMEFRAME_CHART_TRUTH_OUT") or "").strip()
    enabled = (os.environ.get("ENABLE_TIMEFRAME_CHART_TRUTH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not explicit and not enabled and not live1b_paper_active():
        return None
    try:
        from timeframe_chart_truth import PUBLIC_CHART_TRUTH, write_timeframe_chart_truth
    except Exception as exc:  # pragma: no cover - optional path
        print(f"WARN: timeframe_chart_truth unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    target = Path(explicit) if explicit else PUBLIC_CHART_TRUTH
    write_timeframe_chart_truth(target)
    print(f"timeframe_chart_truth written: {target}")
    return target


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

    volume_events = load_volume_events()
    candle_rows = build_candle_rows(candles, memory, volume_events=volume_events)
    latest_candle_ts = candles["timestamp"].iloc[-1] if len(candles) else pd.NaT
    episode_rows = build_episode_rows(episodes_frame, latest_candle_ts)
    latest = build_latest(memory, episode_rows)
    uncertainty_segments = build_uncertainty_segments(candle_rows)

    write_json(CANDLES_OUT, {"source": "live_market_feed", "rows": candle_rows})
    write_json(EPISODES_OUT, episode_rows)
    write_json(LATEST_OUT, latest)
    write_json(
        UNCERTAINTY_OUT,
        {
            "source": "market_context_lifecycle_memory",
            "shadow_only": True,
            "segments": uncertainty_segments,
        },
    )
    write_json(
        CONTEXT_VISUAL_OUT,
        {
            "generated_at_utc": _iso(pd.Timestamp.now(tz="UTC")),
            "source": "generate_lifecycle_context_data",
            "latest": latest,
            "active_market_context": latest.get("active_market_context"),
            "lifecycle_state": latest.get("lifecycle_state"),
            "latest_decision_timestamp": latest.get("timestamp"),
            "candles_count": len(candle_rows),
            "episodes_count": len(episode_rows),
            "shadow_only": True,
            "visual_only": True,
            "execution_enabled": False,
        },
    )

    candidate_count = sum(1 for s in uncertainty_segments if s["visual_type"] == "CANDIDATE")
    challenged_count = sum(1 for s in uncertainty_segments if s["visual_type"] == "CHALLENGED")
    neutralization_count = sum(1 for s in uncertainty_segments if s["visual_type"] == "AUCTION_NEUTRALIZATION")
    invalidated_count = sum(1 for s in uncertainty_segments if s["visual_type"] == "INVALIDATED")

    print(f"candles written: {len(candle_rows)}")
    print(f"episodes written: {len(episode_rows)}")
    print(f"uncertainty segments written: {len(uncertainty_segments)}")
    print(f"  candidate segments: {candidate_count}")
    print(f"  challenged segments: {challenged_count}")
    print(f"  auction_neutralization markers: {neutralization_count}")
    print(f"  invalidated markers: {invalidated_count}")
    buying_climax = sum(1 for r in candle_rows if r.get("volume_event") == "BUYING_CLIMAX")
    selling_climax = sum(1 for r in candle_rows if r.get("volume_event") == "SELLING_CLIMAX")
    print(f"volume highlight (default): BUYING_CLIMAX={buying_climax} SELLING_CLIMAX={selling_climax}")
    print(f"context blocks (LONG/SHORT): {latest.get('context_blocks_count')}")
    print(f"latest active_market_context: {latest.get('active_market_context')}")
    print(f"latest lifecycle_state: {latest.get('lifecycle_state')}")
    print(f"latest active_context_age_bars: {latest.get('active_context_age_bars')}")
    print(f"output candles: {CANDLES_OUT}")
    print(f"output episodes: {EPISODES_OUT}")
    print(f"output latest: {LATEST_OUT}")
    print(f"output uncertainty: {UNCERTAINTY_OUT}")
    emit_timeframe_chart_truth_if_enabled()
    return 0


if __name__ == "__main__":
    sys.exit(main())
