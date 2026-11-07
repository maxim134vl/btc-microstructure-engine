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
    / "data/research/binance_native_first_reaction_v3"
)

EVENT_LEVEL_PATH = (
    OUTPUT_DIR
    / "first_reaction_event_level.parquet"
)

SUMMARY_PATH = (
    OUTPUT_DIR
    / "first_reaction_summary.csv"
)

DIRECTION_PATH = (
    OUTPUT_DIR
    / "first_reaction_direction_summary.csv"
)


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

BASELINE_WINDOW = 20
INITIATION_BARS = 4
THRESHOLD_MULTIPLIER = 1.0
RETRACE_FRACTION = 0.50


def load_events() -> pd.DataFrame:
    events = pd.read_parquet(
        EVENTS_PATH
    ).copy()

    events["timestamp"] = pd.to_datetime(
        events["timestamp"],
        utc=True,
        errors="coerce",
    )

    return (
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

    return (
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


def upward_excursion_bps(
    high_price: float,
    anchor: float,
) -> float:
    return max(
        0.0,
        (
            high_price
            / anchor
            - 1.0
        )
        * 10000.0,
    )


def downward_excursion_bps(
    low_price: float,
    anchor: float,
) -> float:
    return max(
        0.0,
        (
            anchor
            / low_price
            - 1.0
        )
        * 10000.0,
    )


def directional_close_bps(
    close_price: float,
    anchor: float,
    direction: str,
) -> float:
    raw = (
        close_price
        / anchor
        - 1.0
    ) * 10000.0

    if direction == "UP":
        return raw

    return -raw


def favorable_excursion_bps(
    candle: pd.Series,
    anchor: float,
    direction: str,
) -> float:
    if direction == "UP":
        return upward_excursion_bps(
            float(candle["high"]),
            anchor,
        )

    return downward_excursion_bps(
        float(candle["low"]),
        anchor,
    )


def adverse_excursion_bps(
    candle: pd.Series,
    anchor: float,
    direction: str,
) -> float:
    if direction == "UP":
        return downward_excursion_bps(
            float(candle["low"]),
            anchor,
        )

    return upward_excursion_bps(
        float(candle["high"]),
        anchor,
    )


def baseline_threshold_bps(
    price: pd.DataFrame,
    event_index: int,
) -> float:
    start = max(
        0,
        event_index - BASELINE_WINDOW,
    )

    baseline = price.iloc[
        start:event_index
    ].copy()

    if baseline.empty:
        return np.nan

    ranges = (
        (
            baseline["high"]
            - baseline["low"]
        )
        /
        baseline["close"]
        * 10000.0
    )

    value = float(
        ranges.median()
    )

    if (
        not np.isfinite(value)
        or value <= 0
    ):
        return np.nan

    return (
        value
        * THRESHOLD_MULTIPLIER
    )


def detect_first_direction(
    price: pd.DataFrame,
    event_index: int,
    anchor: float,
    threshold_bps: float,
) -> dict:
    last_index = len(price) - 1

    for relative_bar in range(
        1,
        INITIATION_BARS + 1,
    ):
        position = (
            event_index
            + relative_bar
        )

        if position > last_index:
            break

        candle = price.iloc[
            position
        ]

        up = upward_excursion_bps(
            float(candle["high"]),
            anchor,
        )

        down = downward_excursion_bps(
            float(candle["low"]),
            anchor,
        )

        up_hit = (
            up >= threshold_bps
        )

        down_hit = (
            down >= threshold_bps
        )

        if up_hit and down_hit:
            return {
                "first_reaction_status": (
                    "AMBIGUOUS"
                ),
                "first_reaction_direction": None,
                "activation_bar": float(
                    relative_bar
                ),
                "activation_up_excursion_bps": float(
                    up
                ),
                "activation_down_excursion_bps": float(
                    down
                ),
            }

        if up_hit:
            return {
                "first_reaction_status": "CLEAR",
                "first_reaction_direction": "UP",
                "activation_bar": float(
                    relative_bar
                ),
                "activation_up_excursion_bps": float(
                    up
                ),
                "activation_down_excursion_bps": float(
                    down
                ),
            }

        if down_hit:
            return {
                "first_reaction_status": "CLEAR",
                "first_reaction_direction": "DOWN",
                "activation_bar": float(
                    relative_bar
                ),
                "activation_up_excursion_bps": float(
                    up
                ),
                "activation_down_excursion_bps": float(
                    down
                ),
            }

    return {
        "first_reaction_status": (
            "NO_CLEAR_REACTION"
        ),
        "first_reaction_direction": None,
        "activation_bar": np.nan,
        "activation_up_excursion_bps": np.nan,
        "activation_down_excursion_bps": np.nan,
    }


def measure_first_swing(
    price: pd.DataFrame,
    event_index: int,
    anchor: float,
    direction: str,
    activation_bar: int,
    timeframe_minutes: int,
) -> dict:
    running_peak = 0.0
    peak_bar = np.nan
    peak_timestamp = pd.NaT

    max_adverse = 0.0

    end_bar = np.nan
    end_timestamp = pd.NaT

    last_index = len(price) - 1

    for position in range(
        event_index + 1,
        last_index + 1,
    ):
        relative_bar = (
            position
            - event_index
        )

        candle = price.iloc[
            position
        ]

        favorable = (
            favorable_excursion_bps(
                candle,
                anchor,
                direction,
            )
        )

        adverse = (
            adverse_excursion_bps(
                candle,
                anchor,
                direction,
            )
        )

        max_adverse = max(
            max_adverse,
            adverse,
        )

        if favorable > running_peak:
            running_peak = favorable

            peak_bar = float(
                relative_bar
            )

            peak_timestamp = candle[
                "timestamp"
            ]

        if (
            relative_bar
            < activation_bar
        ):
            continue

        if (
            pd.isna(peak_bar)
            or relative_bar
            <= peak_bar
        ):
            continue

        close_reaction = (
            directional_close_bps(
                float(candle["close"]),
                anchor,
                direction,
            )
        )

        retracement_level = (
            running_peak
            * (
                1.0
                - RETRACE_FRACTION
            )
        )

        if (
            close_reaction
            <= retracement_level
        ):
            end_bar = float(
                relative_bar
            )

            end_timestamp = candle[
                "timestamp"
            ]

            break

    observed = pd.notna(
        end_bar
    )

    return {
        "peak_excursion_bps": float(
            running_peak
        ),
        "peak_bar": peak_bar,
        "peak_minutes": (
            float(
                peak_bar
                * timeframe_minutes
            )
            if pd.notna(
                peak_bar
            )
            else np.nan
        ),
        "peak_timestamp": peak_timestamp,
        "max_adverse_excursion_bps": float(
            max_adverse
        ),
        "reaction_end_observed": bool(
            observed
        ),
        "reaction_end_bar": end_bar,
        "reaction_duration_bars": end_bar,
        "reaction_duration_minutes": (
            float(
                end_bar
                * timeframe_minutes
            )
            if observed
            else np.nan
        ),
        "reaction_end_timestamp": (
            end_timestamp
        ),
        "right_censored": bool(
            not observed
        ),
    }


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
        timestamp: position
        for position, timestamp
        in enumerate(
            price["timestamp"]
        )
    }

    minutes = (
        TIMEFRAME_MINUTES[
            timeframe
        ]
    )

    rows = []

    for _, event in (
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

        expected_direction = (
            EXPECTED_DIRECTION[
                event_type
            ]
        )

        anchor = float(
            price.iloc[
                event_index
            ]["close"]
        )

        threshold = (
            baseline_threshold_bps(
                price,
                event_index,
            )
        )

        row = {
            "timeframe": timeframe,
            "timestamp": timestamp,
            "event_type": event_type,
            "expected_direction": (
                expected_direction
            ),
            "anchor_close": anchor,
            "threshold_bps": threshold,
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

        if (
            not np.isfinite(
                threshold
            )
        ):
            row.update(
                {
                    "first_reaction_status": (
                        "NO_BASELINE"
                    ),
                    "first_reaction_direction": None,
                    "activation_bar": np.nan,
                    "activation_minutes": np.nan,
                    "direction_matches_semantics": np.nan,
                }
            )

            rows.append(row)
            continue

        detection = (
            detect_first_direction(
                price=price,
                event_index=event_index,
                anchor=anchor,
                threshold_bps=threshold,
            )
        )

        row.update(
            detection
        )

        if pd.notna(
            row.get(
                "activation_bar"
            )
        ):
            row[
                "activation_minutes"
            ] = (
                float(
                    row[
                        "activation_bar"
                    ]
                    * minutes
                )
            )
        else:
            row[
                "activation_minutes"
            ] = np.nan

        direction = row.get(
            "first_reaction_direction"
        )

        if direction is None:
            row[
                "direction_matches_semantics"
            ] = np.nan

            rows.append(row)
            continue

        row[
            "direction_matches_semantics"
        ] = bool(
            direction
            == expected_direction
        )

        swing = measure_first_swing(
            price=price,
            event_index=event_index,
            anchor=anchor,
            direction=direction,
            activation_bar=int(
                row["activation_bar"]
            ),
            timeframe_minutes=minutes,
        )

        row.update(
            swing
        )

        rows.append(row)

    return rows


def build_summary(
    result: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for (
        timeframe,
        event_type,
    ), group in result.groupby(
        [
            "timeframe",
            "event_type",
        ]
    ):
        clear = group[
            group[
                "first_reaction_status"
            ].eq("CLEAR")
        ].copy()

        ambiguous = group[
            group[
                "first_reaction_status"
            ].eq("AMBIGUOUS")
        ]

        no_clear = group[
            group[
                "first_reaction_status"
            ].eq(
                "NO_CLEAR_REACTION"
            )
        ]

        up = clear[
            clear[
                "first_reaction_direction"
            ].eq("UP")
        ]

        down = clear[
            clear[
                "first_reaction_direction"
            ].eq("DOWN")
        ]

        observed = clear[
            clear[
                "reaction_end_observed"
            ].fillna(False)
            .astype(bool)
        ]

        expected = (
            EXPECTED_DIRECTION[
                event_type
            ]
        )

        rows.append(
            {
                "timeframe": timeframe,
                "event_type": event_type,
                "expected_direction": expected,
                "cases": int(
                    len(group)
                ),
                "clear_reactions": int(
                    len(clear)
                ),
                "clear_reaction_pct": float(
                    len(clear)
                    / len(group)
                    * 100.0
                ),
                "up_pct_all": float(
                    len(up)
                    / len(group)
                    * 100.0
                ),
                "down_pct_all": float(
                    len(down)
                    / len(group)
                    * 100.0
                ),
                "ambiguous_pct_all": float(
                    len(ambiguous)
                    / len(group)
                    * 100.0
                ),
                "no_clear_pct_all": float(
                    len(no_clear)
                    / len(group)
                    * 100.0
                ),
                "expected_direction_match_pct_clear": (
                    float(
                        clear[
                            "direction_matches_semantics"
                        ]
                        .astype(bool)
                        .mean()
                        * 100.0
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_threshold_bps": float(
                    group[
                        "threshold_bps"
                    ].median()
                ),
                "median_activation_bars": (
                    float(
                        clear[
                            "activation_bar"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_activation_minutes": (
                    float(
                        clear[
                            "activation_minutes"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_peak_excursion_bps": (
                    float(
                        clear[
                            "peak_excursion_bps"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_bars_to_peak": (
                    float(
                        clear[
                            "peak_bar"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_minutes_to_peak": (
                    float(
                        clear[
                            "peak_minutes"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_adverse_excursion_bps": (
                    float(
                        clear[
                            "max_adverse_excursion_bps"
                        ].median()
                    )
                    if len(clear)
                    else np.nan
                ),
                "reaction_end_observed_pct_clear": (
                    float(
                        len(observed)
                        / len(clear)
                        * 100.0
                    )
                    if len(clear)
                    else np.nan
                ),
                "median_duration_bars": (
                    float(
                        observed[
                            "reaction_duration_bars"
                        ].median()
                    )
                    if len(observed)
                    else np.nan
                ),
                "median_duration_minutes": (
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


def build_direction_summary(
    result: pd.DataFrame,
) -> pd.DataFrame:
    clear = result[
        result[
            "first_reaction_status"
        ].eq("CLEAR")
    ].copy()

    rows = []

    for (
        timeframe,
        event_type,
        direction,
    ), group in clear.groupby(
        [
            "timeframe",
            "event_type",
            "first_reaction_direction",
        ]
    ):
        observed = group[
            group[
                "reaction_end_observed"
            ].fillna(False)
            .astype(bool)
        ]

        rows.append(
            {
                "timeframe": timeframe,
                "event_type": event_type,
                "first_reaction_direction": direction,
                "cases": int(
                    len(group)
                ),
                "matches_semantics": bool(
                    direction
                    ==
                    EXPECTED_DIRECTION[
                        event_type
                    ]
                ),
                "median_activation_bars": float(
                    group[
                        "activation_bar"
                    ].median()
                ),
                "median_activation_minutes": float(
                    group[
                        "activation_minutes"
                    ].median()
                ),
                "median_peak_excursion_bps": float(
                    group[
                        "peak_excursion_bps"
                    ].median()
                ),
                "median_bars_to_peak": float(
                    group[
                        "peak_bar"
                    ].median()
                ),
                "median_minutes_to_peak": float(
                    group[
                        "peak_minutes"
                    ].median()
                ),
                "median_adverse_excursion_bps": float(
                    group[
                        "max_adverse_excursion_bps"
                    ].median()
                ),
                "reaction_end_observed_pct": float(
                    len(observed)
                    / len(group)
                    * 100.0
                ),
                "median_duration_bars": (
                    float(
                        observed[
                            "reaction_duration_bars"
                        ].median()
                    )
                    if len(observed)
                    else np.nan
                ),
                "median_duration_minutes": (
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
                timeframe,
                events,
            )
        )

    result = pd.DataFrame(
        rows
    )

    result.to_parquet(
        EVENT_LEVEL_PATH,
        index=False,
    )

    summary = build_summary(
        result
    )

    direction_summary = (
        build_direction_summary(
            result
        )
    )

    summary.to_csv(
        SUMMARY_PATH,
        index=False,
    )

    direction_summary.to_csv(
        DIRECTION_PATH,
        index=False,
    )

    print(
        "SOURCE_EVENT_ROWS",
        len(events),
    )

    print(
        "ANALYZED_EVENT_ROWS",
        len(result),
    )

    print()
    print(
        "FIRST_REACTION_SUMMARY"
    )

    print(
        summary.to_string(
            index=False
        )
    )

    print()
    print(
        "FIRST_REACTION_DIRECTION_DETAIL"
    )

    print(
        direction_summary.to_string(
            index=False
        )
    )

    print()
    print(
        "EVENT_LEVEL",
        EVENT_LEVEL_PATH,
    )

    print(
        "SUMMARY",
        SUMMARY_PATH,
    )

    print(
        "DIRECTION_SUMMARY",
        DIRECTION_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
