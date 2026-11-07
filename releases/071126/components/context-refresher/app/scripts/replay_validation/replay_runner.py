"""Run all Phase 1A replay validation tools."""

from __future__ import annotations

import importlib
import sys

REPLAY_MODULES = [
    "scripts.replay_validation.conviction_evolution",
    "scripts.replay_validation.reinforcement_propagation",
    "scripts.replay_validation.alignment_stability",
    "scripts.replay_validation.saturation_progression",
    "scripts.replay_validation.contradiction_emergence",
    "scripts.replay_validation.discipline_comparison",
]


def main() -> int:
    print()
    print("PHASE 1A REPLAY VALIDATION SUITE")
    print("=" * 60)

    for module_name in REPLAY_MODULES:
        print()
        module = importlib.import_module(module_name)
        module.run()
        print("-" * 60)

    print()
    print("REPLAY SUITE COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
