"""Phase 1A calibration diagnostics — observability only, no behavioral changes."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

SATURATION_THRESHOLD = 0.90
SATURATION_PERSISTENCE_MIN = 3
RUNAWAY_REINFORCEMENT_STEPS = 5
HIGH_CONVICTION_REPEAT_MIN = 4
ENTROPY_SUPPRESSION_CONVICTION_MIN = 0.70
ENTROPY_SUPPRESSION_ENTROPY_MAX = 0.35

TRACKED_SURVIVAL_REGIMES = {
    "HIGH_CONVICTION_AUCTION",
}
TRACKED_SURVIVAL_SYNTHESIS = {
    "LOCAL_EXHAUSTION",
    "STRUCTURAL_REVERSAL",
}
TRACKED_SURVIVAL_LOCATION = {
    "LOWER_ABSORPTION",
}

DECOMPOSITION_COMPONENTS = [
    "alignment_component",
    "persistence_component",
    "reinforcement_component",
    "entropy_penalty",
    "conflict_penalty",
]

SATURATION_EXPORT_COLUMNS = [
    "saturation_score",
    "reinforcement_acceleration",
    "conviction_entropy_ratio",
    "alignment_monoculture_score",
    "conviction_saturated",
    "conviction_saturated_persistence",
    "repeated_high_conviction",
    "runaway_reinforcement",
    "entropy_suppression_failure",
]

PERSISTENCE_EXPORT_COLUMNS = [
    "persistence_duration",
    "survival_half_life",
    "continuation_decay_rate",
    "persistence_decay_velocity",
]

CONFLICT_EXPORT_COLUMNS = [
    "conflict_density",
    "contradiction_flags",
    "contradiction_clusters",
]

CALIBRATION_EXPORT_COLUMNS = [
    "raw_conviction",
    "calibrated_conviction",
]

DIAGNOSTIC_EXPORT_COLUMNS = (
    SATURATION_EXPORT_COLUMNS
    + PERSISTENCE_EXPORT_COLUMNS
    + CONFLICT_EXPORT_COLUMNS
    + CALIBRATION_EXPORT_COLUMNS
)


def apply_sigmoid_calibration(raw_conviction: float) -> float:
    """Passive sigmoid wrapper — does not affect runtime conviction."""

    value = float(raw_conviction)
    value = max(min(value, 20.0), -20.0)
    return 1.0 / (1.0 + math.exp(-value))


def _safe_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns or len(frame) == 0:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _consecutive_true(values: Sequence[bool]) -> int:
    count = 0
    for value in reversed(list(values)):
        if value:
            count += 1
        else:
            break
    return count


def _consecutive_equal(values: Sequence[Any]) -> int:
    if not values:
        return 0
    target = values[-1]
    count = 0
    for value in reversed(list(values)):
        if value == target:
            count += 1
        else:
            break
    return count


def _monotonic_increase(series: pd.Series, steps: int) -> bool:
    if len(series) < steps:
        return False
    tail = series.tail(steps).tolist()
    return all(tail[index] < tail[index + 1] for index in range(len(tail) - 1))


def _estimate_half_life(values: pd.Series) -> float:
    if len(values) < 2:
        return float("nan")

    positive = values[values > 0]
    if len(positive) < 2:
        return float("nan")

    ratios = positive.iloc[1:].values / positive.iloc[:-1].values
    ratios = ratios[(ratios > 0) & (ratios < 1)]
    if len(ratios) == 0:
        return float("nan")

    mean_ratio = float(np.mean(ratios))
    if mean_ratio <= 0 or mean_ratio >= 1:
        return float("nan")

    return float(-1.0 / math.log(mean_ratio))


def compute_saturation_metrics(
    probabilistic_history: pd.DataFrame,
    reinforcement_history: pd.DataFrame,
    current_row: Dict[str, Any],
) -> Dict[str, Any]:
    raw_conviction = float(current_row.get("raw_conviction", 0.0))
    entropy_penalty = float(current_row.get("entropy_penalty", 0.0))
    alignment_component = float(current_row.get("alignment_component", 1.0))
    reinforcement_component = float(
        current_row.get("reinforcement_component", 0.0)
    )

    saturation_score = max(0.0, min(1.0, (raw_conviction - 0.5) / 0.5))

    reinforcement_acceleration = 0.0
    if (
        len(probabilistic_history) >= 2
        and "reinforcement_component" in probabilistic_history.columns
    ):
        recent = _safe_series(probabilistic_history, "reinforcement_component")
        if len(recent) >= 2:
            reinforcement_acceleration = float(recent.iloc[-1] - recent.iloc[-2])

    conviction_entropy_ratio = raw_conviction / max(entropy_penalty, 1e-6)

    alignment_monoculture_score = 0.0
    if (
        len(probabilistic_history) > 0
        and "alignment_component" in probabilistic_history.columns
    ):
        recent_alignment = _safe_series(
            probabilistic_history,
            "alignment_component",
        ).tail(25)
        if len(recent_alignment) > 0:
            mode_share = (
                recent_alignment.round(4).value_counts(normalize=True).max()
            )
            alignment_monoculture_score = float(mode_share)

    conviction_values = _safe_series(
        probabilistic_history,
        "conviction_probability",
    )
    if len(conviction_values) == 0:
        conviction_values = pd.Series([raw_conviction])

    saturated_flags = (conviction_values > SATURATION_THRESHOLD).tolist()
    conviction_saturated = raw_conviction > SATURATION_THRESHOLD
    conviction_saturated_persistence = _consecutive_true(
        saturated_flags + [conviction_saturated]
    )

    repeated_high_conviction = False
    if (
        len(reinforcement_history) > 0
        and "belief_state" in reinforcement_history.columns
    ):
        high_count = int(
            (reinforcement_history.tail(25)["belief_state"] == "HIGH_CONVICTION")
            .sum()
        )
        repeated_high_conviction = high_count >= HIGH_CONVICTION_REPEAT_MIN

    runaway_reinforcement = False
    if len(probabilistic_history) > 0:
        reinforcement_series = _safe_series(
            probabilistic_history,
            "reinforcement_component",
        )
        if len(reinforcement_series) >= RUNAWAY_REINFORCEMENT_STEPS:
            runaway_reinforcement = _monotonic_increase(
                reinforcement_series,
                RUNAWAY_REINFORCEMENT_STEPS,
            )

    entropy_suppression_failure = (
        raw_conviction >= ENTROPY_SUPPRESSION_CONVICTION_MIN
        and entropy_penalty <= ENTROPY_SUPPRESSION_ENTROPY_MAX
    )

    return {
        "saturation_score": saturation_score,
        "reinforcement_acceleration": reinforcement_acceleration,
        "conviction_entropy_ratio": conviction_entropy_ratio,
        "alignment_monoculture_score": alignment_monoculture_score,
        "conviction_saturated": conviction_saturated,
        "conviction_saturated_persistence": conviction_saturated_persistence,
        "repeated_high_conviction": repeated_high_conviction,
        "runaway_reinforcement": runaway_reinforcement,
        "entropy_suppression_failure": entropy_suppression_failure,
    }


def compute_persistence_survival(
    probabilistic_history: pd.DataFrame,
    runtime_cognition: Dict[str, Any],
    current_regime: str,
) -> Dict[str, Any]:
    regimes = []
    if (
        len(probabilistic_history) > 0
        and "auction_regime" in probabilistic_history.columns
    ):
        regimes = probabilistic_history["auction_regime"].tolist()

    persistence_duration = _consecutive_equal(regimes + [current_regime])

    synthesis_state = runtime_cognition.get("synthesis_state", "NONE")
    location_bias = runtime_cognition.get("location_bias", "NEUTRAL")
    persistence_score = float(runtime_cognition.get("persistence_score", 0.0))

    tracked_active = (
        current_regime in TRACKED_SURVIVAL_REGIMES
        or synthesis_state in TRACKED_SURVIVAL_SYNTHESIS
        or location_bias in TRACKED_SURVIVAL_LOCATION
    )

    conviction_series = _safe_series(
        probabilistic_history,
        "conviction_probability",
    )
    persistence_series = _safe_series(
        probabilistic_history,
        "persistence_component",
    )

    survival_half_life = _estimate_half_life(conviction_series.tail(25))
    if not tracked_active:
        survival_half_life = float("nan")

    continuation_decay_rate = 0.0
    if len(conviction_series) >= 2:
        deltas = conviction_series.diff().dropna()
        negative = deltas[deltas < 0]
        if len(negative) > 0:
            continuation_decay_rate = float(abs(negative.mean()))

    persistence_decay_velocity = 0.0
    if len(persistence_series) >= 2:
        persistence_decay_velocity = float(
            persistence_series.iloc[-1] - persistence_series.iloc[-2]
        )
    elif tracked_active:
        persistence_decay_velocity = persistence_score - float(
            persistence_series.iloc[-1]
            if len(persistence_series) > 0
            else persistence_score
        )

    if not tracked_active:
        persistence_duration = 0

    return {
        "persistence_duration": persistence_duration,
        "survival_half_life": survival_half_life,
        "continuation_decay_rate": continuation_decay_rate,
        "persistence_decay_velocity": persistence_decay_velocity,
    }


def compute_conflict_density(
    current_row: Dict[str, Any],
    reinforcement_window: pd.DataFrame,
) -> Dict[str, Any]:
    absorption_probability = float(
        current_row.get("absorption_probability", 0.0)
    )
    distribution_probability = float(
        current_row.get("distribution_probability", 0.0)
    )
    conviction_probability = float(
        current_row.get("raw_conviction", current_row.get("conviction_probability", 0.0))
    )
    alignment_component = float(current_row.get("alignment_component", 1.0))
    entropy_penalty = float(current_row.get("entropy_penalty", 0.0))
    persistence_component = float(current_row.get("persistence_component", 0.0))
    unfinished_auction_component = float(
        current_row.get("unfinished_auction_component", 0.0)
    )

    active_states: List[str] = []
    conflicting_pairs: List[str] = []
    flags: List[str] = []
    clusters: Dict[str, List[str]] = {
        "continuation_distribution": [],
        "alignment_entropy": [],
        "unfinished_persistence": [],
        "reinforcement_conflict": [],
    }

    if absorption_probability > 0.4:
        active_states.append("absorption_active")
    if distribution_probability > 0.4:
        active_states.append("distribution_active")
    if conviction_probability > 0.5:
        active_states.append("continuation_active")
    if alignment_component > 1.0:
        active_states.append("alignment_active")
    if entropy_penalty > 0.3:
        active_states.append("entropy_active")
    if unfinished_auction_component > 0:
        active_states.append("unfinished_auction_active")
    if persistence_component > 0.3:
        active_states.append("persistence_active")

    if (
        conviction_probability > 0.55
        and distribution_probability > 0.5
    ):
        flags.append("continuation_plus_distribution")
        conflicting_pairs.append("continuation_distribution")
        clusters["continuation_distribution"].append(
            "continuation_plus_distribution"
        )

    if alignment_component > 1.15 and entropy_penalty > 0.45:
        flags.append("high_alignment_rising_entropy")
        conflicting_pairs.append("alignment_entropy")
        clusters["alignment_entropy"].append("high_alignment_rising_entropy")

    if unfinished_auction_component > 0 and persistence_component < 0.35:
        flags.append("unfinished_auction_weak_persistence")
        conflicting_pairs.append("unfinished_weak_persistence")
        clusters["unfinished_persistence"].append(
            "unfinished_auction_weak_persistence"
        )

    if (
        len(reinforcement_window) > 0
        and "localized_behavior" in reinforcement_window.columns
        and "effort_result_state" in reinforcement_window.columns
    ):
        distribution_active = (
            reinforcement_window["localized_behavior"]
            == "localized_distribution"
        ).any()
        absorption_active = (
            reinforcement_window["effort_result_state"]
            == "ABSORPTION_RESPONSE"
        ).any()
        if distribution_active and absorption_active and conviction_probability > 0.6:
            flags.append("absorption_distribution_coexistence")
            conflicting_pairs.append("absorption_distribution")
            clusters["reinforcement_conflict"].append(
                "absorption_distribution_coexistence"
            )

    conflict_density = len(set(conflicting_pairs)) / max(len(active_states), 1)

    non_empty_clusters = {
        key: value for key, value in clusters.items() if value
    }

    return {
        "conflict_density": conflict_density,
        "contradiction_flags": "|".join(flags),
        "contradiction_clusters": json.dumps(non_empty_clusters),
    }


def build_diagnostic_exports(
    probabilistic_history: pd.DataFrame,
    reinforcement_history: pd.DataFrame,
    reinforcement_window: pd.DataFrame,
    runtime_cognition: Dict[str, Any],
    current_row: Dict[str, Any],
) -> Dict[str, Any]:
    raw_conviction = float(
        current_row.get(
            "raw_conviction",
            current_row.get("conviction_probability", 0.0),
        )
    )
    current_row = dict(current_row)
    current_row["raw_conviction"] = raw_conviction

    diagnostics = {
        "raw_conviction": raw_conviction,
        "calibrated_conviction": apply_sigmoid_calibration(raw_conviction),
    }
    diagnostics.update(
        compute_saturation_metrics(
            probabilistic_history,
            reinforcement_history,
            current_row,
        )
    )
    diagnostics.update(
        compute_persistence_survival(
            probabilistic_history,
            runtime_cognition,
            str(current_row.get("auction_regime", "UNCERTAIN")),
        )
    )
    diagnostics.update(
        compute_conflict_density(
            current_row,
            reinforcement_window,
        )
    )
    return diagnostics


def dominant_component(row: pd.Series) -> str:
    scores = {}
    for component in DECOMPOSITION_COMPONENTS:
        if component not in row.index:
            continue
        value = row.get(component)
        if pd.isna(value):
            continue
        scores[component] = abs(float(value))

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)


def component_contribution_distribution(
    frame: pd.DataFrame,
    components: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, float]]:
    components = list(components or DECOMPOSITION_COMPONENTS)
    output: Dict[str, Dict[str, float]] = {}

    available = [column for column in components if column in frame.columns]
    if not available or len(frame) == 0:
        return output

    subset = frame[available].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    totals = subset.abs().sum(axis=1).replace(0, np.nan)
    shares = subset.abs().div(totals, axis=0).fillna(0.0)

    for column in available:
        output[column] = {
            "mean_share": float(shares[column].mean()),
            "median_share": float(shares[column].median()),
            "p90_share": float(shares[column].quantile(0.9)),
            "max_share": float(shares[column].max()),
        }

    return output


def alignment_dominance_ratio(frame: pd.DataFrame) -> float:
    if len(frame) == 0 or "alignment_component" not in frame.columns:
        return float("nan")

    alignment = pd.to_numeric(
        frame["alignment_component"],
        errors="coerce",
    ).fillna(1.0)
    components = frame.reindex(
        columns=DECOMPOSITION_COMPONENTS,
        fill_value=0.0,
    ).apply(pd.to_numeric, errors="coerce").fillna(0.0)

    totals = components.abs().sum(axis=1).replace(0, np.nan)
    alignment_share = alignment.abs() / totals
    return float(alignment_share.mean())


def analyze_realism(
    reinforcement_path: str = "auction_reinforcement_memory.parquet",
    probabilistic_path: str = "probabilistic_auction_memory.parquet",
) -> Dict[str, Any]:
    reinforcement = pd.read_parquet(reinforcement_path)
    probabilistic = pd.read_parquet(probabilistic_path)

    prob_diag = probabilistic.dropna(
        subset=[column for column in DECOMPOSITION_COMPONENTS if column in probabilistic.columns],
        how="all",
    )
    if len(prob_diag) == 0:
        prob_diag = probabilistic.tail(100)

    rein_diag = reinforcement.dropna(
        subset=[column for column in DECOMPOSITION_COMPONENTS if column in reinforcement.columns],
        how="all",
    )
    if len(rein_diag) == 0:
        rein_diag = reinforcement.tail(100)

    prob_dominant = prob_diag.apply(dominant_component, axis=1)
    rein_dominant = rein_diag.apply(dominant_component, axis=1)

    conviction = pd.to_numeric(
        prob_diag.get("conviction_probability", prob_diag.get("raw_conviction")),
        errors="coerce",
    )
    entropy = pd.to_numeric(prob_diag.get("entropy_penalty"), errors="coerce")

    high_conviction_runs = rein_diag[
        rein_diag.get("belief_state") == "HIGH_CONVICTION"
    ] if "belief_state" in rein_diag.columns else pd.DataFrame()

    return {
        "probabilistic_rows_analyzed": len(prob_diag),
        "reinforcement_rows_analyzed": len(rein_diag),
        "probabilistic_component_distribution": component_contribution_distribution(
            prob_diag
        ),
        "reinforcement_component_distribution": component_contribution_distribution(
            rein_diag
        ),
        "probabilistic_dominant_component_frequency": prob_dominant.value_counts(
            normalize=True
        ).to_dict(),
        "reinforcement_dominant_component_frequency": rein_dominant.value_counts(
            normalize=True
        ).to_dict(),
        "reinforcement_persistence_duration_estimate": int(
            _consecutive_equal(
                rein_diag["belief_state"].tolist()
                if "belief_state" in rein_diag.columns
                else []
            )
        ),
        "entropy_suppression_frequency": float(
            (
                (conviction >= ENTROPY_SUPPRESSION_CONVICTION_MIN)
                & (entropy <= ENTROPY_SUPPRESSION_ENTROPY_MAX)
            ).mean()
        )
        if len(prob_diag) > 0
        else float("nan"),
        "conviction_saturation_frequency": float(
            (conviction > SATURATION_THRESHOLD).mean()
        )
        if len(prob_diag) > 0
        else float("nan"),
        "alignment_dominance_ratio": alignment_dominance_ratio(prob_diag),
        "high_conviction_state_count": len(high_conviction_runs),
        "mean_conviction_probability": float(conviction.mean())
        if len(conviction.dropna()) > 0
        else float("nan"),
        "mean_entropy_penalty": float(entropy.mean())
        if len(entropy.dropna()) > 0
        else float("nan"),
        "mean_conflict_penalty_probabilistic": float(
            pd.to_numeric(prob_diag.get("conflict_penalty"), errors="coerce").mean()
        )
        if "conflict_penalty" in prob_diag.columns
        else float("nan"),
    }
