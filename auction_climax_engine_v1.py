import pandas as pd
import numpy as np

from state_manager_v1 import STATE

def process_auction_climax(
    dataset,
    timeframe
):

    dataset = dataset.copy()

    dataset["auction_event_type"] = "NORMAL"

    dataset[
        "location_bias"
    ] = "NEUTRAL"

    # =====================================
    # FUTURE RETURNS
    # =====================================

    dataset[
        "future_return_3"
    ] = (

        dataset["close"]
        .shift(-3)

        / dataset["close"]

        - 1

    )

    # =====================================
    # ROLLING PERCENTILES
    # =====================================

    dataset[
        "volume_percentile_50"
    ] = (

        dataset[
            "volume"
        ]

        .rolling(50)

        .rank(pct=True)

    )

    dataset[
        "spread_percentile_50"
    ] = (

        dataset[
            "spread"
    ]

        .rolling(50)

        .rank(pct=True)

    )

    # =====================================
    # DIRECTIONALY EFFICIENCY
    # =====================================

    dataset[
        "directional_efficiency"
    ] = (
        dataset["spread"] /
        dataset["volume"]
    )

    dataset[
        "efficiency_mean_20"
    ] = (
        dataset[
            "directional_efficiency"
        ]
        .rolling(20)
        .mean()
    )

    dataset[
        "efficiency_decay"
    ] = (
        dataset[
            "directional_efficiency"
        ] /
        dataset[
            "efficiency_mean_20"
        ]
    )

    dataset[
        "close_position_ratio"
    ] = (

        (
            dataset["close"]
            - dataset["low"]
        )

        /

        (
            dataset["high"]
            - dataset["low"]
        )

    )

    # =====================================
    # WICK RATIOS
    # =====================================

    dataset[
        "lower_wick_ratio"
    ] = (
        dataset[
            "lower_wick"
        ]
        /
        dataset[
            "spread"
        ]
    )

    dataset[
        "upper_wick_ratio"
    ] = (
        dataset[
            "upper_wick"
        ]
        /
        dataset[
            "spread"
        ]
    )

    # =====================================
    # ROLLING AUCTION RANGE
    # =====================================

    dataset[
        "rolling_high_50"
    ] = (

        dataset[
            "high"
        ]
        .rolling(50)
        .max()

    )

    dataset[
        "rolling_low_50"
    ] = (

        dataset[
            "low"
        ]
        .rolling(50)
        .min()

    )

    # =====================================
    # RANGE POSITION
    # =====================================

    dataset[
        "range_position"
    ] = (

        (

            dataset[
                "close"
            ]

            -

            dataset[
                "rolling_low_50"
            ]

        )

        /

        (

            dataset[
                "rolling_high_50"
            ]

            -

            dataset[
                "rolling_low_50"
            ]

        )

    )

    # =====================================
    # EVENT TYPE
    # =====================================

    dataset[
        "auction_event_type"
    ] = "NORMAL"

    # =====================================
    # EVENT STRENGTH
    # =====================================

    dataset[
        "event_strength"
    ] = (

        dataset[
            "volume_percentile_50"
        ]

        +

        dataset[
            "spread_percentile_50"
        ]

    ) / 2

    # =====================================
    # BUYING CLIMAX
    # =====================================

    buying_climax_condition = (

        (
            dataset[
                "volume_percentile_50"
            ] >= 0.90
        )

        &

        (
            dataset[
                "delta"
            ] > 0
        )

        &

        (
            dataset[
                "spread_percentile_50"
            ] >= 0.60
        )

        &

        (

            (
                dataset[
                    "efficiency_decay"
                ] < 0.80
            )

            |

            (
                dataset[
                    "efficiency_decay"
                ] > 1.20
            )

        )

        &

        (
            dataset[
                "range_position"
            ] > 0.80
        )

    )

    dataset.loc[

        buying_climax_condition,

        "auction_event_type"

    ] = "BUYING_CLIMAX"

    dataset.loc[

        buying_climax_condition,

        "location_bias"

    ] = "UPPER_DISTRIBUTION"

    # =====================================
    # HIGH AVERAGE VOLUME
    # =====================================

    high_average_volume_condition = (

        (
            dataset[
                "volume_percentile_50"
            ] >= 0.70
        )

        &

        (
            dataset[
                "spread_percentile_50"
            ] >= 0.30
        )

        &

        (
            dataset[
                "spread_percentile_50"
            ] < 0.50
        )

        &

        (
            dataset[
                "efficiency_decay"
            ] >= 0.90
        )

        &

        (
            dataset[
                "range_position"
            ] > 0.35
        )

        &

        (
            dataset[
                "range_position"
            ] < 0.65
        )

        &

        (
            dataset[
                "auction_event_type"
            ] == "NORMAL"
        )

    )

    dataset.loc[

        high_average_volume_condition,

        "auction_event_type"

    ] = "HIGH_AVERAGE_VOLUME"

    dataset.loc[

        high_average_volume_condition,

        "location_bias"

    ] = "MID_AUCTION_TRANSFER"

    # =====================================
    # SELLING CLIMAX
    # =====================================

    selling_climax_condition = (

        (
            dataset[
                "volume_percentile_50"
            ] >= 0.80
        )

        &

        (

            dataset[
                "delta"
            ]

            <

            dataset[
                "delta"
            ].rolling(20).quantile(0.35)

        )

        &

        (
            dataset[
                "spread_percentile_50"
            ] >= 0.45
        )

        &

        (

            (
                dataset[
                    "efficiency_decay"
                ] < 0.80
            )

            |

            (

                dataset[
                    "efficiency_decay"
                ] > 1.20

            )

        )

        &

        (
            dataset[
                "range_position"
            ] < 0.45
        )

    )

    dataset.loc[

        selling_climax_condition,

        "auction_event_type"

    ] = "SELLING_CLIMAX"

    dataset.loc[

        selling_climax_condition,

        "location_bias"

    ] = "LOWER_CAPITULATION"

    # =====================================
    # STOPPING VOLUME
    # =====================================

    stopping_volume_condition = (

        (
            dataset[
                "volume_percentile_50"
            ] >= 0.85
        )

        &

        (
            dataset[
                "spread_percentile_50"
            ] >= 0.45
        )

        &

        (
            dataset[
                "delta"
            ] < 0
        )

        &

        (
            dataset[
                "range_position"
            ] < 0.40
        )

        &

        (
            dataset[
                "lower_wick_ratio"
            ] > 0.10
        )

        &

        (
            dataset[
                "future_return_3"
            ] > 0
        )

        &

        (
            dataset[
                "efficiency_decay"
            ] < 1.20
        )

    )

    dataset.loc[

        stopping_volume_condition,

        "auction_event_type"

    ] = "STOPPING_VOLUME"

    dataset.loc[

        stopping_volume_condition,

        "location_bias"

    ] = "LOWER_ABSORPTION"

    # =====================================
    # OUTPUT
    # =====================================

    climax_events = dataset[

        dataset[
            "auction_event_type"
        ] != "NORMAL"

    ][[

        "timestamp",
        "auction_event_type",
        "volume_percentile_50",
        "spread_percentile_50",
        "delta",
        "spread",
        "future_return_3",
        "event_strength"

    ]]

    print()

    print(
        "DIRECTIONAL EFFICIENCY COMPLETE"
    )

    dataset[
        "directional_efficiency"
    ] = (
        dataset["spread"] /
        dataset["volume"]
    )

    dataset[
        "efficiency_mean_20"
    ] = (
        dataset[
            "directional_efficiency"
        ]
        .rolling(20)
        .mean()
    )

    dataset[
        "efficiency_decay"
    ] = (
        dataset[
            "directional_efficiency"
        ] /
        dataset[
            "efficiency_mean_20"
        ]
    )

    print(
        dataset[
        [
                "spread",
                "volume",
                "directional_efficiency",
                "efficiency_decay"
            ]
        ].tail(10)
    )

    print(
        "CLIMAX EVENTS DETECTED"
    )

    print()

    print(
        climax_events.tail(20)
    )

    print()

    print(
        "TOTAL EVENTS:"
    )

    print(
        len(
            climax_events
        )
    )

    print()

    # =====================================
    # INTERNAL VOLUME DISTRIBUTION
    # =====================================

    internal_distribution_rows = []

    climax_events = dataset[

        dataset[
            "auction_event_type"
        ] != "NORMAL"

    ]

    for _, row in climax_events.iterrows():

        # =====================================
        # PRICE LEVELS
        # =====================================

        price_levels = np.linspace(

            row["low"],

            row["high"],

            20

        )

        # =====================================
        # BUYING CLIMAX
        # =====================================

        if row[
            "auction_event_type"
        ] == "BUYING_CLIMAX":

            volume_weights = np.linspace(
                0,
                4,
                20
            )

        # =====================================
        # SELLING CLIMAX
        # =====================================

        elif row[
            "auction_event_type"
        ] == "SELLING_CLIMAX":

            volume_weights = np.linspace(
                4,
                0,
                20
            )

        # =====================================
        # STOPPING VOLUME
        # =====================================

        elif row[
            "auction_event_type"
        ] == "STOPPING_VOLUME":

            center = np.linspace(
                -1,
                1,
                20
            )

            volume_weights = (
                1
                -
                np.abs(center)
            )

        # =====================================
        # HIGH AVERAGE VOLUME
        # =====================================

        else:

            volume_weights = np.ones(20)

        # =====================================
        # NORMALIZE
        # =====================================

        volume_weights = (

            volume_weights
            /
            volume_weights.sum()

        )

        estimated_volume = (

            volume_weights
            *
            row["volume"]

        )

        # =====================================
        # SAVE DISTRIBUTION
        # =====================================

        for level, volume in zip(

            price_levels,

            estimated_volume

        ):

            internal_distribution_rows.append({

                "timestamp":
                    row["timestamp"],

                "auction_event_type":
                    row[
                        "auction_event_type"
                    ],

                "price_level":
                    level,

                "estimated_volume":
                    volume

            })

    return {

        "auction_states":
            dataset[
                dataset[
                    "auction_event_type"
                ] != "NORMAL"
            ],

        "execution_distribution":
            pd.DataFrame(
                internal_distribution_rows
            )

    }

# =====================================
# START
# =====================================

def run():
    # For standalone runs: use preloaded candle structure from STATE.
    # This avoids relying on a placeholder file name.
    dataset = STATE["candle_structure"].copy()

    result = process_auction_climax(
        dataset=dataset,
        timeframe="M15"
    )

    print()

    print(
        result[
            "auction_states"
        ].tail()
    )

    print()

    print(
        result[
            "execution_distribution"
        ].head(20)
    )

if __name__ == "__main__":

    run()
