"""Replay contradiction redistribution after ontology split."""

from __future__ import annotations

from contradiction_redistribution import analyze_contradiction_redistribution
from scripts.replay_validation.stabilization.replay_utils import (
    load_climax_events,
    load_probabilistic,
)


def run() -> None:
    exports = analyze_contradiction_redistribution(
        load_climax_events(),
        probabilistic=load_probabilistic(),
    )
    print("CONTRADICTION REDISTRIBUTION REPLAY")
    print("=" * 60)
    for key, value in exports.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run()
