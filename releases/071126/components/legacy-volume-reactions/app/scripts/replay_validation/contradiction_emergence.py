"""Replay contradiction emergence via conflict density exports."""

from __future__ import annotations

import json
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
            "conflict_density",
            "contradiction_flags",
            "contradiction_clusters",
            "conflict_penalty",
            "entropy_penalty",
            "alignment_component",
        ]
        if column in subset.columns
    ]

    output = subset[columns].copy()

    print("CONTRADICTION EMERGENCE REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print()

    if "contradiction_flags" in output.columns:
        flagged = output[
            output["contradiction_flags"].fillna("").astype(str).str.len() > 0
        ]
        print(f"Rows with contradiction flags: {len(flagged)}")

        if len(flagged) > 0 and "contradiction_clusters" in flagged.columns:
            sample = flagged.iloc[-1]["contradiction_clusters"]
            try:
                parsed = json.loads(sample)
                print("Latest contradiction clusters:")
                print(json.dumps(parsed, indent=2))
            except (TypeError, json.JSONDecodeError):
                print("Latest contradiction clusters:", sample)

    return output


if __name__ == "__main__":
    run()
