from datetime import datetime
import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

print()
print(
    "AUCTION SYNTHESIS ENGINE"
)
print()

# =====================================
# LOAD
# =====================================

response = safe_read_parquet(
    "volume_response_state.parquet"
)

convergence = safe_read_parquet(
    "auction_convergence_memory.parquet"
)

htf = safe_read_parquet(
    "htf_structure_memory.parquet"
)

context = safe_read_parquet(
    "htf_ltf_context_memory.parquet"
)

# =====================================
# LATEST
# =====================================

latest_response = (
    response.iloc[-1]
)

latest_htf = (
    htf.iloc[-1]
)

latest_context = (
    context.iloc[-1]
)

# =====================================
# RESPONSE
# =====================================

effort_result_state = (
    latest_response[
        "effort_result_state"
    ]
)

unfinished_auction = (
    latest_response[
        "unfinished_auction"
    ]
)

unfinished_reason = (
    latest_response[
        "unfinished_reason"
    ]
)

localized_behavior = (
    latest_response[
        "localized_behavior"
    ]
)

# =====================================
# HTF
# =====================================

htf_direction = (
    latest_htf[
        "htf_direction"
    ]
)

htf_structure = (
    latest_htf[
        "htf_structure"
    ]
)

# =====================================
# CONTEXT
# =====================================

interaction_type = (
    latest_context[
        "interaction_type"
    ]
)

contextual_alignment = (
    latest_context[
        "contextual_alignment"
    ]
)

# =====================================
# SYNTHESIS
# =====================================

auction_state = (
    "NEUTRAL"
)

auction_interpretation = []

# -------------------------------------
# ABSORPTION AGAINST HTF
# -------------------------------------

if (

    effort_result_state == (
        "ABSORPTION_RESPONSE"
    )

    and

    htf_direction == (
        "bearish"
    )

):

    auction_state = (
        "COUNTER_TREND_ABSORPTION"
    )

    auction_interpretation.append(

        "Localized absorption "
        "is developing against "
        "the broader bearish auction."
    )

# -------------------------------------
# DISTRIBUTION INSIDE BALANCE
# -------------------------------------

if (

    localized_behavior == (
        "localized_distribution"
    )

    and

    htf_structure == (
        "balanced"
    )

):

    auction_state = (
        "BALANCED_DISTRIBUTION"
    )

    auction_interpretation.append(

        "Inventory transfer "
        "continues inside a broader "
        "balanced auction structure."
    )

# -------------------------------------
# COMPRESSION BUILDUP
# -------------------------------------

if (

    htf_structure == (
        "compression_structure"
    )

    and

    unfinished_auction == True

):

    auction_state = (
        "STRUCTURAL_COMPRESSION"
    )

    auction_interpretation.append(

        "Unresolved auction activity "
        "inside higher timeframe "
        "compression suggests "
        "potential structural expansion."
    )

# -------------------------------------
# EXPANSION INTO DISTRIBUTION
# -------------------------------------

if (

    interaction_type == (
        "expansion_into_distribution"
    )

):

    auction_state = (
        "FAILED_EXPANSION"
    )

    auction_interpretation.append(

        "Expansion activity "
        "is transitioning into "
        "localized distribution behavior."
    )

# =====================================
# OUTPUT
# =====================================

print(
    "AUCTION STATE:"
)

print(
    auction_state
)

print()

print(
    "AUCTION INTERPRETATION"
)

print()

for line in auction_interpretation:

    print(
        "-",
        line
    )

print()

# =====================================
# SAVE
# =====================================

# =====================================
# SAVE
# =====================================

from datetime import datetime

row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "auction_state":
        auction_state,

    "interpretation":
        auction_state

}])

state_payload = {

    "auction_state":
        auction_state

}

if not should_persist_state(

    "auction_synthesis_memory.parquet",

    state_payload

):

    print()

    print(
        "NO STATE CHANGE"
    )

else:

    append_state_row(

        "auction_synthesis_memory.parquet",

        row

    )

    print()

    print(
        "MEMORY SAVED:"
    )

    print(
        "auction_synthesis_memory.parquet"
    )
