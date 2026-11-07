"""Derive Stage 2.5 thresholds from canonical live-feed feature distributions."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from config.stage2_5_calibration import LEGACY_THRESHOLDS, Stage25Thresholds
from intermediate_cognition_engine_v1 import (
    _collapse_bar_candidates,
    _prep,
    should_persist,
)
from parquet_utils import safe_read_parquet
from storage.path_registry import repo_root

DEFAULT_WINDOW = ("2026-05-02", "2026-05-30 23:59:59")
TARGET_WEEKLY_MIN = 12
TARGET_WEEKLY_MAX = 20
MAX_ROTATIONAL_SHARE = 0.50


def _percentile_summary(series: pd.Series) -> dict[str, float]:
    clean = series.dropna().astype(float)
    if len(clean) == 0:
        return {"mean": 0.0, "median": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
    return {
        "mean": round(float(clean.mean()), 4),
        "median": round(float(clean.median()), 4),
        "p75": round(float(clean.quantile(0.75)), 4),
        "p90": round(float(clean.quantile(0.90)), 4),
        "p95": round(float(clean.quantile(0.95)), 4),
        "p99": round(float(clean.quantile(0.99)), 4),
    }


def build_feature_frame(
    candles: pd.DataFrame,
    volume_class: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute per-bar trigger features used by Stage 2.5 detection."""

    candles = _prep(candles)
    vol_class = _prep(volume_class) if volume_class is not None else pd.DataFrame()
    vol_lookup: dict[pd.Timestamp, Any] = {}
    if len(vol_class) > 0 and "volume_class" in vol_class.columns:
        for _, row in vol_class.iterrows():
            vol_lookup[row["timestamp"]] = row.get("volume_class")

    frame = candles.copy()
    frame["dir"] = np.sign(frame["delta"].astype(float))
    rows: list[dict[str, Any]] = []

    for i in range(5, len(frame)):
        ts = frame.iloc[i]["timestamp"]
        w5 = frame.iloc[i - 4 : i + 1]
        delta5 = float(w5["delta"].astype(float).sum())
        price5 = float(frame.iloc[i]["close"] - frame.iloc[i - 5]["close"])
        dirs = w5["dir"].values
        sign_flips = int(np.sum(dirs[1:] != dirs[:-1])) if len(dirs) == 5 else 0
        ma5 = float(w5["delta"].astype(float).mean())
        prev = frame.iloc[max(0, i - 9) : i - 4]
        ma5_prev = float(prev["delta"].astype(float).mean()) if len(prev) >= 3 else np.nan
        swing = abs(ma5 - ma5_prev) if pd.notna(ma5_prev) else np.nan
        effort_up_price_down = delta5 > 0 and price5 < 0
        effort_down_price_up = delta5 < 0 and price5 > 0
        continuation_divergence = effort_up_price_down or effort_down_price_up
        initiative_flip = (
            pd.notna(ma5_prev)
            and np.sign(ma5_prev) != 0
            and np.sign(ma5) != 0
            and np.sign(ma5_prev) != np.sign(ma5)
        )
        rows.append(
            {
                "timestamp": ts,
                "delta": float(frame.iloc[i]["delta"]),
                "delta5": delta5,
                "price5": price5,
                "abs_delta5": abs(delta5),
                "abs_price5": abs(price5),
                "initiative_ma": ma5,
                "initiative_ma_prev": ma5_prev,
                "initiative_swing": swing,
                "abs_initiative_ma": abs(ma5),
                "abs_initiative_ma_prev": abs(ma5_prev) if pd.notna(ma5_prev) else np.nan,
                "sign_flips": sign_flips,
                "volume_class": vol_lookup.get(ts),
                "continuation_divergence": continuation_divergence,
                "initiative_flip": initiative_flip,
            }
        )

    return pd.DataFrame(rows)


def summarize_distributions(features: pd.DataFrame) -> dict[str, Any]:
    """Return distribution stats for all trigger features."""

    divergent = features[features["continuation_divergence"]]
    initiative = features[features["initiative_flip"] & features["initiative_swing"].notna()]

    return {
        "delta": _percentile_summary(features["delta"]),
        "delta5": _percentile_summary(features["delta5"]),
        "abs_delta5": _percentile_summary(features["abs_delta5"]),
        "price5": _percentile_summary(features["price5"]),
        "abs_price5": _percentile_summary(features["abs_price5"]),
        "continuation_divergence_abs_delta5": _percentile_summary(divergent["abs_delta5"]),
        "continuation_divergence_abs_price5": _percentile_summary(divergent["abs_price5"]),
        "initiative_ma": _percentile_summary(features["abs_initiative_ma"]),
        "initiative_ma_prev": _percentile_summary(initiative["abs_initiative_ma_prev"]),
        "initiative_swing": _percentile_summary(initiative["initiative_swing"]),
        "sign_flips": _percentile_summary(features["sign_flips"]),
    }


