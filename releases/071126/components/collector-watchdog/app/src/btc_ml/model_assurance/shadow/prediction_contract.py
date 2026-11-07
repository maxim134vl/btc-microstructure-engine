"""Shadow prediction contract — never creates orders/fills/positions."""

from __future__ import annotations

from typing import Any

from btc_ml.model_assurance.toxic_box.common import canonical_json, sha256_text, utc_now_iso

ALLOWED_CONTEXTS = frozenset({"LONG", "SHORT", "OBSERVE", "STAND_ASIDE"})


def shadow_prediction_id(
    *,
    candidate_registry_record_id: str,
    shadow_input_id: str,
    model_version: str,
    predicted_context: str,
) -> str:
    return "SHPR_" + sha256_text(
        canonical_json(
            {
                "candidate_registry_record_id": candidate_registry_record_id,
                "shadow_input_id": shadow_input_id,
                "model_version": model_version,
                "predicted_context": predicted_context,
            }
        )
    )[:32]


def build_shadow_prediction(
    *,
    active: dict[str, Any],
    candidate: dict[str, Any],
    shadow_input: dict[str, Any],
    predicted_context: str,
    confidence: float | None = None,
    prediction_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = str(predicted_context or "").upper()
    if ctx not in ALLOWED_CONTEXTS:
        raise ValueError(f"INVALID_SHADOW_CONTEXT:{ctx}")
    return {
        "shadow_prediction_id": shadow_prediction_id(
            candidate_registry_record_id=str(candidate.get("registry_record_id")),
            shadow_input_id=str(shadow_input.get("shadow_input_id")),
            model_version=str(candidate.get("model_version")),
            predicted_context=ctx,
        ),
        "candidate_registry_record_id": candidate.get("registry_record_id"),
        "active_registry_record_id": active.get("registry_record_id"),
        "shadow_input_id": shadow_input.get("shadow_input_id"),
        "timeframe": shadow_input.get("timeframe"),
        "causal_cutoff_timestamp": shadow_input.get("causal_cutoff_timestamp"),
        "causal_cutoff_monotonic_ns": shadow_input.get("causal_cutoff_monotonic_ns"),
        "predicted_context": ctx,
        "confidence": confidence,
        "prediction_payload": prediction_payload or {},
        "model_version": candidate.get("model_version"),
        "runtime_fingerprint": candidate.get("runtime_fingerprint"),
        "created_at": utc_now_iso(),
        # Explicit non-execution markers
        "creates_context_lifecycle_event": False,
        "creates_paper_command": False,
        "creates_order": False,
        "creates_fill": False,
        "creates_position": False,
        "creates_trade": False,
    }
