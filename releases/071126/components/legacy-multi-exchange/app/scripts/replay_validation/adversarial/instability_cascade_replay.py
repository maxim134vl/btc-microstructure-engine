"""Replay instability cascade propagation."""

from __future__ import annotations

from instability_propagation import compute_instability_propagation
from scripts.replay_validation.adversarial.replay_utils import load_probabilistic


def run(limit: int = 50) -> None:
    frame = load_probabilistic().tail(limit)
    print("INSTABILITY CASCADE REPLAY")
    print("=" * 60)
    for index in range(max(0, len(frame) - 5), len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        cascade = compute_instability_propagation(row.to_dict(), history)
        print(
            f"{row.get('timestamp')} origin={cascade.get('instability_origin')} "
            f"chain={cascade.get('instability_propagation_chain')} "
            f"severity={cascade.get('cascade_severity', 0):.3f}"
        )


if __name__ == "__main__":
    run()
