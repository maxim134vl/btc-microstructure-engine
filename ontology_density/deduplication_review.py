"""Deduplication sanity review — cluster compression vs diversity loss."""

from __future__ import annotations

from typing import Any, Dict

from ontology_config import get_ontology_settings
from ontology_refinement import apply_semantic_separation, deduplicate_swing_clusters
from ontology_density._climax_helpers import count_events
from ontology_density.ontology_filter_waterfall import _prepare_frame
from stabilization_data_utils import load_candle_structure


def build_deduplication_review(timeframe: str = "M15") -> Dict[str, Any]:
    settings = get_ontology_settings()
    raw = load_candle_structure()
    frame = _prepare_frame(raw)

    # buying + hav
    buying = (
        (frame["volume_percentile_50"] >= 0.90)
        & (frame["delta"] > 0)
        & (frame["spread_percentile_50"] >= 0.60)
        & ((frame["efficiency_decay"] < 0.80) | (frame["efficiency_decay"] > 1.20))
        & (frame["range_position"] > 0.80)
    )
    frame.loc[buying, "auction_event_type"] = "BUYING_CLIMAX"

    before = apply_semantic_separation(frame, settings)
    after = deduplicate_swing_clusters(before, settings)

    before_counts = count_events(before)
    after_counts = count_events(after)

    dedup_loss = {
        cls: before_counts.get(cls, 0) - after_counts.get(cls, 0)
        for cls in before_counts
        if cls != "NORMAL"
    }
    total_loss = before_counts.get("TOTAL_NON_NORMAL", 0) - after_counts.get("TOTAL_NON_NORMAL", 0)

    suppressed = 0
    if "cluster_events_suppressed" in after.columns:
        suppressed = int(after["cluster_events_suppressed"].sum())

    compression = (
        after_counts.get("TOTAL_NON_NORMAL", 0) / before_counts.get("TOTAL_NON_NORMAL", 1)
        if before_counts.get("TOTAL_NON_NORMAL", 0) > 0
        else 1.0
    )

    return {
        "deduplication_review": True,
        "timeframe": timeframe,
        "dedup_event_loss": dedup_loss,
        "total_event_loss": total_loss,
        "cluster_events_suppressed_sum": suppressed,
        "cluster_compression_ratio": round(compression, 4),
        "ontology_cluster_survival": after_counts,
        "before_dedup_counts": before_counts,
        "ontology_classes_most_affected": [
            k for k, v in dedup_loss.items() if v > 0
        ],
        "assessment": (
            "dedup_minimal_impact" if total_loss <= 1 else "dedup_materially_reducing_density"
        ),
    }
