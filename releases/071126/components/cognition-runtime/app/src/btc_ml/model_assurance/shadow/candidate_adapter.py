"""Candidate adapter interface — prediction only, no execution path."""

from __future__ import annotations

import importlib
from typing import Any, Protocol


class CandidateAdapter(Protocol):
    def predict(self, shadow_input: dict[str, Any]) -> dict[str, Any]:
        """Return {predicted_context, confidence?, prediction_payload?}."""


class UnavailableCandidateAdapter:
    """Placeholder when no adapter is configured for a registered candidate."""

    def predict(self, shadow_input: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("CANDIDATE_ADAPTER_UNAVAILABLE")


def load_candidate_adapter(candidate_record: dict[str, Any] | None) -> CandidateAdapter:
    if not candidate_record:
        raise RuntimeError("NO_CANDIDATE_REGISTERED")
    module_name = candidate_record.get("adapter_module")
    class_name = candidate_record.get("adapter_class")
    if not module_name or not class_name:
        return UnavailableCandidateAdapter()
    module = importlib.import_module(str(module_name))
    cls = getattr(module, str(class_name))
    return cls()
