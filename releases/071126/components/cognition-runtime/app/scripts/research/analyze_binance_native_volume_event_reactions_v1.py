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
    / "data/research/binance_native_volume_reactions_v1"
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

PATH_OFFSETS = [
    1,
    2,
    3,
    4,
    6,
    8,
    12,
    16,
    24,
    32,
]

TIMEFRAME_MINUTES = {
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

MAX_EPISODE_BARS = {
    "M15": 96,
    "M30": 96,
    "H1": 72,
    "H4": 42,
    "D1": 20,
}

EXPECTED_DIRECTION = {
    "BUYING_CLIMAX": "DOWN",
    "SELLING_CLIMAX": "UP",
    "STOPPING_VOLUME": "UP",
}


def signed_return_bps(
    end_price: float,
    start_price: float,
) -> float:
    return (
        end_price / start_price - 1.0
    ) * 10000.0


def expected_reaction_bps(
    raw_return_bps: float,
    direction: str,
) -> float:
    if direction == "UP":
        return raw_return_bps

    return -raw_return_bps


def favorable_excursion_bps(
    high_price: float,
    low_price: float,
    anchor_price: float,
    direction: str,
) -> float:
    if direction == "UP":
        return (
            high_price / anchor_price - 1.0
        ) * 10000.0

    return (
        anchor_price / low_price - 1.0
    ) * 10000.0


def adverse_excursion_bps(
    high_price: float,
    low_price: float,
    anchor_price: float,
    direction: str,
) -> float:
    if direction == "UP":
        return (
            anchor_price / low_price - 1.0
        ) * 10000.0

    return (
        high_price / anchor_price - 1.0
    ) * 10000.0


def load_events() -> pd.DataFrame:
    if not EVENTS_PATH.exists():
        raise RuntimeError(
            f"Missing events file: {EVENTS_PATH}"
        )

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

    if not path.exists():
        raise RuntimeError(
            f"Missing price file: {path}"
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


def analyze_timeframe(
    timeframe: str,
    events: pd.DataFrame,
) -> list[dict]:
    price = load_price(
        timeframe
    )

    tf_events = (
        events[
            events["timeframe"]
            .eq(timeframe)
        ]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    index_by_timestamp = {
        timestamp: index
        for index, timestamp
        in enumerate(
            price["timestamp"]
        )
    }

    event_positions = []

    for _, event in tf_events.iterrows():
        timestamp = event["timestamp"]

        if timestamp not in index_by_timestamp:
            continue

        event_positions.append(
            (
                event,
                index_by_timestamp[
                    timestamp
                ],
            )
        )

    rows = []

    for event_number, (
        event,
        index,
    ) in enumerate(event_positions):
        event_type = (
            event[
                "auction_event_type"
            ]
        )

        direction = (
            EXPECTED_DIRECTION[
                event_type
            ]
        )

        anchor_close = float(
            price.iloc[index]["close"]
        )

        hard_stop_index = min(
            index
            + MAX_EPISODE_BARS[
                timeframe
            ],
            len(price) - 1,
        )

        next_event_index = None

        if (
            event_number + 1
            < len(event_positions)
        ):
            next_event_index = (
                event_positions[
                    event_number + 1
                ][1]
            )

        episode_stop_index = (
            hard_stop_index
        )

        stop_reason = "MAX_WINDOW"

        if (
            next_event_index is not None
            and next_event_index
            <= hard_stop_index
        ):
            episode_stop_index = (
                next_event_index - 1
            )
            stop_reason = "NEXT_EVENT"

        if (
            episode_stop_index
            <= index
        ):
            continue

        row = {
            "timeframe": timeframe,
            "timestamp": event[
                "timestamp"
            ],
            "event_type": event_type,
            "expected_direction": direction,
            "anchor_close": anchor_close,
            "location_bias": event.get(
                "location_bias"
            ),
            "volume_class": event.get(
                "volume_class"
            ),
            "coarse_volume_gate_match": event.get(
                "coarse_volume_gate_match"
            ),
            "episode_stop_reason": (
                stop_reason
            ),
            "episode_available_bars": int(
                episode_stop_index
                - index
            ),
        }

        for offset in PATH_OFFSETS:
            target_index = (
                index + offset
            )

            if (
                target_index
                > episode_stop_index
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
                index + 1:
                target_index + 1
            ]

            target_close = float(
                price.iloc[
                    target_index
                ]["close"]
            )

            raw_return = (
                signed_return_bps(
                    target_close,
                    anchor_close,
                )
            )

            max_high = float(
                future["high"].max()
            )

            min_low = float(
                future["low"].min()
            )

            row[
                f"close_return_bar_{offset}_bps"
            ] = raw_return

            row[
                f"expected_reaction_bar_{offset}_bps"
            ] = (
                expected_reaction_bps(
                    raw_return,
                    direction,
                )
            )

            row[
                f"mfe_bar_{offset}_bps"
            ] = (
                favorable_excursion_bps(
                    max_high,
                    min_low,
                    anchor_close,
                    direction,
                )
            )

            row[
                f"mae_bar_{offset}_bps"
            ] = (
                adverse_excursion_bps(
                    max_high,
                    min_low,
                    anchor_close,
                    direction,
                )
            )

        future_episode = price.iloc[
            index + 1:
            episode_stop_index + 1
        ].copy()

        favorable_values = []

        adverse_values = []

        close_reaction_values = []

        for _, candle in (
            future_episode.iterrows()
        ):
            high_price = float(
                candle["high"]
            )

            low_price = float(
                candle["low"]
            )

            close_price = float(
                candle["close"]
            )

            favorable_values.append(
                favorable_excursion_bps(
                    high_price,
                    low_price,
                    anchor_close,
                    direction,
                )
            )

            adverse_values.append(
                adverse_excursion_bps(
                    high_price,
                    low_price,
                    anchor_close,
                    direction,
                )
            )

            raw_close = (
                signed_return_bps(
                    close_price,
                    anchor_close,
                )
            )

            close_reaction_values.append(
                expected_reaction_bps(
                    raw_close,
                    direction,
                )
            )

        favorable_array = np.asarray(
            favorable_values,
            dtype=float,
        )

        adverse_array = np.asarray(
            adverse_values,
            dtype=float,
        )

        close_reaction_array = (
            np.asarray(
                close_reaction_values,
                dtype=float,
            )
        )

        if len(favorable_array) == 0:
            continue

        peak_relative_index = int(
            np.nanargmax(
                favorable_array
            )
        )

        peak_favorable_bps = float(
            favorable_array[
                peak_relative_index
            ]
        )

        bars_to_peak = (
            peak_relative_index + 1
        )

        max_adverse_before_peak = float(
            np.nanmax(
                adverse_array[
                    : peak_relative_index + 1
                ]
            )
        )

        reaction_end_bar = np.nan

        retracement_level = (
            peak_favorable_bps
            * 0.50
        )

        if peak_favorable_bps > 0:
            for relative_index in range(
                peak_relative_index + 1,
                len(
                    close_reaction_array
                ),
            ):
                if (
                    close_reaction_array[
                        relative_index
                    ]
                    <= retracement_level
                ):
                    reaction_end_bar = float(
                        relative_index + 1
                    )
                    break

        reaction_end_censored = (
            pd.isna(
                reaction_end_bar
            )
        )

        row[
            "peak_favorable_bps"
        ] = peak_favorable_bps

        row[
            "bars_to_peak"
        ] = float(
            bars_to_peak
        )

        row[
            "minutes_to_peak"
        ] = float(
            bars_to_peak
            * TIMEFRAME_MINUTES[
                timeframe
            ]
        )

        row[
            "max_adverse_before_peak_bps"
        ] = (
            max_adverse_before_peak
        )

        row[
            "reaction_end_bar_50pct_retrace"
        ] = (
            reaction_end_bar
        )

        row[
            "reaction_duration_minutes_50pct_retrace"
        ] = (
            float(
                reaction_end_bar
                * TIMEFRAME_MINUTES[
                    timeframe
                ]
            )
            if pd.notna(
                reaction_end_bar
            )
            else np.nan
        )

        row[
            "reaction_end_censored"
        ] = (
            reaction_end_censored
        )

        row[
            "episode_stop_timestamp"
        ] = (
            price.iloc[
                episode_stop_index
            ]["timestamp"]
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
        for offset in PATH_OFFSETS:
            reaction_column = (
                f"expected_reaction_bar_{offset}_bps"
            )

            mfe_column = (
                f"mfe_bar_{offset}_bps"
            )

            mae_column = (
                f"mae_bar_{offset}_bps"
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
                    "cases": int(
                        len(valid)
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
                            mfe_column
                        ].median()
                    ),
                    "median_mae_bps": float(
                        valid[
                            mae_column
                        ].median()
                    ),
                }
            )

    return pd.DataFrame(rows)


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
        uncensored = group[
            ~group[
                "reaction_end_censored"
            ].astype(bool)
        ].copy()

        row = {
            "timeframe": timeframe,
            "event_type": event_type,
            "cases": int(
                len(group)
            ),
            "median_peak_favorable_bps": float(
                group[
                    "peak_favorable_bps"
                ].median()
            ),
            "median_bars_to_peak": float(
                group[
                    "bars_to_peak"
                ].median()
            ),
            "median_minutes_to_peak": float(
                group[
                    "minutes_to_peak"
                ].median()
            ),
            "median_adverse_before_peak_bps": float(
                group[
                    "max_adverse_before_peak_bps"
                ].median()
            ),
            "reaction_end_observed_pct": float(
                (
                    ~group[
                        "reaction_end_censored"
                    ].astype(bool)
                ).mean()
                * 100.0
            ),
            "median_duration_bars_50pct_retrace": (
                float(
                    uncensored[
                        "reaction_end_bar_50pct_retrace"
                    ].median()
                )
                if len(
                    uncensored
                )
                else np.nan
            ),
            "median_duration_minutes_50pct_retrace": (
                float(
                    uncensored[
                        "reaction_duration_minutes_50pct_retrace"
                    ].median()
                )
                if len(
                    uncensored
                )
                else np.nan
            ),
        }

        rows.append(row)

    return pd.DataFrame(rows)


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    events = load_events()

    all_rows = []

    for timeframe in (
        TIMEFRAME_MINUTES
    ):
        rows = analyze_timeframe(
            timeframe,
            events,
        )

        all_rows.extend(
            rows
        )

    reactions = pd.DataFrame(
        all_rows
    )

    reactions.to_parquet(
        EVENT_LEVEL_PATH,
        index=False,
    )

    path_summary = summarize_paths(
        reactions
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

    print("EVENT_REACTION_ROWS", len(reactions))

    print()
    print("REACTION_PATH")

    print(
        path_summary[
            path_summary[
                "bar_offset"
            ].isin(
                [
                    1,
                    2,
                    4,
                    8,
                    16,
                    32,
                ]
            )
        ][
            [
                "timeframe",
                "event_type",
                "bar_offset",
                "elapsed_minutes",
                "cases",
                "median_expected_reaction_bps",
                "pct_expected_direction",
                "median_mfe_bps",
                "median_mae_bps",
            ]
        ]
        .to_string(
            index=False
        )
    )

    print()
    print("REACTION_LENGTH")

    print(
        length_summary[
            [
                "timeframe",
                "event_type",
                "cases",
                "median_peak_favorable_bps",
                "median_bars_to_peak",
                "median_minutes_to_peak",
                "median_adverse_before_peak_bps",
                "reaction_end_observed_pct",
                "median_duration_bars_50pct_retrace",
                "median_duration_minutes_50pct_retrace",
            ]
        ]
        .to_string(
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
