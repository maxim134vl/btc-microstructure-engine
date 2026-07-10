"""Tests for shadow auction context arbitrator."""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from btc_ml.cognition.auction_context_arbitrator import (  # noqa: E402
    AuctionContextArbitrationResult,
    AuctionContextEvidence,
    apply_calibrated_v2_filter,
    apply_calibrated_v3_filter,
    classify_short_subtype,
    existing_context_from_trading_state,
    score_auction_context,
)


def _evidence(**overrides) -> AuctionContextEvidence:
    base = {
        "timestamp": pd.Timestamp("2026-07-08 12:00:00", tz="UTC"),
        "close": 62_000.0,
        "market_state": "REVERSAL",
        "market_bias": "BULLISH",
        "trading_state": "REVERSAL_WATCH",
        "tier1_trigger_event": "STOPPING_VOLUME",
        "tier1_location_bias": "LOWER_ABSORPTION",
        "anchor_price": 61_900.0,
        "anchor_status": "HELD",
        "volume_event": "STOPPING_VOLUME",
        "effort_result_state": "ABSORPTION_RESPONSE",
        "recent_return": -0.001,
    }
    base.update(overrides)
    return AuctionContextEvidence(**base)


def test_stopping_volume_held_downside_failed_long_context():
    result = score_auction_context(_evidence())
    assert result.anchor_status == "HELD"
    assert result.chosen_context == "LONG_CONTEXT"
    assert result.long_context_score > result.short_context_score


def test_stopping_volume_failed_efficient_downside_short_context():
    result = score_auction_context(
        _evidence(
            close=61_500.0,
            anchor_status="FAILED",
            effort_result_state="EFFICIENT_CONTINUATION",
            recent_return=-0.006,
            convergence_state="PERSISTENT_DISTRIBUTION",
        )
    )
    assert result.anchor_status == "FAILED"
    assert result.chosen_context == "SHORT_CONTEXT"
    assert result.short_context_score > result.long_context_score


def test_conflicting_weak_evidence_observe():
    result = score_auction_context(
        _evidence(
            market_state="NEUTRAL",
            market_bias="NEUTRAL",
            trading_state="OBSERVE",
            tier1_trigger_event="",
            tier1_location_bias="",
            anchor_price=None,
            anchor_status="NONE",
            volume_event="NEUTRAL_VOLUME",
            effort_result_state="BALANCED_RESPONSE",
            absorption_probability=0.4,
            distribution_probability=0.42,
            recent_return=0.0,
        )
    )
    assert result.chosen_context == "OBSERVE"
    assert result.observe_score >= result.long_context_score
    assert result.observe_score >= result.short_context_score


def test_reversal_watch_is_candidate_not_final_context():
    assert existing_context_from_trading_state("REVERSAL_WATCH") is None
    result = score_auction_context(_evidence(trading_state="REVERSAL_WATCH"))
    assert result.chosen_context in {"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"}
    assert result.chosen_context != "REVERSAL_WATCH"


def test_failed_anchor_cannot_produce_long_context():
    result = score_auction_context(
        _evidence(
            close=61_400.0,
            anchor_status="FAILED",
            market_bias="BULLISH",
            effort_result_state="ABSORPTION_RESPONSE",
            recent_return=-0.005,
        )
    )
    assert result.anchor_status == "FAILED"
    assert result.chosen_context != "LONG_CONTEXT"
    assert result.long_context_score < 0.35 or result.short_context_score > result.long_context_score


def test_calibrated_long_survives_strong_and_anchor_held():
    evidence = _evidence(anchor_status="HELD")
    result = score_auction_context(evidence, mode="calibrated_v2")
    assert result.raw_chosen_context == "LONG_CONTEXT"
    assert result.chosen_context == "LONG_CONTEXT"
    assert result.suppress_reason == ""


def test_calibrated_failed_anchor_blocks_long():
    evidence = _evidence(anchor_status="FAILED", close=61_400.0, recent_return=-0.004)
    result = score_auction_context(evidence, mode="calibrated_v2")
    assert result.raw_chosen_context in {"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"}
    if result.raw_chosen_context == "LONG_CONTEXT":
        assert result.chosen_context == "OBSERVE"
    else:
        assert result.chosen_context != "LONG_CONTEXT"


def test_distribution_short_survives_calibrated():
    evidence = _evidence(
        anchor_status="HELD",
        close=61_750.0,
        market_state="DISTRIBUTION",
        market_bias="BEARISH",
        tier1_trigger_event="BUYING_CLIMAX",
        tier1_location_bias="UPPER_DISTRIBUTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.007,
        forward_return_4b=-0.003,
        forward_return_8b=-0.005,
        forward_return_16b=-0.007,
        max_favorable_16b=0.01,
        max_adverse_16b=0.004,
    )
    result = score_auction_context(evidence, mode="calibrated_v2")
    assert result.short_subtype == "DISTRIBUTION_AFTER_BUYING_CLIMAX"
    assert result.chosen_context == "SHORT_CONTEXT"


