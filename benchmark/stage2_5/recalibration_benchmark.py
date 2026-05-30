"""Compare Stage 2.5 benchmark metrics before and after live-feed recalibration."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from benchmark.stage2_5.aggregator import aggregate_results
from benchmark.stage2_5.live_feed_calibration import (
    detect_candidates_with_thresholds,
    simulate_persisted,
)
from benchmark.stage2_5.verdict_engine import validate_intermediate_events
from config.stage2_5_calibration import LEGACY_THRESHOLDS, Stage25Thresholds, load_stage2_5_thresholds
from intermediate_cognition_engine_v1 import _prep, enrich_with_anchor
from parquet_utils import safe_read_parquet
from storage.path_registry import repo_root

DEFAULT_START = "2026-05-02"
DEFAULT_END = "2026-05-30 23:59:59"


def _events_frame(persisted: list[dict[str, Any]]) -> pd.DataFrame:
    if not persisted:
        return pd.DataFrame()
    frame = pd.DataFrame(persisted)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["event_index"] = range(1, len(frame) + 1)
    return frame


def _weekly_rate(count: int, start: pd.Timestamp, end: pd.Timestamp) -> float:
    days = max((end - start).total_seconds() / 86400, 1)
    return round(count / (days / 7), 2)


def replay_profile(
    thresholds: Stage25Thresholds,
    *,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
) -> dict[str, Any]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    candles = _prep(safe_read_parquet("candle_structure_memory.parquet"))
    volume_class = _prep(safe_read_parquet("volume_classification_memory.parquet"))
    stage2 = _prep(safe_read_parquet("runtime_cognition_memory.parquet"))

    candidates = detect_candidates_with_thresholds(
        candles,
        volume_class,
        thresholds,
        start=start_ts,
        end=end_ts,
    )
    persisted = simulate_persisted(candidates, thresholds)
    persisted = enrich_with_anchor(persisted, stage2)
    events = _events_frame(persisted)

    raw_counts = Counter(row["intermediate_state"] for row in candidates)
    persisted_counts = Counter(row["intermediate_state"] for row in persisted)

    if len(events) == 0:
        summary = aggregate_results([])
    else:
        results = validate_intermediate_events(events)
        summary = aggregate_results(results)

    total = len(persisted)
    rot_share = persisted_counts.get("IC_ROTATIONAL_PRESSURE", 0) / total if total else 0.0

    return {
        "thresholds": thresholds.as_dict(),
        "raw_trigger_counts": dict(raw_counts),
        "persisted_distribution": dict(persisted_counts),
        "persisted_total": total,
        "weekly_rate": _weekly_rate(total, start_ts, end_ts),
        "rotational_share": round(rot_share, 4),
        "benchmark_summary": summary,
        "events": events.to_dict(orient="records") if len(events) else [],
    }


def run_recalibration_benchmark(
    *,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
) -> dict[str, Any]:
    legacy = replay_profile(LEGACY_THRESHOLDS, start=start, end=end)
    live = replay_profile(load_stage2_5_thresholds(profile="live_feed"), start=start, end=end)

    old_summary = legacy["benchmark_summary"]
    new_summary = live["benchmark_summary"]

    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start, "end": end},
        "old_calibration": {
            "profile": "legacy",
            "thresholds": legacy["thresholds"],
            "raw_trigger_counts": legacy["raw_trigger_counts"],
            "persisted_distribution": legacy["persisted_distribution"],
            "persisted_total": legacy["persisted_total"],
            "weekly_rate": legacy["weekly_rate"],
            "rotational_share": legacy["rotational_share"],
            "precision": old_summary.get("precision"),
            "confirmation_rate": old_summary.get("confirmation_rate"),
            "false_positive_rate": old_summary.get("false_positive_rate"),
            "early_warning_rate": old_summary.get("early_warning_rate"),
            "narrative_confirmation_rate": old_summary.get("narrative_confirmation_rate"),
            "by_state": old_summary.get("by_state"),
        },
        "new_calibration": {
            "profile": "live_feed",
            "thresholds": live["thresholds"],
            "raw_trigger_counts": live["raw_trigger_counts"],
            "persisted_distribution": live["persisted_distribution"],
            "persisted_total": live["persisted_total"],
            "weekly_rate": live["weekly_rate"],
            "rotational_share": live["rotational_share"],
            "precision": new_summary.get("precision"),
            "confirmation_rate": new_summary.get("confirmation_rate"),
            "false_positive_rate": new_summary.get("false_positive_rate"),
            "early_warning_rate": new_summary.get("early_warning_rate"),
            "narrative_confirmation_rate": new_summary.get("narrative_confirmation_rate"),
            "by_state": new_summary.get("by_state"),
        },
        "delta": {
            "precision": round((new_summary.get("precision") or 0) - (old_summary.get("precision") or 0), 4),
            "confirmation_rate": round(
                (new_summary.get("confirmation_rate") or 0) - (old_summary.get("confirmation_rate") or 0),
                4,
            ),
            "false_positive_rate": round(
                (new_summary.get("false_positive_rate") or 0) - (old_summary.get("false_positive_rate") or 0),
                4,
            ),
            "early_warning_rate": round(
                (new_summary.get("early_warning_rate") or 0) - (old_summary.get("early_warning_rate") or 0),
                4,
            ),
            "weekly_rate": round(live["weekly_rate"] - legacy["weekly_rate"], 2),
            "rotational_share": round(live["rotational_share"] - legacy["rotational_share"], 4),
        },
    }

    exports_dir = repo_root() / "benchmark" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_path = exports_dir / f"stage2_5_recalibration_{stamp}.json"
    with open(export_path, "w", encoding="utf-8") as handle:
        json.dump(comparison, handle, indent=2, default=str)

    comparison["export_path"] = str(export_path)
    return comparison


if __name__ == "__main__":
    import argparse
    import sys

    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    parser = argparse.ArgumentParser(description="Stage 2.5 recalibration benchmark comparison")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()

    payload = run_recalibration_benchmark(start=args.start, end=args.end)
    print(json.dumps(payload, indent=2, default=str))
