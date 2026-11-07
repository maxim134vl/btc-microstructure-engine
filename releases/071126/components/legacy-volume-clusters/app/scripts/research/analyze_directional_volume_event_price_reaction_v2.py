from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

VOLUME_PATH = ROOT / "data/cognition/volume_response_state.parquet"
SYNTHESIS_PATH = ROOT / "data/cognition/runtime_cognition_memory.parquet"
PRICE_PATH = ROOT / "data/cognition/candle_structure_memory.parquet"

OUTPUT_DIR = ROOT / "data/research/directional_volume_event_price_reaction_v2"

EVENTS_PATH = OUTPUT_DIR / "directional_volume_event_reactions.parquet"
HORIZON_SUMMARY_PATH = OUTPUT_DIR / "directional_volume_event_horizon_summary.csv"
LENGTH_SUMMARY_PATH = OUTPUT_DIR / "directional_volume_event_length_summary.csv"

HORIZONS = {
    "M15": 1,
    "M30": 2,
    "H1": 4,
    "H2": 8,
    "H4": 16,
}

DIRECTIONAL_EVENTS = {
    "BUYING_CLIMAX": "DOWN",
    "SELLING_CLIMAX": "UP",
    "STOPPING_VOLUME": "UP",
}


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"Missing file: {path}")

    return pd.read_parquet(path)


