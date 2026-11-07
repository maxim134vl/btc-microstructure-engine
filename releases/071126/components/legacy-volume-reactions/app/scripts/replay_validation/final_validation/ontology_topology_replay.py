"""Ontology topology replay for freeze-candidate validation."""

from __future__ import annotations

import json

from scripts.replay_validation.final_validation.replay_utils import (
    build_ontology_topology_audit,
)


def run() -> None:
    audit = build_ontology_topology_audit()
    print("ONTOLOGY TOPOLOGY REPLAY")
    print("=" * 60)
    print(f"semantic_stability_index={audit.get('semantic_stability_index')}")
    print(f"compression_zones={audit.get('ontology_compression_zones')}")
    topology = json.loads(audit.get("ontology_topology_map", "{}"))
    print(f"event_counts={topology.get('event_counts')}")
    print(f"grey_zone_rate={topology.get('grey_zone_rate')}")


if __name__ == "__main__":
    run()
