import pandas as pd
import numpy as np

from multi_timeframe_dataset_builder import (
    aggregate_behavioral_timeframe
)

from auction_climax_engine_v1 import (
    process_auction_climax
)

from multi_timeframe_synthesis_engine import (
    synthesize_multi_timeframe_behavior
)

print()
print(
    "RESEARCH DATASET BUILDER"
)
print()

# =====================================
# LOAD
# =====================================

market = pd.read_parquet(
    "live_market_feed.parquet"
)

candle_structure = pd.read_parquet(
    "candle_structure_memory.parquet"
)

response = pd.read_parquet(
    "volume_response_state.parquet"
)

convergence = pd.read_parquet(
    "auction_convergence_memory.parquet"
)

synthesis = pd.read_parquet(
    "auction_synthesis_memory.parquet"
)

probabilistic = pd.read_parquet(
    "probabilistic_auction_memory.parquet"
)

reinforcement = pd.read_parquet(
    "auction_reinforcement_memory.parquet"
)

print(
    "DATASETS LOADED"
)

print()

# =====================================
# DATASET SHAPES
# =====================================

print(
    "MARKET:",
    market.shape
)

print(
    "CANDLE STRUCTURE:",
    candle_structure.shape
)

print()

print(
    candle_structure.columns
)

print()

print(
    "RESPONSE:",
    response.shape
)

print(
    "CONVERGENCE:",
    convergence.shape
)

print(
    "SYNTHESIS:",
    synthesis.shape
)

print(
    "PROBABILISTIC:",
    probabilistic.shape
)

print(
    "REINFORCEMENT:",
    reinforcement.shape
)

print()

# =====================================
# TIMESTAMP STANDARDIZATION
# =====================================

market["timestamp"] = pd.to_datetime(
    market["timestamp"]
)

candle_structure["timestamp"] = pd.to_datetime(
    candle_structure["timestamp"]
)

response["timestamp"] = pd.to_datetime(
    response["timestamp"]
)

convergence["timestamp"] = pd.to_datetime(
    convergence["timestamp"]
)

synthesis["timestamp"] = pd.to_datetime(
    synthesis["timestamp"]
)

probabilistic["timestamp"] = pd.to_datetime(
    probabilistic["timestamp"]
)

reinforcement["timestamp"] = pd.to_datetime(
    reinforcement["timestamp"]
)

print(
    "TIMESTAMPS STANDARDIZED"
)

print()

# =====================================
# SORT
# =====================================

market = market.sort_values(
    "timestamp"
)

candle_structure = candle_structure.sort_values(
    "timestamp"
)

response = response.sort_values(
    "timestamp"
)

convergence = convergence.sort_values(
    "timestamp"
)

synthesis = synthesis.sort_values(
    "timestamp"
)

probabilistic = probabilistic.sort_values(
    "timestamp"
)

reinforcement = reinforcement.sort_values(
    "timestamp"
)

print(
    "DATASETS SORTED"
)

print()

# =====================================
# BASE MERGE
# =====================================

research_dataset = pd.merge_asof(

    candle_structure,

    market,

    on="timestamp",

    direction="backward"

)

print(
    "BASE MERGE COMPLETE"
)

print()

print(
    research_dataset.shape
)

print()

print(
    research_dataset.tail(5)
)

# =====================================
# COLUMN CLEANUP
# =====================================

research_dataset = research_dataset.rename(

    columns={

        "open_x":
            "open",

        "high_x":
            "high",

        "low_x":
            "low",

        "close_x":
            "close",

        "volume_x":
            "volume",

        "open_y":
            "market_open",

        "high_y":
            "market_high",

        "low_y":
            "market_low",

        "close_y":
            "market_close",

        "volume_y":
            "market_volume"

    }

)

print(
    "COLUMN CLEANUP COMPLETE"
)

print()

print(
    research_dataset.columns
)

print()

# =====================================
# SAVE MASTER DATASET
# =====================================

research_dataset.to_parquet(

    "research_master_dataset.parquet",

    index=False

)

print(
    "MASTER DATASET SAVED"
)

print()

print(
    "research_master_dataset.parquet"
)

print()

# =====================================
# TRAIN / VALIDATION / TEST
# =====================================

train_size = int(
    len(research_dataset) * 0.7
)

validation_size = int(
    len(research_dataset) * 0.15
)

train_dataset = research_dataset.iloc[
    :train_size
]

validation_dataset = research_dataset.iloc[
    train_size:
    train_size + validation_size
]

test_dataset = research_dataset.iloc[
    train_size + validation_size:
]

print(
    "TEMPORAL SPLITS COMPLETE"
)

