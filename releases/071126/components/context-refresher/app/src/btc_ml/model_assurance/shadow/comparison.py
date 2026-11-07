"""Active-vs-shadow comparison (MODEL-7) — no economic/promotion scoring."""

from __future__ import annotations

from typing import Any

from btc_ml.model_assurance.toxic_box.common import canonical_json, sha256_text, utc_now_iso

DIRECTIONAL = frozenset({"LONG", "SHORT"})
NEUTRAL = frozenset({"OBSERVE", "STAND_ASIDE"})


def comparison_id(
    *,
    active_registry_record_id: str,
    candidate_registry_record_id: str,
    timeframe: str,
    causal_cutoff_monotonic_ns: Any,
) -> str:
    return "SHCMP_" + sha256_text(
        canonical_json(
            {
                "active_registry_record_id": active_registry_record_id,
                "candidate_registry_record_id": candidate_registry_record_id,
                "timeframe": timeframe,
                "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
            }
        )
    )[:32]


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).upper().strip()
    return text or None


def compare_active_shadow(
    *,
    active: dict[str, Any],
    candidate: dict[str, Any],
    timeframe: str,
    causal_cutoff_timestamp: str | None,
    causal_cutoff_monotonic_ns: Any,
    active_context: str | None,
    shadow_context: str | None,
    active_confidence: float | None = None,
    shadow_confidence: float | None = None,
    active_context_event_id: str | None = None,
    shadow_prediction_id: str | None = None,
) -> dict[str, Any]:
    a_ctx = _norm(active_context)
    s_ctx = _norm(shadow_context)
    if a_ctx is None and s_ctx is None:
        status = "NOT_EVALUABLE"
        agreement = None
    elif a_ctx is None and s_ctx is not None:
        status = "SHADOW_ONLY"
        agreement = False
    elif a_ctx is not None and s_ctx is None:
        status = "ACTIVE_ONLY"
        agreement = False
    elif a_ctx == s_ctx:
        status = "AGREE"
        agreement = True
    else:
        # OBSERVE vs STAND_ASIDE treated as disagree (distinct states)
        status = "DISAGREE"
        agreement = False

    conf_diff = None
    if active_confidence is not None and shadow_confidence is not None:
        try:
            conf_diff = float(shadow_confidence) - float(active_confidence)
        except (TypeError, ValueError):
            conf_diff = None

    return {
        "comparison_id": comparison_id(
            active_registry_record_id=str(active.get("registry_record_id")),
            candidate_registry_record_id=str(candidate.get("registry_record_id")),
            timeframe=timeframe,
            causal_cutoff_monotonic_ns=causal_cutoff_monotonic_ns,
        ),
        "active_registry_record_id": active.get("registry_record_id"),
        "candidate_registry_record_id": candidate.get("registry_record_id"),
        "timeframe": timeframe,
        "causal_cutoff_timestamp": causal_cutoff_timestamp,
        "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
        "active_context": a_ctx,
        "shadow_context": s_ctx,
        "context_agreement": agreement,
        "active_confidence": active_confidence,
        "shadow_confidence": shadow_confidence,
        "confidence_difference": conf_diff,
        "active_context_event_id": active_context_event_id,
        "shadow_prediction_id": shadow_prediction_id,
        "comparison_status": status,
        "created_at": utc_now_iso(),
    }
