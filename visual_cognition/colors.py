"""Canonical cognition color semantics for visual replay."""

from __future__ import annotations

COGNITION_COLORS = {
    "buyer_initiative": "#22c55e",
    "seller_initiative": "#ef4444",
    "instability": "#eab308",
    "absorption": "#06b6d4",
    "climax": "#f97316",
    "contradiction": "#a855f7",
    "neutral_rotation": "#f8fafc",
    "dormant": "#64748b",
}

INITIATIVE_COLORS = {
    "buyer": COGNITION_COLORS["buyer_initiative"],
    "seller": COGNITION_COLORS["seller_initiative"],
    "neutral": COGNITION_COLORS["neutral_rotation"],
    "dormant": COGNITION_COLORS["dormant"],
}

BEHAVIOR_COLORS = {
    "BUYING_CLIMAX": COGNITION_COLORS["climax"],
    "SELLING_CLIMAX": COGNITION_COLORS["climax"],
    "STOPPING_ACTIVITY": COGNITION_COLORS["absorption"],
    "ABSORPTION": COGNITION_COLORS["absorption"],
    "COMPRESSION": COGNITION_COLORS["absorption"],
    "ROTATIONAL_PRESSURE": COGNITION_COLORS["neutral_rotation"],
    "CONTINUATION_DETERIORATION": COGNITION_COLORS["instability"],
    "INITIATIVE_BUY": COGNITION_COLORS["buyer_initiative"],
    "INITIATIVE_SELL": COGNITION_COLORS["seller_initiative"],
    "CONTRADICTION": COGNITION_COLORS["contradiction"],
    "EFFORT_RESULT_DIVERGENCE": COGNITION_COLORS["instability"],
    "TRANSITION_DETERIORATION": COGNITION_COLORS["instability"],
    "DIRECTIONAL_COLLAPSE": COGNITION_COLORS["instability"],
}
