#!/usr/bin/env python3
"""Run full ontology density diagnostic suite (replay env audit first)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ontology_density.deduplication_review import build_deduplication_review
from ontology_density.expectation_model import build_timeframe_density_expectation
from ontology_density.grey_zone_review import build_grey_zone_review
from ontology_density.ontology_density_audit import build_ontology_density_audit
from ontology_density.ontology_filter_waterfall import build_ontology_filter_waterfall
from ontology_density.replay_environment_audit import build_replay_environment_profile
from ontology_density.threshold_sanity_review import build_threshold_sanity_review


def main() -> int:
    timeframe = os.environ.get("ONTOLOGY_REPLAY_TIMEFRAME", "M15")

    print()
    print("ONTOLOGY DENSITY DIAGNOSTICS")
    print("=" * 60)
    print(f"timeframe={timeframe}")
    print()

    replay_env = build_replay_environment_profile(timeframe=timeframe)
    expectation = build_timeframe_density_expectation(timeframe)
    density = build_ontology_density_audit(timeframe=timeframe)
    waterfall = build_ontology_filter_waterfall(timeframe=timeframe)
    grey = build_grey_zone_review(timeframe=timeframe)
    dedup = build_deduplication_review(timeframe=timeframe)
    thresholds = build_threshold_sanity_review(timeframe=timeframe)

    exports = {
        "replay_environment_profile": replay_env,
        "timeframe_density_expectation": expectation,
        "ontology_event_expectation_model": expectation,
        "volatility_regime_mix": replay_env.get("volatility_regime_mix"),
        "ontology_density_audit": density,
        "ontology_filter_waterfall": waterfall,
        "grey_zone_review": grey,
        "deduplication_review": dedup,
        "threshold_sanity_review": thresholds,
    }

    out_dir = os.path.join(ROOT, "reports", "ontology_density")
    os.makedirs(out_dir, exist_ok=True)
    for name, payload in exports.items():
        path = os.path.join(out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        print(f"Wrote {path}")

    print()
    print("SUMMARY")
    print("-" * 60)
    if replay_env.get("row_count_mismatch", {}).get("is_misleading_denominator"):
        print("WARN: probabilistic row count is NOT valid ontology denominator")
    print(f"candle_rows={replay_env.get('candle_row_count')} "
          f"duration_days={replay_env.get('replay_duration_days')}")
    print(f"diagnosis={density.get('diagnosis_hint')}")
    print(f"collapse_stage={waterfall.get('collapse_stage')}")
    print(f"current_counts={density.get('counts_by_mode', {}).get('post_phase_3b_current')}")
    print(f"legacy_counts={density.get('counts_by_mode', {}).get('pre_phase_3a_legacy')}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
