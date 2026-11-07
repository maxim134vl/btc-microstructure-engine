"""HIGH_AVERAGE_VOLUME behavioral analysis replay."""

from __future__ import annotations

from hav_semantic_analysis import analyze_hav_semantics
from stabilization_data_utils import load_candle_structure
from scripts.replay_validation.stabilization.replay_utils import (
    load_climax_events,
    load_probabilistic,
)


def run() -> None:
    exports = analyze_hav_semantics(
        load_climax_events(),
        load_candle_structure(),
        probabilistic=load_probabilistic(),
    )
    print("HAV BEHAVIOR ANALYSIS REPLAY")
    print("=" * 60)
    for key, value in exports.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run()
