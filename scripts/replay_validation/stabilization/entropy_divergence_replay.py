"""Replay entropy divergence between STOPPING and SELLING."""

from __future__ import annotations

from semantic_entropy_evolution import analyze_entropy_evolution_divergence
from scripts.replay_validation.stabilization.replay_utils import load_climax_events


def run() -> None:
    exports = analyze_entropy_evolution_divergence(load_climax_events())
    print("ENTROPY DIVERGENCE REPLAY")
    print("=" * 60)
    for key, value in exports.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run()
