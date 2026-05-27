"""Replay reinforcement propagation and component inflation."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd

from calibration_diagnostics import dominant_component
from scripts.replay_validation.replay_utils import load_reinforcement


def run(limit: int = 50) -> pd.DataFrame:
    reinforcement = load_reinforcement().tail(limit)

    columns = [
        column
        for column in [
            "timestamp",
            "belief_state",
            "belief_strength",
            "reinforcement_component",
            "alignment_component",
            "persistence_component",
            "conflict_penalty",
            "entropy_penalty",
            "runaway_reinforcement",
        ]
        if column in reinforcement.columns
    ]

    output = reinforcement[columns].copy()
    if len(output) > 0 and "reinforcement_component" in output.columns:
        output["reinforcement_delta"] = output["reinforcement_component"].diff()
        output["dominant_component"] = reinforcement.apply(
            dominant_component,
            axis=1,
        ).values

    print("REINFORCEMENT PROPAGATION REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print()
    print(f"Rows replayed: {len(output)}")
    return output


if __name__ == "__main__":
    run()