print()

print(
    "TRAIN:",
    train_dataset.shape
)

print(
    "VALIDATION:",
    validation_dataset.shape
)

print(
    "TEST:",
    test_dataset.shape
)

print()

# =====================================
# ROLLING PERCENTILES
# =====================================

research_dataset[
    "volume_percentile_50"
] = (

    research_dataset["volume"]

    .rolling(50)

    .rank(pct=True)

)

research_dataset[
    "spread_percentile_50"
] = (

    research_dataset["spread"]

    .rolling(50)

    .rank(pct=True)

)

print(
    "ROLLING PERCENTILES COMPLETE"
)

print()

print(

    research_dataset[[
        "volume",
        "volume_percentile_50",
        "spread",
        "spread_percentile_50"
    ]].tail(10)

)

print()

# =====================================
# FUTURE RETURNS
# =====================================

research_dataset[
    "future_return_1"
] = (

    research_dataset["close"]

    .shift(-1)

    /

    research_dataset["close"]

    - 1

)

research_dataset[
    "future_return_3"
] = (

    research_dataset["close"]

    .shift(-3)

    /

    research_dataset["close"]

    - 1

)

research_dataset[
    "future_return_5"
] = (

    research_dataset["close"]

    .shift(-5)

    /

    research_dataset["close"]

    - 1

)

print(
    "FUTURE RETURNS COMPLETE"
)

print()

print(

    research_dataset[[
        "close",
        "future_return_1",
        "future_return_3",
        "future_return_5"
    ]].tail(10)

)

print()

# =====================================
# SIGNAL TEST
# =====================================

high_volume = research_dataset[

    research_dataset[
        "volume_percentile_50"
    ] >= 0.9

]

normal_volume = research_dataset[

    research_dataset[
        "volume_percentile_50"
    ] < 0.9

]

print(
    "HIGH VOLUME SAMPLE:"
)

print(
    len(high_volume)
)

print()

print(
    "NORMAL VOLUME SAMPLE:"
)

print(
    len(normal_volume)
)

print()

print(
    "HIGH VOLUME FUTURE RETURN 3:"
)

print(

    high_volume[
        "future_return_3"
    ].mean()

)

print()

print(
    "NORMAL VOLUME FUTURE RETURN 3:"
)

print(

    normal_volume[
        "future_return_3"
    ].mean()

)

print()

# =====================================
# BOOTSTRAP VALIDATION
# =====================================

bootstrap_results = []

for i in range(1000):

    sample = high_volume[
        "future_return_3"
    ].dropna().sample(

        frac=1,

        replace=True

    )

    bootstrap_results.append(

        sample.mean()

    )

bootstrap_df = pd.DataFrame({

    "bootstrap_mean":
        bootstrap_results

})

print(
    "BOOTSTRAP COMPLETE"
)

print()

print(
    bootstrap_df.describe()
)

print()

# =====================================
# NULL HYPOTHESIS TEST
# =====================================

shuffled = research_dataset.copy()

shuffled[
    "future_return_3"
] = np.random.permutation(

    shuffled[
        "future_return_3"
    ].values

)

random_high_volume = shuffled[

    shuffled[
        "volume_percentile_50"
    ] >= 0.9

]

print(
    "NULL HYPOTHESIS TEST"
)

print()

print(
    "REAL EDGE:"
)

print(

    high_volume[
        "future_return_3"
    ].mean()

)

print()

print(
    "RANDOMIZED EDGE:"
)

print(

    random_high_volume[
        "future_return_3"
    ].mean()

)

print()

# =====================================
# CONFIDENCE INTERVALS
# =====================================

lower_bound = bootstrap_df[
    "bootstrap_mean"
].quantile(0.025)

upper_bound = bootstrap_df[
    "bootstrap_mean"
].quantile(0.975)

print(
    "95% CONFIDENCE INTERVAL"
)

print()

print(
    "LOWER:"
)

print(
    lower_bound
)

print()

print(
    "UPPER:"
)

print(
    upper_bound
)

print()

# =====================================
# CONDITIONAL SIGNAL TEST
# =====================================

bullish_high_volume = research_dataset[

    (
        research_dataset[
            "volume_percentile_50"
        ] >= 0.9
    )

    &

    (
        research_dataset[
            "delta"
        ] > 0
    )

    &

    (
        research_dataset[
            "candle_type"
        ] == "bullish"
    )

]

print(
    "BULLISH HIGH VOLUME SAMPLE:"
)

print(
    len(bullish_high_volume)
)

print()

print(
    "BULLISH HIGH VOLUME FUTURE RETURN 3:"
)

