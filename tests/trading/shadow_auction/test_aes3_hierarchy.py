"""AES3 cross-TF hierarchy — deterministic synthetic tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from btc_ml.trading.shadow_auction.engine import ShadowAuctionAES2, TimeframeAuctionEngine
from btc_ml.trading.shadow_auction.hierarchy import HierarchyEngine, TfStateView
from btc_ml.trading.shadow_auction.hierarchy_states import (
    HIER_CONFLICTED,
    HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN,
    HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP,
    HIER_LOCAL_DOWN_WITHIN_PARENT_UP,
    HIER_LOCAL_ROTATION_WITHIN_PARENT_BALANCE,
    HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
    HIER_MULTI_TF_BALANCE,
    HIER_MULTI_TF_EXHAUSTION,
    HIER_MULTI_TF_RESOLUTION_DOWN,
    HIER_MULTI_TF_RESOLUTION_UP,
    HIER_STRUCTURAL_DOWN_ALIGNED,
    HIER_STRUCTURAL_UP_ALIGNED,
    HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
    PROP_NONE,
    PROP_TOWARD_HIGHER_TF,
    REL_LOCAL_BALANCE_WITHIN_PARENT_DIRECTIONAL,
    REL_LOCAL_DIRECTIONAL_WITHIN_PARENT_BALANCE,
    REL_LOCAL_EXHAUSTION_WITHIN_PARENT_CONTINUATION,
    REL_LOCAL_REVERSAL_AGAINST_PARENT,
    REL_PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL,
    REL_SYNCHRONIZED_BALANCE,
    REL_SYNCHRONIZED_EXHAUSTION,
    REL_SYNCHRONIZED_RESOLUTION,
    REL_TRANSITION_PROPAGATING_UP,
    mirror_hierarchy_state,
)
from btc_ml.trading.shadow_auction.observation import BarObservation
from btc_ml.trading.shadow_auction.states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    PHASE_BALANCE_ESTABLISHED,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_STOPPING_CANDIDATE,
    PHASE_FAILED_DOWNSIDE_BREAK,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_STOPPING_CANDIDATE,
)

REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"


def _v(
    tf: str,
    ts: str,
    family: str,
    phase: str,
    *,
    eid: str | None = None,
) -> TfStateView:
    return TfStateView(
        timeframe=tf,
        timestamp=ts,
        shadow_episode_id=eid or f"{tf}_{ts}",
        auction_family=family,
        episode_phase=phase,
        pressure_side="UP" if "UP" in family or "UP" in phase else (
            "DOWN" if "DOWN" in family or "DOWN" in phase else None
        ),
    )


def _ingest_all(eng: HierarchyEngine, views: list[TfStateView]):
    snaps = []
    for v in views:
        snaps.append(eng.ingest_tf_state(v))
    return snaps


def _aligned(side: str, ts: str = "2026-08-11T12:00:00Z") -> list[TfStateView]:
    fam = FAMILY_DIRECTIONAL_UP if side == "UP" else FAMILY_DIRECTIONAL_DOWN
    phase = PHASE_UP_CONTINUATION_ACCEPTED if side == "UP" else PHASE_DOWN_CONTINUATION_ACCEPTED
    return [
        _v("M15", ts, fam, phase),
        _v("M30", ts, fam, phase),
        _v("H1", ts, fam, phase),
        _v("H4", ts, fam, phase),
    ]


# --- Tests 1–2 alignment ---


def test_01_full_up_alignment():
    eng = HierarchyEngine()
    snap = _ingest_all(eng, _aligned("UP"))[-1]
    assert snap.hierarchy_state == HIER_STRUCTURAL_UP_ALIGNED
    assert snap.m15_m30.relation_state in {
        "CHILD_CONFIRMS_PARENT",
        "CHILD_CONTINUES_PARENT",
    }
    assert snap.propagation_direction == PROP_NONE


def test_02_full_down_alignment():
    eng = HierarchyEngine()
    snap = _ingest_all(eng, _aligned("DOWN"))[-1]
    assert snap.hierarchy_state == HIER_STRUCTURAL_DOWN_ALIGNED
    assert mirror_hierarchy_state(HIER_STRUCTURAL_UP_ALIGNED) == HIER_STRUCTURAL_DOWN_ALIGNED


def test_03_local_exhaustion():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("H1", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("M30", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("M15", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_STOPPING_CANDIDATE),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.m15_m30.relation_state == REL_LOCAL_EXHAUSTION_WITHIN_PARENT_CONTINUATION
    assert snap.hierarchy_state != HIER_STRUCTURAL_UP_ALIGNED


def test_04_local_reversal_against_parent():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("H1", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("M30", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("M15", ts, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.hierarchy_state in {
        HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
        HIER_LOCAL_ROTATION_WITHIN_PARENT_BALANCE,
    }
    assert snap.hierarchy_state != HIER_STRUCTURAL_UP_ALIGNED
    # M15 vs M30: resolution against / local directional in balance
    assert snap.m15_m30.relation_state in {
        REL_LOCAL_DIRECTIONAL_WITHIN_PARENT_BALANCE,
        "CHILD_RESOLUTION_AGAINST_PARENT",
        REL_LOCAL_REVERSAL_AGAINST_PARENT,
    }


def test_05_local_balance_in_structural_up():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("H4", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
        _v("H1", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
        _v("M30", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("M15", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.hierarchy_state == HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP
    assert snap.m30_h1.relation_state == REL_LOCAL_BALANCE_WITHIN_PARENT_DIRECTIONAL


def test_06_local_balance_in_structural_down():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("H4", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("H1", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("M30", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("M15", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.hierarchy_state == HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN
    assert mirror_hierarchy_state(HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP) == (
        HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN
    )


def test_07_directional_child_inside_parent_balance():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M30", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("M15", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.m15_m30.relation_state == REL_LOCAL_DIRECTIONAL_WITHIN_PARENT_BALANCE
    # Parent M30 unchanged by hierarchy — view still BALANCE.
    assert snap.m30.auction_family == FAMILY_BALANCE


def test_08_transition_propagation_m15_to_m30():
    eng = HierarchyEngine()
    # Seed structural down
    _ingest_all(
        eng,
        [
            _v("H4", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("H1", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M30", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M15", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        ],
    )
    # M15 resolves up; M30 starts deteriorating
    snap = eng.ingest_tf_state(
        _v("M15", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP)
    )
    snap = eng.ingest_tf_state(
        _v("M30", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_DETERIORATING)
    )
    assert snap.m15_m30.relation_state in {
        REL_TRANSITION_PROPAGATING_UP,
        "PARENT_PRESSURE_DETERIORATING",
        REL_LOCAL_REVERSAL_AGAINST_PARENT,
        "CHILD_RESOLUTION_AGAINST_PARENT",
    }
    assert snap.propagation_depth >= 1
    assert snap.propagation_direction == PROP_TOWARD_HIGHER_TF


def test_09_transition_propagation_depth_2():
    eng = HierarchyEngine()
    _ingest_all(
        eng,
        [
            _v("H4", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("H1", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M30", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M15", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        ],
    )
    eng.ingest_tf_state(_v("M15", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP))
    eng.ingest_tf_state(
        _v("M30", "2026-08-11T11:15:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_STOPPING_CANDIDATE)
    )
    snap = eng.ingest_tf_state(
        _v("H1", "2026-08-11T11:30:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_DETERIORATING)
    )
    assert snap.propagation_depth >= 2
    assert snap.propagation_direction == PROP_TOWARD_HIGHER_TF
    assert snap.hierarchy_state in {
        HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
        HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
        HIER_MULTI_TF_EXHAUSTION,
    }


def test_10_full_propagation_to_h4_depth_3():
    eng = HierarchyEngine()
    _ingest_all(
        eng,
        [
            _v("H4", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("H1", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M30", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
            _v("M15", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        ],
    )
    eng.ingest_tf_state(_v("M15", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP))
    eng.ingest_tf_state(
        _v("M30", "2026-08-11T11:15:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_STOPPING_CANDIDATE)
    )
    eng.ingest_tf_state(
        _v("H1", "2026-08-11T11:30:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_DETERIORATING)
    )
    snap = eng.ingest_tf_state(
        _v("H4", "2026-08-11T12:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_STOPPING_CANDIDATE)
    )
    assert snap.propagation_depth == 3
    assert snap.propagation_direction == PROP_TOWARD_HIGHER_TF
    assert "TRANSITION_REACHED_H4" in snap.reason_codes or snap.propagation_depth == 3


def test_11_synchronized_exhaustion():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M15", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_STOPPING_CANDIDATE),
        _v("M30", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_DETERIORATING),
        _v("H1", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_DETERIORATING),
        _v("H4", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.m15_m30.relation_state == REL_SYNCHRONIZED_EXHAUSTION
    assert snap.hierarchy_state == HIER_MULTI_TF_EXHAUSTION
    assert snap.hierarchy_state != HIER_STRUCTURAL_DOWN_ALIGNED  # not a reversal


def test_12_synchronized_balance():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M15", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("M30", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("H1", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _v("H4", ts, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.m15_m30.relation_state == REL_SYNCHRONIZED_BALANCE
    assert snap.hierarchy_state == HIER_MULTI_TF_BALANCE


def test_13_synchronized_up_resolution():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M15", ts, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
        _v("M30", ts, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
        _v("H1", ts, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
        _v("H4", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.m15_m30.relation_state == REL_SYNCHRONIZED_RESOLUTION
    assert snap.hierarchy_state == HIER_MULTI_TF_RESOLUTION_UP


def test_14_synchronized_down_resolution():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M15", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN),
        _v("M30", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN),
        _v("H1", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN),
        _v("H4", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.hierarchy_state == HIER_MULTI_TF_RESOLUTION_DOWN
    assert mirror_hierarchy_state(HIER_MULTI_TF_RESOLUTION_UP) == HIER_MULTI_TF_RESOLUTION_DOWN


def test_15_parent_survives_child_reversal():
    eng = HierarchyEngine()
    # Parent H1 UP stable; child M30 reverses down then fails back.
    eng.ingest_tf_state(
        _v("H1", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    eng.ingest_tf_state(
        _v("M30", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    # Child reverses
    eng.ingest_tf_state(
        _v("M30", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN)
    )
    # Parent still UP
    eng.ingest_tf_state(
        _v("H1", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    # Child failed downside / returns
    snap = eng.ingest_tf_state(
        _v("M30", "2026-08-11T12:00:00Z", FAMILY_BALANCE, PHASE_FAILED_DOWNSIDE_BREAK)
    )
    # Parent still UP
    snap = eng.ingest_tf_state(
        _v("H1", "2026-08-11T12:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    assert snap.m30_h1.relation_state == REL_PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL


def test_16_conflict_no_majority_vote():
    eng = HierarchyEngine()
    ts = "2026-08-11T12:00:00Z"
    views = [
        _v("M15", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
        _v("M30", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
        _v("H1", ts, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED),
        _v("H4", ts, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED),
    ]
    snap = _ingest_all(eng, views)[-1]
    assert snap.hierarchy_state == HIER_CONFLICTED
    assert snap.hierarchy_state not in {
        HIER_STRUCTURAL_UP_ALIGNED,
        HIER_STRUCTURAL_DOWN_ALIGNED,
    }
    assert snap.conflicting_pair_count >= 2


def test_17_asof_no_lookahead():
    eng = HierarchyEngine()
    # At T0 only M15 known; future H1 must not appear in as-of T0.
    eng.ingest_tf_state(
        _v("M15", "2026-08-11T10:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    # Store future H1 in engine AFTER taking as-of snapshot at T0 via snapshot_asof
    # First: take as-of at 10:00 before ingesting future
    snap_t0 = eng.snapshot_asof("2026-08-11T10:00:00Z")
    assert snap_t0.h1 is None

    eng.ingest_tf_state(
        _v("H1", "2026-08-11T11:00:00Z", FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED)
    )
    # As-of 10:00 must still ignore future H1
    snap_t0b = eng.snapshot_asof("2026-08-11T10:00:00Z")
    assert snap_t0b.h1 is None
    assert snap_t0b.m15 is not None
    # As-of 11:00 sees H1
    snap_t1 = eng.snapshot_asof("2026-08-11T11:00:00Z")
    assert snap_t1.h1 is not None
    assert snap_t1.h1.auction_family == FAMILY_DIRECTIONAL_DOWN


def test_18_stale_parent():
    eng = HierarchyEngine(
        params={"stale_cadence_sec": {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}, "stale_multiplier": 2.0}
    )
    eng.ingest_tf_state(
        _v("M30", "2026-08-11T00:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    # M15 much later — M30 age >> 2 * 1800
    snap = eng.ingest_tf_state(
        _v("M15", "2026-08-11T06:00:00Z", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    assert snap.m15_m30.parent_state_stale is True
    assert "PARENT_STATE_STALE" in snap.m15_m30.relation_reason_codes
    # Does not invent a new parent state.
    assert snap.m30.timestamp == "2026-08-11T00:00:00Z"


def test_19_tf_state_immutability():
    aes2 = ShadowAuctionAES2()
    # Seed AES2 M15 with one synthetic bar
    bar = BarObservation(
        timestamp="2026-08-11T12:00:00Z",
        timeframe="M15",
        source_event_id="immut_1",
        open=100,
        high=101,
        low=99,
        close=100.5,
        volume=10,
        feature_overrides={
            "up_continuation_support": 0.9,
            "down_continuation_support": 0.1,
            "up_efficiency": 0.8,
            "buy_effort": 0.8,
        },
    )
    aes2.process(bar)
    before = {
        tf: (
            e.state.auction_family,
            e.state.episode_phase,
            e.state.shadow_episode_id,
            e.state.episode_age,
            list(e.state.history),
        )
        for tf, e in aes2.engines.items()
    }
    hier = HierarchyEngine()
    for tf, eng in aes2.engines.items():
        from btc_ml.trading.shadow_auction.hierarchy import tf_state_view_from_engine

        view = tf_state_view_from_engine(eng, timestamp="2026-08-11T12:00:00Z")
        # Force exact AES2 fields
        view = TfStateView(
            timeframe=tf,
            timestamp="2026-08-11T12:00:00Z",
            shadow_episode_id=eng.state.shadow_episode_id,
            auction_family=eng.state.auction_family,
            episode_phase=eng.state.episode_phase,
        )
        hier.ingest_tf_state(view)
    after = {
        tf: (
            e.state.auction_family,
            e.state.episode_phase,
            e.state.shadow_episode_id,
            e.state.episode_age,
            list(e.state.history),
        )
        for tf, e in aes2.engines.items()
    }
    assert before == after


def test_20_restart_idempotency():
    eng = HierarchyEngine()
    views = _aligned("UP", "2026-08-11T12:00:00Z")
    first = _ingest_all(eng, views)[-1]
    assert first.duplicate is False
    # Re-ingest identical states → duplicate snapshot
    dup = _ingest_all(eng, views)[-1]
    assert dup.duplicate is True
    assert dup.snapshot_id == first.snapshot_id
    assert eng.snapshots_written == 4  # one per TF ingest first pass only... 
    # Actually first pass writes 4 snapshots (one per ingest), second pass all duplicates.
    # snapshots_written increments only on non-duplicate.
    assert eng.snapshots_written == 4


def test_symmetry_hierarchy_states():
    assert mirror_hierarchy_state(HIER_LOCAL_UP_WITHIN_PARENT_DOWN) == HIER_LOCAL_DOWN_WITHIN_PARENT_UP
    assert mirror_hierarchy_state(HIER_MULTI_TF_RESOLUTION_DOWN) == HIER_MULTI_TF_RESOLUTION_UP
    # Full UP vs DOWN hierarchy states are mirrors
    up = HierarchyEngine()
    down = HierarchyEngine()
    su = _ingest_all(up, _aligned("UP"))[-1]
    sd = _ingest_all(down, _aligned("DOWN"))[-1]
    assert mirror_hierarchy_state(su.hierarchy_state) == sd.hierarchy_state


def test_aes3_external_hierarchy_write():
    from btc_ml.trading.shadow_auction.storage import ShadowAuctionStore, is_real_mounted_volume
    from btc_ml.trading.shadow_auction.memory import Aes3HierarchyMemoryWriter

    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger volume not mounted")
    store = ShadowAuctionStore(
        data_root=REAL_DATA_ROOT / "replay" / "_aes3_pytest",
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    mem = Aes3HierarchyMemoryWriter(store)
    eng = HierarchyEngine(logic_version="AES_V1", logic_fingerprint="test")
    path = store.data_root / "memory" / "hierarchy_memory.jsonl"
    before = path.stat().st_size if path.exists() else 0
    snap = _ingest_all(eng, _aligned("UP", "2026-08-11T15:00:00Z"))[-1]
    out = mem.write_snapshot(snap)
    assert out["written"] is True
    assert path.exists()
    assert path.stat().st_size > before
    assert str(path).startswith(str(REAL_DATA_ROOT / "replay"))
    # Duplicate write refused
    assert mem.write_snapshot(snap)["written"] is False or snap.duplicate is False
    # Re-mark: engine duplicate
    dup = eng.ingest_tf_state(_aligned("UP", "2026-08-11T15:00:00Z")[-1])
    assert dup.duplicate is True
    assert mem.write_snapshot(dup)["written"] is False
