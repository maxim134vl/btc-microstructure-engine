"""BUYING_CLIMAX vs HIGH_AVERAGE_VOLUME divergence replay."""

from __future__ import annotations

import json

from buying_exhaustion_validation import analyze_buying_exhaustion
from hav_semantic_analysis import analyze_hav_semantics
from ontology_overlap_matrix import build_overlap_matrix
from stabilization_data_utils import load_candle_structure
from scripts.replay_validation.stabilization.replay_utils import (
    load_climax_events,
    load_probabilistic,
)


def run() -> None:
    events = load_climax_events()
    dataset = load_candle_structure()
    probabilistic = load_probabilistic()

    buying = analyze_buying_exhaustion(events, dataset)
    hav = analyze_hav_semantics(events, dataset, probabilistic=probabilistic)
    overlap = build_overlap_matrix(events, dataset, probabilistic=probabilistic)

    print("BUYING VS HAV DIVERGENCE REPLAY")
    print("=" * 60)
    print(f"buying_exhaustion_quality={buying.get('buying_exhaustion_quality')}")
    print(f"hav_ontology_ambiguity_score={hav.get('hav_ontology_ambiguity_score')}")
    print(f"semantic_overlap_score={overlap.get('semantic_overlap_score')}")
    matrix = json.loads(overlap.get("ontology_overlap_matrix", "{}"))
    pair_key = "BUYING_CLIMAX|HIGH_AVERAGE_VOLUME"
    print(f"buying_hav_overlap={matrix.get(pair_key, 0.0)}")


if __name__ == "__main__":
    run()
