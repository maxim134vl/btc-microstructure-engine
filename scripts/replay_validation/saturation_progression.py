"""Replay saturation progression through probabilistic memory."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd

from scripts.replay_validation.replay_utils import (
    load_probabilistic,
    rows_with_decomposition,
)


def run(limit: int = 100) -> pd.DataFrame:
    probabilistic = load_probabilistic()
    subset = rows_with_decomposition(probabilistic)
    if len(subset) == 0:
        subset = probabilistic.tail(limit)
    else:
        subset = subset.tail(limit)

    columns = [
        column
        for column in [
            "timestamp",
            "raw_conviction",
            "conviction_probability",
            "saturation_score",
            "conviction_saturated",
            "conviction_saturated_persistence",
            "reinforcement_acceleration",
            "conviction_entropy_ratio",
            "entropy_suppression_failure",
            "runaway_reinforcement",
        ]
        if column in subset.columns
    ]

    output = subset[columns].copy()

    print("SATURATION PROGRESSION REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print()

    if "saturation_score" in output.columns and len(output) > 0:
        print(
            "Max saturation_score:",
            round(float(output["saturation_score"].max()), 4),
        )
        if "conviction_saturated" in output.columns:
            print(
                "Saturated rows:",
                int(output["conviction_saturated"].fillna(False).sum()),
            )

    return output


if __name__ == "__main__":
    run()
