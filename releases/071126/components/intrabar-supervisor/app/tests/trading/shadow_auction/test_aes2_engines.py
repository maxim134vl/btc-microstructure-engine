"""AES2 independent TF auction episode engine — deterministic synthetic tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from btc_ml.trading.shadow_auction.engine import ShadowAuctionAES2, TimeframeAuctionEngine
from btc_ml.trading.shadow_auction.observation import BarObservation
from btc_ml.trading.shadow_auction.states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    PHASE_ACCEPTANCE_ABOVE,
    PHASE_ACCEPTANCE_BELOW,
    PHASE_BALANCE_ESTABLISHED,
    PHASE_BALANCE_FORMING,
    PHASE_BALANCE_ROTATION,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_PRESSURE_ACTIVE,
    PHASE_DOWN_STOPPING_CANDIDATE,
    PHASE_DOWNSIDE_EXPANSION_ATTEMPT,
    PHASE_EXTREME_DOWN_PARTICIPATION,
    PHASE_EXTREME_UP_PARTICIPATION,
    PHASE_FAILED_DOWNSIDE_BREAK,
    PHASE_FAILED_UPSIDE_BREAK,
    PHASE_INTERNAL_TRANSFER_SUPPORT,
    PHASE_POST_DOWN_STRESS_REACTION,
    PHASE_POST_UP_STRESS_REACTION,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
    PHASE_TRANSITION,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_PRESSURE_ACTIVE,
    PHASE_UP_STOPPING_CANDIDATE,
    PHASE_UPSIDE_EXPANSION_ATTEMPT,
    mirror_phase,
)

REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"


def _bar(
    i: int,
    *,
    tf: str = "M15",
    o: float,
    h: float,
    l: float,
    c: float,
    volume: float = 100.0,
    overrides: dict | None = None,
    eid: str | None = None,
) -> BarObservation:
    ts = f"2026-08-01T00:{i:02d}:00Z" if i < 60 else f"2026-08-01T01:{i - 60:02d}:00Z"
    return BarObservation(
        timestamp=ts,
        timeframe=tf,
        source_event_id=eid or f"{tf}|{ts}|{i}",
        open=o,
        high=h,
        low=l,
        close=c,
        volume=volume,
        buy_volume=max(0.0, volume * (0.5 + (c - o) / max(h - l, 1e-9) * 0.5)),
        sell_volume=max(0.0, volume * (0.5 - (c - o) / max(h - l, 1e-9) * 0.5)),
        delta=None,
        close_position=(c - l) / max(h - l, 1e-9),
        body=abs(c - o),
        spread=h - l,
        upper_wick=h - max(o, c),
        lower_wick=min(o, c) - l,
        volume_zscore=0.0,
        feature_overrides=dict(overrides or {}),
    )


def _run(engine: TimeframeAuctionEngine, bars: list[BarObservation]):
    return [engine.process(b) for b in bars]


def _phases(results):
    return [r.episode_phase for r in results]


def _down_cascade_bars(tf: str = "M15", start_i: int = 0) -> list[BarObservation]:
    """Extreme sell + strong downside result + continuation + extreme + continuation."""
    bars = []
    px = 100.0
    seq = [
        # enter down pressure
        dict(
            move=-1.2,
            ov={
                "down_continuation_support": 0.85,
                "up_continuation_support": 0.1,
                "down_efficiency": 0.75,
                "sell_effort": 0.7,
                "buy_effort": 0.2,
                "down_result": 0.7,
                "range_expansion": 0.6,
            },
        ),
        # expand
        dict(
            move=-1.0,
            ov={
                "down_continuation_support": 0.85,
                "up_continuation_support": 0.1,
                "down_efficiency": 0.8,
                "sell_effort": 0.75,
                "buy_effort": 0.15,
                "down_result": 0.75,
                "range_expansion": 0.7,
            },
        ),
        # extreme participation + new low + strong result
        dict(
            move=-1.5,
            ov={
                "extreme_down_participation": True,
                "down_continuation_support": 0.9,
                "up_continuation_support": 0.05,
                "down_efficiency": 0.85,
                "sell_effort": 0.9,
                "buy_effort": 0.1,
                "down_result": 0.85,
                "follow_through": 0.35,
                "range_expansion": 0.8,
            },
        ),
        # continuation after extreme
        dict(
            move=-1.2,
            ov={
                "down_continuation_support": 0.88,
                "up_continuation_support": 0.05,
                "down_efficiency": 0.82,
                "sell_effort": 0.8,
                "buy_effort": 0.1,
                "down_result": 0.8,
                "follow_through": 0.3,
                "range_expansion": 0.7,
            },
        ),
        # second extreme
        dict(
            move=-1.4,
            ov={
                "extreme_down_participation": True,
                "down_continuation_support": 0.9,
                "up_continuation_support": 0.05,
                "down_efficiency": 0.86,
                "sell_effort": 0.92,
                "buy_effort": 0.08,
                "down_result": 0.86,
                "follow_through": 0.32,
                "range_expansion": 0.85,
            },
        ),
        # continuation again
        dict(
            move=-1.0,
            ov={
                "down_continuation_support": 0.87,
                "up_continuation_support": 0.05,
                "down_efficiency": 0.8,
                "sell_effort": 0.78,
                "buy_effort": 0.1,
                "down_result": 0.78,
                "follow_through": 0.28,
                "range_expansion": 0.65,
            },
        ),
    ]
    for j, step in enumerate(seq):
        o = px
        c = px + step["move"]
        h = max(o, c) + 0.1
        l = min(o, c) - 0.15
        bars.append(_bar(start_i + j, tf=tf, o=o, h=h, l=l, c=c, overrides=step["ov"]))
        px = c
    return bars


def _mirror_bar(b: BarObservation, pivot: float = 100.0) -> BarObservation:
    """Price-mirror a bar around pivot and flip directional feature overrides."""
    o = pivot - (b.open - pivot)
    h = pivot - (b.low - pivot)
    l = pivot - (b.high - pivot)
    c = pivot - (b.close - pivot)
    ov = dict(b.feature_overrides)
    swap = {
        "buy_effort": "sell_effort",
        "sell_effort": "buy_effort",
        "up_result": "down_result",
        "down_result": "up_result",
        "up_efficiency": "down_efficiency",
        "down_efficiency": "up_efficiency",
        "up_continuation_support": "down_continuation_support",
        "down_continuation_support": "up_continuation_support",
        "up_exhaustion_support": "down_exhaustion_support",
        "down_exhaustion_support": "up_exhaustion_support",
        "up_resolution_support": "down_resolution_support",
        "down_resolution_support": "up_resolution_support",
        "efficiency_trend_up": "efficiency_trend_down",
        "efficiency_trend_down": "efficiency_trend_up",
        "extreme_up_participation": "extreme_down_participation",
        "extreme_down_participation": "extreme_up_participation",
        "upper_rejection": "lower_rejection",
        "lower_rejection": "upper_rejection",
    }
    mirrored: dict = {}
    for k, v in ov.items():
        if k == "follow_through" and isinstance(v, (int, float)):
            mirrored[k] = 1.0 - float(v)
            continue
        if k in swap:
            mirrored[swap[k]] = v
        else:
            mirrored[k] = v
    # force_phase mirror
    if "force_phase" in mirrored:
        mirrored["force_phase"] = mirror_phase(str(mirrored["force_phase"]))
    return BarObservation(
        timestamp=b.timestamp,
        timeframe=b.timeframe,
        source_event_id=b.source_event_id.replace("DOWN", "UP") + "|UP",
        open=o,
        high=h,
        low=l,
        close=c,
        volume=b.volume,
        buy_volume=b.sell_volume,
        sell_volume=b.buy_volume,
        delta=None if b.delta is None else -b.delta,
        close_position=1.0 - (b.close_position or 0.5),
        body=b.body,
        spread=b.spread,
        upper_wick=b.lower_wick,
        lower_wick=b.upper_wick,
        volume_zscore=b.volume_zscore,
        feature_overrides=mirrored,
    )


# ---------------------------------------------------------------------------
# Tests 1–3 DOWN
# ---------------------------------------------------------------------------


def test_01_downside_cascade_single_episode():
    eng = TimeframeAuctionEngine("M15")
    results = _run(eng, _down_cascade_bars())
    phases = _phases(results)
    assert PHASE_DOWN_PRESSURE_ACTIVE in phases or PHASE_DOWN_CONTINUATION_ACCEPTED in phases
    assert PHASE_EXTREME_DOWN_PARTICIPATION in phases
    assert phases.count(PHASE_EXTREME_DOWN_PARTICIPATION) >= 1
    assert any(p == PHASE_DOWN_CONTINUATION_ACCEPTED for p in phases)
    # No premature climax / reversal labels.
    assert all("CLIMAX" not in p for p in phases)
    assert results[-1].auction_family == FAMILY_DIRECTIONAL_DOWN
    ids = {r.shadow_episode_id for r in results if r.shadow_episode_id}
    assert len(ids) == 1


def test_02_downside_deterioration():
    eng = TimeframeAuctionEngine("M15")
    bars = _down_cascade_bars()[:4]
    # Append deteriorating bars: sell effort ↑, down result ↓
    px = bars[-1].close
    for j, (effort, result, eff) in enumerate(
        [(0.85, 0.55, 0.45), (0.92, 0.40, 0.30), (0.97, 0.28, 0.20)]
    ):
        o = px
        c = px - 0.2
        bars.append(
            _bar(
                10 + j,
                o=o,
                h=o + 0.3,
                l=c - 0.05,
                c=c,
                overrides={
                    "sell_effort": effort,
                    "buy_effort": 0.1,
                    "down_result": result,
                    "up_result": 0.1,
                    "down_efficiency": eff,
                    "up_efficiency": 0.1,
                    "down_continuation_support": 0.4,
                    "up_continuation_support": 0.2,
                    "efficiency_trend_down": -0.2,
                    "down_exhaustion_support": 0.4,
                    "balance_support": 0.2,
                },
            )
        )
        px = c
    results = _run(eng, bars)
    assert PHASE_DOWN_CONTINUATION_DETERIORATING in _phases(results)


def test_03_false_downside_stopping_invalidated():
    eng = TimeframeAuctionEngine("M15")
    bars = _down_cascade_bars()[:4]
    px = bars[-1].close
    # Force path into stopping candidate then reaction then new low acceptance.
    seq = [
        (
            -0.1,
            {
                "force_phase": PHASE_DOWN_CONTINUATION_DETERIORATING,
                "sell_effort": 0.9,
                "down_result": 0.25,
                "down_efficiency": 0.2,
                "efficiency_trend_down": -0.3,
                "down_exhaustion_support": 0.7,
                "reaction_strength": 0.4,
                "balance_support": 0.2,
            },
        ),
        (
            0.4,
            {
                "force_phase": PHASE_DOWN_STOPPING_CANDIDATE,
                "sell_effort": 0.7,
                "down_result": 0.2,
                "down_efficiency": 0.2,
                "reaction_strength": 0.5,
                "balance_support": 0.2,
            },
        ),
        (
            0.3,
            {
                "reaction_strength": 0.6,
                "balance_support": 0.2,
                "down_efficiency": 0.2,
                "sell_effort": 0.5,
            },
        ),
        (
            -1.5,
            {
                "down_efficiency": 0.85,
                "down_result": 0.8,
                "sell_effort": 0.85,
                "buy_effort": 0.1,
                "follow_through": 0.3,
                "down_continuation_support": 0.85,
                "up_continuation_support": 0.1,
                "balance_support": 0.1,
                "reaction_strength": 0.1,
            },
        ),
    ]
    for j, (move, ov) in enumerate(seq):
        o = px
        c = px + move
        bars.append(
            _bar(
                20 + j,
                o=o,
                h=max(o, c) + 0.1,
                l=min(o, c) - 0.2,
                c=c,
                overrides=ov,
            )
        )
        px = c
    results = _run(eng, bars)
    phases = _phases(results)
    assert PHASE_DOWN_STOPPING_CANDIDATE in phases or PHASE_POST_DOWN_STRESS_REACTION in phases
    assert PHASE_DOWN_CONTINUATION_ACCEPTED in phases
    # After invalidation, family restored to DOWN.
    assert results[-1].auction_family == FAMILY_DIRECTIONAL_DOWN
    assert "STOPPING_CANDIDATE_INVALIDATED" in results[-1].reason_codes or any(
        "STOPPING_CANDIDATE_INVALIDATED" in r.reason_codes for r in results
    )
    # History of prior candidate preserved.
    assert any(h["new_state"] == PHASE_DOWN_STOPPING_CANDIDATE for h in eng.state.history) or any(
        h["new_state"] == PHASE_POST_DOWN_STRESS_REACTION for h in eng.state.history
    )


# ---------------------------------------------------------------------------
# Tests 4–6 UP mirrors
# ---------------------------------------------------------------------------


def test_04_upside_cascade_mirror():
    eng = TimeframeAuctionEngine("M15")
    down_bars = _down_cascade_bars()
    up_bars = [_mirror_bar(b) for b in down_bars]
    results = _run(eng, up_bars)
    phases = _phases(results)
    assert PHASE_EXTREME_UP_PARTICIPATION in phases
    assert PHASE_UP_CONTINUATION_ACCEPTED in phases
    assert results[-1].auction_family == FAMILY_DIRECTIONAL_UP
    assert len({r.shadow_episode_id for r in results if r.shadow_episode_id}) == 1


def test_05_upside_deterioration_mirror():
    eng_d = TimeframeAuctionEngine("M15")
    eng_u = TimeframeAuctionEngine("M15")
    down_bars = _down_cascade_bars()[:4]
    px = down_bars[-1].close
    for j, (effort, result, eff) in enumerate(
        [(0.85, 0.55, 0.45), (0.92, 0.40, 0.30), (0.97, 0.28, 0.20)]
    ):
        o = px
        c = px - 0.2
        down_bars.append(
            _bar(
                10 + j,
                o=o,
                h=o + 0.3,
                l=c - 0.05,
                c=c,
                overrides={
                    "sell_effort": effort,
                    "buy_effort": 0.1,
                    "down_result": result,
                    "up_result": 0.1,
                    "down_efficiency": eff,
                    "up_efficiency": 0.1,
                    "down_continuation_support": 0.4,
                    "up_continuation_support": 0.2,
                    "efficiency_trend_down": -0.2,
                    "balance_support": 0.2,
                },
            )
        )
        px = c
    up_bars = [_mirror_bar(b) for b in down_bars]
    rd = _run(eng_d, down_bars)
    ru = _run(eng_u, up_bars)
    assert PHASE_DOWN_CONTINUATION_DETERIORATING in _phases(rd)
    assert PHASE_UP_CONTINUATION_DETERIORATING in _phases(ru)
    # Symmetry: mirrored phase sequence
    assert [mirror_phase(p) for p in _phases(rd)] == _phases(ru)


def test_06_false_upside_stopping_mirror():
    eng = TimeframeAuctionEngine("M15")
    # Build via force_phase upside path
    bars = [_mirror_bar(b) for b in _down_cascade_bars()[:4]]
    px = bars[-1].close
    seq = [
        (
            0.1,
            {
                "force_phase": PHASE_UP_CONTINUATION_DETERIORATING,
                "buy_effort": 0.9,
                "up_result": 0.25,
                "up_efficiency": 0.2,
                "efficiency_trend_up": -0.3,
                "up_exhaustion_support": 0.7,
                "reaction_strength": 0.4,
                "balance_support": 0.2,
            },
        ),
        (
            -0.4,
            {
                "force_phase": PHASE_UP_STOPPING_CANDIDATE,
                "buy_effort": 0.7,
                "up_result": 0.2,
                "up_efficiency": 0.2,
                "reaction_strength": 0.5,
                "balance_support": 0.2,
            },
        ),
        (
            -0.3,
            {
                "reaction_strength": 0.6,
                "balance_support": 0.2,
                "up_efficiency": 0.2,
                "buy_effort": 0.5,
            },
        ),
        (
            1.5,
            {
                "up_efficiency": 0.85,
                "up_result": 0.8,
                "buy_effort": 0.85,
                "sell_effort": 0.1,
                "follow_through": 0.7,
                "up_continuation_support": 0.85,
                "down_continuation_support": 0.1,
                "balance_support": 0.1,
                "reaction_strength": 0.1,
            },
        ),
    ]
    for j, (move, ov) in enumerate(seq):
        o = px
        c = px + move
        bars.append(
            _bar(30 + j, o=o, h=max(o, c) + 0.2, l=min(o, c) - 0.1, c=c, overrides=ov)
        )
        px = c
    results = _run(eng, bars)
    assert results[-1].auction_family == FAMILY_DIRECTIONAL_UP
    assert any("STOPPING_CANDIDATE_INVALIDATED" in r.reason_codes for r in results)


# ---------------------------------------------------------------------------
# Balance tests 7–15
# ---------------------------------------------------------------------------


def _seed_balance(eng: TimeframeAuctionEngine, start_i: int = 0) -> list:
    """Drive UNRESOLVED → TRANSITION → BALANCE_FORMING → ESTABLISHED."""
    bars = []
    # Oscillating range with high balance_support
    prices = [100, 100.4, 99.8, 100.2, 99.9, 100.1, 100.0, 100.15, 99.95, 100.05]
    for j, px in enumerate(prices):
        o = px - 0.05
        c = px
        bars.append(
            _bar(
                start_i + j,
                o=o,
                h=px + 0.25,
                l=px - 0.25,
                c=c,
                overrides={
                    "balance_support": 0.75,
                    "up_continuation_support": 0.25,
                    "down_continuation_support": 0.25,
                    "up_efficiency": 0.25,
                    "down_efficiency": 0.25,
                    "buy_effort": 0.4,
                    "sell_effort": 0.4,
                    "range_expansion": 0.25,
                    "price_displacement": 0.1,
                },
            )
        )
    return _run(eng, bars)


def test_07_balance_formation():
    eng = TimeframeAuctionEngine("M15")
    results = _seed_balance(eng)
    phases = _phases(results)
    assert PHASE_TRANSITION in phases or PHASE_BALANCE_FORMING in phases
    assert PHASE_BALANCE_FORMING in phases or PHASE_BALANCE_ESTABLISHED in phases
    assert any(r.auction_family in {FAMILY_TRANSITION, FAMILY_BALANCE} for r in results)
    assert results[-1].auction_family == FAMILY_BALANCE


def test_08_balance_rotation_no_directional_flipflop():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    # Rotate low → mid → high → mid → low
    rot = [99.7, 100.0, 100.3, 100.0, 99.75, 100.05, 100.25, 99.9]
    bars = []
    for j, px in enumerate(rot):
        bars.append(
            _bar(
                40 + j,
                o=px,
                h=px + 0.15,
                l=px - 0.15,
                c=px,
                overrides={
                    "balance_support": 0.7,
                    "up_continuation_support": 0.3,
                    "down_continuation_support": 0.3,
                    "range_expansion": 0.3,
                    "price_displacement": 0.1,
                },
            )
        )
    results = _run(eng, bars)
    families = [r.auction_family for r in results]
    assert all(f == FAMILY_BALANCE for f in families)
    # No directional flip-flop.
    assert FAMILY_DIRECTIONAL_UP not in families
    assert FAMILY_DIRECTIONAL_DOWN not in families
    assert PHASE_BALANCE_ROTATION in _phases(results) or PHASE_BALANCE_ESTABLISHED in _phases(results)


def test_09_internal_extreme_volume_not_climax():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    # Push to established
    while eng.state.episode_phase == PHASE_BALANCE_FORMING:
        eng.process(
            _bar(
                50 + eng.state.episode_age,
                o=100,
                h=100.2,
                l=99.8,
                c=100.0,
                overrides={"balance_support": 0.7, "range_expansion": 0.2},
            )
        )
    bal = eng.state.balance
    mid = bal.balance_mid or 100.0
    r = eng.process(
        _bar(
            60,
            o=mid,
            h=mid + 0.05,
            l=mid - 0.05,
            c=mid,
            volume=5000,
            overrides={
                "extreme_up_participation": True,
                "balance_support": 0.8,
                "price_displacement": 0.01,
                "up_resolution_support": 0.2,
                "down_resolution_support": 0.2,
                "range_expansion": 0.1,
            },
        )
    )
    assert r.episode_phase == PHASE_INTERNAL_TRANSFER_SUPPORT
    assert r.auction_family == FAMILY_BALANCE
    assert "CLIMAX" not in r.episode_phase
    assert r.episode_phase not in {PHASE_RESOLUTION_UP, PHASE_RESOLUTION_DOWN}


def test_10_failed_upside_break():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    # Ensure established with known bounds
    for j in range(4):
        eng.process(
            _bar(
                70 + j,
                o=100,
                h=100.2,
                l=99.8,
                c=100.0,
                overrides={"balance_support": 0.7, "range_expansion": 0.2},
            )
        )
    hi = eng.state.balance.balance_high or 100.3
    r1 = eng.process(
        _bar(
            80,
            o=hi - 0.05,
            h=hi + 0.4,
            l=hi - 0.1,
            c=hi + 0.2,
            overrides={
                "up_resolution_support": 0.3,
                "balance_support": 0.5,
                "extreme_up_participation": True,
            },
        )
    )
    assert r1.episode_phase == PHASE_UPSIDE_EXPANSION_ATTEMPT
    r2 = eng.process(
        _bar(
            81,
            o=hi + 0.1,
            h=hi + 0.15,
            l=hi - 0.3,
            c=hi - 0.1,
            overrides={"up_resolution_support": 0.2, "balance_support": 0.6},
        )
    )
    assert r2.episode_phase == PHASE_FAILED_UPSIDE_BREAK
    assert r2.auction_family == FAMILY_BALANCE
    assert r2.auction_family != FAMILY_DIRECTIONAL_UP


def test_11_failed_downside_break():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    for j in range(4):
        eng.process(
            _bar(
                90 + j,
                o=100,
                h=100.2,
                l=99.8,
                c=100.0,
                overrides={"balance_support": 0.7, "range_expansion": 0.2},
            )
        )
    lo = eng.state.balance.balance_low or 99.7
    r1 = eng.process(
        _bar(
            100,
            o=lo + 0.05,
            h=lo + 0.1,
            l=lo - 0.4,
            c=lo - 0.2,
            overrides={"down_resolution_support": 0.3, "balance_support": 0.5},
        )
    )
    assert r1.episode_phase == PHASE_DOWNSIDE_EXPANSION_ATTEMPT
    r2 = eng.process(
        _bar(
            101,
            o=lo - 0.1,
            h=lo + 0.3,
            l=lo - 0.15,
            c=lo + 0.1,
            overrides={"down_resolution_support": 0.2, "balance_support": 0.6},
        )
    )
    assert r2.episode_phase == PHASE_FAILED_DOWNSIDE_BREAK


def test_12_upside_resolution():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    for j in range(4):
        eng.process(
            _bar(
                110 + j,
                o=100,
                h=100.2,
                l=99.8,
                c=100.0,
                overrides={"balance_support": 0.7, "range_expansion": 0.2},
            )
        )
    hi = eng.state.balance.balance_high or 100.3
    phases = []
    for j in range(3):
        r = eng.process(
            _bar(
                120 + j,
                o=hi + 0.05 + j * 0.1,
                h=hi + 0.4 + j * 0.2,
                l=hi + 0.02,
                c=hi + 0.25 + j * 0.15,
                overrides={
                    "up_resolution_support": 0.8,
                    "up_continuation_support": 0.8,
                    "down_continuation_support": 0.1,
                    "up_efficiency": 0.8,
                    "follow_through": 0.75,
                    "balance_support": 0.3,
                },
            )
        )
        phases.append(r.episode_phase)
    assert PHASE_UPSIDE_EXPANSION_ATTEMPT in phases
    assert PHASE_ACCEPTANCE_ABOVE in phases or PHASE_RESOLUTION_UP in phases
    # After acceptance, resolution then directional.
    if eng.state.episode_phase == PHASE_ACCEPTANCE_ABOVE:
        r = eng.process(
            _bar(
                130,
                o=hi + 0.5,
                h=hi + 0.8,
                l=hi + 0.4,
                c=hi + 0.7,
                overrides={"up_resolution_support": 0.85, "up_continuation_support": 0.85},
            )
        )
        phases.append(r.episode_phase)
    if eng.state.episode_phase == PHASE_RESOLUTION_UP:
        r = eng.process(
            _bar(
                131,
                o=hi + 0.7,
                h=hi + 1.0,
                l=hi + 0.6,
                c=hi + 0.9,
                overrides={
                    "up_continuation_support": 0.9,
                    "down_continuation_support": 0.05,
                    "up_efficiency": 0.85,
                    "buy_effort": 0.8,
                },
            )
        )
        phases.append(r.episode_phase)
    assert PHASE_RESOLUTION_UP in phases or eng.state.auction_family == FAMILY_DIRECTIONAL_UP
    assert eng.state.auction_family in {FAMILY_DIRECTIONAL_UP, FAMILY_BALANCE}
    if eng.state.episode_phase in {PHASE_UP_PRESSURE_ACTIVE, PHASE_UP_CONTINUATION_ACCEPTED}:
        assert eng.state.auction_family == FAMILY_DIRECTIONAL_UP


def test_13_downside_resolution():
    eng = TimeframeAuctionEngine("M15")
    _seed_balance(eng)
    for j in range(4):
        eng.process(
            _bar(
                140 + j,
                o=100,
                h=100.2,
                l=99.8,
                c=100.0,
                overrides={"balance_support": 0.7, "range_expansion": 0.2},
            )
        )
    lo = eng.state.balance.balance_low or 99.7
    phases = []
    for j in range(3):
        r = eng.process(
            _bar(
                150 + j,
                o=lo - 0.05 - j * 0.1,
                h=lo - 0.02,
                l=lo - 0.4 - j * 0.2,
                c=lo - 0.25 - j * 0.15,
                overrides={
                    "down_resolution_support": 0.8,
                    "down_continuation_support": 0.8,
                    "up_continuation_support": 0.1,
                    "down_efficiency": 0.8,
                    "follow_through": 0.25,
                    "balance_support": 0.3,
                },
            )
        )
        phases.append(r.episode_phase)
    assert PHASE_DOWNSIDE_EXPANSION_ATTEMPT in phases
    # Drive acceptance → resolution → directional
    for k in range(4):
        if eng.state.episode_phase in {
            PHASE_ACCEPTANCE_BELOW,
            PHASE_RESOLUTION_DOWN,
            PHASE_DOWNSIDE_EXPANSION_ATTEMPT,
        } or eng.state.auction_family == FAMILY_BALANCE:
            r = eng.process(
                _bar(
                    160 + k,
                    o=lo - 0.5 - k * 0.1,
                    h=lo - 0.4,
                    l=lo - 0.8 - k * 0.1,
                    c=lo - 0.6 - k * 0.1,
                    overrides={
                        "down_resolution_support": 0.9,
                        "down_continuation_support": 0.9,
                        "down_efficiency": 0.85,
                        "sell_effort": 0.8,
                        "up_continuation_support": 0.05,
                    },
                )
            )
            phases.append(r.episode_phase)
    assert PHASE_ACCEPTANCE_BELOW in phases or PHASE_RESOLUTION_DOWN in phases or any(
        p == PHASE_DOWN_PRESSURE_ACTIVE for p in phases
    )


def test_14_continuation_through_balance():
    # DIRECTIONAL_UP → BALANCE → RESOLUTION_UP
    eng = TimeframeAuctionEngine("M15")
    # Start directional up via force then transition to balance then resolve up.
    r = eng.process(
        _bar(
            0,
            o=100,
            h=101,
            l=99.9,
            c=100.8,
            overrides={
                "force_phase": PHASE_UP_CONTINUATION_ACCEPTED,
                "up_continuation_support": 0.9,
                "up_efficiency": 0.8,
            },
        )
    )
    assert r.auction_family == FAMILY_DIRECTIONAL_UP
    r = eng.process(
        _bar(
            1,
            o=100.8,
            h=100.9,
            l=100.5,
            c=100.6,
            overrides={
                "force_phase": PHASE_UP_CONTINUATION_DETERIORATING,
                "balance_support": 0.7,
                "up_efficiency": 0.2,
            },
        )
    )
    r = eng.process(
        _bar(
            2,
            o=100.6,
            h=100.7,
            l=100.4,
            c=100.5,
            overrides={"balance_support": 0.8, "up_continuation_support": 0.2, "down_continuation_support": 0.2},
        )
    )
    assert r.episode_phase in {PHASE_TRANSITION, PHASE_BALANCE_FORMING}
    # Establish balance then resolve same direction
    for j in range(5):
        eng.process(
            _bar(
                3 + j,
                o=100.5,
                h=100.7,
                l=100.3,
                c=100.5,
                overrides={"balance_support": 0.75, "range_expansion": 0.2},
            )
        )
    hi = eng.state.balance.balance_high or 100.7
    for j in range(4):
        eng.process(
            _bar(
                20 + j,
                o=hi + 0.1 * j,
                h=hi + 0.3 + 0.1 * j,
                l=hi + 0.05,
                c=hi + 0.2 + 0.1 * j,
                overrides={
                    "up_resolution_support": 0.85,
                    "up_continuation_support": 0.85,
                    "up_efficiency": 0.8,
                    "follow_through": 0.7,
                },
            )
        )
    assert eng.state.episode_phase in {
        PHASE_ACCEPTANCE_ABOVE,
        PHASE_RESOLUTION_UP,
        PHASE_UP_PRESSURE_ACTIVE,
        PHASE_UP_CONTINUATION_ACCEPTED,
        PHASE_UPSIDE_EXPANSION_ATTEMPT,
    } or eng.state.auction_family == FAMILY_DIRECTIONAL_UP


def test_15_reversal_through_balance():
    eng = TimeframeAuctionEngine("M15")
    eng.process(
        _bar(
            0,
            o=100,
            h=100.1,
            l=98.5,
            c=98.8,
            overrides={
                "force_phase": PHASE_DOWN_CONTINUATION_ACCEPTED,
                "down_continuation_support": 0.9,
            },
        )
    )
    eng.process(
        _bar(
            1,
            o=98.8,
            h=99.0,
            l=98.6,
            c=98.9,
            overrides={
                "force_phase": PHASE_DOWN_CONTINUATION_DETERIORATING,
                "balance_support": 0.7,
            },
        )
    )
    eng.process(
        _bar(
            2,
            o=98.9,
            h=99.1,
            l=98.7,
            c=99.0,
            overrides={"balance_support": 0.8, "up_continuation_support": 0.2, "down_continuation_support": 0.2},
        )
    )
    assert eng.state.auction_family in {FAMILY_TRANSITION, FAMILY_BALANCE}
    for j in range(5):
        eng.process(
            _bar(
                3 + j,
                o=99.0,
                h=99.2,
                l=98.8,
                c=99.0,
                overrides={"balance_support": 0.75, "range_expansion": 0.2},
            )
        )
    hi = eng.state.balance.balance_high or 99.2
    for j in range(4):
        eng.process(
            _bar(
                20 + j,
                o=hi + 0.1 * j,
                h=hi + 0.35 + 0.1 * j,
                l=hi + 0.05,
                c=hi + 0.25 + 0.1 * j,
                overrides={
                    "up_resolution_support": 0.85,
                    "up_continuation_support": 0.85,
                    "up_efficiency": 0.8,
                    "follow_through": 0.7,
                },
            )
        )
    # Reversal path: was DOWN, balance, resolve UP
    assert eng.state.auction_family in {FAMILY_DIRECTIONAL_UP, FAMILY_BALANCE}
    assert eng.state.episode_phase in {
        PHASE_ACCEPTANCE_ABOVE,
        PHASE_RESOLUTION_UP,
        PHASE_UP_PRESSURE_ACTIVE,
        PHASE_UP_CONTINUATION_ACCEPTED,
        PHASE_UPSIDE_EXPANSION_ATTEMPT,
        PHASE_BALANCE_ESTABLISHED,
        PHASE_FAILED_UPSIDE_BREAK,
    }


# ---------------------------------------------------------------------------
# TF independence / no-lookahead / idempotency
# ---------------------------------------------------------------------------


def test_16_tf_independence():
    shadow = ShadowAuctionAES2()
    # Process M15 reversal cascade
    for b in _down_cascade_bars("M15"):
        shadow.process(b)
    m15 = shadow.engines["M15"]
    m30 = shadow.engines["M30"]
    h1 = shadow.engines["H1"]
    h4 = shadow.engines["H4"]
    assert m15.state.auction_family == FAMILY_DIRECTIONAL_DOWN
    assert m30.state.auction_family == "UNRESOLVED"
    assert h1.state.auction_family == "UNRESOLVED"
    assert h4.state.auction_family == "UNRESOLVED"
    assert m30.state.episode_phase == "UNRESOLVED"
    # Mutating M15 again still leaves others untouched
    before = (m30.state.episode_phase, h1.state.episode_phase, h4.state.episode_phase)
    shadow.process(
        _bar(
            50,
            tf="M15",
            o=90,
            h=90.2,
            l=88,
            c=88.5,
            overrides={
                "down_continuation_support": 0.9,
                "down_efficiency": 0.8,
                "sell_effort": 0.8,
            },
        )
    )
    assert (m30.state.episode_phase, h1.state.episode_phase, h4.state.episode_phase) == before


def test_17_no_lookahead():
    bars = _down_cascade_bars()
    eng_full = TimeframeAuctionEngine("M15")
    full = _run(eng_full, bars)
    for t in range(1, len(bars) + 1):
        eng = TimeframeAuctionEngine("M15")
        partial = _run(eng, bars[:t])
        assert _phases(partial) == _phases(full[:t])
        assert [r.shadow_episode_id for r in partial] == [r.shadow_episode_id for r in full[:t]]


def test_18_restart_idempotency():
    eng = TimeframeAuctionEngine("M15")
    bars = _down_cascade_bars()
    first = _run(eng, bars)
    # Re-feed same events
    dupes = _run(eng, bars)
    assert all(r.duplicate for r in dupes)
    assert eng.transitions_written == sum(1 for r in first if r.previous_state != r.new_state)
    # New engine replay same sequence → identical phases
    eng2 = TimeframeAuctionEngine("M15")
    second = _run(eng2, bars)
    assert _phases(second) == _phases(first)


def test_symmetry_phase_mirror_helper():
    assert mirror_phase(PHASE_UP_PRESSURE_ACTIVE) == PHASE_DOWN_PRESSURE_ACTIVE
    assert mirror_phase(PHASE_FAILED_DOWNSIDE_BREAK) == PHASE_FAILED_UPSIDE_BREAK
    assert mirror_phase(PHASE_BALANCE_ESTABLISHED) == PHASE_BALANCE_ESTABLISHED


def test_aes2_health_fields():
    shadow = ShadowAuctionAES2()
    for b in _down_cascade_bars("M15")[:3]:
        shadow.process(b)
    health = shadow.health_fields()
    assert "m15_auction_family" in health
    assert "m30_episode_phase" in health
    assert "h1_episode_id" in health
    assert "h4_auction_family" in health
    assert health["aes2_events_written"] >= 3
    assert health["open_tf_episodes"] >= 1


def test_aes2_external_memory_write():
    from btc_ml.trading.shadow_auction.storage import ShadowAuctionStore, is_real_mounted_volume
    from btc_ml.trading.shadow_auction.memory import Aes2MemoryWriter
    from btc_ml.trading.shadow_auction.engine import TimeframeAuctionEngine

    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger volume not mounted")
    store = ShadowAuctionStore(
        data_root=REAL_DATA_ROOT / "replay" / "_aes2_pytest",
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    eng = TimeframeAuctionEngine("M15", logic_version="AES_V1", logic_fingerprint="test")
    mem = Aes2MemoryWriter(store)
    before_event = (store.data_root / "memory" / "tf_event_memory.jsonl")
    before_size = before_event.stat().st_size if before_event.exists() else 0
    for b in _down_cascade_bars()[:3]:
        mem.write_transition(obs=b, result=eng.process(b))
    assert before_event.exists()
    assert before_event.stat().st_size > before_size
    assert str(before_event).startswith(str(REAL_DATA_ROOT / "replay"))
    assert (store.data_root / "memory" / "tf_episode_memory.jsonl").exists()


def test_bc_stopping_beats_balance_escape():
    """B: deteriorating + stopping evidence promotes even when balance_support high."""
    eng = TimeframeAuctionEngine("M15")
    eng.process(
        _bar(
            0,
            o=100,
            h=101,
            l=99.9,
            c=100.8,
            overrides={"force_phase": PHASE_UP_CONTINUATION_DETERIORATING, "balance_support": 0.2},
        )
    )
    r = eng.process(
        _bar(
            1,
            o=100.8,
            h=100.9,
            l=100.4,
            c=100.5,
            overrides={
                "up_exhaustion_support": 0.7,
                "reaction_strength": 0.4,
                "balance_support": 0.85,
                "up_efficiency": 0.2,
            },
        )
    )
    assert r.episode_phase == PHASE_UP_STOPPING_CANDIDATE
    assert "STOPPING_CANDIDATE_EVIDENCE" in r.reason_codes
    assert "STOPPING_BEFORE_BALANCE_ESCAPE" in r.reason_codes


def test_bc_same_bar_promote_extreme_to_stopping():
    """C: EXTREME with weak efficiency + stopping evidence → STOPPING same bar."""
    eng = TimeframeAuctionEngine("M15")
    eng.process(
        _bar(
            0,
            o=100,
            h=101.5,
            l=99.9,
            c=101.2,
            overrides={
                "force_phase": PHASE_EXTREME_UP_PARTICIPATION,
                "up_efficiency": 0.7,
                "balance_support": 0.2,
            },
        )
    )
    r = eng.process(
        _bar(
            1,
            o=101.2,
            h=101.3,
            l=100.6,
            c=100.7,
            overrides={
                "up_efficiency": 0.15,  # < weak_efficiency 0.28
                "up_exhaustion_support": 0.6,
                "reaction_strength": 0.35,
                "balance_support": 0.8,
                "follow_through": 0.4,
            },
        )
    )
    assert r.episode_phase == PHASE_UP_STOPPING_CANDIDATE
    assert "SAME_BAR_STOPPING_PROMOTE" in r.reason_codes


def test_bc_balance_escape_still_works_without_stopping_evidence():
    """Without stopping evidence, deteriorating + high balance still → TRANSITION."""
    eng = TimeframeAuctionEngine("M15")
    eng.process(
        _bar(
            0,
            o=100,
            h=101,
            l=99.9,
            c=100.8,
            overrides={"force_phase": PHASE_UP_CONTINUATION_DETERIORATING, "balance_support": 0.2},
        )
    )
    r = eng.process(
        _bar(
            1,
            o=100.8,
            h=100.9,
            l=100.5,
            c=100.6,
            overrides={
                "up_exhaustion_support": 0.3,
                "reaction_strength": 0.1,
                "balance_support": 0.7,
                "up_efficiency": 0.2,
            },
        )
    )
    assert r.episode_phase == PHASE_TRANSITION
    assert "BALANCE_SUPPORT_RISING" in r.reason_codes
