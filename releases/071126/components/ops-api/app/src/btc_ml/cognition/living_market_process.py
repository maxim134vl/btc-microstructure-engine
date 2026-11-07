"""Living market process: LONG/SHORT from accepted process + trend strength.

Bar labels (absorption at lows, failed breakout at highs) are events, not
context. Context follows who is accepted and how strong that process still is.
Do not restore MIN_ACTIVE_CONTEXT_HOLD_BARS=3. Strength is not a bar delay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

BUYER = "BUYER"
SELLER = "SELLER"
NONE = "NONE"

LONG_CONTEXT = "LONG_CONTEXT"
SHORT_CONTEXT = "SHORT_CONTEXT"
OBSERVE = "OBSERVE"

ACCEPTED_BUYER_STATES = frozenset({"ACCEPTANCE_HIGHER", "BUYER_CONTROL"})
ACCEPTED_SELLER_STATES = frozenset({"ACCEPTANCE_LOWER", "SELLER_CONTROL"})
ABSORPTION_EVENTS = frozenset({"LOWER_ABSORPTION"})
DISTRIBUTION_EVENTS = frozenset({"UPPER_DISTRIBUTION"})
PAUSE_STATES = frozenset({"BALANCE", "UNCERTAIN"})
ACCEPTED_RESULTS = frozenset({"ACCEPTED", "CONTINUED"})
NO_EFFORT_VOLUME = frozenset({"LOW", "VERY_LOW"})

# One H1 bar is four M15 bars of the same process. Growth and hold scale with
# the bar; a thin pause still cannot flip the process (only opposite accept can).
TF_WEIGHT = {"M15": 1.0, "M30": 1.5, "H1": 2.0, "H4": 4.0}
ACCEPT_DELTA = 1.0
NO_EFFORT_DELTA = 0.25
CHALLENGE_DELTA = 0.35
# Half of one accept on this TF. Below that the colour can still exist,
# but there is nothing to catch and not enough force to kill the other side.
TRADE_STRENGTH_FLOOR = 0.5


def _clean(value: Any, default: str = "UNKNOWN") -> str:
    if value is None:
        return default
    text = str(value).strip().upper()
    if not text or text in {"NAN", "NONE", "NULL", ""}:
        return default
    return text


def _tf_weight(timeframe: str | None) -> float:
    return TF_WEIGHT.get(_clean(timeframe, default="M15"), 1.0)


def trade_strength_floor(timeframe: str | None = "M15") -> float:
    """Minimum strength that may open or reverse on this timeframe."""
    return TRADE_STRENGTH_FLOOR * _tf_weight(timeframe)


def process_from_context(
    market_context: str | None,
    strength: float = 0.0,
    timeframe: str = "M15",
) -> "ProcessSnapshot":
    ctx = _clean(market_context, default=OBSERVE)
    try:
        value = float(strength)
    except (TypeError, ValueError):
        value = 0.0
    if value != value:  # NaN
        value = 0.0
    seed = ACCEPT_DELTA * _tf_weight(timeframe)
    if ctx == LONG_CONTEXT:
        return ProcessSnapshot(process=BUYER, strength=value if value > 0 else seed, market_context=LONG_CONTEXT)
    if ctx == SHORT_CONTEXT:
        return ProcessSnapshot(process=SELLER, strength=value if value > 0 else seed, market_context=SHORT_CONTEXT)
    return ProcessSnapshot(process=NONE, strength=0.0, market_context=OBSERVE)


@dataclass(frozen=True)
class ProcessSnapshot:
    process: str
    strength: float
    market_context: str
    context_reason: str = ""

    def with_reason(self, reason: str) -> "ProcessSnapshot":
        return ProcessSnapshot(
            process=self.process,
            strength=self.strength,
            market_context=self.market_context,
            context_reason=reason,
        )


def _is_accepted_buyer(*, state: str, direction: str, price_result: str, effort_result: str, effort_side: str) -> bool:
    if state in ACCEPTED_BUYER_STATES:
        return True
    if direction == "BUYER_CONTROL" and state not in ABSORPTION_EVENTS | DISTRIBUTION_EVENTS | PAUSE_STATES:
        return True
    if price_result == "ACCEPTED_HIGHER" and effort_result in ACCEPTED_RESULTS:
        return True
    if effort_side == "BUYER" and effort_result in ACCEPTED_RESULTS and price_result == "ACCEPTED_HIGHER":
        return True
    return False


def _is_accepted_seller(*, state: str, direction: str, price_result: str, effort_result: str, effort_side: str) -> bool:
    if state in ACCEPTED_SELLER_STATES:
        return True
    if direction == "SELLER_CONTROL" and state not in ABSORPTION_EVENTS | DISTRIBUTION_EVENTS | PAUSE_STATES:
        return True
    if price_result == "ACCEPTED_LOWER" and effort_result in ACCEPTED_RESULTS:
        return True
    if effort_side == "SELLER" and effort_result in ACCEPTED_RESULTS and price_result == "ACCEPTED_LOWER":
        return True
    return False


def _is_no_effort(*, volume_effort: str, relative_volume: float | None, relative_spread: float | None, price_result: str) -> bool:
    if volume_effort in NO_EFFORT_VOLUME:
        return True
    if relative_volume is not None and relative_spread is not None:
        if relative_volume <= 0.45 and relative_spread <= 0.75:
            return True
    return False


def _keep(process: str, strength: float, *, reason: str, add: float = 0.0) -> ProcessSnapshot:
    strength = max(0.0, float(strength) + add)
    if process == BUYER:
        return ProcessSnapshot(BUYER, strength, LONG_CONTEXT, reason)
    if process == SELLER:
        return ProcessSnapshot(SELLER, strength, SHORT_CONTEXT, reason)
    return ProcessSnapshot(NONE, 0.0, OBSERVE, reason)


def step_living_process(
    prior: ProcessSnapshot | None,
    *,
    cognitive_market_state: str,
    state_direction: str = "UNKNOWN",
    state_status: str = "UNKNOWN",
    effort_result: str = "UNKNOWN",
    price_result: str = "UNKNOWN",
    effort_side: str = "UNKNOWN",
    volume_effort: str = "UNKNOWN",
    relative_volume: float | None = None,
    relative_spread: float | None = None,
    timeframe: str = "M15",
) -> ProcessSnapshot:
    """Advance the living process by one bar. Events do not flip.

    Opposite accept kills only when its hit is at least the living strength.
    A 0.5 poke cannot reverse a 2.0 process. Equal force can.
    """
    prior = prior or ProcessSnapshot(NONE, 0.0, OBSERVE)
    state = _clean(cognitive_market_state)
    direction = _clean(state_direction)
    status = _clean(state_status)
    result = _clean(effort_result)
    price = _clean(price_result)
    side = _clean(effort_side)
    volume = _clean(volume_effort)
    weight = _tf_weight(timeframe)

    if status == "INVALIDATED" and prior.process == NONE:
        return ProcessSnapshot(NONE, 0.0, OBSERVE, "INVALIDATED cognitive state implies OBSERVE")

    accepted_buyer = _is_accepted_buyer(
        state=state, direction=direction, price_result=price, effort_result=result, effort_side=side
    )
    accepted_seller = _is_accepted_seller(
        state=state, direction=direction, price_result=price, effort_result=result, effort_side=side
    )
    no_effort = _is_no_effort(
        volume_effort=volume,
        relative_volume=relative_volume,
        relative_spread=relative_spread,
        price_result=price,
    )
    absorption = state in ABSORPTION_EVENTS
    distribution = state in DISTRIBUTION_EVENTS
    pause = state in PAUSE_STATES or price in {"RANGE", "NO_PROGRESS"} or result in {"ABSORBED", "NO_RESULT", "UNKNOWN"}

    if accepted_buyer and not accepted_seller:
        hit = ACCEPT_DELTA * weight
        if prior.process == BUYER:
            reason = (
                "ACCEPTANCE_HIGHER implies LONG_CONTEXT"
                if state == "ACCEPTANCE_HIGHER"
                else "BUYER_CONTROL implies LONG_CONTEXT"
                if state == "BUYER_CONTROL"
                else "accepted higher continues buyer process"
            )
            return ProcessSnapshot(BUYER, prior.strength + hit, LONG_CONTEXT, reason)
        if prior.process == SELLER and hit < prior.strength:
            return _keep(
                SELLER,
                prior.strength,
                add=-hit,
                reason="accepted higher lacks strength to kill seller process",
            )
        reason = (
            "accepted higher kills seller process"
            if prior.process == SELLER
            else (
                "ACCEPTANCE_HIGHER implies LONG_CONTEXT"
                if state == "ACCEPTANCE_HIGHER"
                else "BUYER_CONTROL implies LONG_CONTEXT"
                if state == "BUYER_CONTROL"
                else "accepted higher starts buyer process"
            )
        )
        return ProcessSnapshot(BUYER, hit, LONG_CONTEXT, reason)

    if accepted_seller and not accepted_buyer:
        hit = ACCEPT_DELTA * weight
        if prior.process == SELLER:
            reason = (
                "ACCEPTANCE_LOWER implies SHORT_CONTEXT"
                if state == "ACCEPTANCE_LOWER"
                else "SELLER_CONTROL implies SHORT_CONTEXT"
                if state == "SELLER_CONTROL"
                else "accepted lower continues seller process"
            )
            return ProcessSnapshot(SELLER, prior.strength + hit, SHORT_CONTEXT, reason)
        if prior.process == BUYER and hit < prior.strength:
            return _keep(
                BUYER,
                prior.strength,
                add=-hit,
                reason="accepted lower lacks strength to kill buyer process",
            )
        reason = (
            "accepted lower kills buyer process"
            if prior.process == BUYER
            else (
                "ACCEPTANCE_LOWER implies SHORT_CONTEXT"
                if state == "ACCEPTANCE_LOWER"
                else "SELLER_CONTROL implies SHORT_CONTEXT"
                if state == "SELLER_CONTROL"
                else "accepted lower starts seller process"
            )
        )
        return ProcessSnapshot(SELLER, hit, SHORT_CONTEXT, reason)

    if prior.process != NONE and no_effort:
        return _keep(
            prior.process,
            prior.strength,
            add=NO_EFFORT_DELTA * weight,
            reason="no-effort pause holds living process",
        )

    if prior.process == SELLER and (absorption or pause or distribution):
        add = -CHALLENGE_DELTA * weight if absorption or distribution else 0.0
        if no_effort or (pause and not absorption and not distribution):
            add = NO_EFFORT_DELTA * weight if no_effort else 0.0
        reason = (
            "living seller process holds SHORT_CONTEXT"
            if not absorption
            else "lower absorption is an event, seller process holds SHORT_CONTEXT"
        )
        return _keep(SELLER, prior.strength, add=add, reason=reason)

    if prior.process == BUYER and (distribution or pause or absorption):
        add = -CHALLENGE_DELTA * weight if absorption or distribution else 0.0
        if no_effort or (pause and not absorption and not distribution):
            add = NO_EFFORT_DELTA * weight if no_effort else 0.0
        reason = (
            "living buyer process holds LONG_CONTEXT"
            if not distribution
            else "upper distribution is an event, buyer process holds LONG_CONTEXT"
        )
        return _keep(BUYER, prior.strength, add=add, reason=reason)

    if absorption:
        return ProcessSnapshot(
            NONE, 0.0, OBSERVE, "LOWER_ABSORPTION is an event, not LONG_CONTEXT"
        )
    if distribution:
        return ProcessSnapshot(
            NONE, 0.0, OBSERVE, "UPPER_DISTRIBUTION is an event, not SHORT_CONTEXT"
        )
    if state == "BALANCE" or direction == "NEUTRAL":
        return ProcessSnapshot(NONE, 0.0, OBSERVE, "BALANCE implies OBSERVE")
    if state == "UNCERTAIN" or direction in {"UNKNOWN", "NEUTRAL"}:
        return ProcessSnapshot(NONE, 0.0, OBSERVE, "UNCERTAIN implies OBSERVE")
    return ProcessSnapshot(NONE, 0.0, OBSERVE, "insufficient cognitive state evidence implies OBSERVE")


def classify_market_context(
    *,
    cognitive_market_state: str,
    state_direction: str,
    state_status: str,
    prior_context: str | None = None,
    prior_strength: float = 0.0,
    effort_result: str = "UNKNOWN",
    price_result: str = "UNKNOWN",
    effort_side: str = "UNKNOWN",
    volume_effort: str = "UNKNOWN",
    relative_volume: float | None = None,
    relative_spread: float | None = None,
    timeframe: str = "M15",
    prior: ProcessSnapshot | None = None,
) -> tuple[str, str]:
    """Return (market_context, context_reason) from living process + this bar."""
    if prior is None and prior_context:
        prior = process_from_context(prior_context, prior_strength, timeframe)
    snap = step_living_process(
        prior,
        cognitive_market_state=cognitive_market_state,
        state_direction=state_direction,
        state_status=state_status,
        effort_result=effort_result,
        price_result=price_result,
        effort_side=effort_side,
        volume_effort=volume_effort,
        relative_volume=relative_volume,
        relative_spread=relative_spread,
        timeframe=timeframe,
    )
    return snap.market_context, snap.context_reason


def walk_bars(rows: list[Mapping[str, Any]], *, timeframe: str = "M15") -> list[ProcessSnapshot]:
    """Apply the living process across a time-ordered sequence of bars."""
    prior: ProcessSnapshot | None = None
    out: list[ProcessSnapshot] = []
    for row in rows:
        tf = str(row.get("timeframe") or timeframe or "M15")
        prior = step_living_process(
            prior,
            cognitive_market_state=str(row.get("cognitive_market_state") or "UNCERTAIN"),
            state_direction=str(row.get("state_direction") or "UNKNOWN"),
            state_status=str(row.get("state_status") or "UNKNOWN"),
            effort_result=str(row.get("effort_result") or "UNKNOWN"),
            price_result=str(row.get("price_result") or "UNKNOWN"),
            effort_side=str(row.get("effort_side") or "UNKNOWN"),
            volume_effort=str(row.get("volume_effort") or "UNKNOWN"),
            relative_volume=_optional_float(row.get("relative_volume")),
            relative_spread=_optional_float(row.get("relative_spread")),
            timeframe=tf,
        )
        out.append(prior)
    return out


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number
