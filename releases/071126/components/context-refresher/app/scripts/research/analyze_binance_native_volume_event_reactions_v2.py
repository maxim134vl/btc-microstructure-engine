from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

EVENTS_PATH = (
    ROOT
    / "data/research/binance_native_volume_events_v1/events.parquet"
)

PRICE_DIR = (
    ROOT
    / "data/research/binance_native_ohlcv_v1"
)

OUTPUT_DIR = (
    ROOT
    / "data/research/binance_native_volume_reactions_v2"
)

EVENT_LEVEL_PATH = (
    OUTPUT_DIR
    / "event_reactions.parquet"
)

PATH_SUMMARY_PATH = (
    OUTPUT_DIR
    / "reaction_path_summary.csv"
)

LENGTH_SUMMARY_PATH = (
    OUTPUT_DIR
    / "reaction_length_summary.csv"
)

COVERAGE_PATH = (
    OUTPUT_DIR
    / "event_coverage.csv"
)

PATH_OFFSETS = [
    1,
    2,
    4,
    8,
    16,
    32,
]

TIMEFRAME_MINUTES = {
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

EXPECTED_DIRECTION = {
    "BUYING_CLIMAX": "DOWN",
    "SELLING_CLIMAX": "UP",
    "STOPPING_VOLUME": "UP",
}


def raw_return_bps(
    end_price: float,
    start_price: float,
) -> float:
    return (
        end_price / start_price - 1.0
    ) * 10000.0


def expected_close_reaction_bps(
    end_price: float,
    start_price: float,
    direction: str,
) -> float:
    value = raw_return_bps(
        end_price,
        start_price,
    )

    if direction == "UP":
        return value

    return -value


def favorable_excursion_bps(
    high_price: float,
    low_price: float,
    anchor_price: float,
    direction: str,
) -> float:
    if direction == "UP":
        return (
            high_price
            / anchor_price
            - 1.0
        ) * 10000.0

    return (
        anchor_price
        / low_price
        - 1.0
    ) * 10000.0


def adverse_excursion_bps(
    high_price: float,
    low_price: float,
    anchor_price: float,
    direction: str,
) -> float:
    if direction == "UP":
        return (
            anchor_price
            / low_price
            - 1.0
        ) * 10000.0

    return (
        high_price
        / anchor_price
        - 1.0
    ) * 10000.0


def load_events() -> pd.DataFrame:
    events = pd.read_parquet(
        EVENTS_PATH
    ).copy()

    events["timestamp"] = pd.to_datetime(
        events["timestamp"],
        utc=True,
        errors="coerce",
    )

    events = (
        events
        .dropna(
            subset=[
                "timestamp",
                "timeframe",
                "auction_event_type",
            ]
        )
        .sort_values(
            [
                "timeframe",
                "timestamp",
            ]
        )
        .reset_index(drop=True)
    )

    return events


def load_price(
    timeframe: str,
) -> pd.DataFrame:
    path = (
        PRICE_DIR
        / f"{timeframe}_native.parquet"
    )

    frame = pd.read_parquet(
        path
    ).copy()

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    frame = (
        frame
        .dropna(
            subset=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
            ]
        )
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return frame


def find_next_event_features(
    tf_events: pd.DataFrame,
    event_number: int,
    current_index: int,
    index_by_timestamp: dict,
) -> dict:
    if (
        event_number + 1
        >= len(tf_events)
    ):
        return {
            "next_event_type": None,
            "bars_to_next_event": np.nan,
            "next_event_same_type": False,
            "next_event_different_type": False,
        }

    current = tf_events.iloc[
        event_number
    ]

    next_event = tf_events.iloc[
        event_number + 1
    ]

    next_timestamp = next_event[
        "timestamp"
    ]

    if (
        next_timestamp
        not in index_by_timestamp
    ):
        return {
            "next_event_type": next_event[
                "auction_event_type"
            ],
            "bars_to_next_event": np.nan,
            "next_event_same_type": False,
            "next_event_different_type": False,
        }

    next_index = index_by_timestamp[
        next_timestamp
    ]

    next_type = next_event[
        "auction_event_type"
    ]

    current_type = current[
        "auction_event_type"
    ]

    return {
        "next_event_type": next_type,
        "bars_to_next_event": float(
            next_index - current_index
        ),
        "next_event_same_type": bool(
            next_type == current_type
        ),
        "next_event_different_type": bool(
            next_type != current_type
        ),
    }


def analyze_reaction_length(
    price: pd.DataFrame,
    event_index: int,
    direction: str,
) -> dict:
    event_bar = price.iloc[
        event_index
    ]

    anchor_close = float(
        event_bar["close"]
    )

    event_range_bps = (
        (
            float(event_bar["high"])
            - float(event_bar["low"])
        )
        / anchor_close
        * 10000.0
    )

    activation_threshold_bps = (
        event_range_bps
    )

    activated = False
    activation_bar = np.nan

    running_peak_bps = 0.0
    running_peak_bar = np.nan

    max_adverse_before_peak = 0.0

    end_bar = np.nan
    end_timestamp = pd.NaT

    last_position = (
        len(price) - 1
    )

    for position in range(
        event_index + 1,
        last_position + 1,
    ):
        relative_bar = (
            position - event_index
        )

        candle = price.iloc[
            position
        ]

        favorable = (
            favorable_excursion_bps(
                float(candle["high"]),
                float(candle["low"]),
                anchor_close,
                direction,
            )
        )

        adverse = (
            adverse_excursion_bps(
                float(candle["high"]),
                float(candle["low"]),
                anchor_close,
                direction,
            )
        )

        if favorable > running_peak_bps:
            running_peak_bps = (
                favorable
            )

            running_peak_bar = float(
                relative_bar
            )

            max_adverse_before_peak = (
                adverse
            )

        elif (
            pd.notna(
                running_peak_bar
            )
            and relative_bar
            <= running_peak_bar
        ):
            max_adverse_before_peak = max(
                max_adverse_before_peak,
                adverse,
            )

        if (
            not activated
            and running_peak_bps
            >= activation_threshold_bps
        ):
            activated = True

            activation_bar = float(
                relative_bar
            )

        if not activated:
            continue

        close_reaction = (
            expected_close_reaction_bps(
                float(candle["close"]),
                anchor_close,
                direction,
            )
        )

        retracement_level = (
            running_peak_bps
            * 0.50
        )

        if (
            pd.notna(
                running_peak_bar
            )
            and relative_bar
            > running_peak_bar
            and close_reaction
            <= retracement_level
        ):
            end_bar = float(
                relative_bar
            )

            end_timestamp = candle[
                "timestamp"
            ]

            break

    if not activated:
        return {
            "reaction_activated": False,
            "activation_threshold_bps": float(
                activation_threshold_bps
            ),
            "activation_bar": np.nan,
            "activation_minutes": np.nan,
            "peak_favorable_bps": float(
                running_peak_bps
            ),
            "bars_to_peak": running_peak_bar,
            "minutes_to_peak": np.nan,
            "max_adverse_before_peak_bps": float(
                max_adverse_before_peak
            ),
            "reaction_end_observed": False,
            "reaction_end_bar": np.nan,
            "reaction_duration_minutes": np.nan,
            "reaction_end_timestamp": pd.NaT,
            "right_censored": True,
        }

    timeframe_minutes = int(
        event_bar[
            "timeframe_minutes"
        ]
    )

    return {
        "reaction_activated": True,
        "activation_threshold_bps": float(
            activation_threshold_bps
        ),
        "activation_bar": float(
            activation_bar
        ),
        "activation_minutes": float(
            activation_bar
            * timeframe_minutes
        ),
        "peak_favorable_bps": float(
            running_peak_bps
        ),
        "bars_to_peak": float(
            running_peak_bar
        ),
        "minutes_to_peak": float(
            running_peak_bar
            * timeframe_minutes
        ),
        "max_adverse_before_peak_bps": float(
            max_adverse_before_peak
        ),
        "reaction_end_observed": bool(
            pd.notna(end_bar)
        ),
        "reaction_end_bar": end_bar,
        "reaction_duration_minutes": (
            float(
                end_bar
                * timeframe_minutes
            )
            if pd.notna(end_bar)
            else np.nan
        ),
        "reaction_end_timestamp": (
            end_timestamp
        ),
        "right_censored": bool(
            pd.isna(end_bar)
        ),
    }


def analyze_timeframe(
    timeframe: str,
    events: pd.DataFrame,
) -> list[dict]:
    price = load_price(
        timeframe
    )

    price[
        "timeframe_minutes"
    ] = TIMEFRAME_MINUTES[
        timeframe
    ]

    tf_events = (
        events[
            events["timeframe"]
            .eq(timeframe)
        ]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    index_by_timestamp = {
        timestamp: position
        for position, timestamp
        in enumerate(
            price["timestamp"]
        )
    }

    rows = []

    for event_number, event in (
        tf_events.iterrows()
    ):
        timestamp = event[
            "timestamp"
        ]

        if (
            timestamp
            not in index_by_timestamp
        ):
            continue

        event_index = (
            index_by_timestamp[
                timestamp
            ]
        )

        event_type = event[
            "auction_event_type"
        ]

        direction = (
            EXPECTED_DIRECTION[
                event_type
            ]
        )

        event_bar = price.iloc[
            event_index
        ]

        anchor_close = float(
            event_bar["close"]
        )

        row = {
            "timeframe": timeframe,
            "timestamp": timestamp,
            "event_type": event_type,
            "expected_direction": direction,
            "anchor_close": anchor_close,
            "location_bias": event.get(
                "location_bias"
            ),
            "volume_class": event.get(
                "volume_class"
            ),
            "coarse_volume_gate_match": (
                event.get(
                    "coarse_volume_gate_match"
                )
            ),
        }

        next_features = (
            find_next_event_features(
                tf_events=tf_events,
                event_number=event_number,
                current_index=event_index,
                index_by_timestamp=index_by_timestamp,
            )
        )

        row.update(
            next_features
        )

        for offset in PATH_OFFSETS:
            target_index = (
                event_index + offset
            )

            if (
                target_index
                >= len(price)
            ):
                row[
                    f"close_return_bar_{offset}_bps"
                ] = np.nan

                row[
                    f"expected_reaction_bar_{offset}_bps"
                ] = np.nan

                row[
                    f"mfe_bar_{offset}_bps"
                ] = np.nan

                row[
                    f"mae_bar_{offset}_bps"
                ] = np.nan

                continue

            future = price.iloc[
                event_index + 1:
                target_index + 1
            ]

            target_close = float(
                price.iloc[
                    target_index
                ]["close"]
            )

            row[
                f"close_return_bar_{offset}_bps"
            ] = raw_return_bps(
                target_close,
                anchor_close,
            )

            row[
                f"expected_reaction_bar_{offset}_bps"
            ] = (
                expected_close_reaction_bps(
                    target_close,
                    anchor_close,
                    direction,
                )
            )

            row[
                f"mfe_bar_{offset}_bps"
            ] = (
                favorable_excursion_bps(
                    float(
                        future[
                            "high"
                        ].max()
                    ),
                    float(
                        future[
                            "low"
                        ].min()
                    ),
                    anchor_close,
                    direction,
                )
            )

            row[
                f"mae_bar_{offset}_bps"
            ] = (
                adverse_excursion_bps(
                    float(
                        future[
                            "high"
                        ].max()
                    ),
                    float(
                        future[
                            "low"
                        ].min()
                    ),
                    anchor_close,
                    direction,
                )
            )

        length = (
            analyze_reaction_length(
                price=price,
                event_index=event_index,
                direction=direction,
            )
        )

        row.update(
            length
        )

        rows.append(row)

    return rows


def summarize_paths(
    reactions: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for (
        timeframe,
        event_type,
    ), group in reactions.groupby(
        [
            "timeframe",
            "event_type",
        ]
    ):
        total_events = len(
            group
        )

        for offset in PATH_OFFSETS:
            reaction_column = (
                f"expected_reaction_bar_{offset}_bps"
            )

            valid = group[
                group[
                    reaction_column
                ].notna()
            ].copy()

            if valid.empty:
                continue

            reaction = valid[
                reaction_column
            ].astype(float)

            rows.append(
                {
                    "timeframe": timeframe,
                    "event_type": event_type,
                    "bar_offset": offset,
                    "elapsed_minutes": (
                        offset
                        * TIMEFRAME_MINUTES[
                            timeframe
                        ]
                    ),
                    "total_events": int(
                        total_events
                    ),
                    "available_cases": int(
                        len(valid)
                    ),
                    "coverage_pct": float(
                        len(valid)
                        / total_events
                        * 100.0
                    ),
                    "median_expected_reaction_bps": float(
                        reaction.median()
                    ),
                    "mean_expected_reaction_bps": float(
                        reaction.mean()
                    ),
                    "pct_expected_direction": float(
                        (
                            reaction > 0
                        ).mean()
                        * 100.0
                    ),
                    "median_mfe_bps": float(
                        valid[
                            f"mfe_bar_{offset}_bps"
                        ].median()
                    ),
                    "median_mae_bps": float(
                        valid[
                            f"mae_bar_{offset}_bps"
                        ].median()
                    ),
                }
            )

    return pd.DataFrame(
        rows
    )


def summarize_length(
    reactions: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for (
        timeframe,
        event_type,
    ), group in reactions.groupby(
        [
            "timeframe",
            "event_type",
        ]
    ):
        activated = group[
            group[
                "reaction_activated"
            ].astype(bool)
        ].copy()

        observed = activated[
            activated[
                "reaction_end_observed"
            ].astype(bool)
        ].copy()

        rows.append(
            {
                "timeframe": timeframe,
                "event_type": event_type,
                "cases": int(
                    len(group)
                ),
                "reaction_activated_pct": float(
                    len(activated)
                    / len(group)
                    * 100.0
                ),
                "median_activation_threshold_bps": float(
                    group[
                        "activation_threshold_bps"
                    ].median()
                ),
                "median_activation_bars": (
                    float(
                        activated[
                            "activation_bar"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_activation_minutes": (
                    float(
                        activated[
                            "activation_minutes"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_peak_favorable_bps": (
                    float(
                        activated[
                            "peak_favorable_bps"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_bars_to_peak": (
                    float(
                        activated[
                            "bars_to_peak"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_minutes_to_peak": (
                    float(
                        activated[
                            "minutes_to_peak"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_adverse_before_peak_bps": (
                    float(
                        activated[
                            "max_adverse_before_peak_bps"
                        ].median()
                    )
                    if len(activated)
                    else np.nan
                ),
                "reaction_end_observed_pct_of_activated": (
                    float(
                        len(observed)
                        / len(activated)
                        * 100.0
                    )
                    if len(activated)
                    else np.nan
                ),
                "median_duration_bars_50pct_retrace": (
                    float(
                        observed[
                            "reaction_end_bar"
                        ].median()
                    )
                    if len(observed)
                    else np.nan
                ),
                "median_duration_minutes_50pct_retrace": (
                    float(
                        observed[
                            "reaction_duration_minutes"
                        ].median()
                    )
                    if len(observed)
                    else np.nan
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    events = load_events()

    rows = []

    for timeframe in (
        TIMEFRAME_MINUTES
    ):
        rows.extend(
            analyze_timeframe(
                timeframe=timeframe,
                events=events,
            )
        )

    reactions = pd.DataFrame(
        rows
    )

    reactions.to_parquet(
        EVENT_LEVEL_PATH,
        index=False,
    )

    coverage = (
        reactions
        .groupby(
            [
                "timeframe",
                "event_type",
            ]
        )
        .size()
        .reset_index(
            name="analyzed_events"
        )
    )

    source_counts = (
        events
        .groupby(
            [
                "timeframe",
                "auction_event_type",
            ]
        )
        .size()
        .reset_index(
            name="source_events"
        )
        .rename(
            columns={
                "auction_event_type": (
                    "event_type"
                )
            }
        )
    )

    coverage = (
        source_counts
        .merge(
            coverage,
            on=[
                "timeframe",
                "event_type",
            ],
            how="left",
        )
    )

    coverage[
        "analyzed_events"
    ] = (
        coverage[
            "analyzed_events"
        ]
        .fillna(0)
        .astype(int)
    )

    coverage[
        "coverage_pct"
    ] = (
        coverage[
            "analyzed_events"
        ]
        / coverage[
            "source_events"
        ]
        * 100.0
    )

    coverage.to_csv(
        COVERAGE_PATH,
        index=False,
    )

    path_summary = (
        summarize_paths(
            reactions
        )
    )

    length_summary = (
        summarize_length(
            reactions
        )
    )

    path_summary.to_csv(
        PATH_SUMMARY_PATH,
        index=False,
    )

    length_summary.to_csv(
        LENGTH_SUMMARY_PATH,
        index=False,
    )

    print(
        "SOURCE_EVENT_ROWS",
        len(events),
    )

    print(
        "ANALYZED_EVENT_ROWS",
        len(reactions),
    )

    print()
    print("EVENT_COVERAGE")

    print(
        coverage.to_string(
            index=False
        )
    )

    print()
    print("FIXED_REACTION_PATH")

    print(
        path_summary[
            [
                "timeframe",
                "event_type",
                "bar_offset",
                "elapsed_minutes",
                "total_events",
                "available_cases",
                "coverage_pct",
                "median_expected_reaction_bps",
                "pct_expected_direction",
                "median_mfe_bps",
                "median_mae_bps",
            ]
        ].to_string(
            index=False
        )
    )

    print()
    print("REACTION_LENGTH")

    print(
        length_summary.to_string(
            index=False
        )
    )

    print()
    print(
        "EVENT_LEVEL",
        EVENT_LEVEL_PATH,
    )

    print(
        "PATH_SUMMARY",
        PATH_SUMMARY_PATH,
    )

    print(
        "LENGTH_SUMMARY",
        LENGTH_SUMMARY_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
