"""Replay abrupt regime flip stress scenarios."""

from __future__ import annotations

from synthetic_stress_engine import apply_stress_scenario
from scripts.replay_validation.adversarial.replay_utils import load_probabilistic


def run(limit: int = 50, seed: int = 200) -> None:
    frame = load_probabilistic().tail(limit)
    print("REGIME FLIP REPLAY")
    print("=" * 60)
    for index, (_, row) in enumerate(frame.tail(5).iterrows()):
        base = row.to_dict()
        stressed, _ = apply_stress_scenario(
            "ABRUPT_REGIME_FLIP",
            base,
            seed=seed + index,
        )
        print(
            f"{base.get('regime_state')} -> {stressed.get('regime_state')} "
            f"transition_p={stressed.get('regime_transition_probability', 0):.3f}"
        )


if __name__ == "__main__":
    run()
