"""Run all Phase 3A ontology replay validators."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "scripts.replay_validation.ontology.selling_climax_evolution",
    "scripts.replay_validation.ontology.stopping_volume_evolution",
    "scripts.replay_validation.ontology.absorption_vs_capitulation",
    "scripts.replay_validation.ontology.post_event_entropy_decay",
    "scripts.replay_validation.ontology.continuation_failure_analysis",
]


def main() -> int:
    print()
    print("PHASE 3A ONTOLOGY REPLAY SUITE")
    print("=" * 60)

    for module_name in MODULES:
        print()
        module = importlib.import_module(module_name)
        module.run()
        print("-" * 60)

    print("\nONTOLOGY REPLAY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
