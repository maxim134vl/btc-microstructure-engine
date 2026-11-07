"""Broad market replay across volatility and regime samples."""

from __future__ import annotations

from scripts.replay_validation.final_validation.replay_utils import (
    load_climax_events,
    load_probabilistic,
)


def run(limit: int = 100) -> None:
    probabilistic = load_probabilistic()
    events = load_climax_events()

    print("BROAD MARKET REPLAY")
    print("=" * 60)
    print(f"probabilistic_rows={len(probabilistic)} climax_events={len(events)}")

    if len(probabilistic) == 0:
        print("No probabilistic data")
        return

    sample = probabilistic.tail(limit)
    if "regime_state" in sample.columns:
        print(sample["regime_state"].value_counts().to_string())
    if "entropy_penalty" in sample.columns:
        print(f"entropy_mean={sample['entropy_penalty'].astype(float).mean():.3f}")


if __name__ == "__main__":
    run()
