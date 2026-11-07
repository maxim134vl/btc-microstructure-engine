from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = (
    ROOT
    / "data/research/binance_native_first_reaction_v3"
    / "first_reaction_event_level.parquet"
)

OUTPUT_DIR = (
    ROOT
    / "data/research/volume_event_validation_v1"
)

CONFIDENCE_PATH = (
    OUTPUT_DIR
    / "confidence_summary.csv"
)

BOOTSTRAP_PATH = (
    OUTPUT_DIR
    / "bootstrap_summary.csv"
)

SCALING_PATH = (
    OUTPUT_DIR
    / "timeframe_scaling.csv"
)

ONTOLOGY_PATH = (
    OUTPUT_DIR
    / "ontology_review.csv"
)

REPORT_PATH = (
    OUTPUT_DIR
    / "validation_report.json"
)

PRIMARY_TIMEFRAMES = [
    "M15",
    "M30",
    "H1",
    "H4",
]

EXPLORATORY_TIMEFRAMES = [
    "D1",
]

TIMEFRAME_ORDER = {
    "M15": 0,
    "M30": 1,
    "H1": 2,
    "H4": 3,
    "D1": 4,
}

EVENT_ORDER = {
    "BUYING_CLIMAX": 0,
    "SELLING_CLIMAX": 1,
    "STOPPING_VOLUME": 2,
}

EXPECTED_DIRECTION = {
    "BUYING_CLIMAX": "DOWN",
    "SELLING_CLIMAX": "UP",
    "STOPPING_VOLUME": "UP",
}

CONFIDENCE_LEVEL = 0.95
WILSON_Z = 1.959963984540054
ALPHA = 0.05

MIN_CLEAR_CASES = 20
MIN_SCALING_MATCHED_CASES = 10

BOOTSTRAP_ITERATIONS = 10000
RANDOM_SEED = 20260811

BOOTSTRAP_METRICS = [
    "peak_excursion_bps",
    "peak_minutes",
    "reaction_duration_minutes",
    "max_adverse_excursion_bps",
]


def load_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        raise RuntimeError(
            f"Missing input: {INPUT_PATH}"
        )

    frame = pd.read_parquet(
        INPUT_PATH
    ).copy()

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    required = [
        "timeframe",
        "event_type",
        "first_reaction_status",
        "direction_matches_semantics",
    ]

    missing = [
        column
        for column in required
        if column not in frame.columns
    ]

    if missing:
        raise RuntimeError(
            f"Missing columns: {missing}"
        )

    return frame


def wilson_interval(
    successes: int,
    total: int,
    z: float = WILSON_Z,
) -> tuple[float, float]:
    if total <= 0:
        return np.nan, np.nan

    p = successes / total

    denominator = (
        1.0
        + z * z / total
    )

    center = (
        p
        + z * z / (2.0 * total)
    ) / denominator

    margin = (
        z
        * math.sqrt(
            (
                p * (1.0 - p) / total
                + z * z / (
                    4.0 * total * total
                )
            )
        )
        / denominator
    )

    lower = max(
        0.0,
        center - margin,
    )

    upper = min(
        1.0,
        center + margin,
    )

    return lower, upper


def exact_binomial_two_sided(
    successes: int,
    total: int,
) -> float:
    if total <= 0:
        return np.nan

    denominator = float(
        2 ** total
    )

    probabilities = np.asarray(
        [
            math.comb(
                total,
                k,
            )
            / denominator
            for k in range(
                total + 1
            )
        ],
        dtype=float,
    )

    observed = probabilities[
        successes
    ]

    p_value = float(
        probabilities[
            probabilities
            <= observed + 1e-15
        ].sum()
    )

    return min(
        1.0,
        p_value,
    )


def bh_adjust(
    values: pd.Series,
) -> pd.Series:
    result = pd.Series(
        np.nan,
        index=values.index,
        dtype=float,
    )

    valid = values.dropna()

    if valid.empty:
        return result

    ordered = valid.sort_values()

    m = len(ordered)

    raw = np.asarray(
        ordered.values,
        dtype=float,
    )

    ranks = np.arange(
        1,
        m + 1,
        dtype=float,
    )

    adjusted = (
        raw
        * m
        / ranks
    )

    adjusted = np.minimum.accumulate(
        adjusted[::-1]
    )[::-1]

    adjusted = np.clip(
        adjusted,
        0.0,
        1.0,
    )

    result.loc[
        ordered.index
    ] = adjusted

    return result