def prepare_price() -> pd.DataFrame:
    price = load_frame(PRICE_PATH).copy()

    price["timestamp"] = pd.to_datetime(
        price["timestamp"],
        utc=True,
        errors="coerce",
    )

    price = (
        price.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return price


def prepare_volume() -> pd.DataFrame:
    volume = load_frame(VOLUME_PATH).copy()

    volume["timestamp"] = pd.to_datetime(
        volume["timestamp"],
        utc=True,
        errors="coerce",
    )

    explicit = pd.to_datetime(
        volume.get("source_candle_timestamp"),
        utc=True,
        errors="coerce",
    )

    legacy = volume["timestamp"].dt.floor("15min")

    volume["source_bar_timestamp"] = explicit.fillna(
        legacy
    )

    volume["identity_mode"] = np.where(
        explicit.notna(),
        "EXPLICIT_M15",
        "LEGACY_TIMESTAMP_FLOOR",
    )

    volume["volume_class"] = (
        volume["volume_class"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    if "source_timeframe" in volume.columns:
        source_tf = (
            volume["source_timeframe"]
            .fillna("")
            .astype(str)
            .str.upper()
        )

        volume = volume[
            source_tf.isin(["", "M15"])
        ].copy()

    evaluated = pd.to_datetime(
        volume.get(
            "evaluated_at",
            volume["timestamp"],
        ),
        utc=True,
        errors="coerce",
    )

    volume["_evaluated"] = evaluated

    volume = (
        volume.dropna(
            subset=["source_bar_timestamp"]
        )
        .sort_values(
            [
                "source_bar_timestamp",
                "_evaluated",
            ]
        )
        .drop_duplicates(
            subset=["source_bar_timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return volume


def prepare_synthesis() -> pd.DataFrame:
    synthesis = load_frame(
        SYNTHESIS_PATH
    ).copy()

    synthesis["timestamp"] = pd.to_datetime(
        synthesis["timestamp"],
        utc=True,
        errors="coerce",
    )

    synthesis = synthesis.dropna(
        subset=["timestamp"]
    ).copy()

    synthesis["source_bar_timestamp"] = (
        synthesis["timestamp"]
        .dt.floor("15min")
    )

    synthesis["trigger_event"] = (
        synthesis["trigger_event"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    synthesis = synthesis[
        synthesis["trigger_event"].isin(
            [
                "BUYING_CLIMAX",
                "SELLING_CLIMAX",
                "STOPPING_VOLUME",
            ]
        )
    ].copy()

    grouped_rows = []

    for timestamp, group in synthesis.groupby(
        "source_bar_timestamp"
    ):
        events = sorted(
            set(
                group["trigger_event"]
                .dropna()
                .astype(str)
            )
        )

        buying = "BUYING_CLIMAX" in events
        selling = "SELLING_CLIMAX" in events
        stopping = "STOPPING_VOLUME" in events

        if buying and selling:
            directional = "AMBIGUOUS_CLIMAX"
        elif buying:
            directional = "BUYING_CLIMAX"
        elif selling:
            directional = "SELLING_CLIMAX"
        elif stopping:
            directional = "STOPPING_VOLUME"
        else:
            directional = None

        grouped_rows.append(
            {
                "source_bar_timestamp": timestamp,
                "synthesis_events": "|".join(events),
                "directional_trigger": directional,
            }
        )

    return pd.DataFrame(grouped_rows)


def build_events(
    volume: pd.DataFrame,
    synthesis: pd.DataFrame,
) -> pd.DataFrame:
    merged = volume.merge(
        synthesis,
        on="source_bar_timestamp",
        how="left",
    )

    rows = []

    for _, row in merged.iterrows():
        volume_class = row["volume_class"]
        trigger = row.get(
            "directional_trigger"
        )

        event = None

        if volume_class == "climax":
            if trigger in {
                "BUYING_CLIMAX",
                "SELLING_CLIMAX",
            }:
                event = trigger

        elif volume_class == "stopping":
            event = "STOPPING_VOLUME"

        if event is None:
            continue

        rows.append(
            {
                "source_bar_timestamp": row[
                    "source_bar_timestamp"
                ],
                "identity_mode": row[
                    "identity_mode"
                ],
                "volume_class": volume_class,
                "directional_event": event,
                "expected_reaction": DIRECTIONAL_EVENTS[
                    event
                ],
                "raw_volume_event": row.get(
                    "volume_event"
                ),
                "climax_state": row.get(
                    "climax_state"
                ),
                "synthesis_events": row.get(
                    "synthesis_events"
                ),
            }
        )

    events = pd.DataFrame(rows)

    if events.empty:
        return events

    return (
        events.sort_values(
            "source_bar_timestamp"
        )
        .drop_duplicates(
            subset=[
                "source_bar_timestamp",
                "directional_event",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )


def reaction_bps(
    raw_return_bps: float,
    direction: str,
) -> float:
    if direction == "UP":
        return raw_return_bps

    return -raw_return_bps


def add_reactions(
    events: pd.DataFrame,
    price: pd.DataFrame,
) -> pd.DataFrame:
    if events.empty:
        return events

    price_index = {
        timestamp: index
        for index, timestamp
        in enumerate(price["timestamp"])
    }

    rows = []

    for _, event in events.iterrows():
        timestamp = event[
            "source_bar_timestamp"
        ]

        if timestamp not in price_index:
            continue

        index = price_index[timestamp]

        entry_close = float(
            price.iloc[index]["close"]
        )

        direction = event[
            "expected_reaction"
        ]

        row = event.to_dict()

        row["entry_close"] = entry_close

        for horizon_name, bars in HORIZONS.items():
            end_index = index + bars

            if end_index >= len(price):
                row[
                    f"return_{horizon_name}_bps"
                ] = np.nan

                row[
                    f"reaction_{horizon_name}_bps"
                ] = np.nan

                row[
                    f"favorable_excursion_{horizon_name}_bps"
                ] = np.nan

                row[
                    f"adverse_excursion_{horizon_name}_bps"
                ] = np.nan

                row[
                    f"reaction_correct_{horizon_name}"
                ] = np.nan

                continue

            future = price.iloc[
                index + 1:
                end_index + 1
            ]

            end_close = float(
                price.iloc[end_index]["close"]
            )

            raw_return = (
                end_close / entry_close - 1.0
            ) * 10000.0

            max_high = float(
                future["high"].max()
            )

            min_low = float(
                future["low"].min()
            )

            up_excursion = (
                max_high / entry_close - 1.0
            ) * 10000.0

            down_excursion = (
                entry_close / min_low - 1.0
            ) * 10000.0

            if direction == "UP":
                favorable = up_excursion
                adverse = down_excursion
            else:
                favorable = down_excursion
                adverse = up_excursion

            signed_reaction = reaction_bps(
                raw_return,
                direction,
            )

            row[
                f"return_{horizon_name}_bps"
            ] = raw_return

            row[
                f"reaction_{horizon_name}_bps"
            ] = signed_reaction

            row[
                f"favorable_excursion_{horizon_name}_bps"
            ] = favorable

            row[
                f"adverse_excursion_{horizon_name}_bps"
            ] = adverse

            row[
                f"reaction_correct_{horizon_name}"
            ] = signed_reaction > 0

        max_end_index = min(
            index + HORIZONS["H4"],
            len(price) - 1,
        )

        future_h4 = price.iloc[
            index + 1:
            max_end_index + 1
        ].copy()

        if len(future_h4) == HORIZONS["H4"]:
            if direction == "UP":
                extreme_relative_index = int(
                    np.argmax(
                        future_h4["high"]
                        .to_numpy(dtype=float)
                    )
                )

                extreme_price = float(
                    future_h4.iloc[
                        extreme_relative_index
                    ]["high"]
                )

                distance_bps = (
                    extreme_price
                    / entry_close
                    - 1.0
                ) * 10000.0

            else:
                extreme_relative_index = int(
                    np.argmin(
                        future_h4["low"]
                        .to_numpy(dtype=float)
                    )
                )

                extreme_price = float(
                    future_h4.iloc[
                        extreme_relative_index
                    ]["low"]
                )

                distance_bps = (
                    entry_close
                    / extreme_price
                    - 1.0
                ) * 10000.0

            bars_to_extreme = (
                extreme_relative_index + 1
            )

            row[
                "reaction_distance_h4_bps"
            ] = distance_bps

            row[
                "bars_to_reaction_extreme_h4"
            ] = bars_to_extreme

            row[
                "minutes_to_reaction_extreme_h4"
            ] = bars_to_extreme * 15

            for barrier in [
                25,
                50,
                100,
                150,
                200,
            ]:
                hit = False
                first_bar = np.nan

                for step in range(
                    1,
                    HORIZONS["H4"] + 1,
                ):
                    candle = price.iloc[
                        index + step
                    ]

                    if direction == "UP":
                        excursion = (
                            float(candle["high"])
                            / entry_close
                            - 1.0
                        ) * 10000.0
                    else:
                        excursion = (
                            entry_close
                            / float(candle["low"])
                            - 1.0
                        ) * 10000.0

                    if excursion >= barrier:
                        hit = True
                        first_bar = float(step)
                        break

                row[
                    f"hit_{barrier}bps_h4"
                ] = hit

                row[
                    f"bars_to_{barrier}bps"
                ] = first_bar

        rows.append(row)

    return pd.DataFrame(rows)


def summarize_horizons(
    reactions: pd.DataFrame,
    cohort: str,
) -> pd.DataFrame:
    rows = []

    for event_name, group in reactions.groupby(
        "directional_event"
    ):
        expected_direction = (
            group["expected_reaction"]
            .iloc[0]
        )

        for horizon_name in HORIZONS:
            reaction_col = (
                f"reaction_{horizon_name}_bps"
            )

            favorable_col = (
                f"favorable_excursion_{horizon_name}_bps"
            )

            adverse_col = (
                f"adverse_excursion_{horizon_name}_bps"
            )

            valid = group[
                group[reaction_col].notna()
            ].copy()

            if valid.empty:
                continue

            reaction = valid[
                reaction_col
            ].astype(float)

            favorable = valid[
                favorable_col
            ].astype(float)

            adverse = valid[
                adverse_col
            ].astype(float)

            rows.append(
                {
                    "cohort": cohort,
                    "event": event_name,
                    "expected_reaction": expected_direction,
                    "horizon": horizon_name,
                    "cases": int(len(valid)),
                    "median_reaction_bps": float(
                        reaction.median()
                    ),
                    "mean_reaction_bps": float(
                        reaction.mean()
                    ),
                    "p25_reaction_bps": float(
                        reaction.quantile(0.25)
                    ),
                    "p75_reaction_bps": float(
                        reaction.quantile(0.75)
                    ),
                    "median_favorable_excursion_bps": float(
                        favorable.median()
                    ),
                    "median_adverse_excursion_bps": float(
                        adverse.median()
                    ),
                    "reaction_correct_pct": float(
                        (reaction > 0).mean()
                        * 100.0
                    ),
                }
            )

    return pd.DataFrame(rows)


def summarize_length(
    reactions: pd.DataFrame,
    cohort: str,
) -> pd.DataFrame:
    rows = []

    for event_name, group in reactions.groupby(
        "directional_event"
    ):
        valid = group[
            group[
                "reaction_distance_h4_bps"
            ].notna()
        ].copy()

        if valid.empty:
            continue

        distance = valid[
            "reaction_distance_h4_bps"
        ].astype(float)

        bars = valid[
            "bars_to_reaction_extreme_h4"
        ].astype(float)

        row = {
            "cohort": cohort,
            "event": event_name,
            "expected_reaction": (
                valid[
                    "expected_reaction"
                ].iloc[0]
            ),
            "cases": int(len(valid)),
            "median_distance_bps": float(
                distance.median()
            ),
            "mean_distance_bps": float(
                distance.mean()
            ),
            "p25_distance_bps": float(
                distance.quantile(0.25)
            ),
            "p75_distance_bps": float(
                distance.quantile(0.75)
            ),
            "median_bars_to_extreme": float(
                bars.median()
            ),
            "mean_bars_to_extreme": float(
                bars.mean()
            ),
            "median_minutes_to_extreme": float(
                bars.median() * 15.0
            ),
        }

        for barrier in [
            25,
            50,
            100,
            150,
            200,
        ]:
            hit_col = (
                f"hit_{barrier}bps_h4"
            )

            row[
                f"hit_{barrier}bps_pct"
            ] = float(
                valid[
                    hit_col
                ]
                .fillna(False)
                .astype(bool)
                .mean()
                * 100.0
            )

            hit_rows = valid[
                valid[
                    hit_col
                ]
                .fillna(False)
                .astype(bool)
            ]

            bars_col = (
                f"bars_to_{barrier}bps"
            )

            if not hit_rows.empty:
                row[
                    f"median_bars_to_{barrier}bps"
                ] = float(
                    hit_rows[
                        bars_col
                    ].median()
                )
            else:
                row[
                    f"median_bars_to_{barrier}bps"
                ] = np.nan

        rows.append(row)

    return pd.DataFrame(rows)


def print_horizon_table(
    summary: pd.DataFrame,
    cohort: str,
) -> None:
    selected = summary[
        summary["cohort"] == cohort
    ].copy()

    print()
    print(cohort)
    print(
        selected[
            [
                "event",
                "expected_reaction",
                "horizon",
                "cases",
                "median_reaction_bps",
                "median_favorable_excursion_bps",
                "median_adverse_excursion_bps",
                "reaction_correct_pct",
            ]
        ]
        .to_string(index=False)
    )


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    volume = prepare_volume()
    synthesis = prepare_synthesis()
    price = prepare_price()

    events = build_events(
        volume,
        synthesis,
    )

    reactions = add_reactions(
        events,
        price,
    )

    reactions.to_parquet(
        EVENTS_PATH,
        index=False,
    )

    explicit = reactions[
        reactions[
            "identity_mode"
        ].eq("EXPLICIT_M15")
    ].copy()

    all_summary = summarize_horizons(
        reactions,
        "ALL_USABLE",
    )

    explicit_summary = summarize_horizons(
        explicit,
        "EXPLICIT_M15",
    )

    horizon_summary = pd.concat(
        [
            all_summary,
            explicit_summary,
        ],
        ignore_index=True,
    )

    all_length = summarize_length(
        reactions,
        "ALL_USABLE",
    )

    explicit_length = summarize_length(
        explicit,
        "EXPLICIT_M15",
    )

    length_summary = pd.concat(
        [
            all_length,
            explicit_length,
        ],
        ignore_index=True,
    )

    horizon_summary.to_csv(
        HORIZON_SUMMARY_PATH,
        index=False,
    )

    length_summary.to_csv(
        LENGTH_SUMMARY_PATH,
        index=False,
    )

    print("RAW_VOLUME_ROWS", len(volume))
    print("DIRECTIONAL_EVENT_ROWS", len(reactions))

    print()
    print("EVENT_COUNTS_ALL")
    print(
        reactions[
            "directional_event"
        ]
        .value_counts()
        .to_string()
    )

    print()
    print("EVENT_COUNTS_EXPLICIT_M15")
    print(
        explicit[
            "directional_event"
        ]
        .value_counts()
        .to_string()
    )

    print_horizon_table(
        horizon_summary,
        "ALL_USABLE",
    )

    print_horizon_table(
        horizon_summary,
        "EXPLICIT_M15",
    )

    print()
    print("REACTION_LENGTH_ALL")
    print(
        length_summary[
            length_summary[
                "cohort"
            ].eq("ALL_USABLE")
        ].to_string(index=False)
    )

    print()
    print("REACTION_LENGTH_EXPLICIT_M15")
    print(
        length_summary[
            length_summary[
                "cohort"
            ].eq("EXPLICIT_M15")
        ].to_string(index=False)
    )

    print()
    print("EVENTS", EVENTS_PATH)
    print(
        "HORIZON_SUMMARY",
        HORIZON_SUMMARY_PATH,
    )
    print(
        "LENGTH_SUMMARY",
        LENGTH_SUMMARY_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
