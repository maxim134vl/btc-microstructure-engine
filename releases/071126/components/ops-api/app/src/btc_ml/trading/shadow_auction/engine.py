"""Independent per-timeframe AES2 auction episode engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .features import FeatureEngine, FeatureSnapshot, merge_aes2_params
from .observation import BarObservation
from .states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    FAMILY_UNRESOLVED,
    PHASE_ACCEPTANCE_ABOVE,
    PHASE_ACCEPTANCE_BELOW,
    PHASE_BALANCE_COMPRESSION,
    PHASE_BALANCE_ESTABLISHED,
    PHASE_BALANCE_FORMING,
    PHASE_BALANCE_LOWER_PRESSURE,
    PHASE_BALANCE_ROTATION,
    PHASE_BALANCE_UPPER_PRESSURE,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_PRESSURE_ACTIVE,
    PHASE_DOWN_PRESSURE_EXPANDING,
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
    PHASE_UNRESOLVED,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_PRESSURE_ACTIVE,
    PHASE_UP_PRESSURE_EXPANDING,
    PHASE_UP_STOPPING_CANDIDATE,
    PHASE_UPSIDE_EXPANSION_ATTEMPT,
    family_for_phase,
)


@dataclass
class BalanceStructure:
    balance_low: float | None = None
    balance_high: float | None = None
    balance_mid: float | None = None
    balance_width: float = 0.0
    balance_age: int = 0
    time_inside: int = 0
    midpoint_cross_count: int = 0
    upper_test_count: int = 0
    lower_test_count: int = 0
    upper_rejection_count: int = 0
    lower_rejection_count: int = 0
    failed_breakout_count: int = 0
    failed_breakdown_count: int = 0
    bars_beyond_high: int = 0
    bars_beyond_low: int = 0
    last_side: str | None = None  # "UPPER" | "LOWER" | "MID"
    lower_eff_hist: list[float] = field(default_factory=list)
    upper_eff_hist: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance_low": self.balance_low,
            "balance_high": self.balance_high,
            "balance_mid": self.balance_mid,
            "balance_width": self.balance_width,
            "balance_age": self.balance_age,
            "time_inside": self.time_inside,
            "time_inside_ratio": (self.time_inside / self.balance_age) if self.balance_age else 0.0,
            "midpoint_cross_count": self.midpoint_cross_count,
            "upper_test_count": self.upper_test_count,
            "lower_test_count": self.lower_test_count,
            "upper_rejection_count": self.upper_rejection_count,
            "lower_rejection_count": self.lower_rejection_count,
            "failed_breakout_count": self.failed_breakout_count,
            "failed_breakdown_count": self.failed_breakdown_count,
            "upper_efficiency_trend": _hist_trend(self.upper_eff_hist),
            "lower_efficiency_trend": _hist_trend(self.lower_eff_hist),
        }


@dataclass
class EpisodeState:
    shadow_episode_id: str | None = None
    auction_family: str = FAMILY_UNRESOLVED
    episode_phase: str = PHASE_UNRESOLVED
    pressure_side: str | None = None
    resolution_side: str | None = None
    episode_age: int = 0
    stress_event_count: int = 0
    extreme_event_count: int = 0
    continuation_count: int = 0
    failed_continuation_count: int = 0
    prev_buy_effort: float = 0.0
    prev_sell_effort: float = 0.0
    prev_up_result: float = 0.0
    prev_down_result: float = 0.0
    balance: BalanceStructure = field(default_factory=BalanceStructure)
    recent_closes: list[float] = field(default_factory=list)
    recent_phases: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)  # immutable online trail


@dataclass
class TransitionResult:
    emitted: bool
    previous_state: str
    new_state: str
    auction_family: str
    episode_phase: str
    shadow_episode_id: str | None
    reason_codes: list[str]
    features: dict[str, Any]
    episode_snapshot: dict[str, Any]
    duplicate: bool = False


def _hist_trend(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mid = max(1, len(values) // 2)
    a = sum(values[:mid]) / mid
    b = sum(values[mid:]) / max(1, len(values) - mid)
    return float(b - a)


def _new_episode_id(timeframe: str, timestamp: str, seq: int) -> str:
    raw = f"{timeframe}|{timestamp}|{seq}"
    return "AES_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class TimeframeAuctionEngine:
    """Single-TF auction episode engine. Never mutates other TF engines."""

    def __init__(
        self,
        timeframe: str,
        *,
        params: Mapping[str, Any] | None = None,
        logic_version: str = "AES_V1",
        logic_fingerprint: str = "",
    ) -> None:
        self.timeframe = str(timeframe).upper()
        self.params = merge_aes2_params({"aes2": dict(params or {})})
        window = int(self.params["window_bars"].get(self.timeframe, 8))
        self.features = FeatureEngine(
            window=window,
            extreme_volume_z=float(self.params["extreme_volume_z"]),
        )
        self.state = EpisodeState()
        self.logic_version = logic_version
        self.logic_fingerprint = logic_fingerprint
        self._episode_seq = 0
        self._seen_events: set[str] = set()
        self.events_written = 0
        self.transitions_written = 0
        self._window_highs: list[float] = []
        self._window_lows: list[float] = []

    def reset(self) -> None:
        self.features.reset()
        self.state = EpisodeState()
        self._episode_seq = 0
        self._seen_events.clear()
        self.events_written = 0
        self.transitions_written = 0
        self._window_highs.clear()
        self._window_lows.clear()

    def process(self, obs: BarObservation) -> TransitionResult:
        if obs.timeframe.upper() != self.timeframe:
            raise ValueError(
                f"TF independence violation: engine={self.timeframe} obs={obs.timeframe}"
            )
        prev_phase = self.state.episode_phase
        if obs.source_event_id in self._seen_events:
            return TransitionResult(
                emitted=False,
                previous_state=prev_phase,
                new_state=prev_phase,
                auction_family=self.state.auction_family,
                episode_phase=prev_phase,
                shadow_episode_id=self.state.shadow_episode_id,
                reason_codes=["DUPLICATE_SOURCE_EVENT"],
                features={},
                episode_snapshot=self.episode_snapshot(obs, None),
                duplicate=True,
            )
        self._seen_events.add(obs.source_event_id)
        # Bound seen-set (RAM contract).
        if len(self._seen_events) > 5000:
            self._seen_events = set(list(self._seen_events)[-2500:])

        snap = self.features.update(obs)
        self._window_highs.append(obs.high)
        self._window_lows.append(obs.low)
        max_w = int(self.params["window_bars"].get(self.timeframe, 8))
        self._window_highs = self._window_highs[-max_w:]
        self._window_lows = self._window_lows[-max_w:]
        self.state.recent_closes.append(obs.close)
        self.state.recent_closes = self.state.recent_closes[-max_w:]

        new_phase, reasons = self._next_phase(obs, snap)
        family = family_for_phase(new_phase)

        # Episode identity: new structural auction process only.
        if self.state.shadow_episode_id is None:
            self._episode_seq += 1
            self.state.shadow_episode_id = _new_episode_id(
                self.timeframe, obs.timestamp, self._episode_seq
            )
            reasons = list(reasons) + ["EPISODE_OPENED"]
        elif self._requires_new_episode(prev_phase, new_phase):
            self._episode_seq += 1
            self.state.shadow_episode_id = _new_episode_id(
                self.timeframe, obs.timestamp, self._episode_seq
            )
            self.state.episode_age = 0
            self.state.stress_event_count = 0
            self.state.extreme_event_count = 0
            self.state.continuation_count = 0
            self.state.failed_continuation_count = 0
            if family == FAMILY_BALANCE:
                self._init_balance(obs)
            reasons = list(reasons) + ["EPISODE_ROLLED"]

        self.state.episode_age += 1
        self._update_counts(new_phase, snap)
        self._update_balance(obs, snap, new_phase)
        self.state.pressure_side = self._pressure_side(new_phase, snap)
        if new_phase in {PHASE_RESOLUTION_UP, PHASE_ACCEPTANCE_ABOVE}:
            self.state.resolution_side = "UP"
        elif new_phase in {PHASE_RESOLUTION_DOWN, PHASE_ACCEPTANCE_BELOW}:
            self.state.resolution_side = "DOWN"

        changed = new_phase != prev_phase
        self.state.auction_family = family
        self.state.episode_phase = new_phase
        self.state.recent_phases.append(new_phase)
        self.state.recent_phases = self.state.recent_phases[-max_w:]
        self.state.prev_buy_effort = snap.buy_effort
        self.state.prev_sell_effort = snap.sell_effort
        self.state.prev_up_result = snap.up_result
        self.state.prev_down_result = snap.down_result

        # Online immutability: append-only history of transitions.
        if changed:
            self.state.history.append(
                {
                    "timestamp": obs.timestamp,
                    "previous_state": prev_phase,
                    "new_state": new_phase,
                    "reason_codes": list(reasons),
                    "source_event_id": obs.source_event_id,
                }
            )
            self.transitions_written += 1

        episode_snap = self.episode_snapshot(obs, snap)
        self.events_written += 1
        return TransitionResult(
            emitted=True,
            previous_state=prev_phase,
            new_state=new_phase,
            auction_family=family,
            episode_phase=new_phase,
            shadow_episode_id=self.state.shadow_episode_id,
            reason_codes=list(reasons),
            features=snap.to_dict(),
            episode_snapshot=episode_snap,
            duplicate=False,
        )

    def episode_snapshot(self, obs: BarObservation, snap: FeatureSnapshot | None) -> dict[str, Any]:
        feats = snap.to_dict() if snap is not None else {}
        bal = self.state.balance.to_dict()
        return {
            "timestamp": obs.timestamp,
            "timeframe": self.timeframe,
            "shadow_episode_id": self.state.shadow_episode_id,
            "auction_family": self.state.auction_family,
            "episode_phase": self.state.episode_phase,
            "pressure_side": self.state.pressure_side,
            "resolution_side": self.state.resolution_side,
            "directional_efficiency": feats.get("up_efficiency")
            if self.state.auction_family == FAMILY_DIRECTIONAL_UP
            else feats.get("down_efficiency"),
            "efficiency_trend": feats.get("efficiency_trend_up")
            if self.state.auction_family == FAMILY_DIRECTIONAL_UP
            else feats.get("efficiency_trend_down"),
            "reaction_strength": feats.get("reaction_strength"),
            "acceptance_state": self.state.episode_phase
            if self.state.episode_phase
            in {PHASE_ACCEPTANCE_ABOVE, PHASE_ACCEPTANCE_BELOW}
            else None,
            "stress_event_count": self.state.stress_event_count,
            "extreme_event_count": self.state.extreme_event_count,
            "failed_continuation_count": self.state.failed_continuation_count,
            "continuation_count": self.state.continuation_count,
            "episode_age": self.state.episode_age,
            "balance_state": self.state.episode_phase if self.state.auction_family == FAMILY_BALANCE else None,
            **{f"balance_{k}" if not k.startswith("balance_") else k: v for k, v in {
                "low": bal["balance_low"],
                "high": bal["balance_high"],
                "mid": bal["balance_mid"],
                "age": bal["balance_age"],
                "width": bal["balance_width"],
            }.items()},
            "time_inside_ratio": bal["time_inside_ratio"],
            "midpoint_cross_count": bal["midpoint_cross_count"],
            "upper_test_count": bal["upper_test_count"],
            "lower_test_count": bal["lower_test_count"],
            "upper_rejection_count": bal["upper_rejection_count"],
            "lower_rejection_count": bal["lower_rejection_count"],
            "failed_breakout_count": bal["failed_breakout_count"],
            "failed_breakdown_count": bal["failed_breakdown_count"],
            "up_continuation_support": feats.get("up_continuation_support"),
            "down_continuation_support": feats.get("down_continuation_support"),
            "up_exhaustion_support": feats.get("up_exhaustion_support"),
            "down_exhaustion_support": feats.get("down_exhaustion_support"),
            "balance_support": feats.get("balance_support"),
            "up_resolution_support": feats.get("up_resolution_support"),
            "down_resolution_support": feats.get("down_resolution_support"),
            "score_disclaimer": feats.get("score_disclaimer"),
            "source_event_id": obs.source_event_id,
            "source_timestamp": obs.timestamp,
            "logic_version": self.logic_version,
            "logic_fingerprint": self.logic_fingerprint,
        }

    def _requires_new_episode(self, prev: str, new: str) -> bool:
        prev_f = family_for_phase(prev)
        new_f = family_for_phase(new)
        if prev_f == FAMILY_UNRESOLVED and new_f != FAMILY_UNRESOLVED:
            return False  # same opening episode
        if new in {PHASE_RESOLUTION_UP, PHASE_RESOLUTION_DOWN}:
            return False  # resolution closes current process; next bar opens new
        if prev in {PHASE_RESOLUTION_UP, PHASE_RESOLUTION_DOWN} and new_f in {
            FAMILY_DIRECTIONAL_UP,
            FAMILY_DIRECTIONAL_DOWN,
            FAMILY_BALANCE,
        }:
            return True
        if prev_f in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN} and new_f == FAMILY_BALANCE:
            return True
        if prev_f == FAMILY_BALANCE and new_f in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}:
            return True
        return False

    def _pressure_side(self, phase: str, snap: FeatureSnapshot) -> str | None:
        if phase in {
            PHASE_UP_PRESSURE_ACTIVE,
            PHASE_UP_PRESSURE_EXPANDING,
            PHASE_EXTREME_UP_PARTICIPATION,
            PHASE_UP_CONTINUATION_ACCEPTED,
            PHASE_UP_CONTINUATION_DETERIORATING,
            PHASE_UP_STOPPING_CANDIDATE,
            PHASE_POST_UP_STRESS_REACTION,
            PHASE_BALANCE_UPPER_PRESSURE,
            PHASE_UPSIDE_EXPANSION_ATTEMPT,
            PHASE_RESOLUTION_UP,
        }:
            return "UP"
        if phase in {
            PHASE_DOWN_PRESSURE_ACTIVE,
            PHASE_DOWN_PRESSURE_EXPANDING,
            PHASE_EXTREME_DOWN_PARTICIPATION,
            PHASE_DOWN_CONTINUATION_ACCEPTED,
            PHASE_DOWN_CONTINUATION_DETERIORATING,
            PHASE_DOWN_STOPPING_CANDIDATE,
            PHASE_POST_DOWN_STRESS_REACTION,
            PHASE_BALANCE_LOWER_PRESSURE,
            PHASE_DOWNSIDE_EXPANSION_ATTEMPT,
            PHASE_RESOLUTION_DOWN,
        }:
            return "DOWN"
        if snap.buy_effort > snap.sell_effort:
            return "UP"
        if snap.sell_effort > snap.buy_effort:
            return "DOWN"
        return None

    def _update_counts(self, phase: str, snap: FeatureSnapshot) -> None:
        if phase in {
            PHASE_EXTREME_UP_PARTICIPATION,
            PHASE_EXTREME_DOWN_PARTICIPATION,
        } or snap.extreme_up_participation or snap.extreme_down_participation:
            self.state.extreme_event_count += 1
            self.state.stress_event_count += 1
        if phase in {
            PHASE_UP_CONTINUATION_ACCEPTED,
            PHASE_DOWN_CONTINUATION_ACCEPTED,
            PHASE_UP_PRESSURE_EXPANDING,
            PHASE_DOWN_PRESSURE_EXPANDING,
        }:
            self.state.continuation_count += 1
        if phase in {
            PHASE_UP_CONTINUATION_DETERIORATING,
            PHASE_DOWN_CONTINUATION_DETERIORATING,
            PHASE_FAILED_UPSIDE_BREAK,
            PHASE_FAILED_DOWNSIDE_BREAK,
        }:
            self.state.failed_continuation_count += 1

    def _init_balance(self, obs: BarObservation) -> None:
        self.state.balance = BalanceStructure(
            balance_low=obs.low,
            balance_high=obs.high,
            balance_mid=(obs.high + obs.low) / 2.0,
            balance_width=max(obs.high - obs.low, 0.0),
            balance_age=1,
            time_inside=1,
        )

    def _update_balance(self, obs: BarObservation, snap: FeatureSnapshot, phase: str) -> None:
        bal = self.state.balance
        if family_for_phase(phase) != FAMILY_BALANCE and phase != PHASE_TRANSITION:
            return
        if bal.balance_low is None or bal.balance_high is None:
            self._init_balance(obs)
            bal = self.state.balance
        bal.balance_age += 1
        # Dynamic bounds while forming.
        if phase in {PHASE_BALANCE_FORMING, PHASE_TRANSITION}:
            bal.balance_low = min(bal.balance_low, obs.low)  # type: ignore[arg-type]
            bal.balance_high = max(bal.balance_high, obs.high)  # type: ignore[arg-type]
        bal.balance_mid = (bal.balance_low + bal.balance_high) / 2.0  # type: ignore[operator]
        bal.balance_width = float(bal.balance_high - bal.balance_low)  # type: ignore[operator]
        inside = bal.balance_low <= obs.close <= bal.balance_high  # type: ignore[operator]
        if inside:
            bal.time_inside += 1
        # Midpoint crosses / rotations.
        side = "MID"
        width = bal.balance_width or 1.0
        if obs.close >= bal.balance_mid + 0.25 * width:  # type: ignore[operator]
            side = "UPPER"
            bal.upper_test_count += 1
        elif obs.close <= bal.balance_mid - 0.25 * width:  # type: ignore[operator]
            side = "LOWER"
            bal.lower_test_count += 1
        if bal.last_side and side != bal.last_side and side != "MID" and bal.last_side != "MID":
            bal.midpoint_cross_count += 1
        if snap.upper_rejection >= 0.5:
            bal.upper_rejection_count += 1
            bal.upper_eff_hist.append(snap.up_efficiency)
        if snap.lower_rejection >= 0.5:
            bal.lower_rejection_count += 1
            bal.lower_eff_hist.append(snap.down_efficiency)
        bal.upper_eff_hist = bal.upper_eff_hist[-8:]
        bal.lower_eff_hist = bal.lower_eff_hist[-8:]
        if obs.close > bal.balance_high:  # type: ignore[operator]
            bal.bars_beyond_high += 1
            bal.bars_beyond_low = 0
        elif obs.close < bal.balance_low:  # type: ignore[operator]
            bal.bars_beyond_low += 1
            bal.bars_beyond_high = 0
        else:
            bal.bars_beyond_high = 0
            bal.bars_beyond_low = 0
        bal.last_side = side

    def _next_phase(self, obs: BarObservation, snap: FeatureSnapshot) -> tuple[str, list[str]]:
        p = self.params
        strong_e = float(p["strong_efficiency"])
        weak_e = float(p["weak_efficiency"])
        strong_effort = float(p["strong_effort"])
        phase = self.state.episode_phase
        reasons: list[str] = []

        # Explicit synthetic force (tests / research harness only).
        force = obs.feature_overrides.get("force_phase")
        if force:
            return str(force), ["FORCED_PHASE_OVERRIDE"]

        # Balance path takes priority when already in balance family.
        if family_for_phase(phase) == FAMILY_BALANCE or phase == PHASE_TRANSITION:
            return self._balance_phase(obs, snap, phase, reasons)

        # B: stopping evidence beats balance escape while still deteriorating.
        # (Previously balance_support≥enter always preempted *_STOPPING_CANDIDATE.)
        if phase == PHASE_UP_CONTINUATION_DETERIORATING and _up_stopping_evidence(snap):
            reasons += ["STOPPING_CANDIDATE_EVIDENCE", "STOPPING_BEFORE_BALANCE_ESCAPE"]
            return PHASE_UP_STOPPING_CANDIDATE, reasons
        if phase == PHASE_DOWN_CONTINUATION_DETERIORATING and _down_stopping_evidence(snap):
            reasons += ["STOPPING_CANDIDATE_EVIDENCE", "STOPPING_BEFORE_BALANCE_ESCAPE"]
            return PHASE_DOWN_STOPPING_CANDIDATE, reasons

        # Entering balance from directional deterioration / post-stress + balance support.
        # STOPPING_CANDIDATE intentionally omitted here — handled inside _directional_*.
        if phase in {
            PHASE_UP_CONTINUATION_DETERIORATING,
            PHASE_DOWN_CONTINUATION_DETERIORATING,
            PHASE_POST_UP_STRESS_REACTION,
            PHASE_POST_DOWN_STRESS_REACTION,
        } and snap.balance_support >= float(p["balance_support_enter"]):
            reasons += ["DIRECTIONAL_EFFICIENCY_DROPPING", "BALANCE_SUPPORT_RISING"]
            return PHASE_TRANSITION, reasons

        # UNRESOLVED / start directional.
        if phase in {PHASE_UNRESOLVED, PHASE_RESOLUTION_UP, PHASE_RESOLUTION_DOWN}:
            if snap.up_continuation_support >= snap.down_continuation_support and (
                snap.up_efficiency >= strong_e or snap.buy_effort >= strong_effort
            ):
                reasons += ["EFFORT_HIGH_RESULT_STRONG", "UP_PRESSURE_DETECTED"]
                return PHASE_UP_PRESSURE_ACTIVE, reasons
            if snap.down_continuation_support > snap.up_continuation_support and (
                snap.down_efficiency >= strong_e or snap.sell_effort >= strong_effort
            ):
                reasons += ["EFFORT_HIGH_RESULT_STRONG", "DOWN_PRESSURE_DETECTED"]
                return PHASE_DOWN_PRESSURE_ACTIVE, reasons
            if snap.balance_support >= float(p["balance_support_enter"]):
                reasons += ["BALANCE_SUPPORT_RISING"]
                return PHASE_TRANSITION, reasons
            return PHASE_UNRESOLVED, ["NO_DIRECTIONAL_PRESSURE"]

        # UP cascade
        if phase in UP_ACTIVE:
            return self._directional_up(obs, snap, phase, reasons, strong_e, weak_e, strong_effort)
        # DOWN cascade
        if phase in DOWN_ACTIVE:
            return self._directional_down(obs, snap, phase, reasons, strong_e, weak_e, strong_effort)

        return phase, ["PHASE_HOLD"]

    def _directional_up(
        self,
        obs: BarObservation,
        snap: FeatureSnapshot,
        phase: str,
        reasons: list[str],
        strong_e: float,
        weak_e: float,
        strong_effort: float,
    ) -> tuple[str, list[str]]:
        new_high = obs.high >= max(self._window_highs)
        # Invalidation of stopping candidate.
        if phase in {PHASE_UP_STOPPING_CANDIDATE, PHASE_POST_UP_STRESS_REACTION}:
            if new_high and snap.up_efficiency >= strong_e and snap.up_result >= 0.45:
                reasons += ["NEW_EXTREME_ACCEPTED", "STOPPING_CANDIDATE_INVALIDATED"]
                return PHASE_UP_CONTINUATION_ACCEPTED, reasons
            if snap.reaction_strength >= float(self.params["reaction_retrace_ratio"]):
                reasons += ["POST_STRESS_REACTION"]
                return PHASE_POST_UP_STRESS_REACTION, reasons
            if snap.balance_support >= float(self.params["balance_support_enter"]):
                reasons += ["BALANCE_SUPPORT_RISING"]
                return PHASE_TRANSITION, reasons

        if snap.extreme_up_participation and phase in {
            PHASE_UP_PRESSURE_ACTIVE,
            PHASE_UP_PRESSURE_EXPANDING,
            PHASE_UP_CONTINUATION_ACCEPTED,
        }:
            reasons += ["EXTREME_PARTICIPATION_ATTENTION"]
            # Extreme alone is NOT climax/reversal — stay directional via extreme phase.
            if new_high and snap.up_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED", "EFFORT_HIGH_RESULT_STRONG"]
                return PHASE_EXTREME_UP_PARTICIPATION, reasons
            reasons += ["EFFORT_HIGH_RESULT_WEAK"]
            return PHASE_EXTREME_UP_PARTICIPATION, reasons

        if phase == PHASE_EXTREME_UP_PARTICIPATION:
            # follow_through is signed: >0.5 means close advanced higher vs prior bar.
            if new_high and snap.up_efficiency >= strong_e and snap.follow_through >= 0.45:
                reasons += ["CONTINUATION_AFTER_EXTREME"]
                return PHASE_UP_CONTINUATION_ACCEPTED, reasons
            if snap.up_efficiency < weak_e:
                reasons += ["EFFORT_HIGH_RESULT_WEAK"]
                # C: same-bar promote when stopping evidence already present.
                if _up_stopping_evidence(snap):
                    reasons += ["STOPPING_CANDIDATE_EVIDENCE", "SAME_BAR_STOPPING_PROMOTE"]
                    return PHASE_UP_STOPPING_CANDIDATE, reasons
                return PHASE_UP_CONTINUATION_DETERIORATING, reasons

        # Deterioration: effort up, result down.
        if (
            snap.buy_effort >= self.state.prev_buy_effort + float(self.params["deterioration_effort_rise"])
            and snap.up_result <= self.state.prev_up_result - float(self.params["deterioration_result_drop"])
            and snap.efficiency_trend_up <= 0
        ):
            reasons += ["DIRECTIONAL_EFFICIENCY_DROPPING", "EFFORT_HIGH_RESULT_WEAK"]
            if phase in {
                PHASE_UP_CONTINUATION_ACCEPTED,
                PHASE_UP_PRESSURE_EXPANDING,
                PHASE_EXTREME_UP_PARTICIPATION,
            }:
                # C: same-bar promote when stopping evidence already present.
                if _up_stopping_evidence(snap):
                    reasons += ["STOPPING_CANDIDATE_EVIDENCE", "SAME_BAR_STOPPING_PROMOTE"]
                    return PHASE_UP_STOPPING_CANDIDATE, reasons
                return PHASE_UP_CONTINUATION_DETERIORATING, reasons

        if phase == PHASE_UP_CONTINUATION_DETERIORATING:
            if _up_stopping_evidence(snap):
                reasons += ["STOPPING_CANDIDATE_EVIDENCE"]
                return PHASE_UP_STOPPING_CANDIDATE, reasons
            if snap.balance_support >= float(self.params["balance_support_enter"]):
                reasons += ["BALANCE_SUPPORT_RISING"]
                return PHASE_TRANSITION, reasons

        if phase == PHASE_UP_PRESSURE_ACTIVE:
            if snap.up_efficiency >= strong_e and snap.range_expansion >= 0.4:
                reasons += ["PRESSURE_EXPANDING"]
                return PHASE_UP_PRESSURE_EXPANDING, reasons
            if new_high and snap.up_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED"]
                return PHASE_UP_CONTINUATION_ACCEPTED, reasons

        if phase == PHASE_UP_PRESSURE_EXPANDING:
            if new_high and snap.up_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED", "EFFORT_HIGH_RESULT_STRONG"]
                return PHASE_UP_CONTINUATION_ACCEPTED, reasons

        if phase == PHASE_UP_CONTINUATION_ACCEPTED:
            if new_high and snap.up_efficiency >= strong_e:
                reasons += ["CONTINUATION_PERSISTING"]
                return PHASE_UP_CONTINUATION_ACCEPTED, reasons

        return phase, reasons or ["PHASE_HOLD"]

    def _directional_down(
        self,
        obs: BarObservation,
        snap: FeatureSnapshot,
        phase: str,
        reasons: list[str],
        strong_e: float,
        weak_e: float,
        strong_effort: float,
    ) -> tuple[str, list[str]]:
        # Exact mirror of _directional_up.
        new_low = obs.low <= min(self._window_lows)
        if phase in {PHASE_DOWN_STOPPING_CANDIDATE, PHASE_POST_DOWN_STRESS_REACTION}:
            if new_low and snap.down_efficiency >= strong_e and snap.down_result >= 0.45:
                reasons += ["NEW_EXTREME_ACCEPTED", "STOPPING_CANDIDATE_INVALIDATED"]
                return PHASE_DOWN_CONTINUATION_ACCEPTED, reasons
            if snap.reaction_strength >= float(self.params["reaction_retrace_ratio"]):
                reasons += ["POST_STRESS_REACTION"]
                return PHASE_POST_DOWN_STRESS_REACTION, reasons
            if snap.balance_support >= float(self.params["balance_support_enter"]):
                reasons += ["BALANCE_SUPPORT_RISING"]
                return PHASE_TRANSITION, reasons

        if snap.extreme_down_participation and phase in {
            PHASE_DOWN_PRESSURE_ACTIVE,
            PHASE_DOWN_PRESSURE_EXPANDING,
            PHASE_DOWN_CONTINUATION_ACCEPTED,
        }:
            reasons += ["EXTREME_PARTICIPATION_ATTENTION"]
            if new_low and snap.down_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED", "EFFORT_HIGH_RESULT_STRONG"]
                return PHASE_EXTREME_DOWN_PARTICIPATION, reasons
            reasons += ["EFFORT_HIGH_RESULT_WEAK"]
            return PHASE_EXTREME_DOWN_PARTICIPATION, reasons

        if phase == PHASE_EXTREME_DOWN_PARTICIPATION:
            # Mirror of UP: strong downside follow-through (close continuing lower).
            if new_low and snap.down_efficiency >= strong_e and snap.follow_through <= 0.55:
                reasons += ["CONTINUATION_AFTER_EXTREME"]
                return PHASE_DOWN_CONTINUATION_ACCEPTED, reasons
            if snap.down_efficiency < weak_e:
                reasons += ["EFFORT_HIGH_RESULT_WEAK"]
                # C: same-bar promote when stopping evidence already present.
                if _down_stopping_evidence(snap):
                    reasons += ["STOPPING_CANDIDATE_EVIDENCE", "SAME_BAR_STOPPING_PROMOTE"]
                    return PHASE_DOWN_STOPPING_CANDIDATE, reasons
                return PHASE_DOWN_CONTINUATION_DETERIORATING, reasons

        if (
            snap.sell_effort >= self.state.prev_sell_effort + float(self.params["deterioration_effort_rise"])
            and snap.down_result <= self.state.prev_down_result - float(self.params["deterioration_result_drop"])
            and snap.efficiency_trend_down <= 0
        ):
            reasons += ["DIRECTIONAL_EFFICIENCY_DROPPING", "EFFORT_HIGH_RESULT_WEAK"]
            if phase in {
                PHASE_DOWN_CONTINUATION_ACCEPTED,
                PHASE_DOWN_PRESSURE_EXPANDING,
                PHASE_EXTREME_DOWN_PARTICIPATION,
            }:
                # C: same-bar promote when stopping evidence already present.
                if _down_stopping_evidence(snap):
                    reasons += ["STOPPING_CANDIDATE_EVIDENCE", "SAME_BAR_STOPPING_PROMOTE"]
                    return PHASE_DOWN_STOPPING_CANDIDATE, reasons
                return PHASE_DOWN_CONTINUATION_DETERIORATING, reasons

        if phase == PHASE_DOWN_CONTINUATION_DETERIORATING:
            if _down_stopping_evidence(snap):
                reasons += ["STOPPING_CANDIDATE_EVIDENCE"]
                return PHASE_DOWN_STOPPING_CANDIDATE, reasons
            if snap.balance_support >= float(self.params["balance_support_enter"]):
                reasons += ["BALANCE_SUPPORT_RISING"]
                return PHASE_TRANSITION, reasons

        if phase == PHASE_DOWN_PRESSURE_ACTIVE:
            if snap.down_efficiency >= strong_e and snap.range_expansion >= 0.4:
                reasons += ["PRESSURE_EXPANDING"]
                return PHASE_DOWN_PRESSURE_EXPANDING, reasons
            if new_low and snap.down_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED"]
                return PHASE_DOWN_CONTINUATION_ACCEPTED, reasons

        if phase == PHASE_DOWN_PRESSURE_EXPANDING:
            if new_low and snap.down_efficiency >= strong_e:
                reasons += ["NEW_EXTREME_ACCEPTED", "EFFORT_HIGH_RESULT_STRONG"]
                return PHASE_DOWN_CONTINUATION_ACCEPTED, reasons

        if phase == PHASE_DOWN_CONTINUATION_ACCEPTED:
            if new_low and snap.down_efficiency >= strong_e:
                reasons += ["CONTINUATION_PERSISTING"]
                return PHASE_DOWN_CONTINUATION_ACCEPTED, reasons

        return phase, reasons or ["PHASE_HOLD"]

    def _balance_phase(
        self,
        obs: BarObservation,
        snap: FeatureSnapshot,
        phase: str,
        reasons: list[str],
    ) -> tuple[str, list[str]]:
        bal = self.state.balance
        accept_n = int(self.params["acceptance_bars_beyond"])
        if phase == PHASE_TRANSITION:
            if snap.balance_support >= float(self.params["balance_support_enter"]):
                reasons += ["BALANCE_FORMING_EVIDENCE"]
                if bal.balance_low is None:
                    self._init_balance(obs)
                return PHASE_BALANCE_FORMING, reasons
            return PHASE_TRANSITION, ["TRANSITION_HOLD"]

        if bal.balance_low is None or bal.balance_high is None:
            self._init_balance(obs)
            bal = self.state.balance

        # Already-accepted / resolved phases advance before re-checking breaks.
        if phase == PHASE_ACCEPTANCE_ABOVE:
            reasons += ["RESOLUTION_UP"]
            return PHASE_RESOLUTION_UP, reasons
        if phase == PHASE_ACCEPTANCE_BELOW:
            reasons += ["RESOLUTION_DOWN"]
            return PHASE_RESOLUTION_DOWN, reasons
        if phase == PHASE_RESOLUTION_UP:
            reasons += ["NEW_DIRECTIONAL_UP_AFTER_RESOLUTION"]
            return PHASE_UP_PRESSURE_ACTIVE, reasons
        if phase == PHASE_RESOLUTION_DOWN:
            reasons += ["NEW_DIRECTIONAL_DOWN_AFTER_RESOLUTION"]
            return PHASE_DOWN_PRESSURE_ACTIVE, reasons

        # Expansion attempts / acceptance / failed breaks.
        if obs.close > bal.balance_high:
            reasons += ["UPSIDE_BREAK_ATTEMPT"]
            if bal.bars_beyond_high + 1 >= accept_n and snap.up_resolution_support >= 0.55:
                if phase == PHASE_UPSIDE_EXPANSION_ATTEMPT:
                    reasons += ["ACCEPTANCE_ABOVE_CONFIRMED"]
                    return PHASE_ACCEPTANCE_ABOVE, reasons
                return PHASE_UPSIDE_EXPANSION_ATTEMPT, reasons
            if phase == PHASE_UPSIDE_EXPANSION_ATTEMPT and snap.up_resolution_support < 0.4:
                # Will finalize fail on return; hold attempt.
                return PHASE_UPSIDE_EXPANSION_ATTEMPT, reasons
            return PHASE_UPSIDE_EXPANSION_ATTEMPT, reasons

        if obs.close < bal.balance_low:
            reasons += ["DOWNSIDE_BREAK_ATTEMPT"]
            if bal.bars_beyond_low + 1 >= accept_n and snap.down_resolution_support >= 0.55:
                if phase == PHASE_DOWNSIDE_EXPANSION_ATTEMPT:
                    reasons += ["ACCEPTANCE_BELOW_CONFIRMED"]
                    return PHASE_ACCEPTANCE_BELOW, reasons
                return PHASE_DOWNSIDE_EXPANSION_ATTEMPT, reasons
            return PHASE_DOWNSIDE_EXPANSION_ATTEMPT, reasons

        # Return inside after attempt => failed break.
        if phase == PHASE_UPSIDE_EXPANSION_ATTEMPT and obs.close <= bal.balance_high:
            bal.failed_breakout_count += 1
            reasons += ["UPSIDE_BREAK_NO_ACCEPTANCE", "FAILED_UPSIDE_BREAK"]
            return PHASE_FAILED_UPSIDE_BREAK, reasons
        if phase == PHASE_DOWNSIDE_EXPANSION_ATTEMPT and obs.close >= bal.balance_low:
            bal.failed_breakdown_count += 1
            reasons += ["DOWNSIDE_BREAK_NO_ACCEPTANCE", "FAILED_DOWNSIDE_BREAK"]
            return PHASE_FAILED_DOWNSIDE_BREAK, reasons

        # Internal extreme volume + low displacement => neutral transfer.
        if (
            (snap.extreme_up_participation or snap.extreme_down_participation)
            and snap.balance_support >= 0.5
            and abs(snap.price_displacement) < (bal.balance_width or 1.0) * 0.15
        ):
            reasons += ["INTERNAL_EXTREME_LOW_DISPLACEMENT"]
            return PHASE_INTERNAL_TRANSFER_SUPPORT, reasons

        # Asymmetric pressure inside balance.
        if len(bal.lower_eff_hist) >= 2 and _hist_trend(bal.lower_eff_hist) < -0.05:
            reasons += ["BALANCE_LOWER_EFFICIENCY_DETERIORATING", "BALANCE_BOUNDARY_TEST"]
            return PHASE_BALANCE_LOWER_PRESSURE, reasons
        if len(bal.upper_eff_hist) >= 2 and _hist_trend(bal.upper_eff_hist) < -0.05:
            reasons += ["BALANCE_UPPER_EFFICIENCY_DETERIORATING", "BALANCE_BOUNDARY_TEST"]
            return PHASE_BALANCE_UPPER_PRESSURE, reasons

        if bal.midpoint_cross_count >= 2:
            reasons += ["BALANCE_ROTATION_CONFIRMED"]
            if bal.balance_width > 0 and snap.range_expansion < 0.35:
                return PHASE_BALANCE_COMPRESSION, reasons + ["BALANCE_COMPRESSION"]
            return PHASE_BALANCE_ROTATION, reasons

        if phase == PHASE_BALANCE_FORMING and bal.balance_age >= int(self.params["balance_min_bars"]):
            reasons += ["BALANCE_ESTABLISHED"]
            return PHASE_BALANCE_ESTABLISHED, reasons

        if phase in {
            PHASE_FAILED_UPSIDE_BREAK,
            PHASE_FAILED_DOWNSIDE_BREAK,
            PHASE_INTERNAL_TRANSFER_SUPPORT,
            PHASE_BALANCE_UPPER_PRESSURE,
            PHASE_BALANCE_LOWER_PRESSURE,
            PHASE_BALANCE_ROTATION,
            PHASE_BALANCE_COMPRESSION,
        }:
            return PHASE_BALANCE_ESTABLISHED, reasons + ["BALANCE_CONTINUES"]

        return phase if phase != PHASE_UNRESOLVED else PHASE_BALANCE_FORMING, reasons or ["BALANCE_HOLD"]


UP_ACTIVE = {
    PHASE_UP_PRESSURE_ACTIVE,
    PHASE_UP_PRESSURE_EXPANDING,
    PHASE_EXTREME_UP_PARTICIPATION,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_STOPPING_CANDIDATE,
    PHASE_POST_UP_STRESS_REACTION,
}

DOWN_ACTIVE = {
    PHASE_DOWN_PRESSURE_ACTIVE,
    PHASE_DOWN_PRESSURE_EXPANDING,
    PHASE_EXTREME_DOWN_PARTICIPATION,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_STOPPING_CANDIDATE,
    PHASE_POST_DOWN_STRESS_REACTION,
}

# Shared AES2 thresholds for directional stopping-candidate evidence.
_STOPPING_EXHAUSTION_MIN = 0.55
_STOPPING_REACTION_MIN = 0.3


def _up_stopping_evidence(snap: FeatureSnapshot) -> bool:
    return (
        float(snap.up_exhaustion_support) >= _STOPPING_EXHAUSTION_MIN
        and float(snap.reaction_strength) >= _STOPPING_REACTION_MIN
    )


def _down_stopping_evidence(snap: FeatureSnapshot) -> bool:
    return (
        float(snap.down_exhaustion_support) >= _STOPPING_EXHAUSTION_MIN
        and float(snap.reaction_strength) >= _STOPPING_REACTION_MIN
    )


class ShadowAuctionAES2:
    """Four independent TF engines sharing params, never sharing state."""

    def __init__(
        self,
        *,
        params: Mapping[str, Any] | None = None,
        logic_version: str = "AES_V1",
        logic_fingerprint: str = "",
        timeframes: tuple[str, ...] = ("M15", "M30", "H1", "H4"),
    ) -> None:
        merged = merge_aes2_params({"aes2": dict(params or {})})
        self.params = merged
        self.engines = {
            tf: TimeframeAuctionEngine(
                tf,
                params=merged,
                logic_version=logic_version,
                logic_fingerprint=logic_fingerprint,
            )
            for tf in timeframes
        }

    def process(self, obs: BarObservation) -> TransitionResult:
        tf = obs.timeframe.upper()
        if tf not in self.engines:
            raise KeyError(f"unsupported timeframe: {tf}")
        return self.engines[tf].process(obs)

    def health_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "aes2_events_written": sum(e.events_written for e in self.engines.values()),
            "aes2_transitions_written": sum(e.transitions_written for e in self.engines.values()),
            "open_tf_episodes": sum(
                1 for e in self.engines.values() if e.state.shadow_episode_id is not None
            ),
        }
        for tf, eng in self.engines.items():
            key = tf.lower()
            out[f"{key}_auction_family"] = eng.state.auction_family
            out[f"{key}_episode_phase"] = eng.state.episode_phase
            out[f"{key}_episode_id"] = eng.state.shadow_episode_id
        return out

    def tf_state_views(self, *, timestamp: str | None = None) -> dict[str, Any]:
        """Read-only AES2 state views for AES3. Does not mutate engines."""
        from .hierarchy import tf_state_view_from_engine

        return {
            tf: tf_state_view_from_engine(eng, timestamp=timestamp)
            for tf, eng in self.engines.items()
        }
