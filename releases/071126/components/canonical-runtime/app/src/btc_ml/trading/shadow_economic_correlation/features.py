"""Decision-time feature snapshots from canonical sources only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import FIELD_NOT_AVAILABLE


def _get(obj: dict[str, Any] | None, *keys: str, default: Any = FIELD_NOT_AVAILABLE) -> Any:
    if not isinstance(obj, dict):
        return default
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    if cur is None:
        return default
    return cur


def parse_ts(value: Any) -> datetime | None:
    if value is None or value is FIELD_NOT_AVAILABLE:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def build_decision_time_features(
    *,
    candidate: dict[str, Any],
    context_event: dict[str, Any] | None,
    open_positions_before: list[dict[str, Any]],
) -> dict[str, Any]:
    """Snapshot only fields available at/before decision; never invent features."""
    evidence = _get(context_event, "evidence", default={})
    if evidence is FIELD_NOT_AVAILABLE:
        evidence = {}
    synthesis = evidence.get("synthesis") if isinstance(evidence, dict) else {}
    if not isinstance(synthesis, dict):
        synthesis = {}

    ctx_ts = _get(context_event, "event_timestamp")
    cand_ts = candidate.get("candidate_timestamp") or candidate.get("entry_timestamp")
    ctx_dt = parse_ts(ctx_ts)
    cand_dt = parse_ts(cand_ts)
    context_age = FIELD_NOT_AVAILABLE
    if ctx_dt and cand_dt:
        context_age = max(0.0, (cand_dt - ctx_dt).total_seconds())

    ctx_price = _get(context_event, "context_event_price")
    entry_px = candidate.get("entry_executable_price")
    entry_distance = FIELD_NOT_AVAILABLE
    try:
        if ctx_price is not FIELD_NOT_AVAILABLE and entry_px is not None:
            entry_distance = float(entry_px) - float(ctx_price)
    except (TypeError, ValueError):
        entry_distance = FIELD_NOT_AVAILABLE

    return {
        "economic_quality_mode": "DATA_COLLECTION",
        "timeframe": candidate.get("timeframe"),
        "side": candidate.get("side"),
        "context_event_id": candidate.get("context_event_id"),
        "episode_id": candidate.get("lifecycle_episode_id"),
        "context_start_timestamp": ctx_ts,
        "candidate_timestamp": cand_ts,
        "context_age_seconds": context_age,
        "context_price": ctx_price,
        "entry_executable_price": entry_px,
        "entry_distance_from_context_price": entry_distance,
        "current_market_state": {
            "best_bid": _get(context_event, "best_bid"),
            "best_ask": _get(context_event, "best_ask"),
            "bbo_age_ms": _get(context_event, "bbo_age_ms"),
            "open_positions_count_before": len(open_positions_before),
        },
        "existing_cognition_classifications": {
            "new_context": _get(context_event, "new_context"),
            "previous_context": _get(context_event, "previous_context"),
            "lifecycle_phase": _get(evidence if isinstance(evidence, dict) else {}, "lifecycle_phase"),
            "evaluation_mode": _get(context_event, "evaluation_mode"),
        },
        "existing_structural_rank": FIELD_NOT_AVAILABLE,
        "existing_persistence": FIELD_NOT_AVAILABLE,
        "existing_location_bias": _get(synthesis, "localized_behavior"),
        "existing_auction_classification": FIELD_NOT_AVAILABLE,
        "existing_confidence_fields": FIELD_NOT_AVAILABLE,
        "existing_validation_fields": FIELD_NOT_AVAILABLE,
        "existing_volume_event": _get(synthesis, "volume_event"),
        "existing_effort_result_state": _get(synthesis, "effort_result_state"),
        "feature_audit": {
            "available": [
                "timeframe",
                "side",
                "context_event_id",
                "episode_id",
                "context_start_timestamp",
                "candidate_timestamp",
                "context_age_seconds",
                "context_price",
                "entry_executable_price",
                "entry_distance_from_context_price",
                "best_bid",
                "best_ask",
                "new_context",
                "previous_context",
                "lifecycle_phase",
                "localized_behavior",
                "volume_event",
                "effort_result_state",
            ],
            "not_available": [
                "existing_structural_rank",
                "existing_persistence",
                "existing_auction_classification",
                "existing_confidence_fields",
                "existing_validation_fields",
            ],
        },
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
