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
# RELATIVE CONTEXT + RESPONSE (shared evaluator)
# =====================================

from btc_ml.cognition.volume_response_evaluate import evaluate_response_row

_loc_hist = localization.copy() if len(localization) else localization
_geo_hist = geometry.copy() if len(geometry) else geometry
_rxn_hist = reactions.copy() if len(reactions) else reactions

_eval = evaluate_response_row(
    latest_localization,
    structure_row=latest_structure,
    geometry_row=latest_geometry,
    classification_row=latest_classification,
    reaction_row=latest_reaction,
    localization_history=_loc_hist,
    geometry_history=_geo_hist,
    reactions_history=_rxn_hist,
    causal_cutoff=source_candle_timestamp,
    live_v1=_VOLUME_LOCALIZATION_LIVE,
    localization_join_status=localization_join_status if _VOLUME_LOCALIZATION_LIVE else "LEGACY_V2_TIP_CARRY",
)

volume_event = _eval["volume_event"]
continuation_quality = _eval["continuation_quality"]
volume_class = _eval["volume_class"]
participation_state = _eval["participation_state"]
relative_volume = _eval["relative_volume"]
relative_spread = _eval["relative_spread"]
climax_state = _eval["climax_state"]
effort_score = _eval["effort_score"]
result_score = _eval["result_score"]
normalized_result = _eval["normalized_result"]
effort_result_state = _eval["effort_result_state"]
unfinished_auction = _eval["unfinished_auction"]
unfinished_reason = _eval["unfinished_reason"]
localized_behavior = _eval["localized_behavior"]
estimated_local_volume = _eval.get("estimated_local_volume")
volume_concentration = _eval.get("volume_concentration")

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
    ) if relative_volume == relative_volume else relative_volume
)

print()

print(
    "RELATIVE SPREAD:"
)

print(
    round(
        relative_spread,
        2
    ) if relative_spread == relative_spread else relative_spread
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
    ) if effort_score == effort_score else effort_score
)

print()

print(
    "RESULT SCORE:"
)

print(
    round(
        result_score,
        2
    ) if result_score == result_score else result_score
)

print()

print(
    "NORMALIZED RESULT:"
)

print(
    round(
        normalized_result,
        2
    ) if normalized_result == normalized_result else normalized_result
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
