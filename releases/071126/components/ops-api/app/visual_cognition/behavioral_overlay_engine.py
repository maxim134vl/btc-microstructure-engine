"""Derive behavioral overlays from Stage 1 cognition memory."""

from __future__ import annotations

from typing import Any

import pandas as pd

from visual_cognition.colors import BEHAVIOR_COLORS, COGNITION_COLORS, INITIATIVE_COLORS


def _safe_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.lower() in ("nan", "none", ""):
        return None
    return text


def classify_initiative(row: pd.Series) -> str:
    delta = row.get("delta")
    if delta is not None and not pd.isna(delta):
        if float(delta) > 0:
            return "buyer"
        if float(delta) < 0:
            return "seller"
    trigger = _safe_str(row.get("trigger_event"))
    if trigger and "BUY" in trigger.upper():
        return "buyer"
    if trigger and "SELL" in trigger.upper():
        return "seller"
    regime = _safe_str(row.get("auction_regime"))
    if regime and "BALANCED" in regime:
        return "neutral"
    return "dormant"


def detect_behaviors(row: pd.Series) -> list[str]:
    behaviors: list[str] = []

    trigger = _safe_str(row.get("trigger_event"))
    climax = _safe_str(row.get("climax_state"))
    volume_event = _safe_str(row.get("volume_event"))
    volume_class = _safe_str(row.get("volume_class"))
    effort = _safe_str(row.get("effort_result_state"))
    localized = _safe_str(row.get("localized_behavior"))
    synthesis = _safe_str(row.get("synthesis_state"))
    transition = _safe_str(row.get("transition_state"))
    continuation = _safe_str(row.get("continuation_quality"))

    if trigger == "BUYING_CLIMAX" or climax == "BUYING_CLIMAX" or (volume_class == "climax" and classify_initiative(row) == "buyer"):
        behaviors.append("BUYING_CLIMAX")
    if trigger == "SELLING_CLIMAX" or climax == "SELLING_CLIMAX" or (volume_class == "climax" and classify_initiative(row) == "seller"):
        behaviors.append("SELLING_CLIMAX")

    if volume_event in ("STOPPING_VOLUME", "ABSORPTION_VOLUME") or volume_class == "stopping":
        behaviors.append("STOPPING_ACTIVITY")
    if effort in ("ABSORPTION_RESPONSE", "ABSORPTION"):
        behaviors.append("ABSORPTION")
    if localized and "rotation" in localized.lower():
        behaviors.append("ROTATIONAL_PRESSURE")
    if continuation in ("WEAK", "DETERIORATING", "FAILING"):
        behaviors.append("CONTINUATION_DETERIORATION")
    if effort in ("EFFORT_WITHOUT_RESULT", "DIVERGENCE"):
        behaviors.append("EFFORT_RESULT_DIVERGENCE")
    if synthesis in ("LOCAL_EXHAUSTION", "DISTRIBUTION_CLUSTER", "ACCUMULATION_CLUSTER"):
        behaviors.append("COMPRESSION")
    if transition and transition not in ("STABLE_STATE", None):
        behaviors.append("TRANSITION_DETERIORATION")
    if synthesis and trigger and synthesis not in trigger:
        behaviors.append("CONTRADICTION")

    initiative = classify_initiative(row)
    if initiative == "buyer":
        behaviors.append("INITIATIVE_BUY")
    elif initiative == "seller":
        behaviors.append("INITIATIVE_SELL")

    if not behaviors and initiative == "neutral":
        behaviors.append("ROTATIONAL_PRESSURE")

    return list(dict.fromkeys(behaviors))


def continuation_health(row: pd.Series) -> float:
    """0 = collapsed, 1 = strong continuation."""

    score = 0.5
    continuation = _safe_str(row.get("continuation_quality"))
    if continuation in ("STRONG", "HEALTHY"):
        score = 0.9
    elif continuation in ("WEAK", "DETERIORATING"):
        score = 0.35
    elif continuation in ("FAILING", "COLLAPSED"):
        score = 0.1

    behaviors = detect_behaviors(row)
    if "CONTINUATION_DETERIORATION" in behaviors or "DIRECTIONAL_COLLAPSE" in behaviors:
        score = min(score, 0.25)
    if "BUYING_CLIMAX" in behaviors or "SELLING_CLIMAX" in behaviors:
        score = min(score, 0.4)
    if "STOPPING_ACTIVITY" in behaviors or "ABSORPTION" in behaviors:
        score = min(score, 0.45)
    return round(score, 3)


def overlay_for_bar(row: pd.Series) -> dict[str, Any]:
    initiative = classify_initiative(row)
    behaviors = detect_behaviors(row)
    primary = behaviors[0] if behaviors else "DORMANT"
    color = BEHAVIOR_COLORS.get(primary, INITIATIVE_COLORS.get(initiative, COGNITION_COLORS["dormant"]))
    return {
        "initiative": initiative,
        "behaviors": behaviors,
        "primary_behavior": primary,
        "overlay_color": color,
        "continuation_health": continuation_health(row),
        "confidence": float(row.get("persistence_score") or row.get("alignment_score") or 0.5)
        if pd.notna(row.get("persistence_score") or row.get("alignment_score"))
        else 0.5,
    }


def apply_overlays_to_bars(bars: list[dict[str, Any]], cognition_row: pd.Series | None) -> list[dict[str, Any]]:
    """Attach overlay metadata to serialized bars using nearest cognition state."""

    if cognition_row is None or len(bars) == 0:
        return [{**bar, **overlay_for_bar(pd.Series(dtype=object))} for bar in bars]

    enriched: list[dict[str, Any]] = []
    for bar in bars:
        merged = pd.Series({**cognition_row.to_dict(), **bar})
        enriched.append({**bar, **overlay_for_bar(merged)})
    return enriched


def build_overlay_series(cognition_frame: pd.DataFrame, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map cognition memory onto each bar timestamp."""

    if len(cognition_frame) == 0 or len(bars) == 0:
        return apply_overlays_to_bars(bars, None)

    cog = cognition_frame.sort_values("timestamp").dropna(subset=["timestamp"]).copy()
    enriched: list[dict[str, Any]] = []
    for bar in bars:
        ts = pd.to_datetime(bar["timestamp"])
        prior = cog[cog["timestamp"] <= ts]
        row = prior.iloc[-1] if len(prior) else pd.Series(dtype=object)
        merged = pd.Series({**row.to_dict(), **bar})
        enriched.append({**bar, **overlay_for_bar(merged)})
    return enriched
