"""Same-direction BTC correlation cluster snapshots."""

from __future__ import annotations

from typing import Any


def _side_cluster(side: str) -> str:
    u = str(side or "").upper()
    if u == "LONG":
        return "BTC_LONG"
    if u == "SHORT":
        return "BTC_SHORT"
    return "UNKNOWN"


def _notional(row: dict[str, Any]) -> float:
    if row.get("notional_usd") is not None:
        return float(row["notional_usd"])
    q = float(row.get("quantity") or 0.0)
    px = float(row.get("entry_price") or row.get("entry_executable_price") or 0.0)
    return abs(q * px)


def _risk(row: dict[str, Any]) -> float:
    return abs(float(row.get("risk_amount_usd") or row.get("risk_budget_usd") or 0.0))


def build_cluster_snapshot(
    *,
    candidate: dict[str, Any],
    open_positions_before: list[dict[str, Any]],
) -> dict[str, Any]:
    side = str(candidate.get("side") or "").upper()
    cluster = _side_cluster(side)
    same = [p for p in open_positions_before if str(p.get("side") or "").upper() == side]
    opp_side = "SHORT" if side == "LONG" else "LONG"
    opposite = [p for p in open_positions_before if str(p.get("side") or "").upper() == opp_side]

    same_risk = sum(_risk(p) for p in same)
    same_notional = sum(_notional(p) for p in same)
    opp_risk = sum(_risk(p) for p in opposite)
    opp_notional = sum(_notional(p) for p in opposite)
    long_pos = [p for p in open_positions_before if str(p.get("side") or "").upper() == "LONG"]
    short_pos = [p for p in open_positions_before if str(p.get("side") or "").upper() == "SHORT"]
    long_risk = sum(_risk(p) for p in long_pos)
    short_risk = sum(_risk(p) for p in short_pos)
    long_notional = sum(_notional(p) for p in long_pos)
    short_notional = sum(_notional(p) for p in short_pos)
    cand_risk = _risk(candidate)
    cand_notional = _notional(candidate)

    arrival = len(same) + 1  # 1-indexed position in direction cluster after acceptance intent

    return {
        "cluster_id": cluster,
        "candidate_side": side,
        "same_direction_positions_before": len(same),
        "same_direction_timeframes_before": sorted({str(p.get("timeframe")) for p in same}),
        "same_direction_open_risk_before": same_risk,
        "same_direction_notional_before": same_notional,
        "same_direction_unrealized_pnl_before": sum(float(p.get("unrealized_pnl_usd") or 0.0) for p in same),
        "opposite_direction_positions_before": len(opposite),
        "opposite_direction_timeframes_before": sorted({str(p.get("timeframe")) for p in opposite}),
        "opposite_direction_open_risk_before": opp_risk,
        "opposite_direction_notional_before": opp_notional,
        "master_open_risk_before": same_risk + opp_risk,  # gross absolute
        "master_open_notional_before": same_notional + opp_notional,
        "gross_risk_before": long_risk + short_risk,
        "gross_notional_before": long_notional + short_notional,
        "long_risk_before": long_risk,
        "short_risk_before": short_risk,
        "net_directional_notional_before": long_notional - short_notional,
        "arrival_sequence_in_direction_cluster": arrival,
        "same_direction_positions_after": len(same) + 1,
        "same_direction_open_risk_after": same_risk + cand_risk,
        "same_direction_notional_after": same_notional + cand_notional,
        "master_open_risk_after": same_risk + opp_risk + cand_risk,
        "master_open_notional_after": same_notional + opp_notional + cand_notional,
        "gross_risk_after": long_risk + short_risk + cand_risk,
        "gross_notional_after": long_notional + short_notional + cand_notional,
        "long_risk_after": long_risk + (cand_risk if side == "LONG" else 0.0),
        "short_risk_after": short_risk + (cand_risk if side == "SHORT" else 0.0),
        "net_directional_notional_after": (long_notional - short_notional)
        + (cand_notional if side == "LONG" else -cand_notional),
        # Explicit: opposite risk is never netted away for limits.
        "risk_limits_use_absolute_gross": True,
        "opposite_risk_netting_forbidden": True,
    }