print(

    bullish_high_volume[
        "future_return_3"
    ].mean()

)

print()

# =====================================
# ABSORPTION TEST
# =====================================

absorption_sample = research_dataset[

    (
        research_dataset[
            "volume_percentile_50"
        ] >= 0.9
    )

    &

    (
        research_dataset[
            "delta"
        ] < 0
    )

    &

    (
        research_dataset[
            "candle_type"
        ] == "bullish"
    )

]

print(
    "ABSORPTION SAMPLE:"
)

print(
    len(absorption_sample)
)

print()

print(
    "ABSORPTION FUTURE RETURN 3:"
)

print(

    absorption_sample[
        "future_return_3"
    ].mean()

)

print()

# =====================================
# FUTURE VOLATILITY
# =====================================

research_dataset[
    "future_volatility_3"
] = (

    research_dataset[
        "future_return_3"
    ].abs()

)

print(
    "FUTURE VOLATILITY COMPLETE"
)

print()

print(

    research_dataset[[
        "future_return_3",
        "future_volatility_3"
    ]].tail(10)

)

print()

high_volume = research_dataset[

    research_dataset[
        "volume_percentile_50"
    ] >= 0.9

]

normal_volume = research_dataset[

    research_dataset[
        "volume_percentile_50"
    ] < 0.9

]

# =====================================
# HIGH VOLUME VOLATILITY TEST
# =====================================

print(
    "HIGH VOLUME FUTURE VOLATILITY:"
)

print(

    high_volume[
        "future_volatility_3"
    ].mean()

)

print()

print(
    "NORMAL VOLUME FUTURE VOLATILITY:"
)

print(

    normal_volume[
        "future_volatility_3"
    ].mean()

)

print()

# =====================================
# WALK FORWARD VALIDATION
# =====================================

window_size = 50

walk_forward_results = []

for start in range(

    0,

    len(research_dataset) - window_size,

    25

):

    window = research_dataset.iloc[
        start:start + window_size
    ]

    high_volume_window = window[

        window[
            "volume_percentile_50"
        ] >= 0.9

    ]

    edge = high_volume_window[
        "future_return_3"
    ].mean()

    walk_forward_results.append({

        "start_index":
            start,

        "end_index":
            start + window_size,

        "edge":
            edge,

        "samples":
            len(high_volume_window)

    })

walk_forward_df = pd.DataFrame(
    walk_forward_results
)

print(
    "WALK FORWARD VALIDATION"
)

print()

print(
    walk_forward_df
)

print()

# =====================================
# REGIME SEGMENTATION
# =====================================

research_dataset[
    "volatility_regime"
] = np.where(

    research_dataset[
        "spread_percentile_50"
    ] >= 0.7,

    "HIGH_VOL",

    "LOW_VOL"

)

print(
    "REGIME SEGMENTATION COMPLETE"
)

print()

print(

    research_dataset[[
        "spread",
        "spread_percentile_50",
        "volatility_regime"
    ]].tail(10)

)

print()

# =====================================
# REGIME EDGE TEST
# =====================================

high_vol_regime = research_dataset[

    research_dataset[
        "volatility_regime"
    ] == "HIGH_VOL"

]

low_vol_regime = research_dataset[

    research_dataset[
        "volatility_regime"
    ] == "LOW_VOL"

]

high_vol_signal = high_vol_regime[

    high_vol_regime[
        "volume_percentile_50"
    ] >= 0.9

]

low_vol_signal = low_vol_regime[

    low_vol_regime[
        "volume_percentile_50"
    ] >= 0.9

]

print(
    "HIGH VOL REGIME SAMPLE:"
)

print(
    len(high_vol_signal)
)

print()

print(
    "HIGH VOL REGIME EDGE:"
)

print(

    high_vol_signal[
        "future_return_3"
    ].mean()

)

print()

print(
    "LOW VOL REGIME SAMPLE:"
)

print(
    len(low_vol_signal)
)

print()

print(
    "LOW VOL REGIME EDGE:"
)

print(

    low_vol_signal[
        "future_return_3"
    ].mean()

)

print()

# =====================================
# MULTI FACTOR INTERACTION
# =====================================

interaction_signal = research_dataset[

    (
        research_dataset[
            "volatility_regime"
        ] == "HIGH_VOL"
    )

    &

    (
        research_dataset[
            "volume_percentile_50"
        ] >= 0.9
    )

    &

    (
        research_dataset[
            "delta"
        ] > 0
    )

    &

    (
        research_dataset[
            "candle_type"
        ] == "bullish"
    )

]

print(
    "INTERACTION SAMPLE:"
)

