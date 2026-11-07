"""Run all Phase 2B adversarial replay validators."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "scripts.replay_validation.adversarial.entropy_shock_replay",
    "scripts.replay_validation.adversarial.contradiction_flood_replay",
    "scripts.replay_validation.adversarial.regime_flip_replay",
    "scripts.replay_validation.adversarial.reinforcement_trap_replay",
    "scripts.replay_validation.adversarial.instability_cascade_replay",
    "scripts.replay_validation.adversarial.resilience_recovery_replay",
]


def main() -> int:
    print()
    print("PHASE 2B ADVERSARIAL REPLAY SUITE")
    print("=" * 60)

    for module_name in MODULES:
        print()
        module = importlib.import_module(module_name)
        module.run()
        print("-" * 60)

    print("\nADVERSARIAL REPLAY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
