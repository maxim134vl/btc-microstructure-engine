"""Transition cluster replay for regime-heavy environments."""

from __future__ import annotations

from scripts.replay_validation.final_validation.replay_utils import load_probabilistic


def run(limit: int = 50) -> None:
    probabilistic = load_probabilistic()
    print("TRANSITION CLUSTER REPLAY")
    print("=" * 60)

    if len(probabilistic) == 0:
        print("No probabilistic data")
        return

    sample = probabilistic.tail(limit)
    if "regime_transition_probability" not in sample.columns:
        print("No transition probability column")
        return

    high_transition = sample[
        sample["regime_transition_probability"].astype(float) > 0.35
    ]
    print(f"high_transition_rows={len(high_transition)}/{len(sample)}")
    for _, row in high_transition.tail(5).iterrows():
        print(
            f"{row.get('timestamp')} regime={row.get('regime_state')} "
            f"transition_p={row.get('regime_transition_probability')}"
        )


if __name__ == "__main__":
    run()