print(
    len(interaction_signal)
)

print()

print(
    "INTERACTION EDGE:"
)

print(

    interaction_signal[
        "future_return_3"
    ].mean()

)

print()

print(
    "INTERACTION VOLATILITY:"
)

print(

    interaction_signal[
        "future_volatility_3"
    ].mean()

)

print()

# =====================================
# SIGNAL STABILITY SCORE
# =====================================

valid_edges = walk_forward_df[
    "edge"
].dropna()

stability_score = (

    valid_edges.mean()

    /

    (
        valid_edges.std()
        + 0.000001
    )

)

print(
    "SIGNAL STABILITY SCORE"
)

print()

print(
    stability_score
)

print()

# =====================================
# INTERNAL EXECUTION MAPPING
# =====================================

internal_rows = []

for _, row in research_dataset.tail(50).iterrows():

    low_price = row["low"]
    high_price = row["high"]

    total_volume = row["volume"]

    candle_delta = row["delta"]

    spread = high_price - low_price

    if spread <= 0:

        continue

    bins = 10

    bin_size = spread / bins

    for i in range(bins):

        price_level = (
            low_price
            + (i * bin_size)
        )

        normalized_position = i / bins

        if candle_delta > 0:

            aggression_weight = (
                0.5
                + normalized_position
            )

        else:

            aggression_weight = (
                1.5
                - normalized_position
            )

        estimated_volume = (

            total_volume
            * aggression_weight
            / bins

        )

        internal_rows.append({

            "timestamp":
                row["timestamp"],

            "price_level":
                price_level,

            "estimated_volume":
                estimated_volume,

            "delta":
                candle_delta,

            "candle_type":
                row["candle_type"]

        })

internal_distribution = pd.DataFrame(
    internal_rows
)

print(
    "INTERNAL DISTRIBUTION COMPLETE"
)

print()

print(
    internal_distribution.tail(20)
)

print()

# =====================================
# ABSORPTION ZONE DETECTION
# =====================================

absorption_zones = []

for _, row in research_dataset.iterrows():

    if (

        row[
            "volume_percentile_50"
        ] >= 0.9

        and

        abs(
            row[
                "future_return_3"
            ]
        ) < 0.0005

    ):

        if row["delta"] > 0:

            absorption_type = (
                "BUYER_ABSORPTION"
            )

        else:

            absorption_type = (
                "SELLER_ABSORPTION"
            )

        absorption_zones.append({

            "timestamp":
                row["timestamp"],

            "close":
                row["close"],

            "delta":
                row["delta"],

            "volume":
                row["volume"],

            "future_return_3":
                row["future_return_3"],

            "absorption_type":
                absorption_type

        })

absorption_df = pd.DataFrame(
    absorption_zones
)

print(
    "ABSORPTION ZONES DETECTED"
)

print()

print(
    absorption_df.tail(20)
)

print()

print(
    "TOTAL ABSORPTION ZONES:"
)

print(
    len(absorption_df)
)

print()

# =====================================
# TRAPPED PARTICIPATION DETECTION
# =====================================

trapped_rows = []

for _, row in research_dataset.iterrows():

    if row[
        "volume_percentile_50"
    ] < 0.8:

        continue

    # ---------------------------------
    # TRAPPED BUYERS
    # ---------------------------------

    if (

        row["delta"] > 500

        and

        row["candle_type"] == "bullish"

        and

        row["future_return_3"] < -0.0005

    ):

        trapped_type = (
            "TRAPPED_BUYERS"
        )

    # ---------------------------------
    # TRAPPED SELLERS
    # ---------------------------------

    elif (

        row["delta"] < -500

        and

        row["candle_type"] == "bearish"

        and

        row["future_return_3"] > 0.0005

    ):

        trapped_type = (
            "TRAPPED_SELLERS"
        )

    else:

        continue

    trapped_rows.append({

        "timestamp":
            row["timestamp"],

        "close":
            row["close"],

        "delta":
            row["delta"],

        "volume":
            row["volume"],

        "future_return_3":
            row["future_return_3"],

        "trapped_type":
            trapped_type

    })

trapped_df = pd.DataFrame(
    trapped_rows
)

print(
    "TRAPPED PARTICIPATION DETECTED"
)

print()

print(
    trapped_df.tail(20)
)

print()

print(
    "TOTAL TRAPPED EVENTS:"
)

print(
    len(trapped_df)
)

print()

# =====================================
# TRAP IMBALANCE SCORE
# =====================================

trapped_buyers_count = len(

    trapped_df[

        trapped_df[
            "trapped_type"
        ] == "TRAPPED_BUYERS"

    ]

)

