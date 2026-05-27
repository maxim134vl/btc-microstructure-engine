"""Replay regime transitions across probabilistic memory."""

from __future__ import annotations

import sys

from regime_segmentation import infer_regime_segmentation
from scripts.replay_validation.cross_regime.replay_utils import (
    load_probabilistic,
)


def run(limit: int = 100) -> None:
    frame = load_probabilistic().tail(limit)
    rows = []

    for index in range(len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        inferred = infer_regime_segmentation(
            snapshot=row.to_dict(),
            runtime_cognition={},
            probabilistic_history=history,
        )
        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "regime_state": inferred["regime_state"],
                "regime_confidence": inferred["regime_confidence"],
                "regime_transition_probability": inferred[
                    "regime_transition_probability"
                ],
            }
        )

    import pandas as pd

    output = pd.DataFrame(rows)
    print("REGIME TRANSITION REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    if len(output) >= 2:
        transitions = (
            output["regime_state"] != output["regime_state"].shift(1)
        ).sum()
        print(f"\nTransition count: {int(transitions)}")


if __name__ == "__main__":
    run()
