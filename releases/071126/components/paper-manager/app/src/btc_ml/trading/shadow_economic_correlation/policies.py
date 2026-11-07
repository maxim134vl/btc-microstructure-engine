"""Virtual correlation / capital allocation policies (observe-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import STRUCTURAL, TACTICAL


@dataclass(frozen=True)
class PolicyDecision:
    policy_id: str
    action: str  # EXECUTE_FULL | EXECUTE_REDUCED | BLOCK_CORRELATED_EXPOSURE
    risk_multiplier: float
    reason: str


def _open_same(policy_open: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    return [p for p in policy_open if str(p.get("side") or "").upper() == str(side).upper()]


def decide_policy(
    *,
    policy_id: str,
    candidate: dict[str, Any],
    cluster: dict[str, Any],
    policy_open_positions: list[dict[str, Any]],
    master_equity_usd: float = 400_000.0,
) -> PolicyDecision:
    side = str(candidate.get("side") or "").upper()
    tf = str(candidate.get("timeframe") or "").upper()
    same_open = _open_same(policy_open_positions, side)
    same_count = len(same_open)
    standard_risk = float(candidate.get("risk_budget_usd") or candidate.get("risk_amount_usd") or 0.0)
    same_risk = sum(abs(float(p.get("risk_amount_usd") or p.get("risk_budget_usd") or 0.0)) for p in same_open)
    # Cluster arrival remains available for research snapshots; policies use local book state.
    _ = cluster

    if policy_id == "BASELINE_ALL_ELIGIBLE":
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "baseline_execute_all")

    if policy_id.endswith("_ONLY"):
        only_tf = policy_id.replace("_ONLY", "")
        if tf != only_tf:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, f"tf_filter_{only_tf}")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "tf_only_execute")

    if policy_id == "MAX_1_SAME_DIRECTION":
        if same_count >= 1:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "max_1_same_direction")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "first_in_direction")

    if policy_id == "MAX_2_SAME_DIRECTION":
        if same_count >= 2:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "max_2_same_direction")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "within_max_2")

    if policy_id == "MAX_3_SAME_DIRECTION":
        if same_count >= 3:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "max_3_same_direction")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "within_max_3")

    if policy_id == "ONE_TACTICAL_ONE_STRUCTURAL":
        group = "TACTICAL" if tf in TACTICAL else "STRUCTURAL" if tf in STRUCTURAL else "OTHER"
        if group == "OTHER":
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "unknown_group")
        group_tfs = TACTICAL if group == "TACTICAL" else STRUCTURAL
        if any(str(p.get("timeframe") or "").upper() in group_tfs for p in same_open):
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, f"{group}_already_open")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, f"{group}_slot_open")

    if policy_id == "PROGRESSIVE_RISK_REDUCTION":
        # Causal arrival inside this policy's own virtual book (not real master book).
        policy_arrival = same_count + 1
        mult = {1: 1.0, 2: 0.5, 3: 0.25}.get(policy_arrival, 0.0)
        if mult <= 0:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "progressive_4th_blocked")
        if mult < 1.0:
            return PolicyDecision(policy_id, "EXECUTE_REDUCED", mult, f"progressive_arrival_{policy_arrival}")
        return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, "progressive_first")

    if policy_id.startswith("DIRECTION_RISK_CAP_"):
        # e.g. DIRECTION_RISK_CAP_025_BLOCK / _REDUCE
        parts = policy_id.split("_")
        # DIRECTION RISK CAP 025 BLOCK
        pct_token = parts[3]  # 025 / 050 / 075 / 100
        mode = parts[4]  # BLOCK / REDUCE
        pct = int(pct_token) / 10000.0  # 025 -> 0.0025
        cap = float(master_equity_usd) * pct
        remaining = max(0.0, cap - same_risk)
        if standard_risk <= remaining + 1e-12:
            return PolicyDecision(policy_id, "EXECUTE_FULL", 1.0, f"within_cap_{cap}")
        if mode == "BLOCK":
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, f"cap_block_{cap}")
        if remaining <= 0:
            return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, f"cap_exhausted_{cap}")
        mult = remaining / standard_risk if standard_risk > 0 else 0.0
        return PolicyDecision(policy_id, "EXECUTE_REDUCED", mult, f"cap_reduce_to_{remaining}")

    return PolicyDecision(policy_id, "BLOCK_CORRELATED_EXPOSURE", 0.0, "unknown_policy")
