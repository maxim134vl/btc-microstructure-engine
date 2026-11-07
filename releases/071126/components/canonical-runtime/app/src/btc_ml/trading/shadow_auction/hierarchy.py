"""AES3 Cross-Timeframe Hierarchy Engine.

Reads AES2 TfStateView snapshots only. Never mutates AES2 engines or states.
Does not produce LONG/SHORT or trading decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .hierarchy_states import (
    CONFLICT_MULTI,
    CONFLICT_NONE,
    CONFLICT_PAIR,
    CONFLICT_STALE,
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
    HIER_UNRESOLVED,
    LVS_LOCAL_AGAINST_PARENT,
    LVS_LOCAL_ONLY,
    LVS_LOCAL_WITH_PARENT_SUPPORT,
    LVS_PROPAGATING,
    LVS_STRUCTURAL_MULTI_TF,
    LVS_UNRESOLVED,
    PAIR_CHAIN,
    PROP_MIXED,
    PROP_NONE,
    PROP_TOWARD_HIGHER_TF,
    PROP_TOWARD_LOWER_TF,
    REL_CHILD_CONFIRMS_PARENT,
    REL_CHILD_CONTINUES_PARENT,
    REL_CHILD_RESOLUTION_AGAINST_PARENT,
    REL_CHILD_RESOLUTION_ALIGNED_WITH_PARENT,
    REL_COUNTERTREND_REACTION_ONLY,
    REL_LOCAL_BALANCE_WITHIN_PARENT_DIRECTIONAL,
    REL_LOCAL_DIRECTIONAL_WITHIN_PARENT_BALANCE,
    REL_LOCAL_EXHAUSTION_WITHIN_PARENT_CONTINUATION,
    REL_LOCAL_REVERSAL_AGAINST_PARENT,
    REL_PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL,
    REL_PARENT_PRESSURE_DETERIORATING,
    REL_SYNCHRONIZED_BALANCE,
    REL_SYNCHRONIZED_EXHAUSTION,
    REL_SYNCHRONIZED_RESOLUTION,
    REL_TRANSITION_PROPAGATING_UP,
    REL_UNRESOLVED,
    REL_UNRESOLVED_CONFLICT,
    TF_SENIORITY,
    merge_aes3_params,
)
from .states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    FAMILY_UNRESOLVED,
    PHASE_ACCEPTANCE_ABOVE,
    PHASE_ACCEPTANCE_BELOW,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_PRESSURE_ACTIVE,
    PHASE_DOWN_PRESSURE_EXPANDING,
    PHASE_DOWN_STOPPING_CANDIDATE,
    PHASE_EXTREME_DOWN_PARTICIPATION,
    PHASE_EXTREME_UP_PARTICIPATION,
    PHASE_FAILED_DOWNSIDE_BREAK,
    PHASE_FAILED_UPSIDE_BREAK,
    PHASE_POST_DOWN_STRESS_REACTION,
    PHASE_POST_UP_STRESS_REACTION,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
    PHASE_TRANSITION,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_PRESSURE_ACTIVE,
    PHASE_UP_PRESSURE_EXPANDING,
    PHASE_UP_STOPPING_CANDIDATE,
)


UP_CONTINUATION = frozenset(
    {
        PHASE_UP_PRESSURE_ACTIVE,
        PHASE_UP_PRESSURE_EXPANDING,
        PHASE_EXTREME_UP_PARTICIPATION,
        PHASE_UP_CONTINUATION_ACCEPTED,
    }
)
DOWN_CONTINUATION = frozenset(
    {
        PHASE_DOWN_PRESSURE_ACTIVE,
        PHASE_DOWN_PRESSURE_EXPANDING,
        PHASE_EXTREME_DOWN_PARTICIPATION,
        PHASE_DOWN_CONTINUATION_ACCEPTED,
    }
)
UP_EXHAUSTION = frozenset(
    {
        PHASE_UP_CONTINUATION_DETERIORATING,
        PHASE_UP_STOPPING_CANDIDATE,
        PHASE_POST_UP_STRESS_REACTION,
    }
)
DOWN_EXHAUSTION = frozenset(
    {
        PHASE_DOWN_CONTINUATION_DETERIORATING,
        PHASE_DOWN_STOPPING_CANDIDATE,
        PHASE_POST_DOWN_STRESS_REACTION,
    }
)
UP_RESOLUTION = frozenset({PHASE_RESOLUTION_UP, PHASE_ACCEPTANCE_ABOVE})
DOWN_RESOLUTION = frozenset({PHASE_RESOLUTION_DOWN, PHASE_ACCEPTANCE_BELOW})
BALANCE_LIKE = frozenset(
    {
        FAMILY_BALANCE,
        FAMILY_TRANSITION,
    }
)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_sec(snapshot_ts: str, state_ts: str | None) -> float | None:
    a = _parse_ts(snapshot_ts)
    b = _parse_ts(state_ts)
    if a is None or b is None:
        return None
    return max(0.0, (a - b).total_seconds())


@dataclass(frozen=True)
class TfStateView:
    """Immutable read-only view of one AES2 TF state at a known timestamp.

    Hierarchy never writes back into AES2 from this object.
    """

    timeframe: str
    timestamp: str
    shadow_episode_id: str | None
    auction_family: str
    episode_phase: str
    pressure_side: str | None = None
    resolution_side: str | None = None

    def fingerprint(self) -> str:
        raw = (
            f"{self.timeframe}|{self.timestamp}|{self.shadow_episode_id}|"
            f"{self.auction_family}|{self.episode_phase}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class PairRelation:
    child_tf: str
    parent_tf: str
    child_episode_id: str | None
    parent_episode_id: str | None
    child_family: str
    parent_family: str
    child_phase: str
    parent_phase: str
    relation_state: str
    relation_reason_codes: list[str] = field(default_factory=list)
    parent_state_stale: bool = False
    child_age_sec: float | None = None
    parent_age_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_tf": self.child_tf,
            "parent_tf": self.parent_tf,
            "child_episode_id": self.child_episode_id,
            "parent_episode_id": self.parent_episode_id,
            "child_family": self.child_family,
            "parent_family": self.parent_family,
            "child_phase": self.child_phase,
            "parent_phase": self.parent_phase,
            "relation_state": self.relation_state,
            "relation_reason_codes": list(self.relation_reason_codes),
            "parent_state_stale": self.parent_state_stale,
            "child_age_sec": self.child_age_sec,
            "parent_age_sec": self.parent_age_sec,
        }


@dataclass
class HierarchySnapshot:
    timestamp: str
    m15: TfStateView | None
    m30: TfStateView | None
    h1: TfStateView | None
    h4: TfStateView | None
    m15_m30: PairRelation
    m30_h1: PairRelation
    h1_h4: PairRelation
    hierarchy_state: str
    propagation_direction: str
    propagation_depth: int
    local_vs_structural_state: str
    conflict_state: str
    reason_codes: list[str]
    aligned_pair_count: int
    conflicting_pair_count: int
    m15_age_sec: float | None
    m30_age_sec: float | None
    h1_age_sec: float | None
    h4_age_sec: float | None
    source_watermark: str
    logic_version: str
    logic_fingerprint: str
    snapshot_id: str
    duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        def tf_fields(prefix: str, view: TfStateView | None) -> dict[str, Any]:
            if view is None:
                return {
                    f"{prefix}_episode_id": None,
                    f"{prefix}_family": FAMILY_UNRESOLVED,
                    f"{prefix}_phase": "UNRESOLVED",
                    f"{prefix}_timestamp": None,
                }
            return {
                f"{prefix}_episode_id": view.shadow_episode_id,
                f"{prefix}_family": view.auction_family,
                f"{prefix}_phase": view.episode_phase,
                f"{prefix}_timestamp": view.timestamp,
            }

        out: dict[str, Any] = {"timestamp": self.timestamp}
        out.update(tf_fields("m15", self.m15))
        out.update(tf_fields("m30", self.m30))
        out.update(tf_fields("h1", self.h1))
        out.update(tf_fields("h4", self.h4))
        out.update(
            {
                "m15_m30_relation": self.m15_m30.relation_state,
                "m30_h1_relation": self.m30_h1.relation_state,
                "h1_h4_relation": self.h1_h4.relation_state,
                "m15_m30": self.m15_m30.to_dict(),
                "m30_h1": self.m30_h1.to_dict(),
                "h1_h4": self.h1_h4.to_dict(),
                "hierarchy_state": self.hierarchy_state,
                "propagation_direction": self.propagation_direction,
                "propagation_depth": self.propagation_depth,
                "local_vs_structural_state": self.local_vs_structural_state,
                "conflict_state": self.conflict_state,
                "reason_codes": list(self.reason_codes),
                "aligned_pair_count": self.aligned_pair_count,
                "conflicting_pair_count": self.conflicting_pair_count,
                "m15_age_sec": self.m15_age_sec,
                "m30_age_sec": self.m30_age_sec,
                "h1_age_sec": self.h1_age_sec,
                "h4_age_sec": self.h4_age_sec,
                "source_watermark": self.source_watermark,
                "logic_version": self.logic_version,
                "logic_fingerprint": self.logic_fingerprint,
                "snapshot_id": self.snapshot_id,
            }
        )
        return out


def tf_state_view_from_engine(engine: Any, *, timestamp: str | None = None) -> TfStateView:
    """Build a read-only view from an AES2 TimeframeAuctionEngine (no mutation)."""
    st = engine.state
    return TfStateView(
        timeframe=str(engine.timeframe).upper(),
        timestamp=timestamp or (st.history[-1]["timestamp"] if st.history else "1970-01-01T00:00:00Z"),
        shadow_episode_id=st.shadow_episode_id,
        auction_family=st.auction_family,
        episode_phase=st.episode_phase,
        pressure_side=st.pressure_side,
        resolution_side=st.resolution_side,
    )


def _dir_of(family: str, phase: str) -> str | None:
    if family == FAMILY_DIRECTIONAL_UP or phase in UP_CONTINUATION | UP_EXHAUSTION | UP_RESOLUTION:
        return "UP"
    if family == FAMILY_DIRECTIONAL_DOWN or phase in DOWN_CONTINUATION | DOWN_EXHAUSTION | DOWN_RESOLUTION:
        return "DOWN"
    return None


def _is_continuation(phase: str) -> bool:
    return phase in UP_CONTINUATION or phase in DOWN_CONTINUATION


def _is_exhaustion(phase: str) -> bool:
    return phase in UP_EXHAUSTION or phase in DOWN_EXHAUSTION


def _is_resolution(phase: str) -> bool:
    return phase in UP_RESOLUTION or phase in DOWN_RESOLUTION


def _is_balance_family(family: str) -> bool:
    return family in {FAMILY_BALANCE, FAMILY_TRANSITION}


def _resolution_side(phase: str, family: str) -> str | None:
    if phase in UP_RESOLUTION or family == FAMILY_DIRECTIONAL_UP and phase in UP_CONTINUATION:
        if phase in UP_RESOLUTION:
            return "UP"
    if phase in DOWN_RESOLUTION:
        return "DOWN"
    if phase in UP_RESOLUTION:
        return "UP"
    return None


class HierarchyEngine:
    """Incremental as-of hierarchy interpreter over AES2 TfStateView inputs."""

    def __init__(
        self,
        *,
        params: Mapping[str, Any] | None = None,
        logic_version: str = "AES_V1",
        logic_fingerprint: str = "",
    ) -> None:
        self.params = merge_aes3_params({"aes3": dict(params or {})})
        self.logic_version = logic_version
        self.logic_fingerprint = logic_fingerprint
        self._latest: dict[str, TfStateView] = {}
        self._seen_snapshot_ids: set[str] = set()
        self._pair_history: dict[str, list[str]] = {f"{c}_{p}": [] for c, p in PAIR_CHAIN}
        # Track child reversal episodes for parent-survival detection.
        self._child_reversal_active: dict[str, str | None] = {f"{c}_{p}": None for c, p in PAIR_CHAIN}
        self._parent_held_during_child_reversal: dict[str, bool] = {
            f"{c}_{p}": False for c, p in PAIR_CHAIN
        }
        self._survival_latched: dict[str, bool] = {f"{c}_{p}": False for c, p in PAIR_CHAIN}
        self.snapshots_written = 0
        self.last_snapshot: HierarchySnapshot | None = None
        self.last_hierarchy_timestamp: str | None = None

    def reset(self) -> None:
        self._latest.clear()
        self._seen_snapshot_ids.clear()
        for k in self._pair_history:
            self._pair_history[k] = []
        for k in self._child_reversal_active:
            self._child_reversal_active[k] = None
            self._parent_held_during_child_reversal[k] = False
            self._survival_latched[k] = False
        self.snapshots_written = 0
        self.last_snapshot = None
        self.last_hierarchy_timestamp = None

    def ingest_tf_state(self, view: TfStateView) -> HierarchySnapshot:
        """Update as-of store for one TF and emit immutable hierarchy snapshot at view.timestamp.

        Only states with timestamp <= view.timestamp are used (as-of / no-lookahead).
        """
        tf = view.timeframe.upper()
        if tf not in TF_SENIORITY:
            raise ValueError(f"unsupported TF for hierarchy: {tf}")

        # Reject future leakage into store: only accept this view; never pull later TF states.
        prev = self._latest.get(tf)
        if prev is not None:
            prev_ts = _parse_ts(prev.timestamp)
            new_ts = _parse_ts(view.timestamp)
            if prev_ts and new_ts and new_ts < prev_ts:
                # Out-of-order: keep newer-as-of already stored; still snapshot with current as-of set.
                pass
            else:
                self._latest[tf] = view
        else:
            self._latest[tf] = view

        return self.snapshot_asof(view.timestamp, trigger_tf=tf)

    def snapshot_asof(self, timestamp: str, *, trigger_tf: str | None = None) -> HierarchySnapshot:
        """Build hierarchy using only TF states with state.timestamp <= timestamp."""
        asof = {
            tf: v
            for tf, v in self._latest.items()
            if (_parse_ts(v.timestamp) is not None and _parse_ts(timestamp) is not None)
            and _parse_ts(v.timestamp) <= _parse_ts(timestamp)  # type: ignore[operator]
        }
        # Defensive: drop any accidental future.
        for tf, v in list(asof.items()):
            vt = _parse_ts(v.timestamp)
            tt = _parse_ts(timestamp)
            if vt is None or tt is None or vt > tt:
                asof.pop(tf, None)

        m15 = asof.get("M15")
        m30 = asof.get("M30")
        h1 = asof.get("H1")
        h4 = asof.get("H4")

        pairs = []
        for child_tf, parent_tf in PAIR_CHAIN:
            pair = self._classify_pair(
                timestamp=timestamp,
                child=asof.get(child_tf),
                parent=asof.get(parent_tf),
                child_tf=child_tf,
                parent_tf=parent_tf,
            )
            key = f"{child_tf}_{parent_tf}"
            hist = self._pair_history[key]
            hist.append(pair.relation_state)
            max_h = int(self.params.get("propagation_history") or 16)
            self._pair_history[key] = hist[-max_h:]
            pairs.append(pair)

        m15_m30, m30_h1, h1_h4 = pairs
        prop_dir, prop_depth, prop_reasons = self._propagation(pairs)
        hier, lvs, conflict, reasons = self._hierarchy_state(
            m15=m15, m30=m30, h1=h1, h4=h4, pairs=pairs, prop_depth=prop_depth
        )
        reasons = list(reasons) + list(prop_reasons)

        ages = {
            "m15": _age_sec(timestamp, m15.timestamp if m15 else None),
            "m30": _age_sec(timestamp, m30.timestamp if m30 else None),
            "h1": _age_sec(timestamp, h1.timestamp if h1 else None),
            "h4": _age_sec(timestamp, h4.timestamp if h4 else None),
        }
        aligned = sum(
            1
            for p in pairs
            if p.relation_state
            in {
                REL_CHILD_CONFIRMS_PARENT,
                REL_CHILD_CONTINUES_PARENT,
                REL_CHILD_RESOLUTION_ALIGNED_WITH_PARENT,
                REL_SYNCHRONIZED_BALANCE,
                REL_SYNCHRONIZED_EXHAUSTION,
                REL_SYNCHRONIZED_RESOLUTION,
            }
        )
        conflicting = sum(
            1
            for p in pairs
            if p.relation_state
            in {
                REL_UNRESOLVED_CONFLICT,
                REL_LOCAL_REVERSAL_AGAINST_PARENT,
                REL_CHILD_RESOLUTION_AGAINST_PARENT,
            }
        )

        watermark = "|".join(
            [
                m15.fingerprint() if m15 else "-",
                m30.fingerprint() if m30 else "-",
                h1.fingerprint() if h1 else "-",
                h4.fingerprint() if h4 else "-",
            ]
        )
        snap_raw = f"{timestamp}|{watermark}|{hier}|{m15_m30.relation_state}|{m30_h1.relation_state}|{h1_h4.relation_state}"
        snapshot_id = "HIER_" + hashlib.sha1(snap_raw.encode("utf-8")).hexdigest()[:16]
        duplicate = snapshot_id in self._seen_snapshot_ids
        if not duplicate:
            self._seen_snapshot_ids.add(snapshot_id)
            if len(self._seen_snapshot_ids) > 5000:
                self._seen_snapshot_ids = set(list(self._seen_snapshot_ids)[-2500:])
            self.snapshots_written += 1

        snap = HierarchySnapshot(
            timestamp=timestamp,
            m15=m15,
            m30=m30,
            h1=h1,
            h4=h4,
            m15_m30=m15_m30,
            m30_h1=m30_h1,
            h1_h4=h1_h4,
            hierarchy_state=hier,
            propagation_direction=prop_dir,
            propagation_depth=prop_depth,
            local_vs_structural_state=lvs,
            conflict_state=conflict,
            reason_codes=reasons,
            aligned_pair_count=aligned,
            conflicting_pair_count=conflicting,
            m15_age_sec=ages["m15"],
            m30_age_sec=ages["m30"],
            h1_age_sec=ages["h1"],
            h4_age_sec=ages["h4"],
            source_watermark=watermark,
            logic_version=self.logic_version,
            logic_fingerprint=self.logic_fingerprint,
            snapshot_id=snapshot_id,
            duplicate=duplicate,
        )
        if not duplicate:
            self.last_snapshot = snap
            self.last_hierarchy_timestamp = timestamp
        return snap

    def health_fields(self) -> dict[str, Any]:
        snap = self.last_snapshot
        if snap is None:
            return {
                "hierarchy_state": HIER_UNRESOLVED,
                "m15_m30_relation": REL_UNRESOLVED,
                "m30_h1_relation": REL_UNRESOLVED,
                "h1_h4_relation": REL_UNRESOLVED,
                "propagation_direction": PROP_NONE,
                "propagation_depth": 0,
                "local_vs_structural_state": LVS_UNRESOLVED,
                "conflict_state": CONFLICT_NONE,
                "hierarchy_snapshots_written": self.snapshots_written,
                "last_hierarchy_timestamp": self.last_hierarchy_timestamp,
            }
        return {
            "hierarchy_state": snap.hierarchy_state,
            "m15_m30_relation": snap.m15_m30.relation_state,
            "m30_h1_relation": snap.m30_h1.relation_state,
            "h1_h4_relation": snap.h1_h4.relation_state,
            "propagation_direction": snap.propagation_direction,
            "propagation_depth": snap.propagation_depth,
            "local_vs_structural_state": snap.local_vs_structural_state,
            "conflict_state": snap.conflict_state,
            "hierarchy_snapshots_written": self.snapshots_written,
            "last_hierarchy_timestamp": self.last_hierarchy_timestamp,
        }

    def _stale(self, parent_tf: str, parent_age: float | None) -> bool:
        if parent_age is None:
            return False
        cadence = float(self.params["stale_cadence_sec"].get(parent_tf, 3600))
        mult = float(self.params.get("stale_multiplier") or 2.0)
        return parent_age > cadence * mult

    def _classify_pair(
        self,
        *,
        timestamp: str,
        child: TfStateView | None,
        parent: TfStateView | None,
        child_tf: str,
        parent_tf: str,
    ) -> PairRelation:
        reasons: list[str] = []
        child_age = _age_sec(timestamp, child.timestamp if child else None)
        parent_age = _age_sec(timestamp, parent.timestamp if parent else None)
        stale = self._stale(parent_tf, parent_age)
        if stale:
            reasons.append("PARENT_STATE_STALE")

        if child is None or parent is None:
            return PairRelation(
                child_tf=child_tf,
                parent_tf=parent_tf,
                child_episode_id=None if child is None else child.shadow_episode_id,
                parent_episode_id=None if parent is None else parent.shadow_episode_id,
                child_family=FAMILY_UNRESOLVED if child is None else child.auction_family,
                parent_family=FAMILY_UNRESOLVED if parent is None else parent.auction_family,
                child_phase="UNRESOLVED" if child is None else child.episode_phase,
                parent_phase="UNRESOLVED" if parent is None else parent.episode_phase,
                relation_state=REL_UNRESOLVED,
                relation_reason_codes=reasons or ["MISSING_TF_STATE"],
                parent_state_stale=stale,
                child_age_sec=child_age,
                parent_age_sec=parent_age,
            )

        cf, pf = child.auction_family, parent.auction_family
        cp, pp = child.episode_phase, parent.episode_phase
        cd, pd = _dir_of(cf, cp), _dir_of(pf, pp)
        key = f"{child_tf}_{parent_tf}"

        # Track parent survival across child reversal cycles.
        survival_hit = False
        if pd and cd and cd != pd and (
            _is_resolution(cp) or cf in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}
        ):
            self._child_reversal_active[key] = cd
            self._parent_held_during_child_reversal[key] = True
            self._survival_latched[key] = False
        elif self._child_reversal_active[key] is not None or self._survival_latched[key]:
            recovered = (
                (cd == pd and pd is not None)
                or cp in {PHASE_FAILED_UPSIDE_BREAK, PHASE_FAILED_DOWNSIDE_BREAK}
                or (_is_balance_family(cf) and pd is not None)
            )
            parent_holds = pd is not None and _dir_of(pf, pp) == pd
            child_again_opposes = bool(
                cd and pd and cd != pd and cf in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}
            )
            if (
                (recovered or self._survival_latched[key])
                and (self._parent_held_during_child_reversal[key] or self._survival_latched[key])
                and parent_holds
                and not child_again_opposes
            ):
                survival_hit = True
                self._survival_latched[key] = True
                reasons.append("PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL")
            if recovered:
                self._child_reversal_active[key] = None
                self._parent_held_during_child_reversal[key] = False
            if cd == pd and _is_continuation(cp):
                self._survival_latched[key] = False
                survival_hit = False

        if survival_hit:
            return self._pair(
                child, parent, child_tf, parent_tf, REL_PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL,
                reasons, stale, child_age, parent_age,
            )

        # Synchronized exhaustion / balance / resolution (adjacent).
        if _is_exhaustion(cp) and _is_exhaustion(pp) and cd == pd and cd is not None:
            reasons += ["MULTIPLE_ADJACENT_TF_EXHAUSTION", "CHILD_EXHAUSTION_PARENT_CONTINUES"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_SYNCHRONIZED_EXHAUSTION,
                reasons, stale, child_age, parent_age,
            )
        if _is_balance_family(cf) and _is_balance_family(pf):
            reasons.append("MULTIPLE_ADJACENT_TF_BALANCE")
            return self._pair(
                child, parent, child_tf, parent_tf, REL_SYNCHRONIZED_BALANCE,
                reasons, stale, child_age, parent_age,
            )
        if _is_resolution(cp) and _is_resolution(pp):
            if (cp in UP_RESOLUTION and pp in UP_RESOLUTION) or (
                cp in DOWN_RESOLUTION and pp in DOWN_RESOLUTION
            ):
                reasons.append("MULTIPLE_ADJACENT_TF_RESOLUTION")
                return self._pair(
                    child, parent, child_tf, parent_tf, REL_SYNCHRONIZED_RESOLUTION,
                    reasons, stale, child_age, parent_age,
                )

        # Local exhaustion within parent continuation.
        if _is_exhaustion(cp) and _is_continuation(pp) and cd == pd and cd is not None:
            reasons += ["CHILD_EXHAUSTION_PARENT_CONTINUES"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_LOCAL_EXHAUSTION_WITHIN_PARENT_CONTINUATION,
                reasons, stale, child_age, parent_age,
            )

        # Parent deteriorating while child already reversed / resolved against.
        if _is_exhaustion(pp) and cd and pd and cd != pd:
            reasons += ["PARENT_DETERIORATION_AFTER_CHILD_REVERSAL"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_PARENT_PRESSURE_DETERIORATING,
                reasons, stale, child_age, parent_age,
            )

        # Transition propagating: child resolved/directional against, parent now exhausting/balance.
        if (
            cd
            and pd
            and cd != pd
            and (
                _is_resolution(cp)
                or cf in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}
            )
            and (_is_exhaustion(pp) or _is_balance_family(pf) or pp == PHASE_TRANSITION)
        ):
            reasons += ["TRANSITION_PROPAGATING_UP", f"TRANSITION_REACHED_{parent_tf}"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_TRANSITION_PROPAGATING_UP,
                reasons, stale, child_age, parent_age,
            )

        # Child resolution vs parent.
        if _is_resolution(cp) and pd is not None:
            rside = "UP" if cp in UP_RESOLUTION else "DOWN"
            if rside == pd:
                reasons += ["CHILD_PARENT_DIRECTION_MATCH"]
                return self._pair(
                    child, parent, child_tf, parent_tf, REL_CHILD_RESOLUTION_ALIGNED_WITH_PARENT,
                    reasons, stale, child_age, parent_age,
                )
            reasons += ["CHILD_RESOLUTION_OPPOSES_PARENT"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_CHILD_RESOLUTION_AGAINST_PARENT,
                reasons, stale, child_age, parent_age,
            )

        # Balance / directional nesting.
        if _is_balance_family(cf) and pd is not None and pf in {
            FAMILY_DIRECTIONAL_UP,
            FAMILY_DIRECTIONAL_DOWN,
        }:
            reasons.append("CHILD_BALANCE_PARENT_DIRECTIONAL")
            return self._pair(
                child, parent, child_tf, parent_tf, REL_LOCAL_BALANCE_WITHIN_PARENT_DIRECTIONAL,
                reasons, stale, child_age, parent_age,
            )
        if cd is not None and _is_balance_family(pf):
            reasons.append("CHILD_DIRECTIONAL_PARENT_BALANCE")
            return self._pair(
                child, parent, child_tf, parent_tf, REL_LOCAL_DIRECTIONAL_WITHIN_PARENT_BALANCE,
                reasons, stale, child_age, parent_age,
            )

        # Local reversal against parent (directional opposite, not mere reaction).
        if cd and pd and cd != pd:
            if _is_exhaustion(cp) or cp in {
                PHASE_POST_UP_STRESS_REACTION,
                PHASE_POST_DOWN_STRESS_REACTION,
            }:
                reasons.append("COUNTERTREND_REACTION_ONLY")
                return self._pair(
                    child, parent, child_tf, parent_tf, REL_COUNTERTREND_REACTION_ONLY,
                    reasons, stale, child_age, parent_age,
                )
            reasons += ["TF_STATE_CONFLICT", "CHILD_RESOLUTION_OPPOSES_PARENT"]
            return self._pair(
                child, parent, child_tf, parent_tf, REL_LOCAL_REVERSAL_AGAINST_PARENT,
                reasons, stale, child_age, parent_age,
            )

        # Same-direction confirms / continues.
        if cd and pd and cd == pd:
            if _is_continuation(cp) and _is_continuation(pp):
                reasons.append("CHILD_PARENT_DIRECTION_MATCH")
                return self._pair(
                    child, parent, child_tf, parent_tf, REL_CHILD_CONFIRMS_PARENT,
                    reasons, stale, child_age, parent_age,
                )
            if cf == pf:
                reasons.append("CHILD_PARENT_DIRECTION_MATCH")
                return self._pair(
                    child, parent, child_tf, parent_tf, REL_CHILD_CONTINUES_PARENT,
                    reasons, stale, child_age, parent_age,
                )

        if cf == FAMILY_UNRESOLVED or pf == FAMILY_UNRESOLVED:
            return self._pair(
                child, parent, child_tf, parent_tf, REL_UNRESOLVED,
                reasons or ["UNRESOLVED_TF"], stale, child_age, parent_age,
            )

        reasons.append("TF_STATE_CONFLICT")
        return self._pair(
            child, parent, child_tf, parent_tf, REL_UNRESOLVED_CONFLICT,
            reasons, stale, child_age, parent_age,
        )

    def _pair(
        self,
        child: TfStateView,
        parent: TfStateView,
        child_tf: str,
        parent_tf: str,
        state: str,
        reasons: list[str],
        stale: bool,
        child_age: float | None,
        parent_age: float | None,
    ) -> PairRelation:
        return PairRelation(
            child_tf=child_tf,
            parent_tf=parent_tf,
            child_episode_id=child.shadow_episode_id,
            parent_episode_id=parent.shadow_episode_id,
            child_family=child.auction_family,
            parent_family=parent.auction_family,
            child_phase=child.episode_phase,
            parent_phase=parent.episode_phase,
            relation_state=state,
            relation_reason_codes=list(reasons),
            parent_state_stale=stale,
            child_age_sec=child_age,
            parent_age_sec=parent_age,
        )

    def _propagation(
        self, pairs: list[PairRelation]
    ) -> tuple[str, int, list[str]]:
        reasons: list[str] = []
        # Contiguous upward stress chain from M15 toward H4.
        soft = [
            p.relation_state
            in {
                REL_TRANSITION_PROPAGATING_UP,
                REL_PARENT_PRESSURE_DETERIORATING,
                REL_LOCAL_REVERSAL_AGAINST_PARENT,
                REL_CHILD_RESOLUTION_AGAINST_PARENT,
                REL_LOCAL_EXHAUSTION_WITHIN_PARENT_CONTINUATION,
                REL_SYNCHRONIZED_EXHAUSTION,
            }
            for p in pairs
        ]
        depth = 0
        for i, ok in enumerate(soft):
            if ok:
                depth = i + 1
            else:
                break

        if depth > 0:
            reached = ["M30", "H1", "H4"][depth - 1]
            reasons.append(f"TRANSITION_REACHED_{reached}")
            return PROP_TOWARD_HIGHER_TF, depth, reasons
        return PROP_NONE, 0, reasons

    def _hierarchy_state(
        self,
        *,
        m15: TfStateView | None,
        m30: TfStateView | None,
        h1: TfStateView | None,
        h4: TfStateView | None,
        pairs: list[PairRelation],
        prop_depth: int,
    ) -> tuple[str, str, str, list[str]]:
        reasons: list[str] = []
        views = [m15, m30, h1, h4]
        dirs = [_dir_of(v.auction_family, v.episode_phase) if v else None for v in views]
        families = [v.auction_family if v else FAMILY_UNRESOLVED for v in views]
        phases = [v.episode_phase if v else "UNRESOLVED" for v in views]

        stale_any = any(p.parent_state_stale for p in pairs)
        conflict_pairs = sum(
            1
            for p in pairs
            if p.relation_state
            in {
                REL_UNRESOLVED_CONFLICT,
                REL_LOCAL_REVERSAL_AGAINST_PARENT,
                REL_CHILD_RESOLUTION_AGAINST_PARENT,
            }
        )

        # Synchronized multi-TF resolution / exhaustion / balance.
        res_up = sum(1 for ph in phases if ph in UP_RESOLUTION)
        res_down = sum(1 for ph in phases if ph in DOWN_RESOLUTION)
        exh = sum(1 for ph in phases if _is_exhaustion(ph))
        bal = sum(1 for f in families if _is_balance_family(f))

        if prop_depth >= 1 and any(
            p.relation_state == REL_TRANSITION_PROPAGATING_UP for p in pairs
        ):
            reasons.append("TRANSITION_PROPAGATING_UP")
            return (
                HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
                LVS_PROPAGATING,
                CONFLICT_STALE if stale_any else CONFLICT_NONE,
                reasons,
            )

        if res_up >= 2 and res_down == 0:
            reasons.append("MULTIPLE_ADJACENT_TF_RESOLUTION")
            # Preserve structural headwind if H4 still down.
            if dirs[3] == "DOWN":
                reasons.append("TF_STATE_CONFLICT")
                return (
                    HIER_MULTI_TF_RESOLUTION_UP,
                    LVS_LOCAL_AGAINST_PARENT,
                    CONFLICT_PAIR,
                    reasons,
                )
            return HIER_MULTI_TF_RESOLUTION_UP, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons
        if res_down >= 2 and res_up == 0:
            reasons.append("MULTIPLE_ADJACENT_TF_RESOLUTION")
            if dirs[3] == "UP":
                reasons.append("TF_STATE_CONFLICT")
                return (
                    HIER_MULTI_TF_RESOLUTION_DOWN,
                    LVS_LOCAL_AGAINST_PARENT,
                    CONFLICT_PAIR,
                    reasons,
                )
            return HIER_MULTI_TF_RESOLUTION_DOWN, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons

        if exh >= 2:
            reasons.append("MULTIPLE_ADJACENT_TF_EXHAUSTION")
            return HIER_MULTI_TF_EXHAUSTION, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons

        if bal >= 3:
            reasons.append("MULTIPLE_ADJACENT_TF_BALANCE")
            return HIER_MULTI_TF_BALANCE, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons

        # Full alignment (all four same direction, continuation-ish).
        if all(d == "UP" for d in dirs) and all(
            not _is_exhaustion(ph) for ph in phases
        ):
            reasons.append("CHILD_PARENT_DIRECTION_MATCH")
            return HIER_STRUCTURAL_UP_ALIGNED, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons
        if all(d == "DOWN" for d in dirs) and all(
            not _is_exhaustion(ph) for ph in phases
        ):
            reasons.append("CHILD_PARENT_DIRECTION_MATCH")
            return HIER_STRUCTURAL_DOWN_ALIGNED, LVS_STRUCTURAL_MULTI_TF, CONFLICT_NONE, reasons

        # Local balance within structural parent.
        structural = dirs[2] or dirs[3]  # H1 or H4
        lower_bal = bal >= 1 and any(_is_balance_family(f) for f in families[:2])
        if lower_bal and structural == "UP" and dirs[0] != "DOWN":
            reasons.append("CHILD_BALANCE_PARENT_DIRECTIONAL")
            return (
                HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP,
                LVS_LOCAL_WITH_PARENT_SUPPORT,
                CONFLICT_NONE,
                reasons,
            )
        if lower_bal and structural == "DOWN" and dirs[0] != "UP":
            reasons.append("CHILD_BALANCE_PARENT_DIRECTIONAL")
            return (
                HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN,
                LVS_LOCAL_WITH_PARENT_SUPPORT,
                CONFLICT_NONE,
                reasons,
            )

        # Local rotation inside parent balance.
        if _is_balance_family(families[1] if len(families) > 1 else FAMILY_UNRESOLVED) or (
            h1 and _is_balance_family(h1.auction_family)
        ):
            if dirs[0] is not None and (
                (m30 and _is_balance_family(m30.auction_family))
                or (h1 and _is_balance_family(h1.auction_family))
            ):
                reasons.append("CHILD_DIRECTIONAL_PARENT_BALANCE")
                return (
                    HIER_LOCAL_ROTATION_WITHIN_PARENT_BALANCE,
                    LVS_LOCAL_ONLY,
                    CONFLICT_NONE,
                    reasons,
                )

        # Alternating conflict across TF — never majority-vote a direction.
        # Check before single local-against-parent labels so zig-zag stacks stay CONFLICTED.
        unique_dirs = {d for d in dirs if d is not None}
        zig_zag = (
            dirs[0] is not None
            and dirs[1] is not None
            and dirs[2] is not None
            and dirs[3] is not None
            and dirs[0] != dirs[1]
            and dirs[2] != dirs[3]
        )
        if zig_zag or (len(unique_dirs) >= 2 and conflict_pairs >= 2):
            reasons.append("TF_STATE_CONFLICT")
            return HIER_CONFLICTED, LVS_UNRESOLVED, CONFLICT_MULTI, reasons

        # Local against structural parent.
        if dirs[0] == "UP" and (dirs[2] == "DOWN" or dirs[3] == "DOWN"):
            reasons.append("TF_STATE_CONFLICT")
            return (
                HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
                LVS_LOCAL_AGAINST_PARENT,
                CONFLICT_PAIR if conflict_pairs else CONFLICT_MULTI,
                reasons,
            )
        if dirs[0] == "DOWN" and (dirs[2] == "UP" or dirs[3] == "UP"):
            reasons.append("TF_STATE_CONFLICT")
            return (
                HIER_LOCAL_DOWN_WITHIN_PARENT_UP,
                LVS_LOCAL_AGAINST_PARENT,
                CONFLICT_PAIR if conflict_pairs else CONFLICT_MULTI,
                reasons,
            )

        if stale_any:
            return HIER_UNRESOLVED, LVS_UNRESOLVED, CONFLICT_STALE, reasons + ["PARENT_STATE_STALE"]

        return HIER_UNRESOLVED, LVS_UNRESOLVED, CONFLICT_NONE, reasons or ["UNRESOLVED_HIERARCHY"]
