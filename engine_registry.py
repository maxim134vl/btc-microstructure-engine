import auction_reinforcement_engine_v1

import probabilistic_auction_engine_v1

import adaptive_meta_cognition_engine_v1

import auction_convergence_engine_v1

import stage2_cognition_runtime_v1

import state_transition_engine_v1

ENGINES = {

    "auction_convergence_engine_v1.py":
        auction_convergence_engine_v1.run,

    "auction_reinforcement_engine_v1.py":
        auction_reinforcement_engine_v1.run,

    "probabilistic_auction_engine_v1.py":
        probabilistic_auction_engine_v1.run,

    "adaptive_meta_cognition_engine_v1.py":
        adaptive_meta_cognition_engine_v1.run,

    "stage2_cognition_runtime_v1.py":
        stage2_cognition_runtime_v1.run,

    "state_transition_engine_v1.py":
        state_transition_engine_v1.run,

}
