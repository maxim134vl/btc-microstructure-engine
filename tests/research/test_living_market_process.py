"""Living process: LONG/SHORT from accepted process + trend strength.

Regression lock for docs/audit/BUG_JOURNAL.md cognitive plan.
Do not restore absorption→LONG or hold=3.
"""

from __future__ import annotations

from btc_ml.cognition.living_market_process import (
    BUYER,
    LONG_CONTEXT,
    OBSERVE,
    SELLER,
    SHORT_CONTEXT,
    TF_WEIGHT,
    ProcessSnapshot,
    classify_market_context,
    step_living_process,
    walk_bars,
)


def test_isolated_lower_absorption_is_not_long():
    ctx, reason = classify_market_context(
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="BUYER_SUPPORT",
        state_status="CONFIRMED",
    )
    assert ctx == OBSERVE
    assert "not LONG_CONTEXT" in reason


def test_isolated_upper_distribution_is_not_short():
    ctx, reason = classify_market_context(
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_direction="SELLER_PRESSURE",
        state_status="CONFIRMED",
    )
    assert ctx == OBSERVE
    assert "not SHORT_CONTEXT" in reason


def test_acceptance_higher_is_long():
    ctx, reason = classify_market_context(
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="DEVELOPING",
    )
    assert ctx == LONG_CONTEXT
    assert reason == "ACCEPTANCE_HIGHER implies LONG_CONTEXT"


def test_acceptance_lower_is_short():
    ctx, reason = classify_market_context(
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="DEVELOPING",
    )
    assert ctx == SHORT_CONTEXT
    assert reason == "ACCEPTANCE_LOWER implies SHORT_CONTEXT"


def test_pause_inside_seller_process_stays_short():
    snaps = walk_bars(
        [
            {
                "cognitive_market_state": "ACCEPTANCE_LOWER",
                "state_direction": "SELLER_CONTROL",
                "state_status": "CONFIRMED",
                "price_result": "ACCEPTED_LOWER",
                "effort_result": "ACCEPTED",
            },
            {
                "cognitive_market_state": "LOWER_ABSORPTION",
                "state_direction": "NEUTRAL",
                "state_status": "CONFIRMED",
            },
            {
                "cognitive_market_state": "BALANCE",
                "state_direction": "NEUTRAL",
                "state_status": "DEVELOPING",
                "price_result": "RANGE",
            },
        ]
    )
    assert [s.market_context for s in snaps] == [SHORT_CONTEXT, SHORT_CONTEXT, SHORT_CONTEXT]
    assert snaps[0].process == SELLER
    assert snaps[1].process == SELLER
    assert snaps[2].process == SELLER


def test_no_effort_on_dump_holds_short_and_strength_does_not_fall():
    first = step_living_process(
        None,
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_LOWER",
        effort_result="ACCEPTED",
        timeframe="M15",
    )
    pause = step_living_process(
        first,
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="NEUTRAL",
        state_status="CONFIRMED",
        volume_effort="LOW",
        relative_volume=0.4,
        relative_spread=0.6,
        timeframe="M15",
    )
    assert pause.market_context == SHORT_CONTEXT
    assert pause.strength >= first.strength
    assert "holds" in pause.context_reason or "no-effort" in pause.context_reason


def test_accepted_higher_kills_seller_and_starts_long():
    seller = step_living_process(
        None,
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
    )
    buyer = step_living_process(
        seller,
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_HIGHER",
        effort_result="ACCEPTED",
    )
    assert seller.market_context == SHORT_CONTEXT
    assert buyer.market_context == LONG_CONTEXT
    assert buyer.process == BUYER
    assert "kills seller" in buyer.context_reason


def test_weak_accept_does_not_kill_stronger_seller():
    seller = ProcessSnapshot(process=SELLER, strength=2.0, market_context=SHORT_CONTEXT)
    poke = step_living_process(
        seller,
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_HIGHER",
        effort_result="ACCEPTED",
        timeframe="M15",
    )
    assert poke.market_context == SHORT_CONTEXT
    assert poke.process == SELLER
    assert poke.strength == 1.0
    assert "lacks strength" in poke.context_reason


def test_zombie_seller_dies_on_one_accept():
    zombie = ProcessSnapshot(process=SELLER, strength=0.3, market_context=SHORT_CONTEXT)
    buyer = step_living_process(
        zombie,
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_HIGHER",
        effort_result="ACCEPTED",
        timeframe="M15",
    )
    assert buyer.market_context == LONG_CONTEXT
    assert buyer.process == BUYER
    assert buyer.strength == 1.0


def test_h4_accept_kills_h4_seller_when_hit_covers_strength():
    seller = ProcessSnapshot(process=SELLER, strength=3.2, market_context=SHORT_CONTEXT)
    buyer = step_living_process(
        seller,
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_HIGHER",
        effort_result="ACCEPTED",
        timeframe="H4",
    )
    assert buyer.market_context == LONG_CONTEXT
    assert buyer.strength == TF_WEIGHT["H4"] * 1.0


def test_h4_thin_accept_does_not_kill_strong_seller():
    seller = ProcessSnapshot(process=SELLER, strength=3.2, market_context=SHORT_CONTEXT)
    poke = step_living_process(
        seller,
        cognitive_market_state="ACCEPTANCE_HIGHER",
        state_direction="BUYER_CONTROL",
        state_status="CONFIRMED",
        price_result="ACCEPTED_HIGHER",
        effort_result="ACCEPTED",
        timeframe="M15",
    )
    assert poke.market_context == SHORT_CONTEXT
    assert poke.strength == 2.2


