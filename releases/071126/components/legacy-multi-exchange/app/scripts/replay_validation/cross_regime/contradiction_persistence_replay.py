"""Replay contradiction persistence behavior."""

from __future__ import annotations

from calibration_stability import compute_contradiction_persistence
from scripts.replay_validation.cross_regime.replay_utils import load_probabilistic


def run(limit: int = 100) -> None:
    frame = load_probabilistic().tail(limit)
    rows = []

    for index in range(len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        contradiction = compute_contradiction_persistence(history, row.to_dict())
        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "conflict_density": row.get("conflict_density"),
                **contradiction,
            }
        )

    import pandas as pd

    output = pd.DataFrame(rows)
    print("CONTRADICTION PERSISTENCE REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    if len(output) > 0:
        print(
            "\nMean unresolved contradiction score:",
            round(float(output["unresolved_contradiction_score"].mean()), 4),
        )


if __name__ == "__main__":
    run()