def test_late_exhaustion_short_suppressed_to_observe():
    raw = AuctionContextArbitrationResult(
        long_context_score=0.1,
        short_context_score=0.88,
        observe_score=0.2,
        anchor_status="HELD",
        anchor_price_or_zone="LOWER_ABSORPTION@61900.00",
        anchor_event_type="SELLING_PRESSURE",
        chosen_context="SHORT_CONTEXT",
        chosen_reason="efficient downside continuation; persistent distribution convergence",
        why_not_long="",
        why_not_short="",
    )
    evidence = _evidence(
        close=61_700.0,
        market_state="DISTRIBUTION",
        anchor_age_bars=12,
        climax_state="CLIMAX_EXHAUSTION",
        effort_result_state="BALANCED_RESPONSE",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.005,
    )
    adjusted = apply_calibrated_v2_filter(raw, evidence)
    assert adjusted.short_subtype == "LATE_EXHAUSTION_SHORT"
    assert adjusted.chosen_context == "OBSERVE"
    assert adjusted.suppress_reason == "LATE_EXHAUSTION_SHORT_FILTER"


def test_tactical_short_becomes_observe_with_flag():
    evidence = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        recent_return=-0.006,
    )
    result = score_auction_context(evidence, mode="calibrated_v2")
    assert result.chosen_context == "OBSERVE"
    assert result.tactical_short_candidate is True
    assert result.suppress_reason == "TACTICAL_SHORT_CANDIDATE"


def test_unknown_short_promotes_directional_distribution_continuation():
    raw = AuctionContextArbitrationResult(
        long_context_score=0.12,
        short_context_score=0.91,
        observe_score=0.2,
        anchor_status="HELD",
        anchor_price_or_zone="MID_RANGE@61880.00",
        anchor_event_type="SELLING_PRESSURE",
        chosen_context="SHORT_CONTEXT",
        chosen_reason="efficient downside continuation; persistent distribution convergence",
        why_not_long="",
        why_not_short="",
    )
    evidence = _evidence(
        close=61_700.0,
        anchor_status="HELD",
        market_state="DISTRIBUTION",
        tier1_trigger_event="SELLING_PRESSURE",
        tier1_location_bias="MID_RANGE",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.006,
    )
    assert classify_short_subtype(raw, evidence) == "UNKNOWN_SHORT"
    adjusted = apply_calibrated_v2_filter(raw, evidence)
    assert adjusted.short_subtype == "DIRECTIONAL_DISTRIBUTION_CONTINUATION"


def test_calibrated_v2_unchanged_by_forward_returns():
    base = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.006,
    )
    alt = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.006,
        forward_return_4b=0.25,
        forward_return_8b=0.30,
        forward_return_16b=0.40,
    )
    result_a = score_auction_context(base, mode="calibrated_v2")
    result_b = score_auction_context(alt, mode="calibrated_v2")
    assert result_a.chosen_context == result_b.chosen_context
    assert result_a.short_subtype == result_b.short_subtype
    assert result_a.suppress_reason == result_b.suppress_reason
    assert result_a.tactical_short_candidate == result_b.tactical_short_candidate


def test_calibrated_v2_unchanged_by_max_excursions():
    base = _evidence(
        anchor_status="HELD",
        market_state="DISTRIBUTION",
        tier1_trigger_event="BUYING_CLIMAX",
        tier1_location_bias="UPPER_DISTRIBUTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.007,
    )
    alt = _evidence(
        anchor_status="HELD",
        market_state="DISTRIBUTION",
        tier1_trigger_event="BUYING_CLIMAX",
        tier1_location_bias="UPPER_DISTRIBUTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.007,
        max_favorable_16b=0.99,
        max_adverse_16b=0.01,
    )
    result_a = score_auction_context(base, mode="calibrated_v2")
    result_b = score_auction_context(alt, mode="calibrated_v2")
    assert result_a.chosen_context == result_b.chosen_context
    assert result_a.short_subtype == result_b.short_subtype


def test_classify_short_subtype_does_not_read_outcome_fields():
    raw = AuctionContextArbitrationResult(
        long_context_score=0.1,
        short_context_score=0.88,
        observe_score=0.2,
        anchor_status="HELD",
        anchor_price_or_zone="LOWER_ABSORPTION@61900.00",
        anchor_event_type="SELLING_PRESSURE",
        chosen_context="SHORT_CONTEXT",
        chosen_reason="efficient downside continuation",
        why_not_long="",
        why_not_short="",
    )
    evidence_clean = _evidence(market_state="DISTRIBUTION", recent_return=-0.002)
    evidence_leaky = _evidence(
        market_state="DISTRIBUTION",
        recent_return=-0.002,
        forward_return_4b=0.5,
        forward_return_8b=0.5,
        forward_return_16b=0.5,
        max_favorable_16b=0.01,
        max_adverse_16b=0.99,
    )
    assert classify_short_subtype(raw, evidence_clean) == classify_short_subtype(raw, evidence_leaky)