def test_failed_buy_at_highs_does_not_start_short():
    snaps = walk_bars(
        [
            {
                "cognitive_market_state": "ACCEPTANCE_HIGHER",
                "state_direction": "BUYER_CONTROL",
                "state_status": "CONFIRMED",
            },
            {
                "cognitive_market_state": "UPPER_DISTRIBUTION",
                "state_direction": "NEUTRAL",
                "state_status": "CONFIRMED",
            },
        ]
    )
    assert snaps[0].market_context == LONG_CONTEXT
    assert snaps[1].market_context == LONG_CONTEXT


def test_h1_strength_grows_faster_than_m15_and_pause_does_not_flip():
    m15 = step_living_process(
        None,
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
        timeframe="M15",
    )
    h1 = step_living_process(
        None,
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
        timeframe="H1",
    )
    assert h1.strength == TF_WEIGHT["H1"] * 1.0
    assert h1.strength > m15.strength
    h1_pause = step_living_process(
        h1,
        cognitive_market_state="LOWER_ABSORPTION",
        state_direction="NEUTRAL",
        state_status="CONFIRMED",
        timeframe="H1",
    )
    assert h1_pause.market_context == SHORT_CONTEXT
    assert h1_pause.process == SELLER


def test_sep14_dump_pause_cases_from_journal():
    """H1 20:00 / 02:00 and M30_5: pause after accepted down is not LONG."""
    dump = walk_bars(
        [
            {
                "cognitive_market_state": "ACCEPTANCE_LOWER",
                "state_direction": "SELLER_CONTROL",
                "state_status": "CONFIRMED",
                "price_result": "ACCEPTED_LOWER",
                "effort_result": "CONTINUED",
                "timeframe": "H1",
            },
            {
                "cognitive_market_state": "LOWER_ABSORPTION",
                "state_direction": "BUYER_SUPPORT",
                "state_status": "CONFIRMED",
                "timeframe": "H1",
            },
            {
                "cognitive_market_state": "BALANCE",
                "state_direction": "NEUTRAL",
                "state_status": "DEVELOPING",
                "timeframe": "H1",
            },
            {
                "cognitive_market_state": "LOWER_ABSORPTION",
                "state_direction": "BUYER_SUPPORT",
                "state_status": "CONFIRMED",
                "timeframe": "H1",
            },
        ],
        timeframe="H1",
    )
    assert dump[0].market_context == SHORT_CONTEXT
    assert [s.market_context for s in dump[1:]] == [SHORT_CONTEXT, SHORT_CONTEXT, SHORT_CONTEXT]
    assert OBSERVE not in {s.market_context for s in dump}
    assert LONG_CONTEXT not in {s.market_context for s in dump}


def test_accepted_up_rally_stays_long():
    snaps = walk_bars(
        [
            {
                "cognitive_market_state": "ACCEPTANCE_HIGHER",
                "state_direction": "BUYER_CONTROL",
                "state_status": "CONFIRMED",
            },
            {
                "cognitive_market_state": "BUYER_CONTROL",
                "state_direction": "BUYER_CONTROL",
                "state_status": "CONFIRMED",
                "price_result": "ACCEPTED_HIGHER",
                "effort_result": "CONTINUED",
            },
            {
                "cognitive_market_state": "BUYER_CONTROL",
                "state_direction": "BUYER_CONTROL",
                "state_status": "CONFIRMED",
                "price_result": "ACCEPTED_HIGHER",
                "effort_result": "ACCEPTED",
            },
        ]
    )
    assert [s.market_context for s in snaps] == [LONG_CONTEXT, LONG_CONTEXT, LONG_CONTEXT]
    assert snaps[2].strength > snaps[0].strength


def test_short_not_erased_by_trade_policy_reason():
    ctx, reason = classify_market_context(
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
    )
    assert ctx == SHORT_CONTEXT
    assert "SHORT_DISABLED" not in reason
    assert "execution" not in reason.lower()


def test_hold_bars_not_used():
    """Strength is not a three-bar M15 delay. One accepted bar is enough to start."""
    snap = step_living_process(
        ProcessSnapshot(process="NONE", strength=0.0, market_context=OBSERVE),
        cognitive_market_state="ACCEPTANCE_LOWER",
        state_direction="SELLER_CONTROL",
        state_status="CONFIRMED",
    )
    assert snap.market_context == SHORT_CONTEXT


def test_absorption_not_in_long_states_recurrence():
    from pathlib import Path
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[2]
    final_path = root / "scripts" / "research" / "build_final_market_context_memory.py"
    spec = importlib.util.spec_from_file_location("final_ctx_lock", final_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "LOWER_ABSORPTION" not in mod.LONG_STATES
    assert "UPPER_DISTRIBUTION" not in mod.SHORT_STATES

    life_path = root / "scripts" / "research" / "build_market_context_lifecycle_memory.py"
    life_spec = importlib.util.spec_from_file_location("life_hold_lock", life_path)
    life = importlib.util.module_from_spec(life_spec)
    sys.modules.setdefault("build_market_context_lifecycle_memory", life)
    life_spec.loader.exec_module(life)
    assert life.MIN_ACTIVE_CONTEXT_HOLD_BARS == 0
