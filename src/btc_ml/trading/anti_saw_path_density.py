"""Path-density anti-saw: is this closed-bar window a saw right now?

Not a bar-count delay. Scores a closed-bar window:

- rotation / path density: 1 - |net| / path (same family as auction balance_support)
- ATR density: how many ATR units of body-path packed into that net
- failed breakouts: range high/low taken, then close back inside

Gate OPEN only. CONTEXT_END / FLIP-close / TP / SL stay untouched.
Missing history fails open: no bars → do not block.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
DEFAULT_WINDOW_BARS = {"M15": 8, "M30": 8, "H1": 6, "H4": 4}
BLOCK_REASON = "ENTRY_BLOCKED_SAW_PATH_DENSITY"
DEFAULT_CANDLE_PATH = Path("data/cognition/candle_structure_memory.parquet")


@dataclass(frozen=True)
class SawScore:
    n_bars: int
    rotation: float
    two_sided: float
    balance_support: float
    net_over_path: float
    path_atr: float
    net_atr: float
    atr: float
    failed_breakouts: int
    failed_up_breakouts: int
    failed_down_breakouts: int
    is_saw: bool
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SawDecision:
    block: bool
    reason: str | None
    timeframe: str
    score: SawScore | None
    source: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "block": self.block,
            "reason": self.reason,
            "timeframe": self.timeframe,
            "source": self.source,
            "detail": self.detail,
        }
        if self.score is not None:
            payload["score"] = self.score.to_dict()
        return payload


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def count_failed_breakouts(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> tuple[int, int]:
    """Failed probes of the running range: take the extreme, close back inside."""
    if len(highs) < 2:
        return 0, 0
    run_high = float(highs[0])
    run_low = float(lows[0])
    pending_up: float | None = None
    pending_down: float | None = None
    failed_up = 0
    failed_down = 0
    for high, low, close in zip(highs[1:], lows[1:], closes[1:]):
        high_f = float(high)
        low_f = float(low)
        close_f = float(close)
        if high_f > run_high:
            pending_up = run_high
            run_high = high_f
        if low_f < run_low:
            pending_down = run_low
            run_low = low_f
        if pending_up is not None and close_f < pending_up:
            failed_up += 1
            pending_up = None
        if pending_down is not None and close_f > pending_down:
            failed_down += 1
            pending_down = None
    return failed_up, failed_down


def score_bars(
    bars: Sequence[Mapping[str, Any]],
    *,
    balance_support_enter: float = 0.55,
    balance_max_net_disp_ratio: float = 0.40,
    min_path_atr: float = 2.0,
    min_failed_breakouts: int = 1,
    min_bars: int = 3,
) -> SawScore:
    """Score a chronological window of closed OHLC bars."""
    rows = [b for b in bars if _finite_ohlc(b)]
    n = len(rows)
    empty = dict(
        n_bars=n,
        rotation=0.0,
        two_sided=0.0,
        balance_support=0.0,
        net_over_path=1.0,
        path_atr=0.0,
        net_atr=0.0,
        atr=0.0,
        failed_breakouts=0,
        failed_up_breakouts=0,
        failed_down_breakouts=0,
        is_saw=False,
        reason="INSUFFICIENT_HISTORY",
    )
    if n < int(min_bars):
        return SawScore(**empty)
    opens = [float(b["open"]) for b in rows]
    highs = [float(b["high"]) for b in rows]
    lows = [float(b["low"]) for b in rows]
    closes = [float(b["close"]) for b in rows]
    bodies = [c - o for o, c in zip(opens, closes)]
    path = sum(abs(x) for x in bodies)
    net = abs(closes[-1] - closes[0])
    net_over_path = 1.0 if path <= 1e-12 else net / path
    rotation = _clamp(1.0 - net_over_path)
    up = sum(x for x in bodies if x > 0)
    down = sum(-x for x in bodies if x < 0)
    two_sided = _clamp(1.0 - abs(up - down) / (path + 1e-12))
    balance_support = _clamp(0.6 * rotation + 0.4 * two_sided)
    ranges = [max(h - lo, 0.0) for h, lo in zip(highs, lows)]
    atr = _median(ranges) if ranges else 0.0
    path_atr = 0.0 if atr <= 1e-12 else path / atr
    net_atr = 0.0 if atr <= 1e-12 else net / atr
    failed_up, failed_down = count_failed_breakouts(highs, lows, closes)
    failed_breakouts = failed_up + failed_down
    chop = (
        balance_support >= float(balance_support_enter)
        and net_over_path <= float(balance_max_net_disp_ratio)
    )
    atr_dense = path_atr >= float(min_path_atr)
    rejected = failed_breakouts >= int(min_failed_breakouts)
    is_saw = bool(chop and atr_dense and rejected)
    return SawScore(
        n_bars=n,
        rotation=round(rotation, 6),
        two_sided=round(two_sided, 6),
        balance_support=round(balance_support, 6),
        net_over_path=round(net_over_path, 6),
        path_atr=round(path_atr, 6),
        net_atr=round(net_atr, 6),
        atr=round(atr, 6),
        failed_breakouts=int(failed_breakouts),
        failed_up_breakouts=int(failed_up),
        failed_down_breakouts=int(failed_down),
        is_saw=bool(is_saw),
        reason=BLOCK_REASON if is_saw else None,
    )


def _finite_ohlc(bar: Mapping[str, Any]) -> bool:
    try:
        open_ = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
    except (TypeError, ValueError, KeyError):
        return False
    return all(x == x and abs(x) < 1e18 for x in (open_, high, low, close))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _parse_cfg(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    block = dict((raw or {}).get("anti_saw_path_density") or {})
    windows = dict(DEFAULT_WINDOW_BARS)
    extra = block.get("window_bars") or {}
    if isinstance(extra, dict):
        windows.update({str(k).upper(): int(v) for k, v in extra.items()})
    return {
        "enabled": bool(block.get("enabled", False)),
        "mode": str(block.get("mode") or "enforce").strip().lower(),
        "window_bars": windows,
        "balance_support_enter": float(block.get("balance_support_enter", 0.55)),
        "balance_max_net_disp_ratio": float(block.get("balance_max_net_disp_ratio", 0.40)),
        "min_path_atr": float(block.get("min_path_atr", 2.0)),
        "min_failed_breakouts": int(block.get("min_failed_breakouts", 1)),
        "min_bars": int(block.get("min_bars", 3)),
        "candle_structure_path": str(
            block.get("candle_structure_path") or DEFAULT_CANDLE_PATH
        ),
    }


class PathDensitySawFilter:
    """Closed-bar saw detector. Inject ``bars_by_tf`` in tests."""

    def __init__(
        self,
        cfg_raw: Mapping[str, Any] | None = None,
        *,
        repo_root: Path | None = None,
        bars_by_tf: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.params = _parse_cfg(cfg_raw)
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
        self._bars_by_tf = {str(k).upper(): list(v) for k, v in dict(bars_by_tf or {}).items()}
        self._mtime_ns: int | None = None
        self._size: int | None = None
        self._m15: list[dict[str, Any]] = []
        self.last_decision: SawDecision | None = None

    def evaluate(
        self,
        *,
        timeframe: str,
        as_of: Any = None,
    ) -> SawDecision:
        tf = str(timeframe or "").upper()
        if not self.params["enabled"]:
            decision = SawDecision(False, None, tf, None, "disabled")
            self.last_decision = decision
            return decision
        window = int(self.params["window_bars"].get(tf, DEFAULT_WINDOW_BARS.get(tf, 8)))
        bars = self._window(tf, window=window, as_of=as_of)
        if len(bars) < int(self.params["min_bars"]):
            decision = SawDecision(
                False,
                None,
                tf,
                None,
                "insufficient_history",
                detail=f"n={len(bars)}<{self.params['min_bars']}",
            )
            self.last_decision = decision
            return decision
        score = score_bars(
            bars,
            balance_support_enter=float(self.params["balance_support_enter"]),
            balance_max_net_disp_ratio=float(self.params["balance_max_net_disp_ratio"]),
            min_path_atr=float(self.params["min_path_atr"]),
            min_failed_breakouts=int(self.params["min_failed_breakouts"]),
            min_bars=int(self.params["min_bars"]),
        )
        mode = str(self.params["mode"])
        enforce = mode == "enforce"
        block = bool(score.is_saw) and enforce
        reason = BLOCK_REASON if block else None
        decision = SawDecision(
            block=block,
            reason=reason,
            timeframe=tf,
            score=score,
            source="path_density",
            detail=None if enforce else "candidate_observe",
        )
        self.last_decision = decision
        return decision

    def _window(
        self,
        timeframe: str,
        *,
        window: int,
        as_of: Any,
    ) -> list[dict[str, Any]]:
        if timeframe in self._bars_by_tf:
            rows = list(self._bars_by_tf[timeframe])
        else:
            rows = self._tf_bars(timeframe)
        cutoff = _as_of_ts(as_of)
        if cutoff is not None:
            minutes = TF_MINUTES.get(timeframe, 15)
            closed = []
            for row in rows:
                ts = _bar_ts(row.get("timestamp"))
                if ts is None:
                    continue
                close_at = ts + minutes * 60
                if close_at <= cutoff:
                    closed.append(row)
            rows = closed
        return rows[-int(window) :]

    def _tf_bars(self, timeframe: str) -> list[dict[str, Any]]:
        m15 = self._load_m15()
        if timeframe == "M15":
            return m15
        return _resample(m15, timeframe)

    def _load_m15(self) -> list[dict[str, Any]]:
        path = self.params["candle_structure_path"]
        full = Path(path)
        if not full.is_absolute():
            full = self.repo_root / full
        if not full.exists():
            self._m15 = []
            self._mtime_ns = None
            self._size = None
            return self._m15
        stat = full.stat()
        mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        size = int(stat.st_size)
        if self._mtime_ns == mtime_ns and self._size == size:
            return self._m15
        try:
            import pandas as pd
        except ImportError:
            self._m15 = []
            return self._m15
        try:
            frame = pd.read_parquet(full, columns=["timestamp", "open", "high", "low", "close"])
        except Exception:
            try:
                frame = pd.read_parquet(full)
            except Exception:
                return self._m15
        if frame is None or len(frame) == 0:
            self._m15 = []
            self._mtime_ns = mtime_ns
            self._size = size
            return self._m15
        work = frame.copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
        work = work.dropna(subset=["timestamp", "open", "high", "low", "close"])
        work = work.sort_values("timestamp")
        self._m15 = [
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
            }
            for ts, o, h, lo, c in work[["timestamp", "open", "high", "low", "close"]].itertuples(
                index=False, name=None
            )
        ]
        self._mtime_ns = mtime_ns
        self._size = size
        return self._m15


def _as_of_ts(value: Any) -> float | None:
    ts = _bar_ts(value)
    return ts


def _bar_ts(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    try:
        import pandas as pd

        stamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(stamp):
            return None
        return float(stamp.timestamp())
    except Exception:
        return None


def _resample(m15: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    minutes = TF_MINUTES.get(str(timeframe).upper())
    if not minutes or minutes == 15:
        return [dict(row) for row in m15]
    step = minutes * 60
    buckets: dict[int, list[Mapping[str, Any]]] = {}
    order: list[int] = []
    for row in m15:
        ts = _bar_ts(row.get("timestamp"))
        if ts is None:
            continue
        key = int(ts) - (int(ts) % step)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    out: list[dict[str, Any]] = []
    for key in order:
        group = buckets[key]
        if not group:
            continue
        out.append(
            {
                "timestamp": group[0].get("timestamp"),
                "open": float(group[0]["open"]),
                "high": max(float(b["high"]) for b in group),
                "low": min(float(b["low"]) for b in group),
                "close": float(group[-1]["close"]),
            }
        )
    return out


def snapshot_for_candles(
    timeframe: str,
    candles: Sequence[Mapping[str, Any]],
    *,
    cfg_raw: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Observability snapshot for chart / OPS. Does not gate."""
    tf = str(timeframe or "").upper()
    params = _parse_cfg(cfg_raw if cfg_raw is not None else {"anti_saw_path_density": {"enabled": True}})
    window = int(params["window_bars"].get(tf, DEFAULT_WINDOW_BARS.get(tf, 8)))
    rows = [row for row in candles if _finite_ohlc(row)][-window:]
    score = score_bars(
        rows,
        balance_support_enter=float(params["balance_support_enter"]),
        balance_max_net_disp_ratio=float(params["balance_max_net_disp_ratio"]),
        min_path_atr=float(params["min_path_atr"]),
        min_failed_breakouts=int(params["min_failed_breakouts"]),
        min_bars=int(params["min_bars"]),
    )
    return {
        "timeframe": tf,
        "is_saw": bool(score.is_saw),
        "window_bars": window,
        "source": "path_density",
        "score": score.to_dict(),
    }