def detect_candidates_with_thresholds(
    candles: pd.DataFrame,
    volume_class: pd.DataFrame | None,
    thresholds: Stage25Thresholds,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Evaluate intermediate triggers using an explicit threshold profile."""

    from intermediate_cognition_engine_v1 import _confidence, _severity_continuation, _severity_initiative

    candles = _prep(candles)
    if len(candles) < 6:
        return []

    if start is not None:
        candles = candles[candles["timestamp"] >= start]
    if end is not None:
        candles = candles[candles["timestamp"] <= end]
    if len(candles) < 6:
        return []

    vol_class = _prep(volume_class) if volume_class is not None else pd.DataFrame()
    vol_lookup: dict[pd.Timestamp, Any] = {}
    if len(vol_class) > 0 and "volume_class" in vol_class.columns:
        for _, row in vol_class.iterrows():
            vol_lookup[row["timestamp"]] = row.get("volume_class")

    frame = candles.copy()
    frame["dir"] = np.sign(frame["delta"].astype(float))
    candidates: list[dict[str, Any]] = []

    for i in range(5, len(frame)):
        ts = frame.iloc[i]["timestamp"]
        w5 = frame.iloc[i - 4 : i + 1]
        delta5 = float(w5["delta"].astype(float).sum())
        price5 = float(frame.iloc[i]["close"] - frame.iloc[i - 5]["close"])
        dirs = w5["dir"].values
        sign_flips = int(np.sum(dirs[1:] != dirs[:-1])) if len(dirs) == 5 else 0
        ma5 = float(w5["delta"].astype(float).mean())
        prev = frame.iloc[max(0, i - 9) : i - 4]
        ma5_prev = float(prev["delta"].astype(float).mean()) if len(prev) >= 3 else np.nan
        sources = ["candle_structure_memory"]

        if (
            delta5 > thresholds.continuation_delta_min
            and price5 < -thresholds.continuation_price_min
        ) or (
            delta5 < -thresholds.continuation_delta_min
            and price5 > thresholds.continuation_price_min
        ):
            severity = _severity_continuation(delta5, price5)
            direction = "effort-up/price-down" if delta5 > 0 else "effort-down/price-up"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_CONTINUATION_WEAKENING",
                    "severity": severity,
                    "confidence": _confidence("IC_CONTINUATION_WEAKENING", severity, 1),
                    "source_layers": json.dumps(sources),
                    "reason": f"{direction}; delta5={delta5:.0f}, price5={price5:.1f}",
                }
            )

        if pd.notna(ma5_prev) and np.sign(ma5_prev) != np.sign(ma5):
            swing = abs(ma5 - ma5_prev)
            if (
                abs(ma5) >= thresholds.initiative_ma_min
                and abs(ma5_prev) >= thresholds.initiative_ma_min
                and swing >= thresholds.initiative_swing_min
            ):
                severity = _severity_initiative(ma5_prev, ma5)
                candidates.append(
                    {
                        "timestamp": ts,
                        "intermediate_state": "IC_INITIATIVE_DETERIORATION",
                        "severity": severity,
                        "confidence": _confidence("IC_INITIATIVE_DETERIORATION", severity, 1),
                        "source_layers": json.dumps(sources),
                        "reason": f"initiative MA flip {ma5_prev:.0f} → {ma5:.0f}",
                    }
                )

        rotational = sign_flips >= thresholds.rotational_flips_min
        vc = vol_lookup.get(ts)
        if vc == "stopping" and sign_flips >= thresholds.rotational_stopping_min_flips:
            rotational = True
            sources = list(dict.fromkeys(sources + ["volume_classification_memory"]))
        if rotational:
            severity = (
                "HIGH"
                if sign_flips >= thresholds.rotational_flips_min or vc == "stopping"
                else "MEDIUM"
            )
            if severity == "MEDIUM" and vc != "stopping":
                rotational = False
        if rotational:
            reason = f"sign_flips_5={sign_flips}"
            if vc == "stopping":
                reason += "; volume_class=stopping"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_ROTATIONAL_PRESSURE",
                    "severity": severity,
                    "confidence": _confidence("IC_ROTATIONAL_PRESSURE", severity, len(sources)),
                    "source_layers": json.dumps(sources),
                    "reason": reason,
                }
            )

    return _collapse_bar_candidates(candidates)


def simulate_persisted(
    candidates: list[dict[str, Any]],
    thresholds: Stage25Thresholds,
) -> list[dict[str, Any]]:
    existing = pd.DataFrame()
    persisted: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda row: row["timestamp"]):
        if should_persist(existing, candidate, cooldown_bars=thresholds.cooldown_bars):
            persisted.append(candidate)
            row = pd.DataFrame([candidate])
            existing = row if len(existing) == 0 else pd.concat([existing, row], ignore_index=True)
    return persisted


def _weekly_rate(events: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp) -> float:
    if not events:
        return 0.0
    days = max((end - start).total_seconds() / 86400, 1)
    return len(events) / (days / 7)


def _score_profile(
    persisted: list[dict[str, Any]],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    counts = Counter(row["intermediate_state"] for row in persisted)
    total = len(persisted)
    weekly = _weekly_rate(persisted, start, end)
    rot_share = counts.get("IC_ROTATIONAL_PRESSURE", 0) / total if total else 1.0

    density_penalty = 0.0
    if weekly < TARGET_WEEKLY_MIN:
        density_penalty = (TARGET_WEEKLY_MIN - weekly) * 3
    elif weekly > TARGET_WEEKLY_MAX:
        density_penalty = (weekly - TARGET_WEEKLY_MAX) * 3

    rot_penalty = max(0.0, rot_share - MAX_ROTATIONAL_SHARE) * 100
    zero_initiative_penalty = 10.0 if counts.get("IC_INITIATIVE_DETERIORATION", 0) == 0 else 0.0
    zero_continuation_penalty = 8.0 if counts.get("IC_CONTINUATION_WEAKENING", 0) == 0 else 0.0
    hard_fail = rot_share > MAX_ROTATIONAL_SHARE

    score = density_penalty + rot_penalty + zero_initiative_penalty + zero_continuation_penalty
    if hard_fail:
        score += 50.0
    return {
        "score": score,
        "weekly_rate": round(weekly, 2),
        "distribution": dict(counts),
        "rotational_share": round(rot_share, 4),
        "total": total,
    }


def derive_threshold_candidates(distributions: dict[str, Any]) -> dict[str, list[float | int]]:
    divergent_delta = distributions["continuation_divergence_abs_delta5"]
    divergent_price = distributions["continuation_divergence_abs_price5"]
    initiative_ma = distributions["initiative_ma"]
    initiative_swing = distributions["initiative_swing"]
    sign_flips = distributions["sign_flips"]

    return {
        "continuation_delta_min": [
            divergent_delta["p90"],
            divergent_delta["p95"],
        ],
        "continuation_price_min": [
            max(80.0, divergent_price["p90"]),
            max(100.0, divergent_price["p95"]),
        ],
        "initiative_ma_min": [
            initiative_ma["p90"],
            initiative_ma["p95"],
            max(40.0, initiative_ma["p75"]),
        ],
        "initiative_swing_min": [
            initiative_swing["p90"],
            initiative_swing["p95"],
            max(80.0, initiative_swing["p75"]),
        ],
        "rotational_flips_min": [
            5,
        ],
        "rotational_stopping_min_flips": [2, 3],
    }


def _build_candidate_lists(
    features: pd.DataFrame,
    thresholds: Stage25Thresholds,
) -> list[dict[str, Any]]:
    """Fast candidate generation from precomputed feature rows."""

    from intermediate_cognition_engine_v1 import _confidence, _severity_continuation, _severity_initiative

    candidates: list[dict[str, Any]] = []
    for row in features.itertuples(index=False):
        ts = row.timestamp
        delta5 = float(row.delta5)
        price5 = float(row.price5)
        sign_flips = int(row.sign_flips)
        ma5 = float(row.initiative_ma)
        ma5_prev = row.initiative_ma_prev
        vc = row.volume_class
        sources = ["candle_structure_memory"]

        if (
            delta5 > thresholds.continuation_delta_min
            and price5 < -thresholds.continuation_price_min
        ) or (
            delta5 < -thresholds.continuation_delta_min
            and price5 > thresholds.continuation_price_min
        ):
            severity = _severity_continuation(delta5, price5)
            direction = "effort-up/price-down" if delta5 > 0 else "effort-down/price-up"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_CONTINUATION_WEAKENING",
                    "severity": severity,
                    "confidence": _confidence("IC_CONTINUATION_WEAKENING", severity, 1),
                    "source_layers": json.dumps(sources),
                    "reason": f"{direction}; delta5={delta5:.0f}, price5={price5:.1f}",
                }
            )

        if bool(row.initiative_flip) and pd.notna(ma5_prev):
            ma5_prev = float(ma5_prev)
            swing = abs(ma5 - ma5_prev)
            if (
                abs(ma5) >= thresholds.initiative_ma_min
                and abs(ma5_prev) >= thresholds.initiative_ma_min
                and swing >= thresholds.initiative_swing_min
            ):
                severity = _severity_initiative(ma5_prev, ma5)
                candidates.append(
                    {
                        "timestamp": ts,
                        "intermediate_state": "IC_INITIATIVE_DETERIORATION",
                        "severity": severity,
                        "confidence": _confidence("IC_INITIATIVE_DETERIORATION", severity, 1),
                        "source_layers": json.dumps(sources),
                        "reason": f"initiative MA flip {ma5_prev:.0f} → {ma5:.0f}",
                    }
                )

        rotational = sign_flips >= thresholds.rotational_flips_min
        if vc == "stopping" and sign_flips >= thresholds.rotational_stopping_min_flips:
            rotational = True
            sources = list(dict.fromkeys(sources + ["volume_classification_memory"]))
        if rotational:
            severity = (
                "HIGH"
                if sign_flips >= thresholds.rotational_flips_min or vc == "stopping"
                else "MEDIUM"
            )
            if severity == "MEDIUM" and vc != "stopping":
                rotational = False
        if rotational:
            reason = f"sign_flips_5={sign_flips}"
            if vc == "stopping":
                reason += "; volume_class=stopping"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_ROTATIONAL_PRESSURE",
                    "severity": severity,
                    "confidence": _confidence("IC_ROTATIONAL_PRESSURE", severity, len(sources)),
                    "source_layers": json.dumps(sources),
                    "reason": reason,
                }
            )

    return _collapse_bar_candidates(candidates)


def recommend_thresholds(
    candles: pd.DataFrame,
    volume_class: pd.DataFrame | None,
    *,
    start: str = DEFAULT_WINDOW[0],
    end: str = DEFAULT_WINDOW[1],
) -> dict[str, Any]:
    """Search percentile-derived threshold grid for the best live-feed profile."""

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    features = build_feature_frame(candles, volume_class)
    features = features[(features["timestamp"] >= start_ts) & (features["timestamp"] <= end_ts)]
    distributions = summarize_distributions(features)
    grid = derive_threshold_candidates(distributions)

    best: dict[str, Any] | None = None
    for (
        continuation_delta_min,
        continuation_price_min,
        initiative_ma_min,
        initiative_swing_min,
        rotational_flips_min,
        rotational_stopping_min_flips,
    ) in product(
        grid["continuation_delta_min"],
        grid["continuation_price_min"],
        grid["initiative_ma_min"],
        grid["initiative_swing_min"],
        grid["rotational_flips_min"],
        grid["rotational_stopping_min_flips"],
    ):
        thresholds = Stage25Thresholds(
            continuation_delta_min=float(continuation_delta_min),
            continuation_price_min=float(continuation_price_min),
            initiative_ma_min=float(initiative_ma_min),
            initiative_swing_min=float(initiative_swing_min),
            rotational_flips_min=int(rotational_flips_min),
            rotational_stopping_min_flips=int(rotational_stopping_min_flips),
            cooldown_bars=4,
            confidence_material_delta=0.08,
        )
        candidates = _build_candidate_lists(features, thresholds)
        persisted = simulate_persisted(candidates, thresholds)
        profile = _score_profile(persisted, start=start_ts, end=end_ts)
        if profile["total"] == 0:
            continue
        candidate = {"thresholds": thresholds, **profile}
        if best is None or candidate["score"] < best["score"]:
            best = candidate
        elif candidate["score"] == best["score"] and candidate["weekly_rate"] >= best["weekly_rate"]:
            best = candidate

    if best is not None and best.get("rotational_share", 1.0) > MAX_ROTATIONAL_SHARE:
        # Prefer any feasible profile under rotational cap, else keep best effort.
        feasible_best = None
        for (
            continuation_delta_min,
            continuation_price_min,
            initiative_ma_min,
            initiative_swing_min,
            rotational_flips_min,
            rotational_stopping_min_flips,
        ) in product(
            grid["continuation_delta_min"],
            grid["continuation_price_min"],
            grid["initiative_ma_min"],
            grid["initiative_swing_min"],
            [5, 6],
            [3],
        ):
            thresholds = Stage25Thresholds(
                continuation_delta_min=float(continuation_delta_min),
                continuation_price_min=float(continuation_price_min),
                initiative_ma_min=float(initiative_ma_min),
                initiative_swing_min=float(initiative_swing_min),
                rotational_flips_min=int(rotational_flips_min),
                rotational_stopping_min_flips=int(rotational_stopping_min_flips),
                cooldown_bars=4,
                confidence_material_delta=0.08,
            )
            candidates = _build_candidate_lists(features, thresholds)
            persisted = simulate_persisted(candidates, thresholds)
            profile = _score_profile(persisted, start=start_ts, end=end_ts)
            if profile["total"] == 0 or profile["rotational_share"] > MAX_ROTATIONAL_SHARE:
                continue
            candidate = {"thresholds": thresholds, **profile}
            if feasible_best is None or candidate["score"] < feasible_best["score"]:
                feasible_best = candidate
        if feasible_best is not None:
            best = feasible_best

    if best is None:
        best = {
            "thresholds": Stage25Thresholds(
                continuation_delta_min=distributions["continuation_divergence_abs_delta5"]["p90"],
                continuation_price_min=max(80.0, distributions["continuation_divergence_abs_price5"]["p90"]),
                initiative_ma_min=distributions["initiative_ma"]["p90"],
                initiative_swing_min=distributions["initiative_swing"]["p90"],
                rotational_flips_min=5,
                rotational_stopping_min_flips=2,
            ),
            "score": None,
            "weekly_rate": 0.0,
            "distribution": {},
            "rotational_share": 0.0,
            "total": 0,
        }

    return {
        "calibration_window": {"start": start, "end": end},
        "distributions": distributions,
        "recommended": best,
        "grid_candidates": grid,
    }


def write_threshold_config(
    recommendation: dict[str, Any],
    *,
    output_path: Path | None = None,
) -> Path:
    output_path = output_path or (repo_root() / "config" / "stage2_5_thresholds.yaml")
    thresholds: Stage25Thresholds = recommendation["recommended"]["thresholds"]
    payload = {
        "schema_version": 1,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "source": "canonical_live_feed",
        "active_profile": "live_feed",
        "calibration_window": recommendation["calibration_window"],
        "distribution_summary": recommendation["distributions"],
        "expected_density": {
            "weekly_min": TARGET_WEEKLY_MIN,
            "weekly_max": TARGET_WEEKLY_MAX,
            "simulated_weekly_rate": recommendation["recommended"]["weekly_rate"],
            "simulated_total": recommendation["recommended"]["total"],
        },
        "expected_state_mix": recommendation["recommended"]["distribution"],
        "legacy": LEGACY_THRESHOLDS.as_dict(),
        "live_feed": thresholds.as_dict(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, default_flow_style=False)
    return output_path


def run_calibration(
    *,
    start: str = DEFAULT_WINDOW[0],
    end: str = DEFAULT_WINDOW[1],
    write_config: bool = True,
) -> dict[str, Any]:
    candles = _prep(safe_read_parquet("candle_structure_memory.parquet"))
    volume_class = _prep(safe_read_parquet("volume_classification_memory.parquet"))
    recommendation = recommend_thresholds(candles, volume_class, start=start, end=end)
    config_path = None
    if write_config:
        config_path = write_threshold_config(recommendation)
    return {
        **recommendation,
        "config_path": str(config_path) if config_path else None,
    }


if __name__ == "__main__":
    import argparse
    import sys

    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    parser = argparse.ArgumentParser(description="Calibrate Stage 2.5 thresholds from live feed")
    parser.add_argument("--start", default=DEFAULT_WINDOW[0])
    parser.add_argument("--end", default=DEFAULT_WINDOW[1])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    result = run_calibration(start=args.start, end=args.end, write_config=not args.no_write)
    print(json.dumps(result, indent=2, default=str))
