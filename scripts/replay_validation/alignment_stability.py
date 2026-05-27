"""Replay alignment stability across probabilistic and reinforcement memory."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd

from scripts.replay_validation.replay_utils import (
    load_probabilistic,
    load_reinforcement,
)


def run(limit: int = 50) -> pd.DataFrame:
    probabilistic = load_probabilistic().tail(limit)
    reinforcement = load_reinforcement().tail(limit)

    prob_alignment = probabilistic[
        [
            column
            for column in [
                "timestamp",
                "alignment_status",
                "alignment_component",
                "alignment_monoculture_score",
            ]
            if column in probabilistic.columns
        ]
    ].copy()

    rein_alignment = reinforcement[
        [
            column
            for column in [
                "timestamp",
                "alignment_status",
                "alignment_component",
            ]
            if column in reinforcement.columns
        ]
    ].copy()

    print("ALIGNMENT STABILITY REPLAY")
    print("=" * 60)
    print("Probabilistic tail:")
    print(prob_alignment.tail(min(10, len(prob_alignment))).to_string(index=False))
    print()
    print("Reinforcement tail:")
    print(rein_alignment.tail(min(10, len(rein_alignment))).to_string(index=False))
    print()

    if len(prob_alignment) > 0 and "alignment_component" in prob_alignment.columns:
        stable = prob_alignment["alignment_component"].round(4).nunique()
        print(f"Unique alignment_component values (probabilistic tail): {stable}")

    return prob_alignment


if __name__ == "__main__":
    run()
