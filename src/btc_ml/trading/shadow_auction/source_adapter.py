"""Read-only AES2 source adapter — M15 evidence + shadow-side HTF aggregate.

Does NOT create canonical producers. Higher TFs are aggregated only inside Shadow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .observation import BarObservation

TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    # pandas NaT / NaN
    try:
        import pandas as pd

        if value is pd.NaT or (isinstance(value, float) and value != value):
            return None
        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                return None
            dt = value.to_pydatetime()
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text or text.lower() in {"nat", "nan", "none", "null"}:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _floor_bucket(dt: datetime, minutes: int) -> datetime:
    epoch = int(dt.timestamp())
    step = minutes * 60
    floored = epoch - (epoch % step)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


@dataclass
class SourcePaths:
    candle_structure: Path
    volume_classification: Path
    volume_response: Path | None = None
    volume_localization: Path | None = None


def default_source_paths(repo: Path) -> SourcePaths:
    cog = repo / "data" / "cognition"
    return SourcePaths(
        candle_structure=cog / "candle_structure_memory.parquet",
        volume_classification=cog / "volume_classification_memory.parquet",
        volume_response=cog / "volume_response_state.parquet",
        volume_localization=cog / "volume_localization_memory.parquet",
    )


def _optional_join_maps(
    path: Path | None,
    *,
    key: str = "timestamp",
) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        import pandas as pd
    except ImportError:
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if key not in df.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in df.to_dict(orient="records"):
        ts = _parse_ts(row.get(key))
        if ts is None:
            continue
        out[_iso(ts)] = dict(row)
    return out


def load_m15_observations(
    *,
    repo: Path,
    paths: SourcePaths | None = None,
    since_timestamp: str | None = None,
    limit: int | None = None,
) -> list[BarObservation]:
    """Load M15 bars from confirmed cognition parquets (read-only)."""
    sp = paths or default_source_paths(repo)
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas required to read AES2 sources") from exc

    primary = sp.volume_classification if sp.volume_classification.exists() else sp.candle_structure
    if not primary.exists():
        return []
    df = pd.read_parquet(primary)
    if "timestamp" not in df.columns:
        return []
    df = df.copy()
    df["_ts"] = df["timestamp"].map(_parse_ts)
    df = df[df["_ts"].notna()].sort_values("_ts")
    since = _parse_ts(since_timestamp)
    if since is not None:
        df = df[df["_ts"] > since]

    response = _optional_join_maps(sp.volume_response)
    localization = _optional_join_maps(sp.volume_localization)

    rows: list[BarObservation] = []
    records = df.to_dict(orient="records")
    if limit is not None and since is None:
        # Cold-start / latest-only: take the most recent N closed bars.
        records = records[-int(limit) :]
    for raw in records:
        ts = _parse_ts(raw.get("timestamp"))
        if ts is None:
            continue
        ts_s = _iso(ts)
        extra = dict(response.get(ts_s) or {})
        loc = dict(localization.get(ts_s) or {})
        obs = BarObservation(
            timestamp=ts_s,
            timeframe="M15",
            source_event_id=f"M15|{ts_s}",
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume") or 0.0),
            buy_volume=_f(raw.get("buy_volume")),
            sell_volume=_f(raw.get("sell_volume")),
            delta=_f(raw.get("delta")),
            close_position=_f(raw.get("close_position")),
            body=_f(raw.get("body")),
            spread=_f(raw.get("spread")),
            upper_wick=_f(raw.get("upper_wick")),
            lower_wick=_f(raw.get("lower_wick")),
            volume_zscore=_f(raw.get("volume_zscore")),
            spread_zscore=_f(raw.get("spread_zscore")),
            volume_class=_s(raw.get("volume_class")),
            effort_score=_f(extra.get("effort_score")),
            result_score=_f(extra.get("result_score")),
            climax_state=_s(extra.get("climax_state")),
            participation_state=_s(extra.get("participation_state")),
            unfinished_auction=_b(extra.get("unfinished_auction")),
            localized_behavior=_s(loc.get("localized_behavior") or extra.get("localized_behavior")),
            upper_rejection=_b(loc.get("upper_rejection")),
            lower_rejection=_b(loc.get("lower_rejection")),
            oi_change=None,
        )
        rows.append(obs)
        if limit is not None and len(rows) >= int(limit):
            break
    return rows


def aggregate_htf(m15_bars: list[BarObservation], timeframe: str) -> list[BarObservation]:
    """Shadow-side aggregate M15 → M30/H1/H4. Not a canonical producer."""
    tf = timeframe.upper()
    minutes = TF_MINUTES.get(tf)
    if minutes is None:
        raise ValueError(f"unsupported TF: {tf}")
    if tf == "M15":
        return list(m15_bars)
    buckets: dict[str, list[BarObservation]] = {}
    order: list[str] = []
    for bar in m15_bars:
        ts = _parse_ts(bar.timestamp)
        if ts is None:
            continue
        bucket = _iso(_floor_bucket(ts, minutes))
        if bucket not in buckets:
            buckets[bucket] = []
            order.append(bucket)
        buckets[bucket].append(bar)

    out: list[BarObservation] = []
    for bucket in order:
        group = buckets[bucket]
        if not group:
            continue
        # Only emit completed buckets relative to last M15 (caller may filter).
        open_ = group[0].open
        high = max(b.high for b in group)
        low = min(b.low for b in group)
        close = group[-1].close
        volume = sum(b.volume for b in group)
        buy = _sum_opt(b.buy_volume for b in group)
        sell = _sum_opt(b.sell_volume for b in group)
        delta = None if buy is None or sell is None else buy - sell
        spread = high - low
        body = abs(close - open_)
        upper_wick = max(0.0, high - max(open_, close))
        lower_wick = max(0.0, min(open_, close) - low)
        close_pos = 0.0 if spread <= 0 else (close - low) / spread
        vol_z = _mean_opt(b.volume_zscore for b in group)
        end_ts = group[-1].timestamp
        out.append(
            BarObservation(
                timestamp=end_ts,
                timeframe=tf,
                source_event_id=f"{tf}|{end_ts}|{bucket}",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                buy_volume=buy,
                sell_volume=sell,
                delta=delta,
                close_position=close_pos,
                body=body,
                spread=spread,
                upper_wick=upper_wick,
                lower_wick=lower_wick,
                volume_zscore=vol_z,
                spread_zscore=None,
                volume_class=None,
                effort_score=None,
                result_score=None,
                climax_state=None,
                participation_state=None,
                unfinished_auction=None,
                localized_behavior=None,
                upper_rejection=None,
                lower_rejection=None,
                oi_change=None,
            )
        )
    return out


def iter_new_bars(
    *,
    repo: Path,
    last_m15_timestamp: str | None,
    emit_incomplete_htf: bool = False,
) -> Iterator[tuple[str, BarObservation]]:
    """Yield only newly closed bars per TF since last M15 watermark.

    Live mode: no full-history backfill — caller passes last processed timestamp.
    """
    m15 = load_m15_observations(repo=repo, since_timestamp=last_m15_timestamp)
    if not m15:
        return
    # For HTF, drop incomplete trailing bucket unless explicitly allowed.
    for tf in ("M15", "M30", "H1", "H4"):
        bars = aggregate_htf(m15, tf)
        if tf != "M15" and bars and not emit_incomplete_htf:
            # Drop last bucket if it may still be forming (fewer than TF/15 M15 bars).
            need = TF_MINUTES[tf] // 15
            # Recompute last bucket size from original m15 set.
            last = bars[-1]
            bucket_ts = _parse_ts(last.source_event_id.split("|")[-1])
            if bucket_ts is not None:
                count = sum(
                    1
                    for b in m15
                    if (pt := _parse_ts(b.timestamp)) is not None
                    and _floor_bucket(pt, TF_MINUTES[tf]) == bucket_ts
                )
                if count < need:
                    bars = bars[:-1]
        for bar in bars:
            yield tf, bar


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _b(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _sum_opt(values) -> float | None:
    total = 0.0
    any_v = False
    for v in values:
        if v is None:
            continue
        total += float(v)
        any_v = True
    return total if any_v else None


def _mean_opt(values) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
