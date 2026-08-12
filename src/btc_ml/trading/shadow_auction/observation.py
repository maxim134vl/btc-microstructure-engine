"""AES2 bar observation contract — only fields available from confirmed sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass
class BarObservation:
    """Normalized closed-bar observation for one timeframe.

    Upstream sources (read-only):
    - candle_structure_memory / volume_classification_memory: OHLC, volume, delta,
      close_position, wick, volume_zscore, volume_class
    - volume_response_state: effort_score, result_score, climax_state,
      participation_state, unfinished_auction, localized_behavior
    - volume_localization_memory: upper/lower rejection, localized_behavior
    - climactic_behavior_memory: climactic_state (optional join)

    Missing optional fields stay None — engines must not invent them.
    """

    timestamp: str
    timeframe: str
    source_event_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float | None = None
    sell_volume: float | None = None
    delta: float | None = None
    close_position: float | None = None
    body: float | None = None
    spread: float | None = None
    upper_wick: float | None = None
    lower_wick: float | None = None
    volume_zscore: float | None = None
    spread_zscore: float | None = None
    volume_class: str | None = None
    effort_score: float | None = None
    result_score: float | None = None
    climax_state: str | None = None
    participation_state: str | None = None
    unfinished_auction: bool | None = None
    localized_behavior: str | None = None
    upper_rejection: bool | None = None
    lower_rejection: bool | None = None
    oi_change: float | None = None  # only when available; usually None
    # Test / research overrides — NOT calibrated probabilities.
    feature_overrides: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BarObservation":
        overrides = dict(raw.get("feature_overrides") or {})
        return cls(
            timestamp=str(raw["timestamp"]),
            timeframe=str(raw["timeframe"]).upper(),
            source_event_id=str(raw["source_event_id"]),
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume") or 0.0),
            buy_volume=_opt_float(raw.get("buy_volume")),
            sell_volume=_opt_float(raw.get("sell_volume")),
            delta=_opt_float(raw.get("delta")),
            close_position=_opt_float(raw.get("close_position")),
            body=_opt_float(raw.get("body")),
            spread=_opt_float(raw.get("spread")),
            upper_wick=_opt_float(raw.get("upper_wick")),
            lower_wick=_opt_float(raw.get("lower_wick")),
            volume_zscore=_opt_float(raw.get("volume_zscore")),
            spread_zscore=_opt_float(raw.get("spread_zscore")),
            volume_class=_opt_str(raw.get("volume_class")),
            effort_score=_opt_float(raw.get("effort_score")),
            result_score=_opt_float(raw.get("result_score")),
            climax_state=_opt_str(raw.get("climax_state")),
            participation_state=_opt_str(raw.get("participation_state")),
            unfinished_auction=_opt_bool(raw.get("unfinished_auction")),
            localized_behavior=_opt_str(raw.get("localized_behavior")),
            upper_rejection=_opt_bool(raw.get("upper_rejection")),
            lower_rejection=_opt_bool(raw.get("lower_rejection")),
            oi_change=_opt_float(raw.get("oi_change")),
            feature_overrides=overrides,
        )


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _opt_bool(value: Any) -> bool | None:
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
