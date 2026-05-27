"""Replay recursive reinforcement trap stress scenarios."""

from __future__ import annotations

from synthetic_stress_engine import apply_stress_scenario, stress_degradation_score
from scripts.replay_validation.adversarial.replay_utils import load_probabilistic


def run(limit: int = 50, seed: int = 300) -> None:
    frame = load_probabilistic().tail(limit)
    print("REINFORCEMENT TRAP REPLAY")
    print("=" * 60)
    for index, (_, row) in enumerate(frame.tail(5).iterrows()):
        base = row.to_dict()
        stressed, _ = apply_stress_scenario(
            "RECURSIVE_REINFORCEMENT_TRAP",
            base,
            seed=seed + index,
        )
        print(
            f"reinforcement {base.get('reinforcement_component', 0):.3f}"
            f" -> {stressed.get('reinforcement_component', 0):.3f}"
            f" degradation={stress_degradation_score(base, stressed):.3f}"
        )


if __name__ == "__main__":
    run()
