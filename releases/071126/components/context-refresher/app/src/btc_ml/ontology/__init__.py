"""Ontology module shims — Phase 4A incremental migration."""

from ontology_refinement import apply_ontology_pipeline
from ontology_stabilization import build_ontology_stabilization_exports
from post_event_evolution import compute_post_event_evolution

__all__ = [
    "apply_ontology_pipeline",
    "build_ontology_stabilization_exports",
    "compute_post_event_evolution",
]
