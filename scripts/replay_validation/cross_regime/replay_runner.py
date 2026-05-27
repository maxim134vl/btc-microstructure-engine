"""Run all Phase 2A cross-regime replay validators."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "scripts.replay_validation.cross_regime.regime_transition_replay",
    "scripts.replay_validation.cross_regime.entropy_transition_replay",
    "scripts.replay_validation.cross_regime.calibration_drift_replay",
    "scripts.replay_validation.cross_regime.contradiction_persistence_replay",
    "scripts.replay_validation.cross_regime.reinforcement_stability_replay",
]


def main() -> int:
    print()
    print("PHASE 2A CROSS-REGIME REPLAY SUITE")
    print("=" * 60)

    for module_name in MODULES:
        print()
        module = importlib.import_module(module_name)
        module.run()
        print("-" * 60)

    print("\nCROSS-REGIME REPLAY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
