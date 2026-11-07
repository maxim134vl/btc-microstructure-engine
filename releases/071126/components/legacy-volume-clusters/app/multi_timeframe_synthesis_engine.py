import pandas as pd
import numpy as np

from multi_timeframe_dataset_builder import (
    aggregate_behavioral_timeframe
)

from auction_climax_engine_v1 import (
    process_auction_climax
)

# =====================================
# SYNTHESIS ENGINE
# =====================================

def synthesize_multi_timeframe_behavior(

    m15_states,
    m30_states,
    h1_states,
    h4_states

):

    synthesis_rows = []

    print()

    print(
        "M15 INPUT CHECK"
    )

    print()

    print(
        m15_states[
            [
                "timestamp",
                "auction_event_type"
            ]
        ]
    )


    print()

    print(
        "SYNTHESIS ROWS CHECK"
    )

    print()

    print(
        synthesis_rows
    )

    # =====================================
    # LOCAL EXHAUSTION
    # =====================================

    for _, m15_row in m15_states.iterrows():

        m15_timestamp = m15_row["timestamp"]

        m30_window = m30_states[

            (
                m30_states["timestamp"]
                >=
                m15_timestamp
                -
                pd.Timedelta(minutes=30)
            )

            &

            (
                m30_states["timestamp"]
                <=
                m15_timestamp
                +
                pd.Timedelta(minutes=30)
            )

        ]

        h1_window = h1_states[

            (
                h1_states["timestamp"]
                >=
                m15_timestamp
                -
                pd.Timedelta(hours=1)
            )

            &

            (
                h1_states["timestamp"]
                <=
                m15_timestamp
                +
                pd.Timedelta(hours=1)
            )

        ]

        # =====================================
        # TIMEFRAME ALIGNMENT
        # =====================================

        h4_window = h4_states[
            (
                h4_states["timestamp"]
                >=
                m15_timestamp
                -
                pd.Timedelta(hours=2)
            )
            &
            (
                h4_states["timestamp"]
                <=
                m15_timestamp
                +
                pd.Timedelta(hours=2)
            )
        ]

        alignment_score = 0.25

        if len(m30_window) > 0:
            alignment_score += 0.25

        if len(h1_window) > 0:
            alignment_score += 0.25

        if len(h4_window) > 0:
            alignment_score += 0.25

        if (

            len(m30_window) == 0
            and
            len(h1_window) == 0

        ):

            synthesis_rows.append({

                "timestamp":
                    m15_timestamp,

                "synthesis_state":
                    "LOCAL_EXHAUSTION",

                "trigger_event":
                    m15_row[
                        "auction_event_type"
                    ],

                "persistence":
                    "M15_ONLY",

                "persistence_score":
                    0.25,

                "structural_rank":
                    "LOW",

                "alignment_score":
                    alignment_score,

                "location_bias":
                    m15_row[
                "location_bias"
        ],

            })

        elif (

            len(m30_window) > 0
            and
            len(h1_window) == 0

        ):

            synthesis_rows.append({

                "timestamp":
                    m15_timestamp,

                "synthesis_state":
                    "INTERMEDIATE_REVERSAL",

                "trigger_event":
                    m15_row[
                        "auction_event_type"
                    ],

                "persistence":
                    "M30_CONFIRMED",

                "persistence_score":
                    0.50,

                "structural_rank":
                    "MEDIUM",

                "alignment_score":
                    alignment_score,

                "location_bias":
                    m15_row[
                "location_bias"
         ],

            })

        else:

            synthesis_rows.append({

                "timestamp":
                    m15_timestamp,

                "synthesis_state":
                    "STRUCTURAL_REVERSAL",

                "trigger_event":
                    m15_row[
                        "auction_event_type"
                    ],

                "persistence":
                    "H1_CONFIRMED",

                "persistence_score":
                    0.75,

                "structural_rank":
                    "HIGH",

                "alignment_score":
                    alignment_score,

                "location_bias":
                    m15_row[
                "location_bias"
         ],

            })

    return pd.DataFrame(
        synthesis_rows
    )

# =====================================
# START
# =====================================

def run():

    dataset = pd.read_parquet(
        "research_master_dataset.parquet"
    )

    # =====================================
    # BUILD TIMEFRAMES
    # =====================================

    m15_dataset = dataset.copy()

    m30_dataset = aggregate_behavioral_timeframe(
        dataset.copy(),
        "M30"
    )

    h1_dataset = aggregate_behavioral_timeframe(
        dataset.copy(),
        "H1"
    )

    h4_dataset = aggregate_behavioral_timeframe(
        dataset.copy(),
        "H4"
    )

    # =====================================
    # PROCESS AUCTIONS
    # =====================================

    m15_result = process_auction_climax(
        m15_dataset,
        "M15"
    )

    m30_result = process_auction_climax(
        m30_dataset,
        "M30"
    )

    h1_result = process_auction_climax(
        h1_dataset,
        "H1"
    )

    h4_result = process_auction_climax(
        h4_dataset,
        "H4"
    )

    print()

    print(
        "M15 STATES CHECK"
    )

    print()

    print(
        m15_result[
            "auction_states"
        ].head()
    )

    print()

    print(
        "H1 STATES CHECK"
    )

    print()

    print(
        h1_result[
            "auction_states"
        ].head()
    )

    # =====================================
    # SYNTHESIS
    # =====================================

    synthesis = synthesize_multi_timeframe_behavior(

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

    print()

    print(
        synthesis
    )

    print()

    print(
        "MULTI TIMEFRAME SYNTHESIS ENGINE"
    )

    print()


if __name__ == "__main__":

    run()
