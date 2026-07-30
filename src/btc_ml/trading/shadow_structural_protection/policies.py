"""Structural policy IDs and decision geometry (SHADOW-STP2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import DEFAULT_TICK_SIZE
from .reaction import REACTION_THRESHOLDS, ZONE_AGE_POLICIES


ZONE_METHODS = ("POC_BIN", "POC_CONTIGUOUS_50", "POC_VALUE_AREA_70")
VOLUME_CLASS_POLICIES = ("CLIMAX_ONLY", "CLIMAX_OR_STOPPING", "ALL_CANONICAL_SIGNIFICANT")
BUFFER_POLICIES = ("ONE_TICK", "EXECUTABLE_SPREAD", "MAX_ONE_TICK_OR_SPREAD")
TAKE_POLICIES = ("TARGET_PROXIMAL", "TARGET_POC", "TARGET_DISTAL")
ECONOMIC_GATES = (
    "NO_NET_R_GATE",
    "NET_R_MIN_075",
    "NET_R_MIN_100",
    "NET_R_MIN_125",
    "NET_R_MIN_150",
    "NET_R_MIN_200",
)
# Legacy aliases kept for geometry helpers / older tests
LEGACY_BUFFER_ALIASES = {
    "DISTAL_PLUS_ONE_TICK": "ONE_TICK",
    "DISTAL_PLUS_EXECUTABLE_SPREAD": "EXECUTABLE_SPREAD",
}
LEGACY_TAKE_ALIASES = {
    "TP_PROXIMAL": "TARGET_PROXIMAL",
    "TP_POC": "TARGET_POC",
    "TP_DISTAL": "TARGET_DISTAL",
}
LEGACY_GATE_ALIASES = {
    "NO_ECONOMIC_GATE": "NO_NET_R_GATE",
}


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    kind: str  # BASELINE | STRUCTURAL_SL_CANONICAL_TP | CANONICAL_SL_STRUCTURAL_TP | STRUCTURAL_SL_STRUCTURAL_TP
    volume_class_policy: str | None
    zone_method: str | None
    buffer_policy: str | None
    take_policy: str | None
    economic_gate: str
    reaction_threshold_id: str | None = None
    zone_age_policy: str | None = None


def build_policy_specs() -> list[PolicySpec]:
    specs: list[PolicySpec] = [
        PolicySpec("BASELINE_CANONICAL", "BASELINE", None, None, None, None, "NO_NET_R_GATE")
    ]
    pref_vc = "ALL_CANONICAL_SIGNIFICANT"
    pref_zm = "POC_VALUE_AREA_70"
    pref_buf = "MAX_ONE_TICK_OR_SPREAD"
    pref_take = "TARGET_POC"
    pref_react = "REACTION_100_ZONE_WIDTH"
    pref_age = "ZONE_AGE_4_BARS"

    # Parallel geometry research at preferred reaction/age
    for vc in VOLUME_CLASS_POLICIES:
        for zm in ZONE_METHODS:
            for buf in BUFFER_POLICIES:
                for take in TAKE_POLICIES:
                    pid = (
                        f"STRUCTURAL_SL_STRUCTURAL_TP_NO_GATE__{vc}__{zm}__{buf}__{take}"
                        f"__{pref_react}__{pref_age}"
                    )
                    specs.append(
                        PolicySpec(
                            pid,
                            "STRUCTURAL_SL_STRUCTURAL_TP",
                            vc,
                            zm,
                            buf,
                            take,
                            "NO_NET_R_GATE",
                            pref_react,
                            pref_age,
                        )
                    )

    # Reaction threshold sweep
    for react in REACTION_THRESHOLDS:
        if react == pref_react:
            continue
        pid = (
            f"STRUCTURAL_SL_STRUCTURAL_TP_NO_GATE__{pref_vc}__{pref_zm}__{pref_buf}__{pref_take}"
            f"__{react}__{pref_age}"
        )
        specs.append(
            PolicySpec(
                pid,
                "STRUCTURAL_SL_STRUCTURAL_TP",
                pref_vc,
                pref_zm,
                pref_buf,
                pref_take,
                "NO_NET_R_GATE",
                react,
                pref_age,
            )
        )

    # Zone age sweep
    for age in ZONE_AGE_POLICIES:
        if age == pref_age:
            continue
        pid = (
            f"STRUCTURAL_SL_STRUCTURAL_TP_NO_GATE__{pref_vc}__{pref_zm}__{pref_buf}__{pref_take}"
            f"__{pref_react}__{age}"
        )
        specs.append(
            PolicySpec(
                pid,
                "STRUCTURAL_SL_STRUCTURAL_TP",
                pref_vc,
                pref_zm,
                pref_buf,
                pref_take,
                "NO_NET_R_GATE",
                pref_react,
                age,
            )
        )

    # Economic gates on preferred combo
    for gate in ECONOMIC_GATES:
        if gate == "NO_NET_R_GATE":
            continue
        pid = (
            f"STRUCTURAL_SL_STRUCTURAL_TP_{gate}__{pref_vc}__{pref_zm}__{pref_buf}__{pref_take}"
            f"__{pref_react}__{pref_age}"
        )
        specs.append(
            PolicySpec(
                pid,
                "STRUCTURAL_SL_STRUCTURAL_TP",
                pref_vc,
                pref_zm,
                pref_buf,
                pref_take,
                gate,
                pref_react,
                pref_age,
            )
        )

    # Structural SL + canonical TP
    for zm in ZONE_METHODS:
        for react in REACTION_THRESHOLDS:
            for age in ("ZONE_AGE_4_BARS", "ZONE_UNTIL_INVALIDATED"):
                pid = f"STRUCTURAL_SL_CANONICAL_TP__{pref_vc}__{zm}__{pref_buf}__{react}__{age}"
                specs.append(
                    PolicySpec(
                        pid,
                        "STRUCTURAL_SL_CANONICAL_TP",
                        pref_vc,
                        zm,
                        pref_buf,
                        None,
                        "NO_NET_R_GATE",
                        react,
                        age,
                    )
                )

    # Canonical SL + structural TP
    for zm in ZONE_METHODS:
        for take in TAKE_POLICIES:
            pid = f"CANONICAL_SL_STRUCTURAL_TP__{pref_vc}__{zm}__{take}__{pref_react}__{pref_age}"
            specs.append(
                PolicySpec(
                    pid,
                    "CANONICAL_SL_STRUCTURAL_TP",
                    pref_vc,
                    zm,
                    None,
                    take,
                    "NO_NET_R_GATE",
                    pref_react,
                    pref_age,
                )
            )
    return specs


POLICY_SPECS = build_policy_specs()
POLICY_IDS = tuple(p.policy_id for p in POLICY_SPECS)


def _norm_buffer(buffer_policy: str) -> str:
    return LEGACY_BUFFER_ALIASES.get(buffer_policy, buffer_policy)


def _norm_take(take_policy: str) -> str:
    return LEGACY_TAKE_ALIASES.get(take_policy, take_policy)


def _norm_gate(gate: str) -> str:
    return LEGACY_GATE_ALIASES.get(gate, gate)


def structural_stop_price(
    *,
    side: str,
    zone: dict[str, Any],
    buffer_policy: str,
    tick_size: float = DEFAULT_TICK_SIZE,
    executable_spread: float | None,
) -> float:
    side_u = str(side).upper()
    buf_pol = _norm_buffer(buffer_policy)
    tick = float(tick_size)
    spread = float(executable_spread) if executable_spread and executable_spread > 0 else tick
    if buf_pol == "ONE_TICK":
        buf = tick
    elif buf_pol == "EXECUTABLE_SPREAD":
        buf = spread
    else:  # MAX_ONE_TICK_OR_SPREAD
        buf = max(tick, spread)
    if side_u == "LONG":
        return float(zone["lower_boundary"]) - buf
    return float(zone["upper_boundary"]) + buf


def structural_take_price(*, side: str, zone: dict[str, Any], take_policy: str) -> float:
    side_u = str(side).upper()
    lower = float(zone["lower_boundary"])
    upper = float(zone["upper_boundary"])
    poc = float(zone.get("peak_volume_price") or zone.get("POC") or ((lower + upper) / 2.0))
    pol = _norm_take(take_policy)
    if pol == "TARGET_POC":
        return poc
    if side_u == "LONG":
        if pol == "TARGET_PROXIMAL":
            return lower
        return upper  # TARGET_DISTAL
    if pol == "TARGET_PROXIMAL":
        return upper
    return lower


def net_r_threshold(gate: str) -> float | None:
    g = _norm_gate(gate)
    mapping = {
        "NO_NET_R_GATE": None,
        "NET_R_MIN_075": 0.75,
        "NET_R_MIN_100": 1.0,
        "NET_R_MIN_125": 1.25,
        "NET_R_MIN_150": 1.5,
        "NET_R_MIN_200": 2.0,
    }
    return mapping.get(g)


def geometry_valid(*, side: str, entry: float, stop: float, take: float) -> tuple[bool, str | None]:
    side_u = str(side).upper()
    if side_u == "LONG":
        if not (stop < entry < take):
            return False, "SKIP_INVALID_STOP_GEOMETRY" if stop >= entry else "SKIP_INVALID_TARGET_GEOMETRY"
    else:
        if not (take < entry < stop):
            return False, "SKIP_INVALID_TARGET_GEOMETRY" if take >= entry else "SKIP_INVALID_STOP_GEOMETRY"
    return True, None
