"""BUYING_CLIMAX exhaustion validation replay."""

from __future__ import annotations

from buying_exhaustion_validation import analyze_buying_exhaustion
from stabilization_data_utils import load_candle_structure
from scripts.replay_validation.stabilization.replay_utils import load_climax_events


def run() -> None:
    exports = analyze_buying_exhaustion(
        load_climax_events(),
        load_candle_structure(),
    )
    print("BUYING CLIMAX EXHAUSTION REPLAY")
    print("=" * 60)
    for key, value in exports.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run()
