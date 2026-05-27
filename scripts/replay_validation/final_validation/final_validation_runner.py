"""Run all Phase 4A final validation replays."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "scripts.replay_validation.final_validation.broad_market_replay",
    "scripts.replay_validation.final_validation.transition_cluster_replay",
    "scripts.replay_validation.final_validation.ontology_topology_replay",
    "scripts.replay_validation.stabilization.stabilization_runner",
    "scripts.replay_validation.adversarial.replay_runner",
]


def main() -> int:
    print()
    print("PHASE 4A FINAL VALIDATION REPLAY SUITE")
    print("=" * 60)

    for module_name in MODULES:
        print()
        module = importlib.import_module(module_name)
        if hasattr(module, "run"):
            module.run()
        else:
            module.main()
        print("-" * 60)

    print("\nFINAL VALIDATION REPLAY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
