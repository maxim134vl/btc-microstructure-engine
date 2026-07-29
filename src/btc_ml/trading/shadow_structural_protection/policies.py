"""Structural policy IDs and decision geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import (
    BUFFER_POLICIES,
    DEFAULT_TICK_SIZE,
    ECONOMIC_GATES,
    TAKE_POLICIES,
    VOLUME_CLASS_POLICIES,
    ZONE_METHODS,
)


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    kind: str  # BASELINE | STRUCTURAL_SL_CANONICAL_TP | CANONICAL_SL_STRUCTURAL_TP | STRUCTURAL_SL_TP
    volume_class_policy: str | None
    zone_method: str | None
    buffer_policy: str | None
    take_policy: str | None
    economic_gate: str


def build_policy_specs() -> list[PolicySpec]:
    specs: list[PolicySpec] = [
        PolicySpec("BASELINE_CANONICAL", "BASELINE", None, None, None, None, "NO_ECONOMIC_GATE")
    ]
    # Parallel structural research at NO_GATE across class × zone × buffer × take
    for vc in VOLUME_CLASS_POLICIES:
        for zm in ZONE_METHODS:
            for buf in BUFFER_POLICIES:
                for take in TAKE_POLICIES:
                    pid = f"STRUCTURAL_SL_TP_NO_GATE__{vc}__{zm}__{buf}__{take}"
                    specs.append(PolicySpec(pid, "STRUCTURAL_SL_TP", vc, zm, buf, take, "NO_ECONOMIC_GATE"))
    # Economic gates on preferred combo
    pref_vc, pref_zm, pref_buf, pref_take = (
        "ALL_CANONICAL_SIGNIFICANT",
        "POC_VALUE_AREA_70",
        "DISTAL_PLUS_ONE_TICK",
        "TP_POC",
    )
    for gate in ECONOMIC_GATES:
        if gate == "NO_ECONOMIC_GATE":
            continue
        pid = f"STRUCTURAL_SL_TP_{gate}__{pref_vc}__{pref_zm}__{pref_buf}__{pref_take}"
        specs.append(PolicySpec(pid, "STRUCTURAL_SL_TP", pref_vc, pref_zm, pref_buf, pref_take, gate))
    # Structural SL + canonical TP (1.5R on structural risk) per zone method
    for zm in ZONE_METHODS:
        pid = f"STRUCTURAL_SL_CANONICAL_TP__ALL_CANONICAL_SIGNIFICANT__{zm}__DISTAL_PLUS_ONE_TICK"
        specs.append(
            PolicySpec(pid, "STRUCTURAL_SL_CANONICAL_TP", "ALL_CANONICAL_SIGNIFICANT", zm, "DISTAL_PLUS_ONE_TICK", None, "NO_ECONOMIC_GATE")
        )
    # Canonical SL + structural TP
    for zm in ZONE_METHODS:
        for take in TAKE_POLICIES:
            pid = f"CANONICAL_SL_STRUCTURAL_TP__ALL_CANONICAL_SIGNIFICANT__{zm}__{take}"
            specs.append(
                PolicySpec(pid, "CANONICAL_SL_STRUCTURAL_TP", "ALL_CANONICAL_SIGNIFICANT", zm, None, take, "NO_ECONOMIC_GATE")
            )
    return specs


POLICY_SPECS = build_policy_specs()
POLICY_IDS = tuple(p.policy_id for p in POLICY_SPECS)


def structural_stop_price(
    *,
    side: str,
    zone: dict[str, Any],
    buffer_policy: str,
    tick_size: float = DEFAULT_TICK_SIZE,
    executable_spread: float | None,
) -> float:
    side_u = str(side).upper()
    if buffer_policy == "DISTAL_PLUS_ONE_TICK":
        buf = float(tick_size)
    elif buffer_policy == "DISTAL_PLUS_EXECUTABLE_SPREAD":
        buf = float(executable_spread) if executable_spread and executable_spread > 0 else float(tick_size)
    else:
        buf = float(tick_size)
    if side_u == "LONG":
        return float(zone["lower_boundary"]) - buf
    return float(zone["upper_boundary"]) + buf


def structural_take_price(*, side: str, zone: dict[str, Any], take_policy: str) -> float:
    side_u = str(side).upper()
    lower = float(zone["lower_boundary"])
    upper = float(zone["upper_boundary"])
    poc = float(zone["peak_volume_price"])
    if take_policy == "TP_POC":
        return poc
    if side_u == "LONG":
        if take_policy == "TP_PROXIMAL":
            return lower
        return upper  # TP_DISTAL
    # SHORT
    if take_policy == "TP_PROXIMAL":
        return upper
    return lower


def net_r_threshold(gate: str) -> float | None:
    mapping = {
        "NO_ECONOMIC_GATE": None,
        "NET_R_MIN_075": 0.75,
        "NET_R_MIN_100": 1.0,
        "NET_R_MIN_125": 1.25,
        "NET_R_MIN_150": 1.5,
        "NET_R_MIN_200": 2.0,
    }
    return mapping.get(gate)


def geometry_valid(*, side: str, entry: float, stop: float, take: float) -> tuple[bool, str | None]:
    side_u = str(side).upper()
    if side_u == "LONG":
        if not (stop < entry < take):
            return False, "SKIP_INVALID_STOP_GEOMETRY" if stop >= entry else "SKIP_INVALID_TARGET_GEOMETRY"
    else:
        if not (take < entry < stop):
            return False, "SKIP_INVALID_TARGET_GEOMETRY" if take >= entry else "SKIP_INVALID_STOP_GEOMETRY"
    return True, None
