"""Build Stage 1 cognition reasoning flow chain."""

from __future__ import annotations

from typing import Any

import pandas as pd

from visual_cognition.behavioral_overlay_engine import classify_initiative, detect_behaviors


def _step(label: str, detail: str, *, behavior: str | None = None, timeframe: str = "M15") -> dict[str, Any]:
    return {
        "label": label,
        "detail": detail,
        "behavior": behavior,
        "timeframe": timeframe,
    }


def build_stage1_flow(cognition_row: pd.Series, propagation: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Step-by-step behavioral interpretation at cursor timestamp."""

    steps: list[dict[str, Any]] = []
    behaviors = detect_behaviors(cognition_row)
    initiative = classify_initiative(cognition_row)

    trigger = cognition_row.get("trigger_event")
    climax = cognition_row.get("climax_state")
    volume_event = cognition_row.get("volume_event")
    synthesis = cognition_row.get("synthesis_state")
    effort = cognition_row.get("effort_result_state")
    transition = cognition_row.get("transition_state")
    regime = cognition_row.get("auction_regime")

    if pd.notna(trigger) and str(trigger) not in ("NORMAL", "nan"):
        steps.append(_step(str(trigger).replace("_", " "), f"Stage 1 trigger event detected: {trigger}.", behavior=str(trigger)))
    elif pd.notna(climax) and str(climax) not in ("NO_CLIMAX", "nan"):
        steps.append(_step(str(climax).replace("_", " "), f"Climax state registered: {climax}.", behavior=str(climax)))

    if "BUYING_CLIMAX" in behaviors or "SELLING_CLIMAX" in behaviors:
        label = "BUYING CLIMAX" if "BUYING_CLIMAX" in behaviors else "SELLING CLIMAX"
        steps.append(_step(label, "Exhaustion impulse — continuation likely to weaken.", behavior=label.replace(" ", "_")))

    if "CONTINUATION_DETERIORATION" in behaviors or (cognition_row.get("continuation_quality") in ("WEAK", "DETERIORATING")):
        steps.append(_step("CONTINUATION WEAKENS", "Follow-through quality deteriorating relative to initiative.", behavior="CONTINUATION_DETERIORATION"))

    if "ROTATIONAL_PRESSURE" in behaviors or initiative == "neutral":
        steps.append(_step("ROTATION INCREASES", "Balanced two-sided participation — directional edge fading.", behavior="ROTATIONAL_PRESSURE"))

    if initiative in ("buyer", "seller") and "CONTINUATION_DETERIORATION" in behaviors:
        steps.append(
            _step(
                "INITIATIVE DETERIORATES",
                f"{initiative.title()} initiative losing structural support.",
                behavior="INITIATIVE_" + initiative.upper(),
            )
        )
    elif initiative == "buyer":
        steps.append(_step("BUYER INITIATIVE", "Delta and trigger alignment favor buyers.", behavior="INITIATIVE_BUY"))
    elif initiative == "seller":
        steps.append(_step("SELLER INITIATIVE", "Delta and trigger alignment favor sellers.", behavior="INITIATIVE_SELL"))

    if "STOPPING_ACTIVITY" in behaviors or (pd.notna(volume_event) and "STOPPING" in str(volume_event)):
        steps.append(_step("STOPPING ACTIVITY", "Volume response indicates absorption at extremes.", behavior="STOPPING_ACTIVITY"))

    if pd.notna(effort) and str(effort) not in ("BALANCED_RESPONSE", "nan"):
        steps.append(_step("EFFORT / RESULT", f"Effort-result divergence: {effort}.", behavior="EFFORT_RESULT_DIVERGENCE"))

    if pd.notna(synthesis):
        steps.append(_step("SYNTHESIS", f"Multi-signal synthesis state: {synthesis}.", timeframe="M15"))

    if pd.notna(transition) and str(transition) not in ("STABLE_STATE", "nan"):
        steps.append(_step("STATE TRANSITION", f"Behavioral transition: {transition}.", behavior="TRANSITION_DETERIORATION"))

    if "CONTRADICTION" in behaviors:
        steps.append(_step("CONTRADICTION", "Conflicting signals across cognition layers.", behavior="CONTRADICTION"))

    if "CONTINUATION_DETERIORATION" in behaviors and len(steps) >= 2:
        steps.append(_step("CONTINUATION COLLAPSES", "Directional structure breaks down at this timeframe.", behavior="DIRECTIONAL_COLLAPSE"))

    if pd.notna(regime):
        steps.append(_step("AUCTION REGIME", f"Probabilistic regime context: {regime}.", timeframe="MTF"))

    if propagation and propagation.get("chain"):
        for line in propagation["chain"]:
            tf, _, desc = line.partition(": ")
            steps.append(_step(f"{tf} CONTEXT", desc, timeframe=tf))

    if not steps:
        steps.append(_step("NEUTRAL PARTICIPATION", "Stage 1 observed low-confidence dormant market structure."))

    for index, step in enumerate(steps, start=1):
        step["step"] = index
    return steps
