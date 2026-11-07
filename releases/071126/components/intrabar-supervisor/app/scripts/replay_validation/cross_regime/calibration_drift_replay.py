"""Replay calibration drift progression."""

from __future__ import annotations

from calibration_drift_engine import compute_calibration_drift
from scripts.replay_validation.cross_regime.replay_utils import load_probabilistic


def run(limit: int = 100) -> None:
    frame = load_probabilistic().tail(limit)
    rows = []

    for index in range(len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        drift = compute_calibration_drift(history, row.to_dict())
        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "calibration_drift_score": drift["calibration_drift_score"],
                "drift_direction": drift["drift_direction"],
                "drift_persistence_duration": drift["drift_persistence_duration"],
            }
        )

    import pandas as pd

    output = pd.DataFrame(rows)
    print("CALIBRATION DRIFT REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    if len(output) > 0:
        print(
            "\nMean drift score:",
            round(float(output["calibration_drift_score"].mean()), 4),
        )


if __name__ == "__main__":
    run()
