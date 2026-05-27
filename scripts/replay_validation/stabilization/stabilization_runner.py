"""Run all Phase 3B stabilization replay validators."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "scripts.replay_validation.stabilization.reinforcement_shift_replay",
    "scripts.replay_validation.stabilization.contradiction_redistribution_replay",
    "scripts.replay_validation.stabilization.entropy_divergence_replay",
    "scripts.replay_validation.stabilization.ontology_transition_replay",
    "scripts.replay_validation.ontology.buying_climax_exhaustion",
    "scripts.replay_validation.ontology.hav_behavior_analysis",
    "scripts.replay_validation.ontology.buying_vs_hav_divergence",
]


def main() -> int:
    print()
    print("PHASE 3B STABILIZATION REPLAY SUITE")
    print("=" * 60)

    for module_name in MODULES:
        print()
        module = importlib.import_module(module_name)
        module.run()
        print("-" * 60)

    print("\nSTABILIZATION REPLAY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
