"""Replay reinforcement redistribution after ontology split."""

from __future__ import annotations

from post_split_reinforcement_analysis import analyze_reinforcement_redistribution
from scripts.replay_validation.stabilization.replay_utils import (
    load_climax_events,
    load_probabilistic,
    load_reinforcement,
)


def run() -> None:
    events = load_climax_events()
    exports = analyze_reinforcement_redistribution(
        events,
        probabilistic=load_probabilistic(),
        reinforcement=load_reinforcement(),
    )
    print("REINFORCEMENT SHIFT REPLAY")
    print("=" * 60)
    for key, value in exports.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run()
