import pandas as pd
import numpy as np

print("\nCLUSTER EVOLUTION ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

clusters = pd.read_parquet(
    "liquidity_clusters_memory.parquet"
)

tests = pd.read_parquet(
    "test_recognition_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

evolution_rows = []

# =====================================
# LOOP CLUSTERS
# =====================================

for _, cluster in clusters.iterrows():

    cluster_low = cluster["zone_low"]

    cluster_high = cluster["zone_high"]

    cluster_id = cluster["cluster_id"]

    touches = cluster["touches"]

    total_volume = cluster["total_volume"]

    dominant_behavior = cluster[
        "dominant_behavior"
    ]

    # =====================================
    # FIND RELATED TESTS
    # =====================================

    related_tests = tests[

        (
            tests["tested_zone_low"]
            >= cluster_low
        )

        &

        (
            tests["tested_zone_high"]
            <= cluster_high
        )

    ]

    successful = len(

        related_tests[
            related_tests[
                "successful_test"
            ] == True
        ]

    )

    failed = len(

        related_tests[
            related_tests[
                "failed_test"
            ] == True
        ]

    )

    total_tests = len(
        related_tests
    )

    # =====================================
    # SCORES
    # =====================================

    defense_ratio = 0

    if total_tests > 0:

        defense_ratio = (
            successful
            /
            total_tests
        )

    failure_ratio = 0

    if total_tests > 0:

        failure_ratio = (
            failed
            /
            total_tests
        )

    # =====================================
    # EVOLUTION STATE
    # =====================================

    evolution_state = "neutral"

    # strengthening

    if (

        defense_ratio > 0.7

        and

        touches >= 5

    ):

        evolution_state = (
            "strengthening"
        )

    # weakening

    elif (

        failure_ratio > 0.5

        and

        total_tests >= 3

    ):

        evolution_state = (
            "weakening"
        )

    # unstable

    elif (

        total_tests >= 5

        and

        abs(
            defense_ratio
            -
            failure_ratio
        ) < 0.2

    ):

        evolution_state = (
            "unstable"
        )

    # =====================================
    # PRESSURE SCORE
    # =====================================

    pressure_score = (

        touches
        *
        failure_ratio

    )

    # =====================================
    # SAVE
    # =====================================

    evolution_rows.append({

        "cluster_id": cluster_id,

        "zone_low": cluster_low,

        "zone_high": cluster_high,

        "touches": touches,

        "total_volume": total_volume,

        "dominant_behavior":
            dominant_behavior,

        "successful_tests":
            successful,

        "failed_tests":
            failed,

        "defense_ratio":
            defense_ratio,

        "failure_ratio":
            failure_ratio,

        "pressure_score":
            pressure_score,

        "evolution_state":
            evolution_state

    })

# =====================================
# BUILD DF
# =====================================

evolution_df = pd.DataFrame(
    evolution_rows
)

# =====================================
# SAVE
# =====================================

evolution_df.to_parquet(
    "cluster_evolution_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("CLUSTER EVOLUTION DEBUG")

print("=" * 50)

print()

print(
    evolution_df[
        [

            "cluster_id",

            "touches",

            "successful_tests",

            "failed_tests",

            "pressure_score",

            "evolution_state"

        ]

    ]
    .tail(40)

)

print()

print("STATE DISTRIBUTION:")

print(
    evolution_df[
        "evolution_state"
    ].value_counts()
)

print()

print("MEMORY SAVED:")

print(
    "cluster_evolution_memory.parquet"
)

print()
