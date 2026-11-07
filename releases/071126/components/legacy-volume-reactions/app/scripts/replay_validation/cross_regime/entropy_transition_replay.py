"""Replay entropy regime transitions."""

from __future__ import annotations

from calibration_stability import detect_entropy_transition
from scripts.replay_validation.cross_regime.replay_utils import load_probabilistic


def run(limit: int = 100) -> None:
    frame = load_probabilistic().tail(limit)
    rows = []

    for index in range(len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        transition = detect_entropy_transition(row.to_dict(), history)
        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "entropy_penalty": row.get("entropy_penalty"),
                "entropy_transition_type": transition,
            }
        )

    import pandas as pd

    output = pd.DataFrame(rows)
    print("ENTROPY TRANSITION REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print("\nTransition distribution:")
    print(output["entropy_transition_type"].value_counts().to_string())


if __name__ == "__main__":
    run()
