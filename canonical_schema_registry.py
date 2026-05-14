CANONICAL_SCHEMAS = {

    "auction_synthesis_memory.parquet": [

        "timestamp",

        "auction_state",

        "interpretation"

    ],

    "auction_convergence_memory.parquet": [

        "timestamp",

        "convergence_state",

        "distribution_events",

        "absorption_events",

        "unfinished_auctions"

    ],

    "auction_reinforcement_memory.parquet": [

        "timestamp",

        "belief_state",

        "belief_strength",

        "auction_state"

    ]

}
