"""Replay reinforcement stability across regimes."""

from __future__ import annotations

from calibration_stability import metrics_by_regime
from scripts.replay_validation.cross_regime.replay_utils import (
    load_probabilistic,
    load_reinforcement,
)


def run(limit: int = 200) -> None:
    probabilistic = load_probabilistic().tail(limit)
    reinforcement = load_reinforcement()

    metrics = metrics_by_regime(probabilistic)
    print("REINFORCEMENT STABILITY REPLAY")
    print("=" * 60)
    for regime, values in sorted(metrics.items()):
        print(
            f"{regime}: reinforcement_persistence="
            f"{values.get('reinforcement_persistence', 0.0):.3f} "
            f"saturation={values.get('saturation_frequency', 0.0):.3f}"
        )
    print(f"\nReinforcement rows available: {len(reinforcement)}")


if __name__ == "__main__":
    run()
