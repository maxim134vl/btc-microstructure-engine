"""Replay conviction evolution through probabilistic memory."""

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


def run(limit: int = 50) -> pd.DataFrame:
    probabilistic = load_probabilistic()
    subset = rows_with_decomposition(probabilistic)
    if len(subset) == 0:
        subset = probabilistic.tail(limit)
    else:
        subset = subset.tail(limit)

    conviction_column = (
        "raw_conviction"
        if "raw_conviction" in subset.columns
        else "conviction_probability"
    )

    output = subset[
        [
            column
            for column in [
                "timestamp",
                conviction_column,
                "calibrated_conviction",
                "auction_regime",
                "reinforcement_component",
                "alignment_component",
                "entropy_penalty",
                "saturation_score",
                "conflict_density",
            ]
            if column in subset.columns
        ]
    ].copy()

    if conviction_column != "raw_conviction":
        output = output.rename(
            columns={conviction_column: "raw_conviction"}
        )

    print("CONVICTION EVOLUTION REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print()
    print(f"Rows replayed: {len(output)}")
    return output


if __name__ == "__main__":
    run()
