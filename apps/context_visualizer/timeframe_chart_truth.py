"""VIS3A — Isolated native timeframe chart workspace truth (read-only).

Builds a single visualizer payload with:
  - M15 native candles from live_market_feed
  - M30/H1/H4 completed bars via multi_timeframe_availability.build_completed_bars
  - per-TF state / positions / trades (strict TF book isolation)
  - per-TF historical context segments from timeframe_command_memory
  - global lifecycle kept for lineage/tooltips only (not a visual strip)
  - per-TF performance projection from trading_performance_truth

Side-effect free when only build_* is called. Atomic writers are explicit.
Does not modify manager, traders, books, OPS, or aggregation logic.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(os.environ.get("BTC_ML_ROOT", Path(__file__).resolve().parents[2]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from multi_timeframe_availability import (  # noqa: E402
    DURATION_S,
    build_completed_bars,
)

SCHEMA_VERSION = "timeframe_chart_truth_v4"
TIMEFRAMES = ("M15", "M30", "H1", "H4")
DEFAULT_WINDOW_DAYS = 7
COMMAND_MEMORY = ROOT / "data" / "trading" / "manager" / "timeframe_command_memory.parquet"

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
MTF_AVAILABILITY = ROOT / "data" / "runtime" / "multi_timeframe_availability_latest.json"
MANAGER_LATEST = ROOT / "data" / "runtime" / "timeframe_manager_latest.json"
TRADER_BOOKS_ROOT = ROOT / "data" / "trading" / "timeframe_traders"
PUBLIC_DATA = ROOT / "apps" / "context_visualizer" / "public" / "data"
PUBLIC_CHART_TRUTH = PUBLIC_DATA / "timeframe_chart_truth.json"
CANDIDATE_DIR = (
    ROOT
    / "data"
    / "candidate"
    / "architecture_recovery"
    / "vis_trade_render_context_fix"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_utc(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _iso(value: Any) -> str | None:
    ts = _to_utc(value)
    return None if ts is None else ts.isoformat().replace("+00:00", "Z")


def _f(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _txt(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = _txt(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clean_num(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def write_json_atomic(path: Path, payload: Any) -> None:
    """Temp → fsync → atomic replace. No partial public JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_m15_feed(path: Path | None = None) -> pd.DataFrame:
    feed = path or LIVE_FEED
    if not feed.exists():
        raise FileNotFoundError(f"SOURCE_UNAVAILABLE: {feed}")
    frame = pd.read_parquet(feed)
    if "timestamp" not in frame.columns:
        raise ValueError("SCHEMA_INVALID: live feed missing timestamp")
    work = frame.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        if col not in work.columns:
            raise ValueError(f"SCHEMA_INVALID: live feed missing {col}")
        work[col] = pd.to_numeric(work[col], errors="coerce")
    if "volume" in work.columns:
        work["volume"] = pd.to_numeric(work["volume"], errors="coerce").fillna(0.0)
    else:
        work["volume"] = 0.0
    work = work.dropna(subset=["open", "high", "low", "close"])
    return work


def resolve_window(
    m15: pd.DataFrame,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if m15 is None or len(m15) == 0:
        raise ValueError("INSUFFICIENT_HISTORY: empty M15")
    tip_open = _to_utc(m15["timestamp"].max())
    assert tip_open is not None
    # Latest confirmed M15 close boundary (= tip open + 15m for closed feed rows).
    window_end = tip_open + pd.Timedelta(seconds=DURATION_S["M15"])
    window_start = window_end - pd.Timedelta(days=int(window_days))
    return window_start, window_end


def bars_to_candles(bars: pd.DataFrame, timeframe: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, raw in bars.iterrows():
        open_v = _f(raw.get("open"))
        high_v = _f(raw.get("high"))
        low_v = _f(raw.get("low"))
        close_v = _f(raw.get("close"))
        if None in (open_v, high_v, low_v, close_v):
            continue
        bar_open = _to_utc(raw.get("bar_open") or raw.get("timestamp"))
        bar_close = _to_utc(raw.get("bar_close"))
        if bar_open is None:
            continue
        if bar_close is None:
            bar_close = bar_open + pd.Timedelta(seconds=DURATION_S[timeframe])
        rows.append(
            {
                "timestamp": _iso(bar_open),
                "bar_open": _iso(bar_open),
                "bar_close": _iso(bar_close),
                "open": open_v,
                "high": high_v,
                "low": low_v,
                "close": close_v,
                "volume": _f(raw.get("volume")) or 0.0,
                "confirmed": True,
            }
        )
    return rows



def _load_visual_volume_events(timeframe: str) -> dict[pd.Timestamp, str]:
    """Load already-classified volume events for chart rendering only.

    Legacy lifecycle_candles rows without an explicit timeframe are treated
    conservatively as M15 only. They must never be copied onto M30/H1/H4.
    """
    import json

    path = PUBLIC_DATA / "lifecycle_candles.json"
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}

    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}

    target_tf = str(timeframe or "").upper()
    events: dict[pd.Timestamp, str] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        row_tf = str(row.get("timeframe") or row.get("tf") or "").upper()

        # Explicit TF must match.
        if row_tf and row_tf != target_tf:
            continue

        # Legacy rows have no TF. Do not contaminate senior timeframes.
        if not row_tf and target_tf != "M15":
            continue

        event = str(row.get("volume_event") or "").strip().upper()
        if not event:
            continue

        raw_ts = (
            row.get("bar_open")
            or row.get("bar_open_timestamp")
            or row.get("timestamp")
        )
        ts = pd.to_datetime(raw_ts, utc=True, errors="coerce")
        if pd.isna(ts):
            continue

        events[ts] = event

    return events


def _attach_volume_events(candles: list[dict[str, Any]], timeframe: str) -> None:
    events = _load_visual_volume_events(timeframe)
    if not events:
        return

    for candle in candles:
        raw_ts = (
            candle.get("bar_open")
            or candle.get("bar_open_timestamp")
            or candle.get("timestamp")
        )
        ts = pd.to_datetime(raw_ts, utc=True, errors="coerce")
        if pd.isna(ts):
            continue

        event = events.get(ts)
        if event:
            candle["volume_event"] = event


