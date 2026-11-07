"""Replay entropy shock stress scenarios."""

from __future__ import annotations

from synthetic_stress_engine import apply_stress_scenario, stress_degradation_score
from scripts.replay_validation.adversarial.replay_utils import load_probabilistic


def run(limit: int = 50, seed: int = 42) -> None:
    frame = load_probabilistic().tail(limit)
    if len(frame) == 0:
        print("No probabilistic rows available")
        return

    print("ENTROPY SHOCK REPLAY")
    print("=" * 60)
    for index, (_, row) in enumerate(frame.tail(5).iterrows()):
        base = row.to_dict()
        stressed, meta = apply_stress_scenario(
            "ENTROPY_SHOCK",
            base,
            seed=seed + index,
        )
        score = stress_degradation_score(base, stressed)
        print(
            f"row={index} entropy {base.get('entropy_penalty'):.3f}"
            f" -> {stressed.get('entropy_penalty'):.3f} degradation={score:.3f}"
        )


if __name__ == "__main__":
    run()
