"""Provisional Stage2 / final-context synthesis using existing classifiers only."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "research") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "research"))

from build_auction_episode_memory import (  # noqa: E402
    classify_auction_episode,
    classify_auction_location,
    classify_bar_event,
    classify_effort_result,
    classify_effort_side,
    classify_episode_status,
    classify_follow_through,
    classify_price_result,
    classify_volume_effort,
    build_episode_reason,
)
from build_cognitive_market_state_memory import (  # noqa: E402
    classify_cognitive_market_state,
    map_state_status,
)
from build_final_market_context_memory import (  # noqa: E402
    classify_context_status,
    classify_market_context,
)


def synthesize_provisional_state(
    *,
    structure_row: Mapping[str, Any],
    response_row: Mapping[str, Any],
    completed_history: Optional[Mapping[str, pd.DataFrame]] = None,
    causal_cutoff: Any = None,
    prior_auction_episode: str = "UNKNOWN",
    prev_close: float | None = None,
) -> dict[str, Any]:
    """Wire existing episode → cognitive → final context classifiers for one tip."""
    completed_history = completed_history or {}
    close_position = float(structure_row.get("close_position") or 0.5)
    open_ = float(structure_row.get("open") or 0.0)
    high = float(structure_row.get("high") or 0.0)
    low = float(structure_row.get("low") or 0.0)
    close = float(structure_row.get("close") or structure_row.get("last") or 0.0)

    bar_event = classify_bar_event(
        volume_event=str(response_row.get("volume_event") or "UNKNOWN"),
        climax_state=str(response_row.get("climax_state") or "UNKNOWN"),
        effort_result_state=str(response_row.get("effort_result_state") or "UNKNOWN"),
    )
    volume_effort = classify_volume_effort(
        volume_class=str(response_row.get("volume_class") or "UNKNOWN"),
        relative_volume=float(response_row["relative_volume"])
        if response_row.get("relative_volume") == response_row.get("relative_volume")
        else None,
        climax_state=str(response_row.get("climax_state") or "UNKNOWN"),
        volume_event=str(response_row.get("volume_event") or "UNKNOWN"),
    )
    auction_location = classify_auction_location(close_position=close_position)
    effort_side = classify_effort_side(
        bar_event=bar_event,
        auction_location=auction_location,
        candle_type="bullish" if close >= open_ else "bearish",
    )
    price_result = classify_price_result(
        close=close,
        prev_close=prev_close,
        open_=open_,
        high=high,
        low=low,
        bar_event=bar_event,
    )
    # Causal FT: no future closes beyond cutoff → UNKNOWN (no invented look-ahead).
    closes = [float(prev_close)] if prev_close is not None else []
    closes.append(close)
    follow_through = classify_follow_through(
        closes=closes,
        index=max(len(closes) - 2, 0),
        effort_side=effort_side,
        bar_event=bar_event,
        horizon=4,
        auction_episode=None,
    )
    effort_result = classify_effort_result(
        volume_effort=volume_effort,
        price_result=price_result,
        follow_through=follow_through,
        effort_result_state=str(response_row.get("effort_result_state") or "UNKNOWN"),
    )
    auction_episode = classify_auction_episode(
        bar_event=bar_event,
        auction_location=auction_location,
        follow_through=follow_through,
        price_result=price_result,
        volume_effort=volume_effort,
        effort_result=effort_result,
        prior_auction_episode=prior_auction_episode,
    )
    episode_status = classify_episode_status(
        auction_episode=auction_episode,
        follow_through=follow_through,
        effort_result=effort_result,
    )
    episode_reason = build_episode_reason(
        bar_event=bar_event,
        auction_location=auction_location,
        follow_through=follow_through,
        auction_episode=auction_episode,
        price_result=price_result,
    )
    cognitive_market_state, state_direction, state_reason = classify_cognitive_market_state(
        auction_episode=auction_episode,
        episode_status=episode_status,
        effort_side=effort_side,
        effort_result=effort_result,
    )
    state_status = map_state_status(episode_status)
    market_context, context_reason = classify_market_context(
        cognitive_market_state=cognitive_market_state,
        state_direction=state_direction,
        state_status=state_status,
    )
    context_status = classify_context_status(
        market_context=market_context,
        state_status=state_status,
    )
    return {
        "evaluation_mode": "PROVISIONAL_INTRABAR",
        "is_closed": False,
        "causal_cutoff": str(causal_cutoff) if causal_cutoff is not None else None,
        "auction_episode": auction_episode,
        "episode_status": episode_status,
        "episode_reason": episode_reason,
        "bar_event": bar_event,
        "volume_effort": volume_effort,
        "auction_location": auction_location,
        "effort_side": effort_side,
        "price_result": price_result,
        "follow_through": follow_through,
        "effort_result": effort_result,
        "cognitive_market_state": cognitive_market_state,
        "state_direction": state_direction,
        "state_status": state_status,
        "state_reason": state_reason,
        "market_context": market_context,
        "context_status": context_status,
        "context_reason": context_reason,
        "decision_evidence": {
            "volume_event": response_row.get("volume_event"),
            "effort_result_state": response_row.get("effort_result_state"),
            "localized_behavior": response_row.get("localized_behavior"),
            "relative_volume": response_row.get("relative_volume"),
        },
    }