def evidence_label(
    clear_cases: int,
    lower: float,
    upper: float,
    significance: float,
) -> str:
    if (
        clear_cases
        < MIN_CLEAR_CASES
    ):
        return "INSUFFICIENT_SAMPLE"

    if not np.isfinite(
        significance
    ):
        return "INCONCLUSIVE"

    if (
        significance <= ALPHA
        and lower > 0.50
    ):
        return "SUPPORTS_SEMANTICS"

    if (
        significance <= ALPHA
        and upper < 0.50
    ):
        return "CONTRADICTS_SEMANTICS"

    return "INCONCLUSIVE"


def build_confidence_summary(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    grouped = frame.groupby(
        [
            "timeframe",
            "event_type",
        ],
        dropna=False,
    )

    for (
        timeframe,
        event_type,
    ), group in grouped:
        clear = group[
            group[
                "first_reaction_status"
            ].eq("CLEAR")
        ].copy()

        matches = (
            clear[
                "direction_matches_semantics"
            ]
            .fillna(False)
            .astype(bool)
        )

        total_cases = int(
            len(group)
        )

        clear_cases = int(
            len(clear)
        )

        semantic_matches = int(
            matches.sum()
        )

        semantic_misses = int(
            clear_cases
            - semantic_matches
        )

        if clear_cases:
            rate = (
                semantic_matches
                / clear_cases
            )

            lower, upper = (
                wilson_interval(
                    semantic_matches,
                    clear_cases,
                )
            )

            p_value = (
                exact_binomial_two_sided(
                    semantic_matches,
                    clear_cases,
                )
            )
        else:
            rate = np.nan
            lower = np.nan
            upper = np.nan
            p_value = np.nan

        rows.append(
            {
                "timeframe": timeframe,
                "event_type": event_type,
                "expected_direction": (
                    EXPECTED_DIRECTION.get(
                        event_type
                    )
                ),
                "analysis_scope": (
                    "PRIMARY"
                    if timeframe
                    in PRIMARY_TIMEFRAMES
                    else "EXPLORATORY"
                ),
                "total_cases": (
                    total_cases
                ),
                "clear_cases": (
                    clear_cases
                ),
                "clear_rate_pct": (
                    clear_cases
                    / total_cases
                    * 100.0
                    if total_cases
                    else np.nan
                ),
                "semantic_matches": (
                    semantic_matches
                ),
                "semantic_misses": (
                    semantic_misses
                ),
                "semantic_match_pct": (
                    rate * 100.0
                    if np.isfinite(
                        rate
                    )
                    else np.nan
                ),
                "wilson_95_low_pct": (
                    lower * 100.0
                    if np.isfinite(
                        lower
                    )
                    else np.nan
                ),
                "wilson_95_high_pct": (
                    upper * 100.0
                    if np.isfinite(
                        upper
                    )
                    else np.nan
                ),
                "exact_binomial_p": (
                    p_value
                ),
            }
        )

    summary = pd.DataFrame(
        rows
    )

    primary_mask = (
        summary[
            "analysis_scope"
        ].eq("PRIMARY")
    )

    summary[
        "bh_fdr_q"
    ] = np.nan

    summary.loc[
        primary_mask,
        "bh_fdr_q",
    ] = bh_adjust(
        summary.loc[
            primary_mask,
            "exact_binomial_p",
        ]
    )

    summary[
        "raw_evidence"
    ] = summary.apply(
        lambda row: evidence_label(
            int(
                row[
                    "clear_cases"
                ]
            ),
            float(
                row[
                    "wilson_95_low_pct"
                ]
                / 100.0
            )
            if pd.notna(
                row[
                    "wilson_95_low_pct"
                ]
            )
            else np.nan,
            float(
                row[
                    "wilson_95_high_pct"
                ]
                / 100.0
            )
            if pd.notna(
                row[
                    "wilson_95_high_pct"
                ]
            )
            else np.nan,
            float(
                row[
                    "exact_binomial_p"
                ]
            )
            if pd.notna(
                row[
                    "exact_binomial_p"
                ]
            )
            else np.nan,
        ),
        axis=1,
    )

    summary[
        "fdr_evidence"
    ] = summary.apply(
        lambda row: evidence_label(
            int(
                row[
                    "clear_cases"
                ]
            ),
            float(
                row[
                    "wilson_95_low_pct"
                ]
                / 100.0
            )
            if pd.notna(
                row[
                    "wilson_95_low_pct"
                ]
            )
            else np.nan,
            float(
                row[
                    "wilson_95_high_pct"
                ]
                / 100.0
            )
            if pd.notna(
                row[
                    "wilson_95_high_pct"
                ]
            )
            else np.nan,
            float(
                row[
                    "bh_fdr_q"
                ]
            )
            if pd.notna(
                row[
                    "bh_fdr_q"
                ]
            )
            else np.nan,
        ),
        axis=1,
    )

    summary[
        "tf_order"
    ] = summary[
        "timeframe"
    ].map(
        TIMEFRAME_ORDER
    )

    summary[
        "event_order"
    ] = summary[
        "event_type"
    ].map(
        EVENT_ORDER
    )

    summary = (
        summary
        .sort_values(
            [
                "tf_order",
                "event_order",
            ]
        )
        .drop(
            columns=[
                "tf_order",
                "event_order",
            ]
        )
        .reset_index(drop=True)
    )

    return summary


def bootstrap_median(
    values: pd.Series,
    rng: np.random.Generator,
) -> dict:
    clean = pd.to_numeric(
        values,
        errors="coerce",
    )

    clean = clean[
        np.isfinite(
            clean
        )
    ].to_numpy(
        dtype=float
    )

    n = len(clean)

    if n == 0:
        return {
            "sample_n": 0,
            "median": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
        }

    median = float(
        np.median(clean)
    )

    if n == 1:
        return {
            "sample_n": 1,
            "median": median,
            "ci_low": median,
            "ci_high": median,
        }

    indices = rng.integers(
        0,
        n,
        size=(
            BOOTSTRAP_ITERATIONS,
            n,
        ),
    )

    samples = clean[
        indices
    ]

    medians = np.median(
        samples,
        axis=1,
    )

    lower = float(
        np.quantile(
            medians,
            0.025,
        )
    )

    upper = float(
        np.quantile(
            medians,
            0.975,
        )
    )

    return {
        "sample_n": int(n),
        "median": median,
        "ci_low": lower,
        "ci_high": upper,
    }


def build_bootstrap_summary(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rng = np.random.default_rng(
        RANDOM_SEED
    )

    rows = []

    grouped = frame.groupby(
        [
            "timeframe",
            "event_type",
        ],
        dropna=False,
    )

    for (
        timeframe,
        event_type,
    ), group in grouped:
        clear = group[
            group[
                "first_reaction_status"
            ].eq("CLEAR")
        ].copy()

        matched = clear[
            clear[
                "direction_matches_semantics"
            ]
            .fillna(False)
            .astype(bool)
        ].copy()

        scopes = {
            "ALL_CLEAR": clear,
            "SEMANTIC_MATCHED": matched,
        }

        for scope_name, scope in (
            scopes.items()
        ):
            for metric in (
                BOOTSTRAP_METRICS
            ):
                if (
                    metric
                    not in scope.columns
                ):
                    continue

                result = (
                    bootstrap_median(
                        scope[metric],
                        rng,
                    )
                )

                rows.append(
                    {
                        "timeframe": (
                            timeframe
                        ),
                        "event_type": (
                            event_type
                        ),
                        "scope": (
                            scope_name
                        ),
                        "metric": metric,
                        "sample_n": (
                            result[
                                "sample_n"
                            ]
                        ),
                        "median": (
                            result[
                                "median"
                            ]
                        ),
                        "bootstrap_95_low": (
                            result[
                                "ci_low"
                            ]
                        ),
                        "bootstrap_95_high": (
                            result[
                                "ci_high"
                            ]
                        ),
                        "bootstrap_iterations": (
                            BOOTSTRAP_ITERATIONS
                        ),
                        "sample_status": (
                            "SUFFICIENT"
                            if result[
                                "sample_n"
                            ]
                            >= MIN_CLEAR_CASES
                            else "LOW_N"
                        ),
                    }
                )

    result = pd.DataFrame(
        rows
    )

    result[
        "tf_order"
    ] = result[
        "timeframe"
    ].map(
        TIMEFRAME_ORDER
    )

    result[
        "event_order"
    ] = result[
        "event_type"
    ].map(
        EVENT_ORDER
    )

    result = (
        result
        .sort_values(
            [
                "tf_order",
                "event_order",
                "scope",
                "metric",
            ]
        )
        .drop(
            columns=[
                "tf_order",
                "event_order",
            ]
        )
        .reset_index(drop=True)
    )

    return result


def strictly_increasing(
    values: list[float],
) -> bool:
    clean = [
        float(value)
        for value in values
        if np.isfinite(
            value
        )
    ]

    if len(clean) < 3:
        return False

    return all(
        current > previous
        for previous, current
        in zip(
            clean[:-1],
            clean[1:],
        )
    )


def build_scaling_summary(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rng = np.random.default_rng(
        RANDOM_SEED + 1
    )

    rows = []

    primary_frame = frame[
        frame[
            "timeframe"
        ].isin(
            PRIMARY_TIMEFRAMES
        )
    ].copy()

    for event_type in sorted(
        primary_frame[
            "event_type"
        ].dropna().unique(),
        key=lambda value: (
            EVENT_ORDER.get(
                value,
                999,
            )
        ),
    ):
        event_rows = []

        for timeframe in (
            PRIMARY_TIMEFRAMES
        ):
            group = primary_frame[
                primary_frame[
                    "event_type"
                ].eq(
                    event_type
                )
                &
                primary_frame[
                    "timeframe"
                ].eq(
                    timeframe
                )
            ].copy()

            clear = group[
                group[
                    "first_reaction_status"
                ].eq("CLEAR")
            ].copy()

            matched = clear[
                clear[
                    "direction_matches_semantics"
                ]
                .fillna(False)
                .astype(bool)
            ].copy()

            peak = bootstrap_median(
                matched[
                    "peak_excursion_bps"
                ]
                if (
                    "peak_excursion_bps"
                    in matched.columns
                )
                else pd.Series(
                    dtype=float
                ),
                rng,
            )

            peak_time = bootstrap_median(
                matched[
                    "peak_minutes"
                ]
                if (
                    "peak_minutes"
                    in matched.columns
                )
                else pd.Series(
                    dtype=float
                ),
                rng,
            )

            duration = bootstrap_median(
                matched[
                    "reaction_duration_minutes"
                ]
                if (
                    "reaction_duration_minutes"
                    in matched.columns
                )
                else pd.Series(
                    dtype=float
                ),
                rng,
            )

            row = {
                "event_type": event_type,
                "timeframe": timeframe,
                "matched_cases": int(
                    len(matched)
                ),
                "scaling_scope": (
                    "PRIMARY"
                    if len(matched)
                    >= MIN_SCALING_MATCHED_CASES
                    else "EXPLORATORY_LOW_N"
                ),
                "median_peak_excursion_bps": (
                    peak["median"]
                ),
                "peak_bootstrap_95_low": (
                    peak["ci_low"]
                ),
                "peak_bootstrap_95_high": (
                    peak["ci_high"]
                ),
                "median_peak_minutes": (
                    peak_time[
                        "median"
                    ]
                ),
                "peak_minutes_bootstrap_95_low": (
                    peak_time[
                        "ci_low"
                    ]
                ),
                "peak_minutes_bootstrap_95_high": (
                    peak_time[
                        "ci_high"
                    ]
                ),
                "median_duration_minutes": (
                    duration[
                        "median"
                    ]
                ),
                "duration_bootstrap_95_low": (
                    duration[
                        "ci_low"
                    ]
                ),
                "duration_bootstrap_95_high": (
                    duration[
                        "ci_high"
                    ]
                ),
            }

            event_rows.append(
                row
            )

        eligible = [
            row
            for row in event_rows
            if row[
                "matched_cases"
            ]
            >= MIN_SCALING_MATCHED_CASES
        ]

        amplitude_values = [
            row[
                "median_peak_excursion_bps"
            ]
            for row in eligible
        ]

        duration_values = [
            row[
                "median_duration_minutes"
            ]
            for row in eligible
        ]

        amplitude_monotonic = (
            strictly_increasing(
                amplitude_values
            )
            if len(eligible) >= 3
            else np.nan
        )

        duration_monotonic = (
            strictly_increasing(
                duration_values
            )
            if len(eligible) >= 3
            else np.nan
        )

        eligible_timeframes = "|".join(
            row[
                "timeframe"
            ]
            for row in eligible
        )

        previous_peak = np.nan
        previous_duration = np.nan

        for row in event_rows:
            current_peak = row[
                "median_peak_excursion_bps"
            ]

            current_duration = row[
                "median_duration_minutes"
            ]

            row[
                "peak_ratio_vs_previous_tf"
            ] = (
                current_peak
                / previous_peak
                if (
                    np.isfinite(
                        current_peak
                    )
                    and np.isfinite(
                        previous_peak
                    )
                    and previous_peak != 0
                )
                else np.nan
            )

            row[
                "duration_ratio_vs_previous_tf"
            ] = (
                current_duration
                / previous_duration
                if (
                    np.isfinite(
                        current_duration
                    )
                    and np.isfinite(
                        previous_duration
                    )
                    and previous_duration != 0
                )
                else np.nan
            )

            row[
                "event_primary_scaling_timeframes"
            ] = eligible_timeframes

            row[
                "event_primary_amplitude_monotonic"
            ] = amplitude_monotonic

            row[
                "event_primary_duration_monotonic"
            ] = duration_monotonic

            previous_peak = (
                current_peak
            )

            previous_duration = (
                current_duration
            )

            rows.append(
                row
            )

    return pd.DataFrame(
        rows
    )


def build_ontology_review(
    frame: pd.DataFrame,
    confidence: pd.DataFrame,
) -> pd.DataFrame:
    primary = frame[
        frame[
            "timeframe"
        ].isin(
            PRIMARY_TIMEFRAMES
        )
    ].copy()

    rows = []

    for event_type, group in (
        primary.groupby(
            "event_type"
        )
    ):
        clear = group[
            group[
                "first_reaction_status"
            ].eq("CLEAR")
        ].copy()

        matches = (
            clear[
                "direction_matches_semantics"
            ]
            .fillna(False)
            .astype(bool)
        )

        total_cases = int(
            len(group)
        )

        clear_cases = int(
            len(clear)
        )

        semantic_matches = int(
            matches.sum()
        )

        if clear_cases:
            match_rate = (
                semantic_matches
                / clear_cases
            )

            lower, upper = (
                wilson_interval(
                    semantic_matches,
                    clear_cases,
                )
            )

            p_value = (
                exact_binomial_two_sided(
                    semantic_matches,
                    clear_cases,
                )
            )
        else:
            match_rate = np.nan
            lower = np.nan
            upper = np.nan
            p_value = np.nan

        event_conf = confidence[
            confidence[
                "event_type"
            ].eq(
                event_type
            )
            &
            confidence[
                "analysis_scope"
            ].eq("PRIMARY")
        ]

        rows.append(
            {
                "event_type": (
                    event_type
                ),
                "expected_direction": (
                    EXPECTED_DIRECTION.get(
                        event_type
                    )
                ),
                "timeframes": (
                    "|".join(
                        PRIMARY_TIMEFRAMES
                    )
                ),
                "total_cases": (
                    total_cases
                ),
                "clear_cases": (
                    clear_cases
                ),
                "clear_rate_pct": (
                    clear_cases
                    / total_cases
                    * 100.0
                    if total_cases
                    else np.nan
                ),
                "semantic_matches": (
                    semantic_matches
                ),
                "semantic_match_pct": (
                    match_rate * 100.0
                    if np.isfinite(
                        match_rate
                    )
                    else np.nan
                ),
                "wilson_95_low_pct": (
                    lower * 100.0
                    if np.isfinite(
                        lower
                    )
                    else np.nan
                ),
                "wilson_95_high_pct": (
                    upper * 100.0
                    if np.isfinite(
                        upper
                    )
                    else np.nan
                ),
                "exact_binomial_p": (
                    p_value
                ),
                "tf_raw_support_count": int(
                    event_conf[
                        "raw_evidence"
                    ]
                    .eq(
                        "SUPPORTS_SEMANTICS"
                    )
                    .sum()
                ),
                "tf_raw_contradiction_count": int(
                    event_conf[
                        "raw_evidence"
                    ]
                    .eq(
                        "CONTRADICTS_SEMANTICS"
                    )
                    .sum()
                ),
            }
        )

    review = pd.DataFrame(
        rows
    )

    review[
        "bh_fdr_q"
    ] = bh_adjust(
        review[
            "exact_binomial_p"
        ]
    )

    review[
        "raw_evidence"
    ] = review.apply(
        lambda row: evidence_label(
            int(
                row[
                    "clear_cases"
                ]
            ),
            float(
                row[
                    "wilson_95_low_pct"
                ]
                / 100.0
            ),
            float(
                row[
                    "wilson_95_high_pct"
                ]
                / 100.0
            ),
            float(
                row[
                    "exact_binomial_p"
                ]
            ),
        ),
        axis=1,
    )

    review[
        "fdr_evidence"
    ] = review.apply(
        lambda row: evidence_label(
            int(
                row[
                    "clear_cases"
                ]
            ),
            float(
                row[
                    "wilson_95_low_pct"
                ]
                / 100.0
            ),
            float(
                row[
                    "wilson_95_high_pct"
                ]
                / 100.0
            ),
            float(
                row[
                    "bh_fdr_q"
                ]
            ),
        ),
        axis=1,
    )

    review[
        "event_order"
    ] = review[
        "event_type"
    ].map(
        EVENT_ORDER
    )

    review = (
        review
        .sort_values(
            "event_order"
        )
        .drop(
            columns=[
                "event_order"
            ]
        )
        .reset_index(drop=True)
    )

    return review


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame = load_data()

    confidence = (
        build_confidence_summary(
            frame
        )
    )

    bootstrap = (
        build_bootstrap_summary(
            frame
        )
    )

    scaling = (
        build_scaling_summary(
            frame
        )
    )

    ontology = (
        build_ontology_review(
            frame,
            confidence,
        )
    )

    confidence.to_csv(
        CONFIDENCE_PATH,
        index=False,
    )

    bootstrap.to_csv(
        BOOTSTRAP_PATH,
        index=False,
    )

    scaling.to_csv(
        SCALING_PATH,
        index=False,
    )

    ontology.to_csv(
        ONTOLOGY_PATH,
        index=False,
    )

    report = {
        "input": str(
            INPUT_PATH
        ),
        "event_rows": int(
            len(frame)
        ),
        "primary_timeframes": (
            PRIMARY_TIMEFRAMES
        ),
        "exploratory_timeframes": (
            EXPLORATORY_TIMEFRAMES
        ),
        "confidence_level": (
            CONFIDENCE_LEVEL
        ),
        "alpha": ALPHA,
        "minimum_clear_cases": (
            MIN_CLEAR_CASES
        ),
        "minimum_scaling_matched_cases": (
            MIN_SCALING_MATCHED_CASES
        ),
        "bootstrap_iterations": (
            BOOTSTRAP_ITERATIONS
        ),
        "random_seed": (
            RANDOM_SEED
        ),
        "multiple_testing": (
            "Benjamini-Hochberg FDR"
        ),
        "outputs": {
            "confidence_summary": str(
                CONFIDENCE_PATH
            ),
            "bootstrap_summary": str(
                BOOTSTRAP_PATH
            ),
            "timeframe_scaling": str(
                SCALING_PATH
            ),
            "ontology_review": str(
                ONTOLOGY_PATH
            ),
        },
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    key_bootstrap = bootstrap[
        bootstrap[
            "scope"
        ].eq(
            "SEMANTIC_MATCHED"
        )
        &
        bootstrap[
            "metric"
        ].isin(
            [
                "peak_excursion_bps",
                "peak_minutes",
                "reaction_duration_minutes",
            ]
        )
    ].copy()

    print(
        "INPUT_EVENT_ROWS",
        len(frame),
    )

    print()
    print(
        "CONFIDENCE_SUMMARY"
    )

    print(
        confidence.to_string(
            index=False
        )
    )

    print()
    print(
        "ONTOLOGY_REVIEW"
    )

    print(
        ontology.to_string(
            index=False
        )
    )

    print()
    print(
        "TIMEFRAME_SCALING"
    )

    print(
        scaling.to_string(
            index=False
        )
    )

    print()
    print(
        "BOOTSTRAP_KEY_METRICS"
    )

    print(
        key_bootstrap.to_string(
            index=False
        )
    )

    print()
    print(
        "CONFIDENCE",
        CONFIDENCE_PATH,
    )

    print(
        "BOOTSTRAP",
        BOOTSTRAP_PATH,
    )

    print(
        "SCALING",
        SCALING_PATH,
    )

    print(
        "ONTOLOGY",
        ONTOLOGY_PATH,
    )

    print(
        "REPORT",
        REPORT_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
