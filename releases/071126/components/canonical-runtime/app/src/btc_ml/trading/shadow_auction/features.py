"""AES2 compact evidence features — research scores, NOT calibrated probabilities."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Mapping

from .observation import BarObservation

SCORE_DISCLAIMER = "NOT calibrated probability; research evidence score only"


@dataclass(frozen=True)
class FeatureSnapshot:
    # Effort
    volume_intensity: float
    delta_intensity: float
    activity_intensity: float  # §27 diagnostic; NOT used by AES2 state transitions
    buy_effort: float
    sell_effort: float
    oi_change: float | None
    range_expansion: float
    # Result
    price_displacement: float
    up_result: float
    down_result: float
    up_efficiency: float
    down_efficiency: float
    follow_through: float
    new_extreme_distance: float
    close_location: float
    # Response / acceptance helpers
    reaction_strength: float
    retrace_depth: float
    upper_rejection: float
    lower_rejection: float
    # Episode rolling
    efficiency_trend_up: float
    efficiency_trend_down: float
    pressure_persistence_up: float
    pressure_persistence_down: float
    # Extreme participation flags (attention only — not climax verdict)
    extreme_up_participation: bool
    extreme_down_participation: bool
    # Support scores (documented non-probability)
    up_continuation_support: float
    down_continuation_support: float
    up_exhaustion_support: float
    down_exhaustion_support: float
    balance_support: float
    up_resolution_support: float
    down_resolution_support: float
    score_disclaimer: str = SCORE_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "volume_intensity": self.volume_intensity,
            "delta_intensity": self.delta_intensity,
            "activity_intensity": self.activity_intensity,
            "buy_effort": self.buy_effort,
            "sell_effort": self.sell_effort,
            "oi_change": self.oi_change,
            "range_expansion": self.range_expansion,
            "price_displacement": self.price_displacement,
            "up_result": self.up_result,
            "down_result": self.down_result,
            "up_efficiency": self.up_efficiency,
            "down_efficiency": self.down_efficiency,
            "follow_through": self.follow_through,
            "new_extreme_distance": self.new_extreme_distance,
            "close_location": self.close_location,
            "reaction_strength": self.reaction_strength,
            "retrace_depth": self.retrace_depth,
            "upper_rejection": self.upper_rejection,
            "lower_rejection": self.lower_rejection,
            "efficiency_trend_up": self.efficiency_trend_up,
            "efficiency_trend_down": self.efficiency_trend_down,
            "pressure_persistence_up": self.pressure_persistence_up,
            "pressure_persistence_down": self.pressure_persistence_down,
            "extreme_up_participation": self.extreme_up_participation,
            "extreme_down_participation": self.extreme_down_participation,
            "up_continuation_support": self.up_continuation_support,
            "down_continuation_support": self.down_continuation_support,
            "up_exhaustion_support": self.up_exhaustion_support,
            "down_exhaustion_support": self.down_exhaustion_support,
            "balance_support": self.balance_support,
            "up_resolution_support": self.up_resolution_support,
            "down_resolution_support": self.down_resolution_support,
            "score_disclaimer": self.score_disclaimer,
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _safe_div(num: float, den: float) -> float:
    if abs(den) < 1e-12:
        return 0.0
    return float(num) / float(den)


class FeatureEngine:
    """Rolling feature computer with UP/DOWN symmetry."""

    def __init__(self, *, window: int = 8, extreme_volume_z: float = 1.5) -> None:
        self.window = max(2, int(window))
        self.extreme_volume_z = float(extreme_volume_z)
        self._bars: Deque[BarObservation] = deque(maxlen=self.window)
        self._up_eff: Deque[float] = deque(maxlen=self.window)
        self._down_eff: Deque[float] = deque(maxlen=self.window)

    def reset(self) -> None:
        self._bars.clear()
        self._up_eff.clear()
        self._down_eff.clear()

    def update(self, obs: BarObservation) -> FeatureSnapshot:
        self._bars.append(obs)
        ov = dict(obs.feature_overrides or {})

        spread = obs.spread if obs.spread is not None else max(obs.high - obs.low, 0.0)
        body = obs.body if obs.body is not None else abs(obs.close - obs.open)
        close_loc = (
            obs.close_position
            if obs.close_position is not None
            else _safe_div(obs.close - obs.low, spread if spread > 0 else 1.0)
        )

        vol_z = obs.volume_zscore if obs.volume_zscore is not None else 0.0
        volume_intensity = _clamp((vol_z + 2.0) / 4.0) if obs.volume_zscore is not None else _clamp(body / (spread + 1e-9))

        if obs.delta is not None and obs.volume > 0:
            delta_intensity = _clamp(abs(obs.delta) / obs.volume)
            signed_delta = obs.delta / obs.volume
        elif obs.buy_volume is not None and obs.sell_volume is not None and obs.volume > 0:
            signed_delta = (obs.buy_volume - obs.sell_volume) / obs.volume
            delta_intensity = _clamp(abs(signed_delta))
        else:
            signed_delta = _safe_div(obs.close - obs.open, spread if spread > 0 else 1.0)
            delta_intensity = _clamp(abs(signed_delta))

        buy_share = 0.5 + 0.5 * max(0.0, signed_delta)
        sell_share = 0.5 + 0.5 * max(0.0, -signed_delta)
        buy_effort = _clamp(volume_intensity * buy_share)
        sell_effort = _clamp(volume_intensity * sell_share)

        # Result: directional close acceptance + bar displacement.
        up_result = _clamp(max(0.0, signed_delta) * (0.5 + 0.5 * close_loc))
        down_result = _clamp(max(0.0, -signed_delta) * (0.5 + 0.5 * (1.0 - close_loc)))
        if obs.result_score is not None:
            # Map signed result_score into directional halves when present.
            if obs.result_score >= 0:
                up_result = _clamp(0.5 * up_result + 0.5 * _clamp(obs.result_score))
            else:
                down_result = _clamp(0.5 * down_result + 0.5 * _clamp(-obs.result_score))
        if obs.effort_score is not None:
            if signed_delta >= 0:
                buy_effort = _clamp(0.5 * buy_effort + 0.5 * _clamp(obs.effort_score / 2.0))
            else:
                sell_effort = _clamp(0.5 * sell_effort + 0.5 * _clamp(obs.effort_score / 2.0))

        up_efficiency = _clamp(_safe_div(up_result, buy_effort + 1e-6))
        down_efficiency = _clamp(_safe_div(down_result, sell_effort + 1e-6))
        self._up_eff.append(up_efficiency)
        self._down_eff.append(down_efficiency)

        # Range expansion vs prior bar.
        if len(self._bars) >= 2:
            prev = self._bars[-2]
            prev_spread = prev.spread if prev.spread is not None else max(prev.high - prev.low, 1e-9)
            range_expansion = _clamp(_safe_div(spread, prev_spread) / 2.0)
            price_displacement = abs(obs.close - prev.close)
            follow_through = _clamp(
                _safe_div(obs.close - prev.close, abs(prev.close - prev.open) + 1e-9) * 0.5 + 0.5
            )
        else:
            range_expansion = _clamp(spread / (abs(obs.close) * 0.001 + 1e-9) / 10.0)
            price_displacement = abs(obs.close - obs.open)
            follow_through = 0.5

        # New extreme vs window.
        window_high = max(b.high for b in self._bars)
        window_low = min(b.low for b in self._bars)
        new_high = obs.high >= window_high - 1e-12
        new_low = obs.low <= window_low + 1e-12
        new_extreme_distance = 0.0
        if new_high and len(self._bars) >= 2:
            prev_high = max(b.high for b in list(self._bars)[:-1])
            new_extreme_distance = max(0.0, obs.high - prev_high)
        if new_low and len(self._bars) >= 2:
            prev_low = min(b.low for b in list(self._bars)[:-1])
            new_extreme_distance = max(new_extreme_distance, max(0.0, prev_low - obs.low))

        upper_rej = 1.0 if obs.upper_rejection else _clamp(_safe_div(obs.upper_wick or 0.0, spread + 1e-9))
        lower_rej = 1.0 if obs.lower_rejection else _clamp(_safe_div(obs.lower_wick or 0.0, spread + 1e-9))

        # Reaction / retrace vs prior directional move.
        if len(self._bars) >= 2:
            prev = self._bars[-2]
            prior_move = prev.close - prev.open
            retrace = obs.close - prev.close
            if prior_move != 0:
                retrace_depth = _clamp(abs(retrace) / (abs(prior_move) + 1e-9))
                reaction_strength = _clamp(retrace_depth if (prior_move * retrace) < 0 else 0.0)
            else:
                retrace_depth = 0.0
                reaction_strength = 0.0
        else:
            retrace_depth = 0.0
            reaction_strength = 0.0

        eff_trend_up = _trend(self._up_eff)
        eff_trend_down = _trend(self._down_eff)
        persist_up = _clamp(sum(1 for x in self._up_eff if x >= 0.45) / max(len(self._up_eff), 1))
        persist_down = _clamp(sum(1 for x in self._down_eff if x >= 0.45) / max(len(self._down_eff), 1))

        climax = (obs.climax_state or "").upper()
        participation = (obs.participation_state or "").upper()
        extreme_vol = vol_z >= self.extreme_volume_z or "CLIMAX" in climax or "CLIMACTIC" in participation
        extreme_up = bool(extreme_vol and signed_delta >= 0)
        extreme_down = bool(extreme_vol and signed_delta < 0)

        up_cont = _clamp(0.45 * up_efficiency + 0.25 * persist_up + 0.20 * up_result + 0.10 * (1.0 if new_high else 0.0))
        down_cont = _clamp(
            0.45 * down_efficiency + 0.25 * persist_down + 0.20 * down_result + 0.10 * (1.0 if new_low else 0.0)
        )
        up_exh = _clamp(
            0.40 * buy_effort + 0.30 * max(0.0, -eff_trend_up) + 0.20 * upper_rej + 0.10 * reaction_strength
        )
        down_exh = _clamp(
            0.40 * sell_effort + 0.30 * max(0.0, -eff_trend_down) + 0.20 * lower_rej + 0.10 * reaction_strength
        )

        # Balance support: low net displacement + two-sided effort.
        if len(self._bars) >= 3:
            net = abs(self._bars[-1].close - self._bars[0].close)
            path = sum(abs(b.close - b.open) for b in self._bars)
            rotation = _clamp(1.0 - _safe_div(net, path + 1e-9))
            two_sided = 1.0 - abs(buy_effort - sell_effort)
            balance_support = _clamp(0.6 * rotation + 0.4 * two_sided)
        else:
            balance_support = 0.0

        up_res = _clamp(0.5 * up_cont + 0.3 * (1.0 if new_high else 0.0) + 0.2 * follow_through)
        down_res = _clamp(0.5 * down_cont + 0.3 * (1.0 if new_low else 0.0) + 0.2 * (1.0 - follow_through + 0.5))

        snap = FeatureSnapshot(
            volume_intensity=float(ov.get("volume_intensity", volume_intensity)),
            delta_intensity=float(ov.get("delta_intensity", delta_intensity)),
            activity_intensity=float(
                ov.get(
                    "activity_intensity",
                    _clamp(
                        0.5 * float(ov.get("volume_intensity", volume_intensity))
                        + 0.5 * float(ov.get("delta_intensity", delta_intensity))
                    ),
                )
            ),
            buy_effort=float(ov.get("buy_effort", buy_effort)),
            sell_effort=float(ov.get("sell_effort", sell_effort)),
            oi_change=obs.oi_change,
            range_expansion=float(ov.get("range_expansion", range_expansion)),
            price_displacement=float(ov.get("price_displacement", price_displacement)),
            up_result=float(ov.get("up_result", up_result)),
            down_result=float(ov.get("down_result", down_result)),
            up_efficiency=float(ov.get("up_efficiency", up_efficiency)),
            down_efficiency=float(ov.get("down_efficiency", down_efficiency)),
            follow_through=float(ov.get("follow_through", follow_through)),
            new_extreme_distance=float(ov.get("new_extreme_distance", new_extreme_distance)),
            close_location=float(ov.get("close_location", close_loc)),
            reaction_strength=float(ov.get("reaction_strength", reaction_strength)),
            retrace_depth=float(ov.get("retrace_depth", retrace_depth)),
            upper_rejection=float(ov.get("upper_rejection", upper_rej)),
            lower_rejection=float(ov.get("lower_rejection", lower_rej)),
            efficiency_trend_up=float(ov.get("efficiency_trend_up", eff_trend_up)),
            efficiency_trend_down=float(ov.get("efficiency_trend_down", eff_trend_down)),
            pressure_persistence_up=float(ov.get("pressure_persistence_up", persist_up)),
            pressure_persistence_down=float(ov.get("pressure_persistence_down", persist_down)),
            extreme_up_participation=bool(ov.get("extreme_up_participation", extreme_up)),
            extreme_down_participation=bool(ov.get("extreme_down_participation", extreme_down)),
            up_continuation_support=float(ov.get("up_continuation_support", up_cont)),
            down_continuation_support=float(ov.get("down_continuation_support", down_cont)),
            up_exhaustion_support=float(ov.get("up_exhaustion_support", up_exh)),
            down_exhaustion_support=float(ov.get("down_exhaustion_support", down_exh)),
            balance_support=float(ov.get("balance_support", balance_support)),
            up_resolution_support=float(ov.get("up_resolution_support", up_res)),
            down_resolution_support=float(ov.get("down_resolution_support", down_res)),
        )
        return snap


def _trend(values: Deque[float]) -> float:
    if len(values) < 2:
        return 0.0
    first = list(values)[: max(1, len(values) // 2)]
    second = list(values)[max(1, len(values) // 2) :]
    return _clamp((sum(second) / len(second)) - (sum(first) / len(first)) + 0.5) * 2 - 1


def default_aes2_params() -> dict[str, Any]:
    return {
        "window_bars": {"M15": 8, "M30": 8, "H1": 6, "H4": 4},
        "extreme_volume_z": 1.5,
        "strong_efficiency": 0.55,
        "weak_efficiency": 0.28,
        "strong_effort": 0.55,
        "balance_min_bars": 4,
        "balance_support_enter": 0.55,
        "balance_max_net_disp_ratio": 0.40,
        "acceptance_bars_beyond": 2,
        "reaction_retrace_ratio": 0.35,
        "deterioration_effort_rise": 0.05,
        "deterioration_result_drop": 0.05,
    }


def merge_aes2_params(config: Mapping[str, Any] | None) -> dict[str, Any]:
    base = default_aes2_params()
    raw = dict((config or {}).get("aes2") or {})
    for key, value in raw.items():
        if key == "window_bars" and isinstance(value, dict):
            merged = dict(base["window_bars"])
            merged.update({str(k).upper(): int(v) for k, v in value.items()})
            base["window_bars"] = merged
        else:
            base[key] = value
    return base
