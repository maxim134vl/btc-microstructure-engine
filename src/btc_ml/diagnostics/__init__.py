"""Diagnostics module shims."""

from adversarial_diagnostics import build_adversarial_exports
from ontology_stabilization import build_ontology_stabilization_exports
from runtime_integrity import log_runtime_warning
from runtime_lineage import apply_lineage_metadata

__all__ = [
    "build_adversarial_exports",
    "build_ontology_stabilization_exports",
    "log_runtime_warning",
    "apply_lineage_metadata",
]