def test_calibrated_v3_held_stopping_volume_reversal_survives_long():
    result = score_auction_context(_evidence(anchor_status="HELD"), mode="calibrated_v3")
    assert result.long_subtype == "HELD_STOPPING_VOLUME_REVERSAL"
    assert result.chosen_context == "LONG_CONTEXT"
    assert result.raw_chosen_context == "LONG_CONTEXT"
    assert result.suppress_reason == ""


def test_calibrated_v3_weak_or_unknown_long_becomes_observe():
    raw = AuctionContextArbitrationResult(
        long_context_score=0.85,
        short_context_score=0.50,
        observe_score=0.2,
        anchor_status="HELD",
        anchor_price_or_zone="MID_RANGE@62000.00",
        anchor_event_type="BUYING_PRESSURE",
        chosen_context="LONG_CONTEXT",
        chosen_reason="bullish bias with balanced response",
        why_not_long="",
        why_not_short="",
    )
    evidence = _evidence(
        anchor_status="HELD",
        tier1_trigger_event="BUYING_PRESSURE",
        tier1_location_bias="MID_RANGE",
        effort_result_state="BALANCED_RESPONSE",
        recent_return=0.001,
    )
    v2 = apply_calibrated_v2_filter(raw, evidence)
    assert v2.chosen_context == "LONG_CONTEXT"
    v3 = apply_calibrated_v3_filter(v2, evidence)
    assert v3.long_subtype == "WEAK_OR_UNKNOWN_LONG"
    assert v3.chosen_context == "OBSERVE"
    assert v3.raw_chosen_context == "LONG_CONTEXT"
    assert v3.tactical_long_candidate is True
    assert v3.suppress_reason == "WEAK_OR_UNKNOWN_LONG_FILTER"


def test_calibrated_v3_late_rebound_long_becomes_observe():
    raw = AuctionContextArbitrationResult(
        long_context_score=0.82,
        short_context_score=0.48,
        observe_score=0.2,
        anchor_status="HELD",
        anchor_price_or_zone="LOWER_ABSORPTION@61900.00",
        anchor_event_type="SELLING_PRESSURE",
        chosen_context="LONG_CONTEXT",
        chosen_reason="price falling at lows; micro bounce not held",
        why_not_long="",
        why_not_short="",
    )
    evidence = _evidence(
        anchor_status="HELD",
        market_state="NEUTRAL",
        effort_result_state="BALANCED_RESPONSE",
        recent_return=0.002,
        recent_return_8b=-0.01,
        recent_return_16b=-0.015,
    )
    v2 = apply_calibrated_v2_filter(raw, evidence)
    assert v2.chosen_context == "LONG_CONTEXT"
    v3 = apply_calibrated_v3_filter(v2, evidence)
    assert v3.long_subtype == "LATE_REBOUND_LONG"
    assert v3.chosen_context == "OBSERVE"
    assert v3.suppress_reason == "LATE_REBOUND_LONG_FILTER"


def test_calibrated_v3_any_short_context_becomes_observe():
    evidence = _evidence(
        anchor_status="HELD",
        close=61_750.0,
        market_state="DISTRIBUTION",
        market_bias="BEARISH",
        tier1_trigger_event="BUYING_CLIMAX",
        tier1_location_bias="UPPER_DISTRIBUTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.007,
    )
    result = score_auction_context(evidence, mode="calibrated_v3")
    assert result.raw_chosen_context == "SHORT_CONTEXT"
    assert result.chosen_context == "OBSERVE"
    assert result.short_candidate is True
    assert result.suppress_reason == "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE"


def test_calibrated_v3_short_diagnostics_preserved():
    evidence = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        recent_return=-0.006,
    )
    result = score_auction_context(evidence, mode="calibrated_v3")
    assert result.raw_chosen_context == "SHORT_CONTEXT"
    assert result.short_subtype == "FAILED_BULLISH_REVERSAL_BREAKDOWN"
    assert result.tactical_short_candidate is True
    assert result.short_candidate is True
    assert result.suppress_reason == "SHORT_DISABLED_PENDING_LIVE_SAFE_EDGE"


def test_calibrated_v3_unchanged_by_forward_outcomes():
    base = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.006,
    )
    alt = _evidence(
        close=61_500.0,
        anchor_status="FAILED",
        tier1_trigger_event="STOPPING_VOLUME",
        tier1_location_bias="LOWER_ABSORPTION",
        effort_result_state="EFFICIENT_CONTINUATION",
        convergence_state="PERSISTENT_DISTRIBUTION",
        recent_return=-0.006,
        forward_return_4b=0.25,
        forward_return_8b=0.30,
        forward_return_16b=0.40,
        max_favorable_16b=0.99,
        max_adverse_16b=0.01,
    )
    result_a = score_auction_context(base, mode="calibrated_v3")
    result_b = score_auction_context(alt, mode="calibrated_v3")
    assert result_a.chosen_context == result_b.chosen_context
    assert result_a.long_subtype == result_b.long_subtype
    assert result_a.short_subtype == result_b.short_subtype
    assert result_a.suppress_reason == result_b.suppress_reason
    assert result_a.short_candidate == result_b.short_candidate
    assert result_a.tactical_long_candidate == result_b.tactical_long_candidate
