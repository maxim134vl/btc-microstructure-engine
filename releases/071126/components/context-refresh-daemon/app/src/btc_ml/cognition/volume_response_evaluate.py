"""Single-row volume response evaluator (canonical rules from volume_response_engine_v1)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd


def _get(row: Mapping[str, Any] | pd.Series | None, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, pd.Series):
        return row[key] if key in row.index else default
    return row.get(key, default)


def evaluate_response_row(
    localization_row: Mapping[str, Any] | pd.Series | None,
    *,
    structure_row: Mapping[str, Any] | pd.Series,
    geometry_row: Mapping[str, Any] | pd.Series,
    classification_row: Mapping[str, Any] | pd.Series | None = None,
    reaction_row: Mapping[str, Any] | pd.Series | None = None,
    localization_history: Optional[pd.DataFrame] = None,
    geometry_history: Optional[pd.DataFrame] = None,
    reactions_history: Optional[pd.DataFrame] = None,
    causal_cutoff: Any = None,
    live_v1: bool = True,
    localization_join_status: str = "EXACT_FRESH_MATCH",
) -> dict[str, Any]:
    """Evaluate one tip using the same rules as volume_response_engine_v1 tip path."""

    def _hist(df: Optional[pd.DataFrame], col: str) -> pd.Series:
        if df is None or len(df) == 0 or col not in df.columns:
            return pd.Series(dtype=float)
        work = df
        if causal_cutoff is not None and "timestamp" in work.columns:
            ts = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
            cut = pd.Timestamp(causal_cutoff)
            if cut.tzinfo is None:
                cut = cut.tz_localize("UTC")
            else:
                cut = cut.tz_convert("UTC")
            work = work.loc[ts <= cut]
        return work[col].tail(50)

    recent_local_volume = _hist(localization_history, "estimated_local_volume")
    recent_spread = _hist(geometry_history, "spread")
    recent_delta_efficiency = _hist(reactions_history, "delta_efficiency")

    if localization_row is None or (
        live_v1 and localization_join_status != "EXACT_FRESH_MATCH"
    ):
        relative_volume = float("nan")
    else:
        mean_lv = float(recent_local_volume.mean()) if len(recent_local_volume) else float("nan")
        elv = float(_get(localization_row, "estimated_local_volume"))
        relative_volume = elv / mean_lv if mean_lv and mean_lv == mean_lv else float("nan")

    spread_mean = float(recent_spread.mean()) if len(recent_spread) else float("nan")
    relative_spread = (
        float(_get(geometry_row, "spread")) / spread_mean
        if spread_mean and spread_mean == spread_mean
        else float("nan")
    )

    if reaction_row is not None and len(recent_delta_efficiency):
        de_mean = float(recent_delta_efficiency.abs().mean())
        relative_efficiency = (
            abs(float(_get(reaction_row, "delta_efficiency", 0.0))) / de_mean
            if de_mean and de_mean == de_mean
            else float("nan")
        )
    else:
        relative_efficiency = float("nan")

    upper_rejection = bool(_get(geometry_row, "upper_rejection", False))
    lower_rejection = bool(_get(geometry_row, "lower_rejection", False))
    close_position = float(_get(geometry_row, "close_position", 0.5))
    body = float(_get(geometry_row, "body", 0.0))
    spread = float(_get(geometry_row, "spread", 0.0))

    volume_class = str(_get(classification_row, "volume_class", "unknown") or "unknown")
    participation_state = "NORMAL_PARTICIPATION"
    participation_adjustment = 0.0
    climax_state = "NO_CLIMAX"

    if live_v1:
        if localization_row is not None and localization_join_status == "EXACT_FRESH_MATCH":
            localized_behavior = _get(localization_row, "behavior")
            estimated_local_volume = _get(localization_row, "estimated_local_volume")
            volume_concentration = _get(localization_row, "volume_concentration")
        else:
            localized_behavior = None
            estimated_local_volume = None
            volume_concentration = None
    else:
        localized_behavior = _get(localization_row, "behavior")
        estimated_local_volume = _get(localization_row, "estimated_local_volume")
        volume_concentration = _get(localization_row, "volume_concentration")

    delta = float(_get(structure_row, "delta", 0.0) or 0.0)
    if estimated_local_volume is None or (
        isinstance(estimated_local_volume, float) and pd.isna(estimated_local_volume)
    ):
        delta_efficiency = float("nan")
    else:
        delta_efficiency = delta / float(estimated_local_volume)

    effort_score = (
        (relative_volume if relative_volume == relative_volume else 0.0)
        + (abs(delta_efficiency) if delta_efficiency == delta_efficiency else 0.0)
        + (relative_spread if relative_spread == relative_spread else 0.0)
    ) / 3.0
    effort_score += participation_adjustment

    close_acceptance = abs(close_position - 0.5) * 2
    spread_efficiency = (relative_spread if relative_spread == relative_spread else 0.0) * close_acceptance
    rejection_penalty = 0.0
    if upper_rejection:
        rejection_penalty += 0.4
    if lower_rejection:
        rejection_penalty += 0.4
    result_score = close_acceptance + spread_efficiency - rejection_penalty
    effort_result_ratio = result_score / (effort_score + 0.001)
    normalized_result = effort_result_ratio * (1 / (1 + rejection_penalty))

    if "climax" in str(volume_class).lower():
        participation_state = "CLIMACTIC_PARTICIPATION"
        participation_adjustment = 0.5
        effort_score += participation_adjustment
        if normalized_result < 0:
            climax_state = "CLIMAX_EXHAUSTION"
        elif normalized_result > 0.5:
            climax_state = "CLIMAX_CONTINUATION"
        else:
            climax_state = "CLIMAX_ABSORPTION"

    volume_event = "NEUTRAL_VOLUME"
    continuation_quality = "NEUTRAL"
    rv = relative_volume if relative_volume == relative_volume else 0.0
    de = abs(delta_efficiency) if delta_efficiency == delta_efficiency else 0.0
    rs = relative_spread if relative_spread == relative_spread else 0.0

    if rv > 1.8 and de < 0.3 and (upper_rejection or lower_rejection):
        volume_event = "STOPPING_VOLUME"
    if localized_behavior == "localized_absorption" and de < 0.3:
        volume_event = "ABSORPTION_VOLUME"
    if body > (spread * 0.7) and de > 1.0 and rs > 1.5:
        volume_event = "CONTINUATION_VOLUME"
    if rv > 2.0 and de < 0.2:
        volume_event = "EXHAUSTION_VOLUME"

    effort_result_state = "BALANCED_RESPONSE"
    if effort_score > 1.2 and normalized_result < 0.6:
        effort_result_state = "ABSORPTION_RESPONSE"
    elif effort_score > 1.2 and normalized_result > 1.0:
        effort_result_state = "EFFICIENT_CONTINUATION"
    elif rv > 2 and normalized_result < 0.4:
        effort_result_state = "EXHAUSTION_RESPONSE"

    unfinished_auction = False
    unfinished_reason = "NONE"
    if effort_score > 1.0 and normalized_result < 0.3:
        unfinished_auction = True
        unfinished_reason = "INEFFICIENT_AUCTION"
    if localized_behavior == "localized_distribution" and rs < 1.0:
        unfinished_auction = True
        unfinished_reason = "DISTRIBUTION_NOT_RESOLVED"
    if (upper_rejection or lower_rejection) and abs(normalized_result) < 0.2:
        unfinished_auction = True
        unfinished_reason = "REJECTION_WITHOUT_RESOLUTION"

    if volume_event == "CONTINUATION_VOLUME" and close_position > 0.8:
        continuation_quality = "STRONG_ACCEPTANCE"
    elif volume_event == "CONTINUATION_VOLUME" and close_position < 0.5:
        continuation_quality = "FAILED_CONTINUATION"
    elif volume_event == "STOPPING_VOLUME":
        continuation_quality = "AUCTION_STALLED"
    elif volume_event == "ABSORPTION_VOLUME":
        continuation_quality = "PASSIVE_DEFENSE"

    return {
        "volume_event": volume_event,
        "continuation_quality": continuation_quality,
        "volume_class": volume_class,
        "participation_state": participation_state,
        "relative_volume": relative_volume,
        "relative_spread": relative_spread,
        "relative_efficiency": relative_efficiency,
        "climax_state": climax_state,
        "effort_score": effort_score,
        "result_score": result_score,
        "normalized_result": normalized_result,
        "effort_result_state": effort_result_state,
        "unfinished_auction": unfinished_auction,
        "unfinished_reason": unfinished_reason,
        "localized_behavior": localized_behavior,
        "estimated_local_volume": estimated_local_volume,
        "volume_concentration": volume_concentration,
        "delta_efficiency": delta_efficiency,
        "localization_join_status": localization_join_status,
        "evaluation_mode": "PROVISIONAL_INTRABAR" if live_v1 else "CLOSED_BAR",
    }