trapped_sellers_count = len(

    trapped_df[

        trapped_df[
            "trapped_type"
        ] == "TRAPPED_SELLERS"

    ]

)

trap_imbalance_score = (

    trapped_sellers_count
    - trapped_buyers_count

)

print(
    "TRAPPED BUYERS:"
)

print(
    trapped_buyers_count
)

print()

print(
    "TRAPPED SELLERS:"
)

print(
    trapped_sellers_count
)

print()

print(
    "TRAP IMBALANCE SCORE:"
)

print(
    trap_imbalance_score
)

print()

# =====================================
# EXECUTION CONCENTRATION ANALYSIS
# =====================================

execution_profile = (

    internal_distribution

    .groupby(
        "price_level"
    )[
        "estimated_volume"
    ]

    .sum()

    .reset_index()

)

execution_profile = (

    execution_profile

    .sort_values(

        by="estimated_volume",

        ascending=False

    )

)

print(
    "EXECUTION CONCENTRATION ANALYSIS"
)

print()

print(
    execution_profile.head(20)
)

print()

top_execution_zone = execution_profile.iloc[0]

print(
    "TOP EXECUTION ZONE"
)

print()

print(
    top_execution_zone
)

print()

# =====================================
# MULTI TIMEFRAME SYNTHESIS
# =====================================

m15_dataset = research_dataset.copy()

m30_dataset = aggregate_behavioral_timeframe(
    research_dataset.copy(),
    "M30"
)

h1_dataset = aggregate_behavioral_timeframe(
    research_dataset.copy(),
    "H1"
)

h4_dataset = aggregate_behavioral_timeframe(
    research_dataset.copy(),
    "H4"
)

d1_dataset = aggregate_behavioral_timeframe(
    research_dataset.copy(),
    "D1"
)

# =====================================
# AUCTION PROCESSING
# =====================================

m15_result = process_auction_climax(
    dataset=m15_dataset,
    timeframe="M15"
)

m30_result = process_auction_climax(
    dataset=m30_dataset,
    timeframe="M30"
)

h1_result = process_auction_climax(
    dataset=h1_dataset,
    timeframe="H1"
)

h4_result = process_auction_climax(
    dataset=h4_dataset,
    timeframe="H4"
)

d1_result = process_auction_climax(
    dataset=d1_dataset,
    timeframe="D1"
)

print()

print("D1 EVENTS")

print()

print(
    d1_result[
        "auction_states"
    ][[
        "timestamp",
        "auction_event_type",
        "event_strength"
    ]]
)

# =====================================
# SYNTHESIS ENGINE
# =====================================

synthesis_output = synthesize_multi_timeframe_behavior(

    m15_states=
        m15_result[
            "auction_states"
        ],

    m30_states=
        m30_result[
            "auction_states"
        ],

    h1_states=
        h1_result[
            "auction_states"
        ],

    h4_states=
        h4_result[
            "auction_states"
        ]

)

print(
    "MULTI TIMEFRAME SYNTHESIS COMPLETE"
)

print()

print(
    synthesis_output
)

print()

synthesis_output.to_parquet(
    "multi_timeframe_synthesis.parquet",
    index=False
)

# =====================================
# MERGE SYNTHESIS BACK INTO MASTER
# =====================================

research_dataset = research_dataset.merge(

    synthesis_output,

    on="timestamp",

    how="left"

)

print()

print(
    "SYNTHESIS MERGED INTO MASTER DATASET"
)

print()

print(
    research_dataset[[
        "timestamp",
        "synthesis_state",
        "persistence"
    ]].tail(20)
)

print()

research_dataset.to_parquet(
    "research_master_dataset.parquet",
    index=False
)

print(
    "UPDATED MASTER DATASET SAVED"
)

print()

# =====================================
# RUNTIME COGNITION EXPORT
# =====================================

runtime_cognition_memory = research_dataset[[

    "timestamp",

    "synthesis_state",

    "trigger_event",

    "persistence",

    "persistence_score",

    "structural_rank",

    "alignment_score",

    "location_bias"

]].copy()

runtime_cognition_memory = (
    
    runtime_cognition_memory
    .dropna(
        subset=[
            "synthesis_state"
        ]
    )
    .reset_index(
        drop=True
    )

)

runtime_cognition_memory.to_parquet(

    "runtime_cognition_memory.parquet",

    index=False

)

print(
    "RUNTIME COGNITION MEMORY SAVED"
)

print()

print(
    runtime_cognition_memory
)

print()

print(
    "SYNTHESIS MEMORY SAVED"
)

print()
