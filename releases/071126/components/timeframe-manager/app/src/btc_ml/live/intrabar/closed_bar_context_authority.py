"""Closed-bar lifecycle tip used as idea-death authority for the journal.

This is not Anti-Saw. Anti-Saw is the path-density trade filter on OPEN.
Here we only answer: is the completed-bar book still LONG or SHORT?
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from btc_ml.live.intrabar.partial_bar_state import TIMEFRAMES, TF_SECONDS, bar_open_for

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LIFECYCLE_MEMORY = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"

DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})


def _clean_context(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"LONG", "LONG_CONTEXT"}:
        return "LONG_CONTEXT"
    if text in {"SHORT", "SHORT_CONTEXT"}:
        return "SHORT_CONTEXT"
    if text in {"NAN", "NONE", "NULL", "<NA>", ""}:
        return ""
    return text


def closed_bar_still_directional(active_market_context: str | None) -> bool:
    """True when the closed-bar book still holds a living directional thesis."""
    return _clean_context(active_market_context) in DIRECTIONAL_CONTEXTS


def _as_utc(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def closed_bar_tip_is_current(
    *,
    closed_bar_timestamp: object,
    event_timestamp: object,
    timeframe: str,
) -> bool:
    """True when the tip is the bar that has just closed (or newer).

    Lifecycle ``timestamp`` is bar open. At 09:45:00.011 the current M15
    bucket is 09:45, so the just-closed bar is 09:30. A tip of 08:45 is
    stale and must not confirm idea-death.
    """
    event = _as_utc(event_timestamp)
    tip = _as_utc(closed_bar_timestamp)
    tf = str(timeframe or "").upper()
    if event is None or tip is None or tf not in TIMEFRAMES:
        return False
    just_closed = bar_open_for(event, tf) - pd.Timedelta(seconds=TF_SECONDS[tf])
    return tip >= just_closed


class ClosedBarContextAuthority:
    """Latest closed-bar ``active_market_context`` per timeframe.

    ``snapshot`` is a test double. Production reads the lifecycle parquet and
    caches by mtime/size so cognition ticks do not hit disk every trade.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        snapshot: Mapping[str, str] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self._snapshot = dict(snapshot) if snapshot is not None else None
        self._mtime_ns: int | None = None
        self._size: int | None = None
        self._by_tf: dict[str, str] = {}
        self._ts_by_tf: dict[str, pd.Timestamp] = {}

    def set_snapshot(self, snapshot: Mapping[str, str] | None) -> None:
        self._snapshot = None if snapshot is None else dict(snapshot)

    def active_market_context(self, timeframe: str) -> str | None:
        tf = str(timeframe or "").upper()
        if self._snapshot is not None:
            raw = self._snapshot.get(tf)
            return _clean_context(raw) or None
        self._refresh()
        raw = self._by_tf.get(tf)
        return raw or None

    def still_directional(self, timeframe: str) -> bool:
        return closed_bar_still_directional(self.active_market_context(timeframe))

    def known(self, timeframe: str) -> bool:
        """True when this TF has a closed-bar row we can read."""
        return self.active_market_context(timeframe) is not None

    def tip_timestamp(self, timeframe: str) -> pd.Timestamp | None:
        """Bar-open timestamp of the latest closed-bar row, if known."""
        tf = str(timeframe or "").upper()
        if self._snapshot is not None:
            return None
        self._refresh()
        return self._ts_by_tf.get(tf)

    def _refresh(self) -> None:
        if self.path is None or not self.path.exists():
            self._by_tf = {}
            self._ts_by_tf = {}
            self._mtime_ns = None
            self._size = None
            return
        stat = self.path.stat()
        mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        size = int(stat.st_size)
        if self._mtime_ns == mtime_ns and self._size == size:
            return
        try:
            frame = pd.read_parquet(
                self.path,
                columns=["timestamp", "timeframe", "active_market_context"],
            )
        except Exception:
            try:
                frame = pd.read_parquet(self.path)
            except Exception:
                return
        by_tf, ts_by_tf = _latest_active_by_timeframe(frame)
        self._by_tf = by_tf
        self._ts_by_tf = ts_by_tf
        self._mtime_ns = mtime_ns
        self._size = size


def _latest_active_by_timeframe(
    frame: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, pd.Timestamp]]:
    if frame is None or len(frame) == 0:
        return {}, {}
    work = frame.copy()
    if "timestamp" in work.columns:
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
        work = work.dropna(subset=["timestamp"])
        work = work.sort_values("timestamp")
    if "timeframe" not in work.columns:
        work["timeframe"] = "M15"
    work["timeframe"] = work["timeframe"].astype(str).str.upper()
    work["active_market_context"] = work["active_market_context"].map(_clean_context)
    out: dict[str, str] = {}
    ts_out: dict[str, pd.Timestamp] = {}
    for tf in TIMEFRAMES:
        part = work.loc[work["timeframe"] == tf]
        if len(part) == 0:
            continue
        last = part.iloc[-1]
        ctx = str(last["active_market_context"] or "")
        if ctx:
            out[tf] = ctx
        if "timestamp" in part.columns:
            tip = _as_utc(last["timestamp"])
            if tip is not None:
                ts_out[tf] = tip
    return out, ts_out
