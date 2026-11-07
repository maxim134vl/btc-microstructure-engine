"""Replay ontology behavior during regime transitions."""

from __future__ import annotations

from ontology_transition_stability import analyze_ontology_transition_stability
from scripts.replay_validation.stabilization.replay_utils import load_probabilistic


def run() -> None:
    probabilistic = load_probabilistic()
    print("ONTOLOGY TRANSITION REPLAY")
    print("=" * 60)
    if len(probabilistic) == 0:
        print("No probabilistic rows available")
        return

    for _, row in probabilistic.tail(5).iterrows():
        exports = analyze_ontology_transition_stability(
            row.to_dict(),
            probabilistic=probabilistic,
        )
        print(
            f"{row.get('timestamp')} regime={row.get('regime_state')} "
            f"stability={exports.get('ontology_transition_stability')}"
        )


if __name__ == "__main__":
    run()
