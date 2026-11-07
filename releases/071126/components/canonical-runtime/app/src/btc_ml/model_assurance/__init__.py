"""Model Assurance registry (non-blocking identity layer)."""

from btc_ml.model_assurance.registry import (
    read_active_runtime,
    read_registry_status,
    register_active_runtime,
)

__all__ = [
    "register_active_runtime",
    "read_active_runtime",
    "read_registry_status",
]