def build_tf_candles(
    m15: pd.DataFrame,
    timeframe: str,
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> dict[str, Any]:
    missing = timeframe not in TIMEFRAMES
    if missing:
        return {
            "timeframe": timeframe,
            "source": None,
            "aggregation": None,
            "timestamp_semantics": "BAR_OPEN",
            "confirmed_only": True,
            "latest_confirmed_open": None,
            "latest_confirmed_close": None,
            "freshness_status": "SOURCE_UNAVAILABLE",
            "candles": [],
            "error": "unknown timeframe",
        }

    try:
        bars = build_completed_bars(m15, timeframe, evaluation_timestamp=window_end)
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "timeframe": timeframe,
            "source": "data/live/live_market_feed.parquet",
            "aggregation": "native" if timeframe == "M15" else f"build_completed_bars:{timeframe}",
            "timestamp_semantics": "BAR_OPEN",
            "confirmed_only": True,
            "latest_confirmed_open": None,
            "latest_confirmed_close": None,
            "freshness_status": "SOURCE_UNAVAILABLE",
            "candles": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    if len(bars):
        opens = pd.to_datetime(bars["bar_open"], utc=True)
        closes = pd.to_datetime(bars["bar_close"], utc=True)
        mask = (closes >= window_start) & (closes <= window_end)
        bars = bars.loc[mask].copy()

    candles = bars_to_candles(bars, timeframe)
    _attach_volume_events(candles, timeframe)
    latest_open = candles[-1]["bar_open"] if candles else None
    latest_close = candles[-1]["bar_close"] if candles else None
    source = "data/live/live_market_feed.parquet"
    aggregation = "native" if timeframe == "M15" else f"build_completed_bars:{timeframe}"
    block = {
        "timeframe": timeframe,
        "source": source,
        "aggregation": aggregation,
        "timestamp_semantics": "BAR_OPEN",
        "timezone": "UTC",
        "confirmed_only": True,
        "latest_confirmed_open": latest_open,
        "latest_confirmed_close": latest_close,
        "freshness_status": "FRESH" if candles else "SOURCE_UNAVAILABLE",
        "candle_count": len(candles),
        "candles": candles,
        "includes_live_partial": False,
        "partial_source": None,
    }
    return append_live1a_partial_candle(block, timeframe)


def append_live1a_partial_candle(candle_block: dict[str, Any], timeframe: str) -> dict[str, Any]:
    """Append/replace current LIVE1A partial bar so intrabar fills anchor correctly."""
    cog = _read_json(LIVE1A_HEALTH)
    if not cog:
        return candle_block
    bars = cog.get("partial_bars") if isinstance(cog.get("partial_bars"), dict) else {}
    bar = bars.get(timeframe) if isinstance(bars.get(timeframe), dict) else None
    if not bar:
        return candle_block
    bar_open = _iso(bar.get("bar_open_timestamp"))
    if not bar_open:
        return candle_block
    open_v = _f(bar.get("open"))
    high_v = _f(bar.get("high") if bar.get("high") is not None else bar.get("high_so_far"))
    low_v = _f(bar.get("low") if bar.get("low") is not None else bar.get("low_so_far"))
    close_v = _f(bar.get("close") if bar.get("close") is not None else bar.get("last"))
    if None in (open_v, high_v, low_v, close_v):
        return candle_block
    open_ts = _to_utc(bar_open)
    if open_ts is None:
        return candle_block
    bar_close = _iso(open_ts + pd.Timedelta(seconds=int(DURATION_S.get(timeframe, 0))))
    partial = {
        "timestamp": bar_open,
        "bar_open": bar_open,
        "bar_close": bar_close,
        "open": open_v,
        "high": high_v,
        "low": low_v,
        "close": close_v,
        "volume": _f(bar.get("volume") if bar.get("volume") is not None else bar.get("volume_so_far")) or 0.0,
        "confirmed": False,
        "is_partial": True,
        "causal_cutoff_timestamp": _iso(bar.get("causal_cutoff_timestamp")),
        "partial_source": "LIVE1A_INTRABAR_COGNITION_HEALTH",
    }
    candles = list(candle_block.get("candles") or [])
    if candles and str(candles[-1].get("bar_open") or "") == bar_open:
        candles[-1] = partial
    else:
        candles.append(partial)
    candle_block = dict(candle_block)
    candle_block["candles"] = candles
    candle_block["candle_count"] = len(candles)
    candle_block["confirmed_only"] = False
    candle_block["includes_live_partial"] = True
    candle_block["partial_source"] = "LIVE1A_INTRABAR_COGNITION_HEALTH"
    candle_block["latest_partial_open"] = bar_open
    candle_block["freshness_status"] = "FRESH"
    return candle_block


def _map_availability_status(raw: str | None) -> str:
    text = (raw or "").upper()
    if text == "FRESH_EVENT":
        return "FRESH"
    if text == "AVAILABLE_LAST_CONFIRMED":
        return "AVAILABLE_LAST_CONFIRMED"
    if text in {"UPSTREAM_STALE", "WRITER_STALE", "WRITER_DEAD"}:
        return "STALE"
    if text in {"DATASET_MISSING", "SCHEMA_INVALID", "INSUFFICIENT_HISTORY"}:
        return "SOURCE_UNAVAILABLE"
    if text in {"TIMEFRAME_NOT_LIVE"}:
        return "NOT_LIVE"
    return text or "SOURCE_UNAVAILABLE"


LIVE1A_HEALTH = ROOT / "data" / "runtime" / "intrabar_cognition_health.json"
INTRABAR_CONTEXT_JOURNAL = ROOT / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"


def _direction_from_context(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"LONG", "LONG_CONTEXT"} or text.startswith("LONG"):
        return "LONG"
    if text in {"SHORT", "SHORT_CONTEXT"} or text.startswith("SHORT"):
        return "SHORT"
    return None


def _candle_lookup(candles: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in candles or []:
        key = str(row.get("bar_open") or row.get("timestamp") or "")
        if key:
            out[key] = row
    return out


def load_intrabar_context_events_for_tf(
    timeframe: str,
    *,
    candles: list[dict[str, Any]] | None = None,
    paper_epoch_id: str | None = None,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Export CONTEXT_* journal rows for one TF with bar-anchor enrichment."""
    if not INTRABAR_CONTEXT_JOURNAL.exists():
        return []
    try:
        from btc_ml.live.intrabar.partial_bar_state import TF_SECONDS, bar_open_for
    except Exception:
        return []

    candle_by_open = _candle_lookup(candles)
    rows: list[dict[str, Any]] = []
    for line in INTRABAR_CONTEXT_JOURNAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        if str(raw.get("timeframe") or "").upper() != timeframe.upper():
            continue
        event_type = str(raw.get("event_type") or "").upper()
        if event_type not in {"CONTEXT_START", "CONTEXT_END", "CONTEXT_FLIP"}:
            continue
        stamped_epoch = _txt(raw.get("paper_epoch_id"))
        if paper_epoch_id and stamped_epoch and stamped_epoch != paper_epoch_id:
            continue
        event_ts = _iso(raw.get("event_timestamp") or raw.get("causal_cutoff_timestamp"))
        if not event_ts:
            continue
        stamp = _to_utc(event_ts)
        if stamp is None:
            continue
        if window_start is not None and stamp < window_start - pd.Timedelta(days=1):
            continue
        if window_end is not None and stamp > window_end + pd.Timedelta(hours=12):
            continue
        try:
            bar_open_ts = bar_open_for(event_ts, timeframe)
            bar_open = bar_open_ts.isoformat().replace("+00:00", "Z")
            scheduled = bar_open_ts + pd.Timedelta(seconds=int(TF_SECONDS[timeframe]))
            scheduled_close = scheduled.isoformat().replace("+00:00", "Z")
        except Exception:
            bar_open = None
            scheduled_close = None
        candle = candle_by_open.get(bar_open or "")
        confirmed = bool(candle.get("confirmed")) if candle else None
        is_partial = bool(candle.get("is_partial")) if candle else None
        if candle is None:
            bar_status = "UNKNOWN"
            final_close = None
            final_close_ts = None
        elif is_partial or confirmed is False:
            bar_status = "OPEN"
            final_close = None
            final_close_ts = None
        else:
            bar_status = "CONFIRMED"
            final_close = _f(candle.get("close"))
            final_close_ts = _iso(candle.get("bar_close") or scheduled_close)

        direction = _direction_from_context(raw.get("new_context")) or _direction_from_context(
            raw.get("previous_context") if event_type == "CONTEXT_END" else None
        )
        if event_type == "CONTEXT_FLIP":
            direction = _direction_from_context(raw.get("new_context"))
        epoch = _txt(raw.get("paper_epoch_id")) or paper_epoch_id
        rows.append(
            {
                "context_event_id": _txt(raw.get("context_event_id")),
                "event_type": event_type,
                "paper_epoch_id": epoch,
                "timeframe": timeframe.upper(),
                "direction": direction,
                "previous_context": _txt(raw.get("previous_context")),
                "new_context": _txt(raw.get("new_context")),
                "lifecycle_episode_id": _txt(raw.get("lifecycle_episode_id")),
                "event_timestamp": event_ts,
                "context_started_at": event_ts if event_type in {"CONTEXT_START", "CONTEXT_FLIP"} else None,
                "context_ended_at": event_ts if event_type in {"CONTEXT_END", "CONTEXT_FLIP"} else None,
                "context_price": _f(raw.get("context_event_price")),
                "context_price_timestamp": _iso(raw.get("last_trade_timestamp")),
                "context_bar_open_timestamp": bar_open,
                "context_bar_scheduled_close_timestamp": scheduled_close,
                "context_bar_status": bar_status,
                "context_bar_partial_close_at_context": None,  # not persisted on CONTEXT_* event
                "context_bar_partial_close_timestamp": None,
                "context_bar_final_close": final_close,
                "context_bar_final_close_timestamp": final_close_ts,
                "bar_anchor_time": bar_open,
                "causal_cutoff_timestamp": _iso(raw.get("causal_cutoff_timestamp")),
                "source": "LIVE1A_INTRABAR_CONTEXT_JOURNAL",
                "model_version": _txt(raw.get("model_version")),
            }
        )
    rows.sort(key=lambda r: (r.get("event_timestamp") or "", r.get("context_event_id") or ""))
    return rows


def build_context_zones_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map START/END/FLIP into active directional zones for chart bands."""
    zones: list[dict[str, Any]] = []
    open_zone: dict[str, Any] | None = None
    for ev in events:
        et = str(ev.get("event_type") or "").upper()
        direction = ev.get("direction")
        ts = ev.get("event_timestamp")
        if et == "CONTEXT_START" and direction in {"LONG", "SHORT"}:
            if open_zone is not None:
                open_zone["end_timestamp"] = ts
                open_zone["end_event_id"] = ev.get("context_event_id")
                open_zone["end_reason"] = "SUPERSEDED_BY_START"
                zones.append(open_zone)
            open_zone = {
                "timeframe": ev.get("timeframe"),
                "direction": direction,
                "directional_state": f"{direction}_CONTEXT",
                "start_timestamp": ts,
                "end_timestamp": None,
                "start_event_id": ev.get("context_event_id"),
                "lifecycle_episode_id": ev.get("lifecycle_episode_id"),
                "context_price": ev.get("context_price"),
                "bar_anchor_time": ev.get("bar_anchor_time"),
                "paper_epoch_id": ev.get("paper_epoch_id"),
                "source": "LIVE1A_INTRABAR_CONTEXT_JOURNAL",
                "active": True,
                "lifecycle_state": "ACTIVE",
            }
        elif et == "CONTEXT_END" and open_zone is not None:
            open_zone["end_timestamp"] = ts
            open_zone["end_event_id"] = ev.get("context_event_id")
            open_zone["end_reason"] = "CONTEXT_END"
            open_zone["active"] = False
            zones.append(open_zone)
            open_zone = None
        elif et == "CONTEXT_FLIP" and direction in {"LONG", "SHORT"}:
            if open_zone is not None:
                open_zone["end_timestamp"] = ts
                open_zone["end_event_id"] = ev.get("context_event_id")
                open_zone["end_reason"] = "CONTEXT_FLIP"
                open_zone["active"] = False
                zones.append(open_zone)
            open_zone = {
                "timeframe": ev.get("timeframe"),
                "direction": direction,
                "directional_state": f"{direction}_CONTEXT",
                "start_timestamp": ts,
                "end_timestamp": None,
                "start_event_id": ev.get("context_event_id"),
                "lifecycle_episode_id": ev.get("lifecycle_episode_id"),
                "context_price": ev.get("context_price"),
                "bar_anchor_time": ev.get("bar_anchor_time"),
                "paper_epoch_id": ev.get("paper_epoch_id"),
                "source": "LIVE1A_INTRABAR_CONTEXT_JOURNAL",
                "active": True,
                "lifecycle_state": "ACTIVE",
            }
    if open_zone is not None:
        zones.append(open_zone)
    return zones


def _map_live1a_visual_context(
    market_context: str | None,
    lifecycle: str | None,
    *,
    active_market_context: str | None = None,
) -> tuple[str, str]:
    """Return (directional_state, direction) preferring unfinished active context."""
    active = (active_market_context or "").strip().upper()
    if active in {"LONG", "LONG_CONTEXT"} or active.startswith("LONG"):
        return "LONG_CONTEXT", "LONG"
    if active in {"SHORT", "SHORT_CONTEXT"} or active.startswith("SHORT"):
        return "SHORT_CONTEXT", "SHORT"
    mc = (market_context or "OBSERVE").strip().upper()
    life = (lifecycle or "").strip().upper()
    if life == "NO_ACTIVE_CONTEXT" or mc in {"", "OBSERVE", "STAND_ASIDE", "NONE", "NO_ACTIVE_CONTEXT"}:
        return "OBSERVE", "NONE"
    if mc in {"LONG", "LONG_CONTEXT"} or mc.startswith("LONG"):
        return "LONG_CONTEXT", "LONG"
    if mc in {"SHORT", "SHORT_CONTEXT"} or mc.startswith("SHORT"):
        return "SHORT_CONTEXT", "SHORT"
    return "OBSERVE", "NONE"


def load_live1a_visual_overlay(timeframe: str) -> dict[str, Any] | None:
    """Current LIVE1A provisional/lifecycle for visual state (not closed-bar memory)."""
    cog = _read_json(LIVE1A_HEALTH)
    if not cog:
        return None
    evals = cog.get("last_provisional_eval")
    if not isinstance(evals, dict):
        return None
    row = evals.get(timeframe)
    if not isinstance(row, dict):
        return None
    bars = cog.get("partial_bars") if isinstance(cog.get("partial_bars"), dict) else {}
    bar = bars.get(timeframe) if isinstance(bars.get(timeframe), dict) else {}
    active = row.get("active_market_context") if "active_market_context" in row else row.get("active")
    directional, direction = _map_live1a_visual_context(
        row.get("provisional_market_context") or row.get("market_context"),
        row.get("lifecycle_state") or row.get("lifecycle"),
        active_market_context=active,
    )
    last_by_tf = cog.get("last_context_event") if isinstance(cog.get("last_context_event"), dict) else {}
    last_event = last_by_tf.get(timeframe) if isinstance(last_by_tf.get(timeframe), dict) else {}
    if not last_event and str(last_by_tf.get("timeframe") or "").upper() == timeframe.upper():
        last_event = last_by_tf
    # Recover unfinished START from journal when tip was reset after LIVE1A restart.
    if directional == "OBSERVE":
        open_ev = None
        try:
            journal = INTRABAR_CONTEXT_JOURNAL
            if journal.exists():
                for line in journal.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    if str(raw.get("timeframe") or "").upper() != timeframe.upper():
                        continue
                    et = str(raw.get("event_type") or "").upper()
                    if et in {"CONTEXT_START", "CONTEXT_FLIP"}:
                        open_ev = raw
                    elif et == "CONTEXT_END":
                        open_ev = None
        except OSError:
            open_ev = None
        if isinstance(open_ev, dict):
            new_ctx = str(open_ev.get("new_context") or "").upper()
            if new_ctx in {"LONG", "LONG_CONTEXT"} or new_ctx.startswith("LONG"):
                directional, direction = "LONG_CONTEXT", "LONG"
                last_event = open_ev
            elif new_ctx in {"SHORT", "SHORT_CONTEXT"} or new_ctx.startswith("SHORT"):
                directional, direction = "SHORT_CONTEXT", "SHORT"
                last_event = open_ev
    lifecycle_state = _txt(row.get("lifecycle_state") or row.get("lifecycle")) or (
        "NO_ACTIVE_CONTEXT" if directional == "OBSERVE" else "ACTIVE"
    )
    if directional != "OBSERVE" and str(lifecycle_state).upper() in {
        "",
        "NO_ACTIVE_CONTEXT",
        "OBSERVE",
        "NONE",
    }:
        lifecycle_state = "ACTIVE"
    episode = _txt(row.get("lifecycle_episode_id") or row.get("episode_id") or last_event.get("lifecycle_episode_id"))
    event_id = _txt(
        row.get("context_event_id")
        or row.get("event_id")
        or last_event.get("context_event_id")
        or last_event.get("event_id")
    )
    started = _txt(
        row.get("context_started_at")
        or row.get("active_context_started_at")
        or last_event.get("event_timestamp")
    )
    if directional == "OBSERVE":
        episode = None
        event_id = None
        started = None
        lifecycle_state = "NO_ACTIVE_CONTEXT"
    return {
        "directional_state": directional,
        "timeframe_direction": direction,
        "provisional_market_context": _txt(row.get("provisional_market_context") or row.get("market_context"))
        or "OBSERVE",
        "active_market_context": directional if directional in {"LONG_CONTEXT", "SHORT_CONTEXT"} else None,
        "lifecycle_state": lifecycle_state,
        "lifecycle_episode_id": episode,
        "context_event_id": event_id,
        "context_started_at": started,
        "context_price": _f(row.get("context_price") or last_event.get("context_event_price")),
        "causal_cutoff_timestamp": _txt(bar.get("causal_cutoff_timestamp")),
        "evaluation_timestamp": _txt(cog.get("updated_at") or bar.get("causal_cutoff_timestamp")),
        "source": "LIVE1A_INTRABAR_CONTEXT",
        "source_timestamp": _txt(cog.get("updated_at") or bar.get("causal_cutoff_timestamp")),
    }


def load_tf_state(timeframe: str) -> dict[str, Any]:
    avail_payload = _read_json(MTF_AVAILABILITY)
    avail_row = (avail_payload.get("timeframes") or {}).get(timeframe) or {}
    if not avail_row:
        for row in avail_payload.get("rows") or []:
            if isinstance(row, dict) and row.get("timeframe") == timeframe:
                avail_row = row
                break

    manager = _read_json(MANAGER_LATEST)
    cmd = (manager.get("commands") or {}).get(timeframe) or {}

    availability_status = _map_availability_status(_txt(avail_row.get("availability_status")))
    state = {
        "timeframe": timeframe,
        "availability_status": availability_status,
        "availability_raw": _txt(avail_row.get("availability_status")),
        "source_bar_open": _txt(avail_row.get("source_bar_open")),
        "source_bar_close": _txt(avail_row.get("source_bar_close")),
        "directional_state": _txt(cmd.get("timeframe_state")) or _txt(cmd.get("lifecycle_phase")),
        "timeframe_direction": _txt(cmd.get("timeframe_direction")),
        "manager_instruction": _txt(cmd.get("intent")),
        "manager_lifecycle_episode_id": _txt(cmd.get("lifecycle_episode_id")),
        "lifecycle_phase": _txt(cmd.get("lifecycle_phase")),
        "evaluation_timestamp": _txt(cmd.get("evaluation_timestamp") or manager.get("evaluation_timestamp")),
        "context_event_id": None,
        "context_started_at": None,
        "causal_cutoff_timestamp": None,
        "context_source": "timeframe_command_memory",
    }
    live1a = load_live1a_visual_overlay(timeframe)
    if live1a:
        # LIVE1A provisional/lifecycle overrides stale closed-bar manager command tip.
        state["directional_state"] = live1a["directional_state"]
        state["timeframe_direction"] = live1a["timeframe_direction"]
        state["lifecycle_phase"] = live1a["lifecycle_state"]
        state["manager_lifecycle_episode_id"] = live1a["lifecycle_episode_id"]
        state["context_event_id"] = live1a["context_event_id"]
        state["context_started_at"] = live1a["context_started_at"]
        state["causal_cutoff_timestamp"] = live1a["causal_cutoff_timestamp"]
        state["evaluation_timestamp"] = live1a["evaluation_timestamp"]
        state["context_source"] = live1a["source"]
        state["source_timestamp"] = live1a["source_timestamp"]
        state["provisional_market_context"] = live1a.get("provisional_market_context")
        state["active_market_context"] = live1a.get("active_market_context")
        state["context_price"] = live1a.get("context_price")
        if live1a["directional_state"] == "OBSERVE":
            state["manager_instruction"] = "NO_ACTION"
        elif live1a.get("lifecycle_state") == "CHALLENGED":
            state["manager_instruction"] = "HOLD"
    return state


def build_tf_context_segments(
    timeframe: str,
    *,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Collapse timeframe_command_memory into historical TF context segments.

    Proven source: data/trading/manager/timeframe_command_memory.parquet
    filtered by exact timeframe identity. Not a current-snapshot repeat.
    """
    try:
        from btc_ml.trading.command_bus import CommandBus, CommandBusPaths
    except Exception:
        if not COMMAND_MEMORY.exists():
            return []
        frame = pd.read_parquet(COMMAND_MEMORY)
    else:
        frame = CommandBus(CommandBusPaths.production()).timeframe_commands(timeframe)

    if frame is None or not len(frame):
        return []

    work = frame.copy()
    if "timeframe" in work.columns:
        work = work[work["timeframe"].astype(str).str.upper() == timeframe.upper()].copy()
    if not len(work):
        return []

    work["_eval"] = pd.to_datetime(work.get("evaluation_timestamp"), utc=True, errors="coerce")
    work["_bar_open"] = pd.to_datetime(work.get("source_bar_open"), utc=True, errors="coerce")
    work["_bar_close"] = pd.to_datetime(work.get("source_bar_close"), utc=True, errors="coerce")
    work = work.dropna(subset=["_eval"]).sort_values("_eval").reset_index(drop=True)
    if window_start is not None:
        work = work[work["_eval"] >= window_start - pd.Timedelta(days=1)]
    if window_end is not None:
        work = work[work["_eval"] <= window_end + pd.Timedelta(hours=6)]
    if not len(work):
        return []

    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def _flush() -> None:
        nonlocal current
        if current is None:
            return
        if window_start is not None and current["end_ts"] is not None and current["end_ts"] < window_start:
            current = None
            return
        if window_end is not None and current["start_ts"] is not None and current["start_ts"] > window_end:
            current = None
            return
        segments.append(
            {
                "timeframe": timeframe,
                "start_timestamp": _iso(current["start_ts"]),
                "end_timestamp": _iso(current["end_ts"]),
                "directional_state": current["directional_state"],
                "availability_status": _map_availability_status(current["availability_raw"]),
                "availability_raw": current["availability_raw"],
                "manager_instruction": current["manager_instruction"],
                "entry_eligibility": current["entry_eligibility"],
                "source": "timeframe_command_memory",
                "command_count": current["command_count"],
                "lifecycle_episode_id": current.get("lifecycle_episode_id"),
            }
        )
        current = None

    for _, raw in work.iterrows():
        state_name = _txt(raw.get("timeframe_state")) or "OBSERVE"
        avail_raw = _txt(raw.get("availability_status"))
        intent = _txt(raw.get("intent")) or "NO_ACTION"
        allowed = raw.get("action_allowed")
        if isinstance(allowed, str):
            entry_elig = allowed.strip().lower() in {"1", "true", "yes"}
        else:
            entry_elig = bool(allowed)
        start_ts = raw["_bar_open"] if pd.notna(raw["_bar_open"]) else raw["_eval"]
        end_ts = raw["_bar_close"] if pd.notna(raw["_bar_close"]) else raw["_eval"]
        key = state_name
        if current is None:
            current = {
                "key": key,
                "directional_state": state_name,
                "availability_raw": avail_raw,
                "manager_instruction": intent,
                "entry_eligibility": entry_elig,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "command_count": 1,
                "lifecycle_episode_id": _txt(raw.get("lifecycle_episode_id")),
            }
            continue
        if current["key"] != key:
            _flush()
            current = {
                "key": key,
                "directional_state": state_name,
                "availability_raw": avail_raw,
                "manager_instruction": intent,
                "entry_eligibility": entry_elig,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "command_count": 1,
                "lifecycle_episode_id": _txt(raw.get("lifecycle_episode_id")),
            }
        else:
            current["end_ts"] = end_ts if end_ts is not None else current["end_ts"]
            current["availability_raw"] = avail_raw or current["availability_raw"]
            current["manager_instruction"] = intent
            current["entry_eligibility"] = entry_elig
            current["command_count"] += 1
            current["lifecycle_episode_id"] = _txt(raw.get("lifecycle_episode_id")) or current.get(
                "lifecycle_episode_id"
            )
    _flush()
    return segments


def assert_entities_tf_isolated(
    entities: list[dict[str, Any]],
    *,
    timeframe: str,
) -> list[dict[str, Any]]:
    """Return contaminants whose timeframe != chart TF."""
    bad: list[dict[str, Any]] = []
    for entity in entities:
        tf = _txt(entity.get("timeframe"))
        if tf is None or tf.upper() != timeframe.upper():
            bad.append(
                {
                    "timeframe_expected": timeframe,
                    "timeframe_actual": tf,
                    "trade_id": entity.get("trade_id"),
                    "position_id": entity.get("position_id"),
                }
            )
    return bad


def _short_id(value: str | None, *, keep: int = 8) -> str | None:
    if not value:
        return None
    if value.startswith("TF_TRADE_") or value.startswith("TF_POSITION_"):
        return value.split("_")[-1][:keep]
    return value[-keep:]


def _parse_namespaced_episode(value: Any, *, expected_tf: str) -> tuple[str | None, int | None]:
    text = _txt(value)
    if not text:
        return None, None
    if ":" in text:
        prefix, _, rest = text.partition(":")
        if prefix.upper() != expected_tf.upper():
            return text, None
        try:
            return text, int(float(rest))
        except (TypeError, ValueError):
            return text, None
    try:
        return text, int(float(text))
    except (TypeError, ValueError):
        return text, None


def _episode_lookup(episodes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for ep in episodes:
        eid = ep.get("episode_id")
        try:
            key = int(eid)
        except (TypeError, ValueError):
            continue
        out[key] = ep
    return out


def _prove_episode_link(
    *,
    timeframe: str,
    stamped_lifecycle_episode_id: str | None,
    entry_ts: str | None,
    exit_ts: str | None,
    episode_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Prove episode only via namespaced TF:id + temporal overlap with global episode."""
    key, numeric = _parse_namespaced_episode(stamped_lifecycle_episode_id, expected_tf=timeframe)
    if numeric is None:
        return {
            "episode_id": None,
            "episode_key": key,
            "episode_status": "UNPROVEN",
            "episode_link_reason": "NO_NAMESPACE_OR_NON_NUMERIC",
        }
    ep = episode_by_id.get(numeric)
    if ep is None:
        return {
            "episode_id": None,
            "episode_key": key,
            "episode_status": "UNPROVEN",
            "episode_link_reason": "GLOBAL_EPISODE_MISSING",
        }
    entry = _to_utc(entry_ts)
    exit_ = _to_utc(exit_ts) or entry
    ep_start = _to_utc(ep.get("start_timestamp") or ep.get("start_time"))
    ep_end = _to_utc(ep.get("end_timestamp") or ep.get("end_time"))
    if entry is None or ep_start is None or ep_end is None:
        return {
            "episode_id": None,
            "episode_key": key,
            "episode_status": "UNPROVEN",
            "episode_link_reason": "MISSING_TIMESTAMPS",
        }
    # Overlap: trade interval intersects episode interval (inclusive).
    trade_end = exit_ or entry
    if trade_end < ep_start or entry > ep_end:
        return {
            "episode_id": None,
            "episode_key": key,
            "episode_status": "UNPROVEN",
            "episode_link_reason": "NO_TEMPORAL_OVERLAP",
        }
    return {
        "episode_id": numeric,
        "episode_key": str(numeric),
        "episode_status": "PROVEN",
        "episode_link_reason": "TF_NAMESPACE_AND_TEMPORAL_OVERLAP",
        "stamped_lifecycle_episode_id": key,
    }


def load_closed_trades_for_tf(
    timeframe: str,
    *,
    episode_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    from active_epoch_trade_filter import (  # type: ignore
        active_paper_epoch_id,
        filter_active_epoch_rows,
        live1b_paper_active,
    )

    try:
        from trading_truth import _load_live1b_closed_trades  # type: ignore
    except Exception:
        try:
            from apps.context_visualizer.trading_truth import _load_live1b_closed_trades  # type: ignore
        except Exception:
            _load_live1b_closed_trades = None  # type: ignore

    if live1b_paper_active():
        rows = _load_live1b_closed_trades(timeframe=timeframe) if _load_live1b_closed_trades else []
        rows = filter_active_epoch_rows(rows, active_epoch_id=active_paper_epoch_id())
        for row in rows:
            row.setdefault("episode_status", "UNPROVEN")
            row.setdefault("episode_link_reason", "LIVE1B_NEW_EPOCH")
            row.setdefault("episode_id", None)
            row.setdefault("episode_key", None)
            row.setdefault("net_realised_pnl_usd", row.get("realized_pnl"))
        return rows
    path = TRADER_BOOKS_ROOT / timeframe / "trades.parquet"
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    rows: list[dict[str, Any]] = []
    for _, raw in frame.iterrows():
        exit_ts = _iso(raw.get("exit_ts"))
        if not exit_ts:
            continue
        meta = _parse_meta(raw.get("metadata_json"))
        trade_id = _txt(raw.get("trade_id"))
        stamped = _txt(raw.get("lifecycle_episode_id")) or _txt(meta.get("lifecycle_episode_id"))
        link = _prove_episode_link(
            timeframe=timeframe,
            stamped_lifecycle_episode_id=stamped,
            entry_ts=_iso(raw.get("entry_ts")),
            exit_ts=exit_ts,
            episode_by_id=episode_by_id,
        )
        stop = _f(raw.get("stop_loss_price"))
        if stop is None:
            stop = _f(meta.get("stop_loss_price"))
        take = _f(raw.get("take_profit_price"))
        if take is None:
            take = _f(meta.get("take_profit_price"))
        row = {
                "trade_id": trade_id,
                "position_id": _txt(raw.get("position_id")),
                "timeframe": timeframe,
                "status": "CLOSED",
                "side": (_txt(raw.get("side")) or "LONG").upper(),
                "entry_timestamp": _iso(raw.get("entry_ts")),
                "exit_timestamp": exit_ts,
                "entry_price": _f(raw.get("entry_price")),
                "exit_price": _f(raw.get("exit_price")),
                "stop_price": stop,
                "take_profit_price": take,
                "quantity": _f(raw.get("quantity")),
                "net_realised_pnl_usd": _f(raw.get("net_pnl_usd")),
                "fees_usd": _f(raw.get("fees_usd")),
                "slippage_usd": _f(raw.get("slippage_usd")),
                "display_label": None,  # filled by assign_tf_ordinals
                "public_number": None,
                "ordinal": None,
                "created_at": _iso(raw.get("created_at") or raw.get("entry_ts")),
                "manager_cycle_id": _txt(meta.get("manager_cycle_id")),
                "command_id": _txt(raw.get("command_id") or meta.get("command_id")),
                "stamped_lifecycle_episode_id": stamped,
                "paper_epoch_id": _txt(raw.get("paper_epoch_id") or meta.get("paper_epoch_id")),
                **link,
                "source_book": f"TIMEFRAME_TRADER_{timeframe}",
            }
        rows.append(row)
    rows = filter_active_epoch_rows(rows)
    rows.sort(key=lambda r: (r.get("entry_timestamp") or "", r.get("trade_id") or ""))
    return rows


def load_open_positions_for_tf(
    timeframe: str,
    *,
    episode_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    from active_epoch_trade_filter import (  # type: ignore
        active_paper_epoch_id,
        filter_active_epoch_rows,
        live1b_paper_active,
    )

    try:
        from trading_truth import _load_live1b_open_positions  # type: ignore
    except Exception:
        try:
            from apps.context_visualizer.trading_truth import _load_live1b_open_positions  # type: ignore
        except Exception:
            _load_live1b_open_positions = None  # type: ignore

    if live1b_paper_active():
        rows = _load_live1b_open_positions(timeframe=timeframe) if _load_live1b_open_positions else []
        rows = filter_active_epoch_rows(rows, active_epoch_id=active_paper_epoch_id())
        for row in rows:
            row.setdefault("episode_status", "UNPROVEN")
            row.setdefault("episode_link_reason", "LIVE1B_NEW_EPOCH")
            row.setdefault("episode_id", None)
            row.setdefault("episode_key", None)
        return rows
    path = TRADER_BOOKS_ROOT / timeframe / "positions.parquet"
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    if "status" not in frame.columns:
        return []
    open_frame = frame[frame["status"].astype(str).str.upper() == "OPEN"]
    rows: list[dict[str, Any]] = []
    for _, raw in open_frame.iterrows():
        meta = _parse_meta(raw.get("metadata_json"))
        position_id = _txt(raw.get("position_id"))
        stamped = (
            _txt(meta.get("lifecycle_episode_id"))
            or _txt(raw.get("lifecycle_episode_id"))
            or _txt(meta.get("context_episode_id"))
        )
        entry_ts = _iso(raw.get("opened_at") or meta.get("fill_timestamp"))
        link = _prove_episode_link(
            timeframe=timeframe,
            stamped_lifecycle_episode_id=stamped,
            entry_ts=entry_ts,
            exit_ts=None,
            episode_by_id=episode_by_id,
        )
        stop = _f(raw.get("stop_loss_price"))
        if stop is None:
            stop = _f(meta.get("stop_loss_price"))
        take = _f(raw.get("take_profit_price"))
        if take is None:
            take = _f(meta.get("take_profit_price"))
        rows.append(
            {
                "position_id": position_id,
                "trade_id": None,
                "timeframe": timeframe,
                "status": "OPEN",
                "side": (_txt(raw.get("direction")) or _txt(meta.get("side")) or "LONG").upper(),
                "position_side": (_txt(raw.get("direction")) or _txt(meta.get("side")) or "LONG").upper(),
                "position_status": "OPEN",
                "entry_timestamp": entry_ts,
                "exit_timestamp": None,
                "entry_price": _f(raw.get("entry_price") or meta.get("entry_price")),
                "exit_price": None,
                "stop_price": stop,
                "take_profit_price": take,
                "quantity": _f(raw.get("quantity") or meta.get("quantity_btc")),
                "display_label": None,  # filled by assign_tf_ordinals
                "public_number": None,
                "ordinal": None,
                "created_at": _iso(raw.get("created_at") or raw.get("opened_at") or entry_ts),
                "manager_cycle_id": _txt(meta.get("manager_cycle_id")),
                "command_id": _txt(raw.get("command_id") or meta.get("command_id")),
                "stamped_lifecycle_episode_id": stamped,
                "paper_epoch_id": _txt(raw.get("paper_epoch_id") or meta.get("paper_epoch_id")),
                **link,
                "source_book": f"TIMEFRAME_TRADER_{timeframe}",
            }
        )
    rows = filter_active_epoch_rows(rows)
    rows.sort(key=lambda r: (r.get("entry_timestamp") or "", r.get("position_id") or ""))
    return rows


def assign_tf_ordinals(
    timeframe: str,
    *,
    closed_trades: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stable per-TF public numbers: M15_1, M15_2, ...

    Order: entry_timestamp asc → created_at asc → trade_id/position_id tie-break.
    Open and closed share one ordinal space so open→closed keeps the same number.
    """
    entities: list[dict[str, Any]] = []
    for row in closed_trades:
        entities.append(row)
    for row in open_positions:
        entities.append(row)

    def _sort_key(entity: dict[str, Any]) -> tuple[str, str, str]:
        return (
            entity.get("entry_timestamp") or "",
            entity.get("created_at") or entity.get("entry_timestamp") or "",
            entity.get("trade_id") or entity.get("position_id") or "",
        )

    entities.sort(key=_sort_key)
    mapping: dict[str, str] = {}
    for idx, entity in enumerate(entities, start=1):
        public = f"{timeframe}_{idx}"
        entity["ordinal"] = idx
        entity["public_number"] = public
        entity["display_label"] = public
        key = entity.get("trade_id") or entity.get("position_id") or public
        mapping[str(key)] = public
    return {
        "timeframe": timeframe,
        "count": len(entities),
        "mapping": mapping,
    }


def build_global_lifecycle(
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    missing: list[str] = []
    if not LIFECYCLE_EPISODES.exists():
        missing.append(str(LIFECYCLE_EPISODES))
    else:
        frame = pd.read_parquet(LIFECYCLE_EPISODES)
        work = frame.copy()
        work["episode_id"] = pd.to_numeric(work["episode_id"], errors="coerce")
        work = work.dropna(subset=["episode_id"])
        work["start_time"] = work["start_time"].map(_to_utc)
        work["end_time"] = work["end_time"].map(_to_utc)
        for _, raw in work.iterrows():
            start = raw["start_time"]
            end = raw["end_time"] if pd.notna(raw["end_time"]) else window_end
            if start is None:
                continue
            if end < window_start or start > window_end:
                continue
            eid = int(raw["episode_id"])
            episodes.append(
                {
                    "episode_id": eid,
                    "episode_key": str(eid),
                    "state": _txt(raw.get("active_market_context")) or "OBSERVE",
                    "lifecycle_state": _txt(raw.get("dominant_lifecycle_state") or raw.get("end_lifecycle_state")),
                    "start_timestamp": _iso(start),
                    "end_timestamp": _iso(end),
                    "active": False,
                    "source": "market_context_lifecycle_episodes",
                }
            )

    active = None
    if LIFECYCLE_MEMORY.exists():
        memory = pd.read_parquet(LIFECYCLE_MEMORY)
        if len(memory):
            tip = memory.sort_values("timestamp").iloc[-1]
            eid = tip.get("context_episode_id")
            try:
                eid_int = int(float(eid))
            except (TypeError, ValueError):
                eid_int = None
            active = {
                "episode_id": eid_int,
                "episode_key": None if eid_int is None else str(eid_int),
                "state": _txt(tip.get("active_market_context")) or "OBSERVE",
                "lifecycle_state": _txt(tip.get("lifecycle_state")),
                "start_timestamp": _iso(tip.get("active_context_started_at") or tip.get("timestamp")),
                "end_timestamp": _iso(tip.get("timestamp")),
                "active": True,
                "source": "market_context_lifecycle_memory",
            }
            if eid_int is not None:
                for ep in episodes:
                    if ep["episode_id"] == eid_int:
                        ep["active"] = True
                        ep["end_timestamp"] = active["end_timestamp"]
                        break
                else:
                    episodes.append(
                        {
                            **active,
                            "active": True,
                        }
                    )

    episodes.sort(key=lambda r: (r.get("start_timestamp") or "", r.get("episode_id") or 0))
    # Collapse accidental duplicate episode_id rows (keep last / active-preferring).
    dedup: dict[int, dict[str, Any]] = {}
    for ep in episodes:
        eid = ep.get("episode_id")
        if eid is None:
            continue
        prev = dedup.get(int(eid))
        if prev is None or ep.get("active"):
            dedup[int(eid)] = ep
    episodes = sorted(dedup.values(), key=lambda r: (r.get("start_timestamp") or "", r.get("episode_id") or 0))

    # LIVE1A provisional overrides closed-bar memory tip for the *active* visual episode.
    live1a_primary = load_live1a_visual_overlay("M15")
    if live1a_primary is not None:
        if live1a_primary["directional_state"] == "OBSERVE":
            for ep in episodes:
                ep["active"] = False
            active = {
                "episode_id": None,
                "episode_key": None,
                "state": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "start_timestamp": None,
                "end_timestamp": live1a_primary.get("source_timestamp") or live1a_primary.get("evaluation_timestamp"),
                "active": False,
                "source": "LIVE1A_INTRABAR_CONTEXT",
                "context_event_id": live1a_primary.get("context_event_id"),
                "causal_cutoff_timestamp": live1a_primary.get("causal_cutoff_timestamp"),
            }
        else:
            active = {
                "episode_id": live1a_primary.get("lifecycle_episode_id"),
                "episode_key": live1a_primary.get("lifecycle_episode_id"),
                "state": live1a_primary["directional_state"],
                "lifecycle_state": live1a_primary.get("lifecycle_state"),
                "start_timestamp": live1a_primary.get("context_started_at"),
                "end_timestamp": live1a_primary.get("source_timestamp") or live1a_primary.get("evaluation_timestamp"),
                "active": True,
                "source": "LIVE1A_INTRABAR_CONTEXT",
                "context_event_id": live1a_primary.get("context_event_id"),
                "causal_cutoff_timestamp": live1a_primary.get("causal_cutoff_timestamp"),
            }

    return {
        "source": (
            "LIVE1A_INTRABAR_CONTEXT"
            if live1a_primary is not None
            else "market_context_lifecycle_episodes + market_context_lifecycle_memory tip"
        ),
        "active_episode": active,
        "episodes": episodes,
        "freshness": {
            "status": "FRESH" if active is not None else "SOURCE_UNAVAILABLE",
            "tip_timestamp": None if active is None else active.get("end_timestamp"),
        },
        "missing_sources": missing,
    }


def load_performance_by_tf() -> dict[str, dict[str, Any]]:
    """Read-only projection; does not modify trading_performance_truth."""
    try:
        from btc_ml.trading.trading_performance_truth import build_trading_performance_truth
    except Exception as exc:  # pragma: no cover
        return {
            tf: {"status": "SOURCE_UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
            for tf in TIMEFRAMES
        }
    payload = build_trading_performance_truth()
    per_tf = payload.get("timeframes") or {}
    out: dict[str, dict[str, Any]] = {}
    for tf in TIMEFRAMES:
        row = per_tf.get(tf) or {}
        out[tf] = {
            "timeframe": tf,
            "closed_trade_count": row.get("closed_trade_count"),
            "open_position_count": row.get("open_position_count"),
            "realised_net_pnl_usd": _clean_num(_f(row.get("realised_net_pnl_usd"))),
            "unrealised_net_pnl_usd": _clean_num(_f(row.get("unrealised_net_pnl_usd"))),
            "unrealised_gross_pnl_usd": _clean_num(_f(row.get("unrealised_gross_pnl_usd"))),
            "source": "trading_performance_truth",
        }
    return out


def build_timeframe_chart_truth(
    *,
    feed_path: Path | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    data_quality: dict[str, Any] = {
        "missing_sources": [],
        "stale_sources": [],
        "excluded_sources": [
            "research_bar_policy_trades",
            "legacy_controller_trades",
            "dashboard_derived_trades",
            "quarantine_backups",
        ],
        "orphan_entities": [],
        "unproven_episode_links": [],
        "duplicate_entities": [],
    }

    try:
        m15 = load_m15_feed(feed_path)
    except Exception as exc:
        data_quality["missing_sources"].append(str(feed_path or LIVE_FEED))
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at or _utc_now_iso(),
            "window_start": None,
            "window_end": None,
            "global_lifecycle": {"source": None, "active_episode": None, "episodes": [], "freshness": {"status": "SOURCE_UNAVAILABLE"}},
            "timeframes": {
                tf: {
                    "candle_contract": {"error": str(exc)},
                    "candles": [],
                    "state": {"availability_status": "SOURCE_UNAVAILABLE"},
                    "open_positions": [],
                    "closed_trades": [],
                    "performance": {},
                    "freshness": {"status": "SOURCE_UNAVAILABLE"},
                }
                for tf in TIMEFRAMES
            },
            "data_quality": data_quality,
        }

    window_start, window_end = resolve_window(m15, window_days=window_days)
    global_lifecycle = build_global_lifecycle(window_start=window_start, window_end=window_end)
    episode_by_id = _episode_lookup(global_lifecycle.get("episodes") or [])
    # Include full episode catalog for linkage proofs even outside window.
    if LIFECYCLE_EPISODES.exists():
        full = pd.read_parquet(LIFECYCLE_EPISODES)
        for _, raw in full.iterrows():
            try:
                eid = int(float(raw.get("episode_id")))
            except (TypeError, ValueError):
                continue
            if eid in episode_by_id:
                continue
            episode_by_id[eid] = {
                "episode_id": eid,
                "start_timestamp": _iso(raw.get("start_time")),
                "end_timestamp": _iso(raw.get("end_time")),
                "state": _txt(raw.get("active_market_context")),
            }

    perf = load_performance_by_tf()
    timeframes: dict[str, Any] = {}
    from active_epoch_trade_filter import active_paper_epoch_id, live1b_paper_active  # type: ignore

    live1b = bool(live1b_paper_active())
    active_epoch = active_paper_epoch_id()

    for tf in TIMEFRAMES:
        candle_block = build_tf_candles(
            m15,
            tf,
            window_start=window_start,
            window_end=window_end,
        )
        state = load_tf_state(tf)
        closed = load_closed_trades_for_tf(tf, episode_by_id=episode_by_id)
        opens = load_open_positions_for_tf(tf, episode_by_id=episode_by_id)
        number_map = assign_tf_ordinals(tf, closed_trades=closed, open_positions=opens)
        contaminants = assert_entities_tf_isolated(closed + opens, timeframe=tf)
        panel_status = "OK"
        if contaminants:
            panel_status = "TF_SOURCE_CONTAMINATION"
            data_quality["orphan_entities"].extend(contaminants)

        context_events = load_intrabar_context_events_for_tf(
            tf,
            candles=candle_block.get("candles") or [],
            paper_epoch_id=active_epoch,
            window_start=window_start,
            window_end=window_end,
        )
        context_zones = build_context_zones_from_events(context_events)
        # Tip lifecycle (e.g. CHALLENGED) annotates open journal zones; provisional OBSERVE
        # must not close them — only CONTEXT_END/FLIP does.
        tip_life = str(state.get("lifecycle_phase") or "").upper()
        tip_active = str(state.get("active_market_context") or state.get("directional_state") or "").upper()
        for zone in context_zones:
            if not zone.get("active"):
                continue
            zone_dir = str(zone.get("directional_state") or "").upper()
            if tip_life == "CHALLENGED" and (
                tip_active in zone_dir or zone_dir.startswith(tip_active.replace("_CONTEXT", ""))
            ):
                zone["lifecycle_state"] = "CHALLENGED"
            elif tip_active in {"LONG_CONTEXT", "SHORT_CONTEXT"} and tip_active in zone_dir:
                zone["lifecycle_state"] = tip_life or "ACTIVE"

        if live1b:
            # LIVE1A journal is the only active context truth; do not paint legacy
            # closed-bar command-memory bands as current directional context.
            context_segments = [
                {
                    "timeframe": z.get("timeframe"),
                    "start_timestamp": z.get("start_timestamp"),
                    "end_timestamp": z.get("end_timestamp"),
                    "directional_state": z.get("directional_state"),
                    "availability_status": "FRESH",
                    "availability_raw": "LIVE1A_INTRABAR",
                    "manager_instruction": "HOLD" if z.get("active") else "NO_ACTION",
                    "entry_eligibility": False,
                    "source": "LIVE1A_INTRABAR_CONTEXT_JOURNAL",
                    "command_count": 1,
                    "lifecycle_episode_id": z.get("lifecycle_episode_id"),
                    "context_price": z.get("context_price"),
                    "bar_anchor_time": z.get("bar_anchor_time"),
                    "paper_epoch_id": z.get("paper_epoch_id"),
                    "active": z.get("active"),
                    "start_event_id": z.get("start_event_id"),
                    "end_event_id": z.get("end_event_id"),
                    "lifecycle_state": z.get("lifecycle_state"),
                }
                for z in context_zones
                if z.get("direction") in {"LONG", "SHORT"}
            ]
            context_source = "LIVE1A_INTRABAR_CONTEXT_JOURNAL"
        else:
            context_segments = build_tf_context_segments(
                tf,
                window_start=window_start,
                window_end=window_end,
            )
            context_source = "timeframe_command_memory"
            # When LIVE1A is OBSERVE, drop open-ended directional segments that would paint a false active zone.
            if state.get("context_source") == "LIVE1A_INTRABAR_CONTEXT" and state.get("directional_state") == "OBSERVE":
                pruned: list[dict[str, Any]] = []
                for seg in context_segments:
                    ds = str(seg.get("directional_state") or "").upper()
                    if ds in {"LONG_CONTEXT", "SHORT_CONTEXT", "LONG", "SHORT"}:
                        end_ts = seg.get("end_timestamp")
                        if end_ts and state.get("causal_cutoff_timestamp") and str(end_ts) >= str(
                            state.get("causal_cutoff_timestamp")
                        ):
                            continue
                        if not end_ts:
                            continue
                    pruned.append(seg)
                context_segments = pruned

        for entity in closed + opens:
            if entity.get("episode_status") == "UNPROVEN":
                data_quality["unproven_episode_links"].append(
                    {
                        "timeframe": tf,
                        "trade_id": entity.get("trade_id"),
                        "position_id": entity.get("position_id"),
                        "stamped_lifecycle_episode_id": entity.get("stamped_lifecycle_episode_id"),
                        "reason": entity.get("episode_link_reason"),
                    }
                )

        # Position fields on state
        primary_open = opens[0] if opens else None
        state["position_side"] = None if primary_open is None else primary_open.get("position_side") or primary_open.get("side")
        state["position_status"] = "FLAT" if primary_open is None else "OPEN"
        state["open_position_count"] = len(opens)

        freshness_status = state.get("availability_status") or candle_block.get("freshness_status")
        if candle_block.get("freshness_status") == "SOURCE_UNAVAILABLE":
            freshness_status = "SOURCE_UNAVAILABLE"
            data_quality["missing_sources"].append(f"candles:{tf}")
        if freshness_status == "STALE":
            data_quality["stale_sources"].append(tf)

        timeframes[tf] = {
            "candle_contract": {
                "timeframe": tf,
                "source": candle_block.get("source"),
                "aggregation": candle_block.get("aggregation"),
                "timestamp_semantics": candle_block.get("timestamp_semantics"),
                "timezone": "UTC",
                "confirmed_only": bool(candle_block.get("confirmed_only", True)),
                "includes_live_partial": bool(candle_block.get("includes_live_partial")),
                "partial_source": candle_block.get("partial_source"),
                "latest_confirmed_open": candle_block.get("latest_confirmed_open"),
                "latest_confirmed_close": candle_block.get("latest_confirmed_close"),
                "latest_partial_open": candle_block.get("latest_partial_open"),
                "freshness_status": freshness_status,
            },
            "candles": candle_block.get("candles") or [],
            "state": state,
            "context_events": context_events if panel_status == "OK" else [],
            "context_zones": context_zones if panel_status == "OK" else [],
            "context_segments": context_segments if panel_status == "OK" else [],
            "context_history": context_segments if panel_status == "OK" else [],
            "context_source": context_source,
            "open_positions": opens if panel_status == "OK" else [],
            "closed_trades": closed if panel_status == "OK" else [],
            "trade_numbering": number_map,
            "panel_status": panel_status,
            "contamination": contaminants,
            "performance": perf.get(tf) or {},
            "freshness": {
                "latest_confirmed_close": candle_block.get("latest_confirmed_close"),
                "source_tip": candle_block.get("latest_confirmed_open"),
                "status": freshness_status,
            },
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now_iso(),
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "window_days": int(window_days),
        "global_lifecycle": global_lifecycle,
        "visual_contract": {
            "global_lifecycle_strip": False,
            "per_tf_context_bands": True,
            "equal_grid": False,
            "standalone_tf_urls": True,
            "trade_public_numbers": True,
            "timezone": "UTC",
            "context_source_priority": "LIVE1A_INTRABAR_CONTEXT_JOURNAL" if live1b else "timeframe_command_memory",
        },
        "timeframes": timeframes,
        "data_quality": data_quality,
        "runtime": {
            "paper_only": True,
            "execution_enabled": False,
            "real_execution": False,
        },
        **_trade_overlay_meta(timeframes),
    }


def _trade_overlay_meta(timeframes: dict[str, Any]) -> dict[str, Any]:
    from active_epoch_trade_filter import active_paper_epoch_id, live1b_paper_active  # type: ignore

    closed_n = 0
    open_n = 0
    marker_n = 0
    context_n = 0
    for panel in timeframes.values():
        closed = panel.get("closed_trades") or []
        opens = panel.get("open_positions") or []
        events = panel.get("context_events") or []
        closed_n += len(closed)
        open_n += len(opens)
        context_n += len(events)
        # entry+exit markers for closed; entry marker for open; context markers
        marker_n += len(closed) * 2 + len(opens) + len(events)
    eid = active_paper_epoch_id()
    return {
        "active_paper_epoch_id": eid,
        "trade_overlay_source": (
            "LIVE1B_INTRABAR_PAPER_EPOCH" if live1b_paper_active() else "TIMEFRAME_TRADER_BOOKS"
        ),
        "context_overlay_source": (
            "LIVE1A_INTRABAR_CONTEXT_JOURNAL" if live1b_paper_active() else "timeframe_command_memory"
        ),
        "legacy_excluded": bool(live1b_paper_active()),
        "trade_marker_count": marker_n,
        "open_position_overlay_count": open_n,
        "closed_trade_overlay_count": closed_n,
        "context_event_overlay_count": context_n,
        "cache_key": f"chart_trades:{eid or 'none'}:{SCHEMA_VERSION}",
    }


def write_timeframe_chart_truth(
    output_path: Path,
    *,
    payload: dict[str, Any] | None = None,
    feed_path: Path | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    truth = payload if payload is not None else build_timeframe_chart_truth(
        feed_path=feed_path,
        window_days=window_days,
    )
    write_json_atomic(output_path, truth)
    return truth


def write_candidate_bundle(
    candidate_dir: Path | None = None,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    out = candidate_dir or CANDIDATE_DIR
    out.mkdir(parents=True, exist_ok=True)
    payload = build_timeframe_chart_truth(window_days=window_days)
    write_json_atomic(out / "timeframe_chart_truth.json", payload)
    write_json_atomic(out / "global_lifecycle_truth.json", payload.get("global_lifecycle") or {})
    for tf in TIMEFRAMES:
        write_json_atomic(out / f"{tf}_chart_truth.json", (payload.get("timeframes") or {}).get(tf) or {})
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build timeframe chart truth (read-only / explicit write).")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Explicit output path. Omit to skip write (build-only).",
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help=f"Write candidate bundle under {CANDIDATE_DIR}",
    )
    parser.add_argument(
        "--live-public",
        action="store_true",
        help="Write apps/context_visualizer/public/data/timeframe_chart_truth.json (VIS2C activation).",
    )
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    args = parser.parse_args(argv)

    if args.candidate:
        payload = write_candidate_bundle(window_days=args.window_days)
        print(f"candidate written: {CANDIDATE_DIR / 'timeframe_chart_truth.json'}")
        print(f"window: {payload.get('window_start')} → {payload.get('window_end')}")
        return 0

    payload = build_timeframe_chart_truth(window_days=args.window_days)
    target = args.output
    if args.live_public:
        target = PUBLIC_CHART_TRUTH
    if target is not None:
        write_timeframe_chart_truth(Path(target), payload=payload)
        print(f"wrote: {target}")
    else:
        print(json.dumps({"schema_version": payload.get("schema_version"), "generated_at": payload.get("generated_at"), "window_start": payload.get("window_start"), "window_end": payload.get("window_end")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
