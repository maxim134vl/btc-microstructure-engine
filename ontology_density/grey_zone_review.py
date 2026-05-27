"""Grey-zone sanity review — ambiguity absorption vs ontology suppression."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from ontology_config import get_ontology_settings
from ontology_refinement import _base_sell_side_mask, classify_effort_result_zone
from ontology_density.ontology_filter_waterfall import _prepare_frame
from stabilization_data_utils import load_candle_structure


def build_grey_zone_review(timeframe: str = "M15") -> Dict[str, Any]:
    settings = get_ontology_settings()
    frame = _prepare_frame(load_candle_structure())
    if len(frame) == 0:
        return {"grey_zone_review": True, "empty": True}

    de = frame["spread"].astype(float) / frame["volume"].astype(float)
    frame["efficiency_decay"] = de / de.rolling(20, min_periods=1).mean()
    zones = classify_effort_result_zone(frame["efficiency_decay"], settings)
    grey_mask = zones == "AMBIGUOUS"
    sell_base = _base_sell_side_mask(frame)
    sell_grey = sell_base & grey_mask

    total = len(frame)
    grey_rate = float(grey_mask.mean())
    sell_grey_rate = float(sell_grey.sum() / max(sell_base.sum(), 1))

    # Classes most affected: sell-side base in grey zone
    ontology_density_loss = {
        "sell_side_candidates_in_grey_zone": int(sell_grey.sum()),
        "sell_side_grey_absorption_rate": round(sell_grey_rate, 4),
        "global_grey_zone_rate": round(grey_rate, 4),
    }

    return {
        "grey_zone_review": True,
        "timeframe": timeframe,
        "grey_zone_absorption_rate": round(sell_grey_rate, 4),
        "ontology_density_loss": ontology_density_loss,
        "ambiguity_distribution": {
            "ABSORPTION": float((zones == "ABSORPTION").mean()),
            "CAPITULATION": float((zones == "CAPITULATION").mean()),
            "AMBIGUOUS": grey_rate,
        },
        "ontology_classes_most_affected": ["SELLING_CLIMAX", "STOPPING_VOLUME"],
        "assessment": (
            "grey_zone_suppressing_ambiguity_as_designed"
            if sell_grey_rate < 0.5
            else "grey_zone_may_be_over_absorbing_sell_candidates"
        ),
    }
