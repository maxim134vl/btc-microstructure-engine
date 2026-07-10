"""Shadow auction-context arbitrator — scores evidence into directional context.

Research/replay only. Does not drive live trading_state_engine decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

ChosenContext = Literal["LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"]
AnchorStatus = Literal["HELD", "FAILED", "UNRESOLVED", "NONE"]

FINAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"})
DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
CANDIDATE_POSTURES = frozenset({"REVERSAL_WATCH", "STAND_ASIDE"})
CALIBRATED_V2_MIN_DIRECTIONAL_SCORE = 0.75
CALIBRATED_V2_MIN_SCORE_MARGIN = 0.25

# Outcome-only fields — must never influence live/calibrated decisions.
OUTCOME_ONLY_EVIDENCE_FIELDS = frozenset(
    {
        "forward_return_4b",
        "forward_return_8b",
        "forward_return_16b",
        "max_favorable_16b",
        "max_adverse_16b",
    }
)

# Rules that previously used outcome fields for decisions (documented for audit).
NOT_LIVE_SAFE_RULES_REMOVED = (
    "short_subtype.downside_continuation: forward_return_4b < -0.001 → recent_return / reason / effort",
    "short_subtype.upside_failed: forward_return_8b <= 0 → reason / climax / effort",
    "short_subtype.SHORT_IMPULSE_ONLY: forward_return_4b/8b/16b → recent_return + effort + convergence",
    "short_subtype.LATE_EXHAUSTION_SHORT: forward_return_8b/16b + max_favorable/max_adverse → anchor_age + recent_return + climax/effort",
    "short_subtype.DIRECTIONAL_DISTRIBUTION_CONTINUATION: forward_return_4b/8b → recent_return",
    "long_subtype.LATE_REBOUND_LONG: forward_return_* + max_favorable/max_adverse → recent_return_* (backward)",
)


@dataclass(frozen=True)
class AuctionContextEvidence:
    """Point-in-time auction evidence for context arbitration."""

    timestamp: Any
    close: float
    market_state: str = ""
    market_bias: str = ""
    trading_state: str = ""
    volume_event: str = ""
    climax_state: str = ""
    effort_result_state: str = ""
    continuation_quality: str = ""
    localized_behavior: str = ""
    convergence_state: str = ""
    auction_regime: str = ""
    effective_state: str = ""
    tier1_trigger_event: str = ""
    tier1_location_bias: str = ""
    anchor_timestamp: Any = None
    anchor_age_bars: float = 0.0
    absorption_probability: float = 0.0
    distribution_probability: float = 0.0
    absorption_behavior_share: float = 0.0
    supply_behavior_share: float = 0.0
    anchor_price: float | None = None
    anchor_status: str | None = None
    recent_return: float | None = None
    recent_return_8b: float | None = None
    recent_return_16b: float | None = None
    candle_history: pd.DataFrame | None = None
    forward_return_4b: float | None = None
    forward_return_8b: float | None = None
    forward_return_16b: float | None = None
    max_favorable_16b: float | None = None
    max_adverse_16b: float | None = None


@dataclass(frozen=True)
class AuctionContextArbitrationResult:
    """Scored arbitration output for one evidence snapshot."""

    long_context_score: float
    short_context_score: float
    observe_score: float
    anchor_status: AnchorStatus
    anchor_price_or_zone: str | None
    anchor_event_type: str
    chosen_context: ChosenContext
    chosen_reason: str
    why_not_long: str
    why_not_short: str
    short_subtype: str = ""
    tactical_short_candidate: bool = False
    suppress_reason: str = ""
    raw_chosen_context: str = ""
    long_subtype: str = ""
    tactical_long_candidate: bool = False
    short_candidate: bool = False
    long_reasons: tuple[str, ...] = field(default=())
    short_reasons: tuple[str, ...] = field(default=())
    observe_reasons: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class _ScoreBundle:
    long_score: float
    short_score: float
    observe_score: float
    long_reasons: list[str]
    short_reasons: list[str]
    observe_reasons: list[str]
    why_not_long: list[str]
    why_not_short: list[str]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def existing_context_from_trading_state(trading_state: str) -> str | None:
    """Map live trading posture to final directional context (candidates → None)."""
    state = _clean_text(trading_state).upper()
    if state in CANDIDATE_POSTURES:
        return None
    if state in FINAL_CONTEXTS:
        return state
    return None


def resolve_anchor_price(
    candles: pd.DataFrame,
    anchor_ts: pd.Timestamp | None,
    location_bias: str,
) -> float | None:
    if anchor_ts is None or candles.empty or "timestamp" not in candles.columns:
        return None
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    subset = frame[frame["timestamp"] <= anchor_ts]
    if subset.empty:
        return None
    row = subset.iloc[-1]
    bias = location_bias.upper()
    if "LOWER" in bias:
        return _safe_float(row.get("low"))
    if "UPPER" in bias:
        return _safe_float(row.get("high"))
    return _safe_float(row.get("close"))


def resolve_anchor_status(
    *,
    anchor_price: float | None,
    location_bias: str,
    close: float,
    anchor_age_bars: float,
    continuation_quality: str,
    convergence_state: str,
) -> AnchorStatus:
    if anchor_price is None:
        return "NONE"
    bias = location_bias.upper()
    buffer = max(anchor_price * 0.0015, 25.0)
    if "LOWER" in bias:
        if close >= anchor_price:
            return "HELD"
        if close < anchor_price - buffer:
            return "FAILED"
    elif "UPPER" in bias:
        if close <= anchor_price:
            return "HELD"
        if close > anchor_price + buffer:
            return "FAILED"
    else:
        if abs(close - anchor_price) <= buffer:
            return "HELD"
        if abs(close - anchor_price) > buffer * 2:
            return "FAILED"

    if anchor_age_bars >= 12 and continuation_quality.upper() in {
        "EFFICIENT_CONTINUATION",
        "STRONG_CONTINUATION",
    }:
        return "FAILED"
    if convergence_state.upper().startswith("PERSISTENT"):
        return "FAILED"
    if anchor_age_bars >= 8:
        return "UNRESOLVED"
    return "UNRESOLVED"


def compute_recent_return(
    candles: pd.DataFrame,
    timestamp: pd.Timestamp,
    *,
    bars: int = 4,
) -> float:
    if candles.empty or "timestamp" not in candles.columns:
        return 0.0
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    subset = frame[frame["timestamp"] <= timestamp].tail(bars + 1)
    if len(subset) < 2:
        return 0.0
    start = _safe_float(subset.iloc[0]["close"])
    end = _safe_float(subset.iloc[-1]["close"])
    if start <= 0:
        return 0.0
    return (end - start) / start


def _aggregate(bits: list[tuple[float, str]]) -> tuple[float, list[str]]:
    if not bits:
        return 0.0, []
    weights = np.array([weight for weight, _ in bits], dtype=float)
    score = _clip01(1.0 - np.prod(1.0 - weights))
    reasons = [reason for _, reason in sorted(bits, key=lambda item: item[0], reverse=True)]
    return score, reasons


def _compute_scores(
    evidence: AuctionContextEvidence,
    *,
    anchor_status: AnchorStatus,
    recent_return: float,
) -> _ScoreBundle:
    long_bits: list[tuple[float, str]] = []
    short_bits: list[tuple[float, str]] = []
    observe_bits: list[tuple[float, str]] = []

    volume_event = _clean_text(evidence.volume_event).upper()
    climax_state = _clean_text(evidence.climax_state).upper()
    effort_state = _clean_text(evidence.effort_result_state).upper()
    convergence_state = _clean_text(evidence.convergence_state).upper()
    auction_regime = _clean_text(evidence.auction_regime).upper()
    market_state = _clean_text(evidence.market_state).upper()
    market_bias = _clean_text(evidence.market_bias).upper()
    effective_state = _clean_text(evidence.effective_state).upper()
    trigger_event = _clean_text(evidence.tier1_trigger_event).upper()
    location_bias = _clean_text(evidence.tier1_location_bias).upper()
    localized_behavior = _clean_text(evidence.localized_behavior).upper()

    absorption_prob = _safe_float(evidence.absorption_probability)
    distribution_prob = _safe_float(evidence.distribution_probability)
    supply_share = _safe_float(evidence.supply_behavior_share)
    absorption_share = _safe_float(evidence.absorption_behavior_share)
    anchor_age_bars = _safe_float(evidence.anchor_age_bars)

    if anchor_status != "FAILED":
        if volume_event in {"STOPPING_VOLUME", "ABSORPTION_VOLUME"} and "LOWER" in location_bias:
            long_bits.append((0.85, "stopping/absorption volume at lows"))
        elif trigger_event == "STOPPING_VOLUME" and "LOWER" in location_bias:
            long_bits.append((0.8, "cognition anchor is stopping volume at lows"))
    if climax_state == "CLIMAX_EXHAUSTION" and recent_return < 0:
        long_bits.append((0.55, "selling climax into down move"))
    if effort_state == "ABSORPTION_RESPONSE":
        long_bits.append((0.7, "absorption response held"))
    if anchor_status == "HELD" and "LOWER" in location_bias:
        long_bits.append((0.75, "reversal anchor held at lows"))
    if recent_return > -0.002 and recent_return < 0.004 and market_state == "REVERSAL":
        long_bits.append((0.45, "downside continuation failed to extend"))
    if supply_share < 0.45 and absorption_share > 0.4:
        long_bits.append((0.5, "supply effort weakening vs absorption"))
    if market_bias in {"BULLISH", "CONTEXTUAL"} and market_state == "REVERSAL":
        long_bits.append((0.35, "reversal market_state with non-bearish bias"))
    if effective_state in {"INTERMEDIATE_REVERSAL", "STRUCTURAL_REVERSAL", "LOCAL_EXHAUSTION"}:
        long_bits.append((0.4, f"cognition effective_state={effective_state}"))

    if volume_event == "EXHAUSTION_VOLUME" or climax_state == "CLIMAX_CONTINUATION":
        short_bits.append((0.55, "buying climax / continuation exhaustion"))
    if effort_state == "EFFICIENT_CONTINUATION" and recent_return < -0.003:
        short_bits.append((0.75, "efficient downside continuation"))
    if distribution_prob >= 0.45 or auction_regime == "DISTRIBUTION_REGIME":
        short_bits.append((0.65, "distribution regime dominant"))
    if convergence_state.startswith("PERSISTENT_DISTRIBUTION"):
        short_bits.append((0.7, "persistent distribution convergence"))
    if anchor_status == "FAILED" and "LOWER" in location_bias:
        short_bits.append((0.8, "stopping-volume anchor failed (broke below lows)"))
    if localized_behavior in {"DISTRIBUTION", "SUPPLY_DOMINANT"}:
        short_bits.append((0.55, f"localized behavior={localized_behavior}"))
    if market_state == "DISTRIBUTION" or market_bias == "BEARISH":
        short_bits.append((0.5, "bearish market_state/bias"))
    if recent_return <= -0.004:
        short_bits.append((0.6, f"price falling ({recent_return * 100:.2f}% over 4 bars)"))
    if effective_state in {"IC_CONTINUATION_WEAKENING", "IC_INITIATIVE_DETERIORATION"} and recent_return < 0:
        short_bits.append((0.45, "continuation deterioration with lower prices"))

    if anchor_status in {"NONE", "UNRESOLVED"}:
        observe_bits.append((0.55, "no resolved active anchor"))
    if not long_bits and not short_bits:
        observe_bits.append((0.65, "auction evidence sparse on this bar"))
    if absorption_prob > 0.35 and distribution_prob > 0.35:
        observe_bits.append((0.6, "conflicting absorption vs distribution probabilities"))
    if market_state == "NEUTRAL":
        observe_bits.append((0.5, "neutral market_state"))
    if volume_event == "NEUTRAL_VOLUME" and effort_state == "BALANCED_RESPONSE":
        observe_bits.append((0.45, "balanced/neutral volume response"))

    long_score, long_reasons = _aggregate(long_bits)
    short_score, short_reasons = _aggregate(short_bits)
    observe_score, observe_reasons = _aggregate(observe_bits)

    if anchor_status == "FAILED" and "LOWER" in location_bias:
        long_score = _clip01(long_score * 0.2)
        short_score = _clip01(max(short_score, 0.72))
        long_reasons.append("anchor failure discounts long reversal thesis")
        short_reasons.append("failed stopping-volume anchor supports short/exit")
    if convergence_state.startswith("PERSISTENT_DISTRIBUTION") and recent_return < 0:
        short_score = _clip01(max(short_score, 0.68))
    if anchor_status == "UNRESOLVED" and anchor_age_bars >= 8:
        observe_score = _clip01(max(observe_score, 0.62))
        observe_reasons.append("aged unresolved anchor — defer directional commitment")

    if abs(long_score - short_score) < 0.12:
        observe_score = _clip01(max(observe_score, 0.55))
        observe_reasons.append("long/short scores too close")
    if long_score < 0.35 and short_score < 0.35:
        observe_score = _clip01(max(observe_score, 0.6))
        observe_reasons.append("both directional scores weak")

    why_not_long: list[str] = []
    why_not_short: list[str] = []
    if short_score >= long_score:
        why_not_long.extend(short_reasons[:3] or ["short evidence dominated"])
    if long_score >= short_score:
        why_not_short.extend(long_reasons[:3] or ["long evidence dominated"])
    if anchor_status == "FAILED" and "LOWER" in location_bias:
        why_not_long.append("reversal anchor at lows already failed")
    if anchor_status == "HELD" and "LOWER" in location_bias:
        why_not_short.append("reversal anchor still holding at lows")
    if market_state == "REVERSAL" and _clean_text(evidence.trading_state).upper() == "REVERSAL_WATCH":
        why_not_short.append("live model maps REVERSAL market_state → REVERSAL_WATCH (not SHORT_CONTEXT)")

    return _ScoreBundle(
        long_score=long_score,
        short_score=short_score,
        observe_score=observe_score,
        long_reasons=long_reasons,
        short_reasons=short_reasons,
        observe_reasons=observe_reasons,
        why_not_long=sorted(set(why_not_long)),
        why_not_short=sorted(set(why_not_short)),
    )


def _choose_context(
    scores: _ScoreBundle,
    *,
    anchor_status: AnchorStatus,
    location_bias: str,
) -> tuple[ChosenContext, str]:
    candidates: dict[ChosenContext, float] = {
        "LONG_CONTEXT": scores.long_score,
        "SHORT_CONTEXT": scores.short_score,
        "OBSERVE": scores.observe_score,
    }
    chosen: ChosenContext = max(candidates, key=candidates.get)
    margin = sorted(candidates.values(), reverse=True)
    top = margin[0]
    second = margin[1] if len(margin) > 1 else 0.0

    if anchor_status == "FAILED" and chosen == "LONG_CONTEXT":
        chosen = "SHORT_CONTEXT" if scores.short_score >= scores.observe_score else "OBSERVE"
        reason = "failed anchor blocks LONG_CONTEXT commitment"
        if chosen == "SHORT_CONTEXT":
            reason = "; ".join(scores.short_reasons[:4]) or reason
        else:
            reason = "; ".join(scores.observe_reasons[:4]) or reason
        return chosen, reason

    if top < 0.35:
        return "OBSERVE", "all hypothesis scores below commitment threshold"
    if chosen in DIRECTIONAL_CONTEXTS and (top - second) < 0.12:
        return "OBSERVE", "directional scores too close — defer to observe"
    if chosen == "LONG_CONTEXT":
        return chosen, "; ".join(scores.long_reasons[:4]) or "long evidence led"
    if chosen == "SHORT_CONTEXT":
        return chosen, "; ".join(scores.short_reasons[:4]) or "short evidence led"
    return "OBSERVE", "; ".join(scores.observe_reasons[:4]) or "insufficient directional separation"


def _format_anchor_zone(location_bias: str, anchor_price: float | None) -> str | None:
    if anchor_price is None:
        return location_bias or None
    if location_bias:
        return f"{location_bias}@{anchor_price:.2f}"
    return f"{anchor_price:.2f}"


def _extract_anchor_price(anchor_price_or_zone: Any) -> float | None:
    text = _clean_text(anchor_price_or_zone)
    if not text:
        return None
    if "@" in text:
        text = text.split("@", 1)[1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def classify_short_subtype(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
) -> str:
    """Live-safe short subtype for calibrated_v2 decisions (no forward outcome fields)."""
    if result.chosen_context != "SHORT_CONTEXT":
        return ""

    anchor_status = _clean_text(result.anchor_status).upper()
    anchor_event = _clean_text(result.anchor_event_type).upper()
    market_state = _clean_text(evidence.market_state).upper()
    anchor_zone = _clean_text(result.anchor_price_or_zone).upper()
    reason = _clean_text(result.chosen_reason).lower()
    close = _safe_float(evidence.close, default=float("nan"))
    anchor_price = _extract_anchor_price(result.anchor_price_or_zone)
    recent_return = _safe_float(evidence.recent_return)
    effort_state = _clean_text(evidence.effort_result_state).upper()
    continuation_quality = _clean_text(evidence.continuation_quality).upper()
    convergence_state = _clean_text(evidence.convergence_state).upper()
    climax_state = _clean_text(evidence.climax_state).upper()
    anchor_age_bars = _safe_float(evidence.anchor_age_bars)

    lower_reversal_anchor = ("STOPPING" in anchor_event) or ("LOWER" in anchor_zone)
    downside_continuation = (
        ("efficient downside continuation" in reason)
        or ("persistent distribution" in reason)
        or recent_return < -0.001
        or effort_state == "EFFICIENT_CONTINUATION"
    )
    broke_anchor = anchor_price is not None and not pd.isna(close) and close < anchor_price
    if anchor_status == "FAILED" and lower_reversal_anchor and broke_anchor and downside_continuation:
        return "FAILED_BULLISH_REVERSAL_BREAKDOWN"

    buying_or_upper = (
        ("BUYING" in anchor_event)
        or ("CLIMAX" in anchor_event)
        or ("UPPER" in anchor_zone)
        or ("buying climax" in reason)
    )
    distribution_or_supply = (
        market_state == "DISTRIBUTION"
        or ("distribution" in reason)
        or ("supply" in reason)
    )
    upside_failed = (
        ("upside continuation failed" in reason)
        or climax_state in {"CLIMAX_EXHAUSTION", "CLIMAX_CONTINUATION"}
        or recent_return <= 0
    )
    if buying_or_upper and distribution_or_supply and upside_failed:
        return "DISTRIBUTION_AFTER_BUYING_CLIMAX"

    impulse_only = (
        recent_return < -0.001
        and effort_state != "EFFICIENT_CONTINUATION"
        and not convergence_state.startswith("PERSISTENT_DISTRIBUTION")
        and continuation_quality not in {"EFFICIENT_CONTINUATION", "STRONG_CONTINUATION"}
    )
    if impulse_only:
        return "SHORT_IMPULSE_ONLY"

    late_exhaustion = (
        anchor_age_bars >= 8
        and recent_return < -0.003
        and recent_return > -0.02
        and anchor_status != "FAILED"
        and (
            climax_state == "CLIMAX_EXHAUSTION"
            or effort_state in {"BALANCED_RESPONSE", "ABSORPTION_RESPONSE"}
            or convergence_state.startswith("PERSISTENT")
        )
    )
    if late_exhaustion:
        return "LATE_EXHAUSTION_SHORT"

    return "UNKNOWN_SHORT"


def classify_long_subtype(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
) -> str:
    """Live-safe long subtype for calibrated_v3 decisions (backward returns only)."""
    context_for_subtype = _clean_text(result.raw_chosen_context or result.chosen_context).upper()
    if context_for_subtype != "LONG_CONTEXT":
        return ""

    anchor_status = _clean_text(result.anchor_status).upper()
    anchor_event = _clean_text(result.anchor_event_type).upper()
    anchor_zone = _clean_text(result.anchor_price_or_zone).upper()
    reason = _clean_text(result.chosen_reason).lower()
    market_state = _clean_text(evidence.market_state).upper()
    close = _safe_float(evidence.close, default=float("nan"))
    anchor_price = _extract_anchor_price(result.anchor_price_or_zone)
    recent_4 = _safe_float(evidence.recent_return, default=float("nan"))
    recent_8 = _safe_float(evidence.recent_return_8b, default=float("nan"))
    recent_16 = _safe_float(evidence.recent_return_16b, default=float("nan"))

    lower_zone = ("LOWER" in anchor_zone) or ("lower" in reason) or ("at lows" in reason)
    stopping_evidence = (
        ("STOPPING" in anchor_event)
        or ("stopping" in reason)
        or ("stopping/absorption volume at lows" in reason)
    )
    absorption_evidence = (
        ("absorption response held" in reason)
        or ("absorption" in reason)
        or ("ABSORPTION" in anchor_event)
    )
    downside_failed = (
        ("downside continuation failed" in reason)
        or (not pd.isna(recent_8) and recent_8 > -0.004 and recent_8 < 0.004)
    )
    reclaimed = (
        anchor_status == "HELD"
        or (anchor_price is not None and not pd.isna(close) and close >= anchor_price)
        or ("reversal anchor held" in reason)
        or ("reclaims" in reason)
    )

    if anchor_status == "HELD" and stopping_evidence and lower_zone:
        return "HELD_STOPPING_VOLUME_REVERSAL"

    if absorption_evidence and reclaimed and (lower_zone or market_state == "REVERSAL"):
        return "ABSORPTION_RECLAIM_LONG"

    extended_downside = (
        (not pd.isna(recent_8) and recent_8 < -0.005)
        or (not pd.isna(recent_16) and recent_16 < -0.008)
        or ("price falling" in reason)
    )
    micro_bounce_not_held = (
        (not pd.isna(recent_4) and recent_4 > 0) and (not pd.isna(recent_8) and recent_8 < 0)
    )
    if extended_downside and micro_bounce_not_held:
        return "LATE_REBOUND_LONG"

    if lower_zone and (stopping_evidence or absorption_evidence or downside_failed):
        return "LOWER_AUCTION_DEFENSE"

    return "WEAK_OR_UNKNOWN_LONG"


def apply_calibrated_v3_filter(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
    *,
    long_subtype: str | None = None,
) -> AuctionContextArbitrationResult:
    """Live-safe calibrated_v3: HELD stopping-volume LONG only; SHORT disabled."""
    v2 = result
    raw_context = _clean_text(v2.raw_chosen_context or v2.chosen_context).upper() or "OBSERVE"
    long_subtype = long_subtype or classify_long_subtype(v2, evidence)

    chosen = v2.chosen_context
    suppress_reason = v2.suppress_reason
    tactical_short = v2.tactical_short_candidate
    tactical_long = False
    short_candidate = False

    if raw_context == "SHORT_CONTEXT" or v2.chosen_context == "SHORT_CONTEXT":
        chosen = "OBSERVE"
        short_candidate = True
        suppress_reason = "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE"
    elif v2.chosen_context == "LONG_CONTEXT":
        if (
            long_subtype == "HELD_STOPPING_VOLUME_REVERSAL"
            and v2.anchor_status != "FAILED"
            and v2.long_context_score >= CALIBRATED_V2_MIN_DIRECTIONAL_SCORE
            and (v2.long_context_score - v2.short_context_score) >= CALIBRATED_V2_MIN_SCORE_MARGIN
        ):
            chosen = "LONG_CONTEXT"
            suppress_reason = ""
        else:
            chosen = "OBSERVE"
            tactical_long = long_subtype not in {"", "HELD_STOPPING_VOLUME_REVERSAL"}
            if long_subtype == "LATE_REBOUND_LONG":
                suppress_reason = "LATE_REBOUND_LONG_FILTER"
            elif long_subtype == "WEAK_OR_UNKNOWN_LONG":
                suppress_reason = "WEAK_OR_UNKNOWN_LONG_FILTER"
            else:
                suppress_reason = "LONG_V3_HELD_STOPPING_ONLY"
    elif raw_context == "LONG_CONTEXT":
        chosen = "OBSERVE"
        tactical_long = True
        if long_subtype == "LATE_REBOUND_LONG":
            suppress_reason = "LATE_REBOUND_LONG_FILTER"
        elif long_subtype == "WEAK_OR_UNKNOWN_LONG":
            suppress_reason = "WEAK_OR_UNKNOWN_LONG_FILTER"
        else:
            suppress_reason = suppress_reason or "LONG_V3_HELD_STOPPING_ONLY"
    else:
        chosen = "OBSERVE"

    return AuctionContextArbitrationResult(
        **{
            **v2.__dict__,
            "chosen_context": chosen,
            "long_subtype": long_subtype,
            "tactical_long_candidate": tactical_long,
            "short_candidate": short_candidate,
            "tactical_short_candidate": tactical_short,
            "suppress_reason": suppress_reason,
            "raw_chosen_context": raw_context,
        }
    )


def classify_short_subtype_outcome_diagnostic(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
) -> str:
    """Research-only relabel using forward outcomes — not used for calibrated_v2 decisions."""
    if result.chosen_context != "SHORT_CONTEXT":
        return ""

    anchor_status = _clean_text(result.anchor_status).upper()
    anchor_event = _clean_text(result.anchor_event_type).upper()
    market_state = _clean_text(evidence.market_state).upper()
    anchor_zone = _clean_text(result.anchor_price_or_zone).upper()
    reason = _clean_text(result.chosen_reason).lower()
    close = _safe_float(evidence.close, default=float("nan"))
    anchor_price = _extract_anchor_price(result.anchor_price_or_zone)
    f4 = _safe_float(evidence.forward_return_4b, default=float("nan"))
    f8 = _safe_float(evidence.forward_return_8b, default=float("nan"))
    f16 = _safe_float(evidence.forward_return_16b, default=float("nan"))
    max_fav = _safe_float(evidence.max_favorable_16b, default=float("nan"))
    max_adv = _safe_float(evidence.max_adverse_16b, default=float("nan"))

    lower_reversal_anchor = ("STOPPING" in anchor_event) or ("LOWER" in anchor_zone)
    downside_continuation = (
        ("efficient downside continuation" in reason)
        or ("persistent distribution" in reason)
        or (not pd.isna(f4) and f4 < -0.001)
    )
    broke_anchor = anchor_price is not None and not pd.isna(close) and close < anchor_price
    if anchor_status == "FAILED" and lower_reversal_anchor and broke_anchor and downside_continuation:
        return "FAILED_BULLISH_REVERSAL_BREAKDOWN"

    buying_or_upper = (
        ("BUYING" in anchor_event)
        or ("CLIMAX" in anchor_event)
        or ("UPPER" in anchor_zone)
        or ("buying climax" in reason)
    )
    distribution_or_supply = (
        market_state == "DISTRIBUTION"
        or ("distribution" in reason)
        or ("supply" in reason)
    )
    upside_failed = (not pd.isna(f8) and f8 <= 0) or ("upside continuation failed" in reason)
    if buying_or_upper and distribution_or_supply and upside_failed:
        return "DISTRIBUTION_AFTER_BUYING_CLIMAX"

    impulse_only = (
        (not pd.isna(f4) and f4 < 0)
        and ((not pd.isna(f8) and f8 >= 0) or (not pd.isna(f16) and f16 >= 0))
    )
    if impulse_only:
        return "SHORT_IMPULSE_ONLY"

    rebound_soon = ((not pd.isna(f8) and f8 > 0) or (not pd.isna(f16) and f16 > 0))
    if rebound_soon and (not pd.isna(max_adv) and not pd.isna(max_fav) and max_adv > max_fav):
        return "LATE_EXHAUSTION_SHORT"

    return "UNKNOWN_SHORT"


def _matches_directional_distribution_continuation(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
) -> bool:
    recent_return = _safe_float(evidence.recent_return)
    return (
        result.chosen_context == "SHORT_CONTEXT"
        and result.short_subtype == "UNKNOWN_SHORT"
        and result.anchor_status in {"HELD", "UNRESOLVED", "NONE"}
        and _clean_text(evidence.market_state).upper() in {"DISTRIBUTION", "REVERSAL"}
        and (
            "efficient downside continuation" in _clean_text(result.chosen_reason).lower()
            or "persistent distribution" in _clean_text(result.chosen_reason).lower()
            or recent_return < -0.001
        )
        and recent_return <= 0
    )


def apply_calibrated_v2_filter(
    result: AuctionContextArbitrationResult,
    evidence: AuctionContextEvidence,
) -> AuctionContextArbitrationResult:
    short_subtype = classify_short_subtype(result, evidence)
    probe = AuctionContextArbitrationResult(**{**result.__dict__, "short_subtype": short_subtype})
    if _matches_directional_distribution_continuation(probe, evidence):
        short_subtype = "DIRECTIONAL_DISTRIBUTION_CONTINUATION"

    chosen = result.chosen_context
    suppress_reason = ""
    tactical = False

    if chosen == "LONG_CONTEXT":
        if (
            result.long_context_score < CALIBRATED_V2_MIN_DIRECTIONAL_SCORE
            or (result.long_context_score - result.short_context_score) < CALIBRATED_V2_MIN_SCORE_MARGIN
            or result.anchor_status == "FAILED"
        ):
            chosen = "OBSERVE"
            suppress_reason = "LONG_GATE_OR_FAILED_ANCHOR"

    if chosen == "SHORT_CONTEXT":
        if (
            result.short_context_score < CALIBRATED_V2_MIN_DIRECTIONAL_SCORE
            or (result.short_context_score - result.long_context_score) < CALIBRATED_V2_MIN_SCORE_MARGIN
        ):
            chosen = "OBSERVE"
            suppress_reason = "SHORT_GLOBAL_GATE"
        elif short_subtype in {"FAILED_BULLISH_REVERSAL_BREAKDOWN", "SHORT_IMPULSE_ONLY"}:
            chosen = "OBSERVE"
            tactical = True
            suppress_reason = "TACTICAL_SHORT_CANDIDATE"
        elif short_subtype == "LATE_EXHAUSTION_SHORT":
            chosen = "OBSERVE"
            suppress_reason = "LATE_EXHAUSTION_SHORT_FILTER"
        elif short_subtype not in {
            "DISTRIBUTION_AFTER_BUYING_CLIMAX",
            "DIRECTIONAL_DISTRIBUTION_CONTINUATION",
        }:
            chosen = "OBSERVE"
            suppress_reason = "SHORT_SUBTYPE_NOT_DIRECTIONAL_ALLOWED"

    return AuctionContextArbitrationResult(
        **{
            **result.__dict__,
            "chosen_context": chosen,
            "short_subtype": short_subtype,
            "tactical_short_candidate": tactical,
            "suppress_reason": suppress_reason,
            "raw_chosen_context": result.chosen_context,
        }
    )


def score_auction_context(
    evidence: AuctionContextEvidence,
    *,
    mode: Literal["raw", "calibrated_v2", "calibrated_v3"] = "raw",
) -> AuctionContextArbitrationResult:
    """Score auction evidence and return directional context arbitration."""
    location_bias = _clean_text(evidence.tier1_location_bias)
    anchor_ts = pd.to_datetime(evidence.anchor_timestamp, utc=True, errors="coerce")
    if pd.isna(anchor_ts):
        anchor_ts = None

    anchor_price = evidence.anchor_price
    if anchor_price is None and evidence.candle_history is not None:
        anchor_price = resolve_anchor_price(evidence.candle_history, anchor_ts, location_bias)

    if evidence.recent_return is not None:
        recent_return = evidence.recent_return
    elif evidence.candle_history is not None:
        bar_ts = pd.Timestamp(evidence.timestamp)
        if bar_ts.tzinfo is None:
            bar_ts = bar_ts.tz_localize("UTC")
        else:
            bar_ts = bar_ts.tz_convert("UTC")
        recent_return = compute_recent_return(evidence.candle_history, bar_ts)
    else:
        recent_return = 0.0

    if evidence.anchor_status:
        anchor_status: AnchorStatus = _clean_text(evidence.anchor_status).upper()  # type: ignore[assignment]
        if anchor_status not in {"HELD", "FAILED", "UNRESOLVED", "NONE"}:
            anchor_status = resolve_anchor_status(
                anchor_price=anchor_price,
                location_bias=location_bias,
                close=_safe_float(evidence.close),
                anchor_age_bars=_safe_float(evidence.anchor_age_bars),
                continuation_quality=_clean_text(evidence.continuation_quality),
                convergence_state=_clean_text(evidence.convergence_state),
            )
    else:
        anchor_status = resolve_anchor_status(
            anchor_price=anchor_price,
            location_bias=location_bias,
            close=_safe_float(evidence.close),
            anchor_age_bars=_safe_float(evidence.anchor_age_bars),
            continuation_quality=_clean_text(evidence.continuation_quality),
            convergence_state=_clean_text(evidence.convergence_state),
        )

    scores = _compute_scores(evidence, anchor_status=anchor_status, recent_return=recent_return)
    chosen_context, chosen_reason = _choose_context(
        scores,
        anchor_status=anchor_status,
        location_bias=location_bias,
    )

    anchor_event_type = _clean_text(evidence.tier1_trigger_event or evidence.volume_event)

    raw = AuctionContextArbitrationResult(
        long_context_score=round(scores.long_score, 4),
        short_context_score=round(scores.short_score, 4),
        observe_score=round(scores.observe_score, 4),
        anchor_status=anchor_status,
        anchor_price_or_zone=_format_anchor_zone(location_bias, anchor_price),
        anchor_event_type=anchor_event_type,
        chosen_context=chosen_context,
        chosen_reason=chosen_reason,
        why_not_long=" | ".join(scores.why_not_long[:5]),
        why_not_short=" | ".join(scores.why_not_short[:5]),
        long_reasons=tuple(scores.long_reasons),
        short_reasons=tuple(scores.short_reasons),
        observe_reasons=tuple(scores.observe_reasons),
    )
    if mode == "calibrated_v2":
        return apply_calibrated_v2_filter(raw, evidence)
    if mode == "calibrated_v3":
        v2 = apply_calibrated_v2_filter(raw, evidence)
        return apply_calibrated_v3_filter(v2, evidence)
    return raw
