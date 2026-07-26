import importlib.util
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from parquet_utils import (
    safe_read_parquet,
    append_state_row
)

from state_guard import (
    should_persist_state
)

# Phase 4A/4B: default OFF so live subprocesses keep legacy v2 path until activation.
# Activation: BTC_ML_VOLUME_LOCALIZATION_LIVE=1 after localization is registered + restarted.
_VOLUME_LOCALIZATION_LIVE = os.environ.get("BTC_ML_VOLUME_LOCALIZATION_LIVE", "0").strip() == "1"
_LOCALIZATION_V1 = "volume_localization_memory.parquet"
_LOCALIZATION_V2 = "volume_localization_v2_memory.parquet"

from volume_localization_engine_v1 import (  # noqa: E402
    resolve_localization_for_structure,
)


def _load_timestamp_identity():
    path = (
        Path(__file__).resolve().parent
        / "src"
        / "btc_ml"
        / "cognition"
        / "volume_response_timestamp_identity.py"
    )
    spec = importlib.util.spec_from_file_location(
        "btc_ml_cognition_volume_response_timestamp_identity",
        path,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TS_IDENTITY = _load_timestamp_identity()
build_response_identity_fields = _TS_IDENTITY.build_response_identity_fields


print()
print(
    "VOLUME RESPONSE ENGINE"
)
print()

# =====================================
# LOAD DATA
# =====================================

classification_memory = safe_read_parquet(
    "volume_classification_memory.parquet"
)

structure = safe_read_parquet(
    "candle_structure_memory.parquet"
)

latest_structure = (
    structure.iloc[-1]
)

geometry = safe_read_parquet(
    "candle_geometry_v2_memory.parquet"
)

_localization_source = (
    _LOCALIZATION_V1 if _VOLUME_LOCALIZATION_LIVE else _LOCALIZATION_V2
)
localization = safe_read_parquet(
    _localization_source
)

reactions = safe_read_parquet(
    "volume_reactions.parquet"
)

micro = localization

# =====================================
# LATEST
# =====================================

latest_geometry = (
    geometry.iloc[-1]
)

# Phase 4B: canonical M15 bar-open identity from candle_structure (passthrough).
# Wall-clock evaluation time is separate (evaluated_at / legacy timestamp).
_response_identity = build_response_identity_fields(latest_structure)
source_candle_timestamp = _response_identity["source_candle_timestamp"]
source_candle_close = _response_identity["source_candle_close"]
evaluated_at = _response_identity["evaluated_at"]

if _VOLUME_LOCALIZATION_LIVE:
    # Exact join key: localization.timestamp == source_candle_timestamp
    _localization_join = resolve_localization_for_structure(
        localization,
        source_candle_timestamp,
        live_v1=True,
    )
    latest_localization = _localization_join["row"]
    localization_join_status = _localization_join["localization_join_status"]
    localization_source_timestamp = _localization_join["localization_source_timestamp"]
    localization_fresh = _localization_join["localization_fresh"]
else:
    # Legacy default (flag OFF): preserve prior v2 tip-carry live behavior unchanged.
    latest_localization = localization.iloc[-1] if len(localization) else None
    localization_join_status = "LEGACY_V2_TIP_CARRY"
    localization_source_timestamp = (
        latest_localization["timestamp"] if latest_localization is not None else None
    )
    localization_fresh = False

latest_reaction = (
    reactions.iloc[-1]
)

latest_classification = (
    classification_memory.iloc[-1]
)

# =====================================
# CONTEXT WINDOWS
# =====================================

recent_local_volume = (

    localization[
        "estimated_local_volume"
    ]

    .tail(50)

)

recent_spread = (

    geometry[
        "spread"
    ]

    .tail(50)

)

recent_delta_efficiency = (

    reactions[
        "delta_efficiency"
    ]

    .tail(50)

)

# =====================================
# RELATIVE CONTEXT
# =====================================

if latest_localization is None or (
    _VOLUME_LOCALIZATION_LIVE
    and localization_join_status != "EXACT_FRESH_MATCH"
):
    relative_volume = float("nan")
else:
    relative_volume = (

        latest_localization[
            "estimated_local_volume"
        ]

        /

        recent_local_volume.mean()

    )

relative_spread = (

    latest_geometry[
        "spread"
    ]

    /

    recent_spread.mean()

)

relative_efficiency = (

    abs(
        latest_reaction[
            "delta_efficiency"
        ]
    )

    /

    (
        recent_delta_efficiency
        .abs()
        .mean()
    )

)

# =====================================
# GEOMETRY
# =====================================

upper_rejection = (
    latest_geometry[
        "upper_rejection"
    ]
)

lower_rejection = (
    latest_geometry[
        "lower_rejection"
    ]
)

close_position = (
    latest_geometry[
        "close_position"
    ]
)

spread_zscore = (
    latest_geometry[
        "spread_zscore"
    ]
)

body = (
    latest_geometry[
        "body"
    ]
)

spread = (
    latest_geometry[
        "spread"
    ]
)

# =====================================
# VOLUME CLASS
# =====================================

volume_class = (
    latest_classification[
        "volume_class"
    ]
)

participation_state = (
    "NORMAL_PARTICIPATION"
)

participation_adjustment = 0

climax_state = (
    "NO_CLIMAX"
)

# =====================================
# LOCALIZED VOLUME
# Proven mapping: localization.behavior → localized_behavior (identity).
# Live-v1 missing/stale/ambiguous → null (never 0 / never "neutral").
# =====================================

if _VOLUME_LOCALIZATION_LIVE:
    if latest_localization is not None and localization_join_status == "EXACT_FRESH_MATCH":
        localized_behavior = latest_localization["behavior"]
        estimated_local_volume = latest_localization["estimated_local_volume"]
        volume_concentration = latest_localization["volume_concentration"]
    else:
        localized_behavior = None
        estimated_local_volume = None
        volume_concentration = None
else:
    localized_behavior = latest_localization["behavior"]
    estimated_local_volume = latest_localization["estimated_local_volume"]
    volume_concentration = latest_localization["volume_concentration"]

# =====================================
# REACTION
# =====================================

delta = (
    latest_structure[
        "delta"
    ]
)

if estimated_local_volume is None or (
    isinstance(estimated_local_volume, float) and pd.isna(estimated_local_volume)
):
    delta_efficiency = float("nan")
else:
    delta_efficiency = (
        delta / estimated_local_volume
    )

price_change = (
    latest_structure[
        "close"
    ] - latest_structure[
        "open"
    ]
)

# =====================================
# EFFORT VS RESULT
# =====================================

effort_score = (

    (

        relative_volume

    )

    +

    (

        abs(delta_efficiency)

    )

    +

    (

        relative_spread

    )

) / 3

effort_score += (
    participation_adjustment
)

# =====================================
# RESULT QUALITY
# =====================================

close_acceptance = (

    abs(
        close_position - 0.5
    ) * 2

)

# -------------------------------------

spread_efficiency = (

    relative_spread

    *

    close_acceptance

)

# -------------------------------------

rejection_penalty = 0

if (
    upper_rejection == True
):

    rejection_penalty += 0.4

if (
    lower_rejection == True
):

    rejection_penalty += 0.4

# -------------------------------------

result_score = (

    (
        close_acceptance
    )

    +

    (
        spread_efficiency
    )

    -

    rejection_penalty

)

# -------------------------------------

effort_result_ratio = (

    result_score

    /

    (
        effort_score + 0.001
    )

)

# -------------------------------------

normalized_result = (

    effort_result_ratio

    *

    (
        1 / (
            1 +
            rejection_penalty
        )
    )

)

# =====================================
# CLIMACTIC PARTICIPATION
# =====================================

if "climax" in volume_class:

    participation_state = (
        "CLIMACTIC_PARTICIPATION"
    )

    participation_adjustment = 0.5

    if normalized_result < 0:

        climax_state = (
            "CLIMAX_EXHAUSTION"
        )

    elif normalized_result > 0.5:

        climax_state = (
            "CLIMAX_CONTINUATION"
        )

    else:

        climax_state = (
            "CLIMAX_ABSORPTION"
        )

# =====================================
# RESPONSE ENGINE
# =====================================

volume_event = (
    "NEUTRAL_VOLUME"
)

continuation_quality = (
    "NEUTRAL"
)

# -------------------------------------
# STOPPING VOLUME
# -------------------------------------

if (

    relative_volume > 1.8

    and

    abs(delta_efficiency) < 0.3

    and

    (
        upper_rejection == True
        or
        lower_rejection == True
    )

):

    volume_event = (
        "STOPPING_VOLUME"
    )

# -------------------------------------
# ABSORPTION
# -------------------------------------

if (

    localized_behavior == (
        "localized_absorption"
    )

    and

    abs(delta_efficiency) < 0.3

):

    volume_event = (
        "ABSORPTION_VOLUME"
    )

# -------------------------------------
# CONTINUATION VOLUME
# -------------------------------------

if (

    body > (
        spread * 0.7
    )

    and

    abs(delta_efficiency) > 1.0

    and

    relative_spread > 1.5

):

    volume_event = (
        "CONTINUATION_VOLUME"
    )

# -------------------------------------
# EXHAUSTION VOLUME
# -------------------------------------

if (

    relative_volume > 2.0

    and

    abs(delta_efficiency) < 0.2

):

    volume_event = (
        "EXHAUSTION_VOLUME"
    )

# =====================================
# EFFORT RESULT INTERPRETATION
# =====================================

effort_result_state = (
    "BALANCED_RESPONSE"
)

# -------------------------------------
# ABSORPTION
# -------------------------------------

if (

    effort_score > 1.2

    and

    normalized_result < 0.6

):

    effort_result_state = (
        "ABSORPTION_RESPONSE"
    )

# -------------------------------------
# STRONG ACCEPTANCE
# -------------------------------------

elif (

    effort_score > 1.2

    and

    normalized_result > 1.0

):

    effort_result_state = (
        "EFFICIENT_CONTINUATION"
    )

# -------------------------------------
# EXHAUSTION
# -------------------------------------

elif (

    relative_volume > 2

    and

    normalized_result < 0.4

):

    effort_result_state = (
        "EXHAUSTION_RESPONSE"
    )

# =====================================
# UNFINISHED AUCTION
# =====================================

unfinished_auction = False

unfinished_reason = (
    "NONE"
)

# -------------------------------------
# HIGH EFFORT / POOR RESULT
# -------------------------------------

if (

    effort_score > 1.0

    and

    normalized_result < 0.3

):

    unfinished_auction = True

    unfinished_reason = (
        "INEFFICIENT_AUCTION"
    )

# -------------------------------------
# DISTRIBUTION WITHOUT EXPANSION
# -------------------------------------

if (

    localized_behavior == (
        "localized_distribution"
    )

    and

    relative_spread < 1.0

):

    unfinished_auction = True

    unfinished_reason = (
        "DISTRIBUTION_NOT_RESOLVED"
    )

# -------------------------------------
# REJECTION FAILURE
# -------------------------------------

if (

    (
        upper_rejection == True
        or
        lower_rejection == True
    )

    and

    abs(normalized_result) < 0.2

):

    unfinished_auction = True

    unfinished_reason = (
        "REJECTION_WITHOUT_RESOLUTION"
    )

# =====================================
# CONTINUATION QUALITY
# =====================================

if (

    volume_event == (
        "CONTINUATION_VOLUME"
    )

    and

    close_position > 0.8

):

    continuation_quality = (
        "STRONG_ACCEPTANCE"
    )

# -------------------------------------

elif (

    volume_event == (
        "CONTINUATION_VOLUME"
    )

    and

    close_position < 0.5

):

    continuation_quality = (
        "FAILED_CONTINUATION"
    )

# -------------------------------------

elif (

    volume_event == (
        "STOPPING_VOLUME"
    )

):

    continuation_quality = (
        "AUCTION_STALLED"
    )

# -------------------------------------

elif (

    volume_event == (
        "ABSORPTION_VOLUME"
    )

):

    continuation_quality = (
        "PASSIVE_DEFENSE"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "VOLUME EVENT:"
)

print(
    volume_event
)

print()

print(
    "CONTINUATION QUALITY:"
)

print(
    continuation_quality
)

print()

print(
    "VOLUME CLASS:"
)

print(
    volume_class
)

print()

print(
    "PARTICIPATION STATE:"
)

print(
    participation_state
)

print()

print(
    "RELATIVE VOLUME:"
)

print(
    round(
        relative_volume,
        2
    )
)

print()

print(
    "RELATIVE SPREAD:"
)

print(
    round(
        relative_spread,
        2
    )
)

print()

print(
    "CLIMAX STATE:"
)

print(
    climax_state
)

print()

print(
    "EFFORT SCORE:"
)

print(
    round(
        effort_score,
        2
    )
)

print()

print(
    "RESULT SCORE:"
)

print(
    round(
        result_score,
        2
    )
)

print()

print(
    "NORMALIZED RESULT:"
)

print(
    round(
        normalized_result,
        2
    )
)

print()

print(
    "EFFORT RESULT STATE:"
)

print(
    effort_result_state
)

print()

print(
    "UNFINISHED AUCTION:"
)

print(
    unfinished_auction
)

print()

print(
    "UNFINISHED REASON:"
)

print(
    unfinished_reason
)

print()

print(
    "LOCALIZED BEHAVIOR:"
)

print(
    localized_behavior
)

print()

# =====================================
# SAVE
# =====================================

# Legacy `timestamp` remains wall-clock evaluation time for backward compatibility.
# Canonical bar-open identity is additive: source_candle_timestamp / evaluated_at.
# Flag OFF: keep historical utcnow() write semantics byte-for-byte equivalent.
_row_timestamp = (
    evaluated_at.to_pydatetime().replace(tzinfo=None)
    if _VOLUME_LOCALIZATION_LIVE and hasattr(evaluated_at, "to_pydatetime")
    else datetime.utcnow()
)
row = pd.DataFrame([{

    "timestamp":
        _row_timestamp,

    "volume_event":
        volume_event,

    "continuation_quality":
        continuation_quality,

    "volume_class":
        volume_class,

    "participation_state":
        participation_state,

    "relative_volume":
        relative_volume,

    "relative_spread":
        relative_spread,

    "climax_state":
        climax_state,

    "effort_score":
        effort_score,

    "result_score":
        result_score,

    "normalized_result":
        normalized_result,

    "effort_result_state":
        effort_result_state,

    "unfinished_auction":
        unfinished_auction,

    "unfinished_reason":
        unfinished_reason,

    "localized_behavior":
        localized_behavior

}])

# Additive identity + localization join metadata only when live-v1 flag is on
# (avoids live schema writes while candidate remains inactive).
if _VOLUME_LOCALIZATION_LIVE:
    row["estimated_local_volume"] = estimated_local_volume
    row["volume_concentration"] = volume_concentration
    row["localization_join_status"] = localization_join_status
    row["localization_source_timestamp"] = localization_source_timestamp
    row["localization_fresh"] = localization_fresh
    row["source_candle_timestamp"] = source_candle_timestamp
    row["source_candle_close"] = source_candle_close
    row["source_timeframe"] = _response_identity["source_timeframe"]
    row["evaluated_at"] = evaluated_at

state_payload = {

    "effort_result_state":
        effort_result_state,

    "unfinished_auction":
        unfinished_auction,

    "localized_behavior":
        localized_behavior

}

# When live-v1 is on, tip-identity changes must persist even if behavior label is unchanged
# (otherwise source_candle_timestamp / EXACT_FRESH_MATCH never land in state).
if _VOLUME_LOCALIZATION_LIVE:
    state_payload["source_candle_timestamp"] = str(source_candle_timestamp)
    state_payload["localization_join_status"] = localization_join_status

if not should_persist_state(

    "volume_response_state.parquet",

    state_payload

):

    print()

    print(
        "NO RESPONSE STATE CHANGE"
    )

else:

    append_state_row(

        "volume_response_state.parquet",

        row

    )

    print()

    print(
        "MEMORY SAVED:"
    )

    print(
        "volume_response_state.parquet"
    )


def run() -> int:
    """Execute volume response engine. Always returns 0 on completion or deferral."""
    return 0


if __name__ == "__main__":
    import os
    import sys

    run()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
