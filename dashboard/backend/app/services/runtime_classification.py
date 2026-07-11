"""Display classification for dashboard — no runtime engine imports."""

from __future__ import annotations

from typing import Literal

from app.services.required_manifest import (
    is_required_collector,
    is_required_engine,
    is_required_parquet,
)

ComponentClass = Literal["REQUIRED", "OPTIONAL", "LEGACY", "RESEARCH", "DORMANT"]

PARQUET_DISPLAY_CLASS: dict[str, ComponentClass] = {
    "auction_synthesis_memory.parquet": "DORMANT",
    "auction_reinforcement_memory.parquet": "DORMANT",
    "auction_convergence_memory.parquet": "DORMANT",
    "auction_decay_memory.parquet": "DORMANT",
    "state_transition_memory.parquet": "DORMANT",
    "multi_exchange_flow.parquet": "OPTIONAL",
    "volume_reactions.parquet": "OPTIONAL",
    "volume_localization_memory.parquet": "OPTIONAL",
    "live_volume_flow_memory.parquet": "OPTIONAL",
    "flow_liquidity_interaction_memory.parquet": "OPTIONAL",
    "candle_geometry_v2_memory.parquet": "LEGACY",
    "volume_localization_v2_memory.parquet": "LEGACY",
    "behavioral_scoring_memory.parquet": "LEGACY",
    "research_master_dataset.parquet": "RESEARCH",
    "btc_15m.parquet": "RESEARCH",
    "htf_structure_memory.parquet": "DORMANT",
    "htf_ltf_context_memory.parquet": "DORMANT",
    "runtime_dependency_state.parquet": "DORMANT",
    "runtime_cognition_alignment_audit.parquet": "DORMANT",
    "state_transition_engine_state.parquet": "DORMANT",
    "runtime_engine_state.parquet": "DORMANT",
}

COLLECTOR_DISPLAY_CLASS: dict[str, ComponentClass] = {
    "live_feed_legacy_mirror": "LEGACY",
    "multi_exchange": "OPTIONAL",
    "orderbook": "OPTIONAL",
    "oi": "OPTIONAL",
    "liquidation": "OPTIONAL",
}

ARCHIVED_CLASSES: frozenset[ComponentClass] = frozenset({"LEGACY", "RESEARCH", "DORMANT"})


def classify_parquet(filename: str) -> ComponentClass:
    if is_required_parquet(filename):
        return "REQUIRED"
    return PARQUET_DISPLAY_CLASS.get(filename, "DORMANT")


def classify_collector(name: str) -> ComponentClass:
    if is_required_collector(name):
        return "REQUIRED"
    return COLLECTOR_DISPLAY_CLASS.get(name, "OPTIONAL")


def classify_engine(engine: str) -> ComponentClass:
    if is_required_engine(engine):
        return "REQUIRED"
    return "OPTIONAL"


def affects_health(component_class: ComponentClass, *, name: str, kind: str) -> bool:
    if kind == "parquet":
        return is_required_parquet(name)
    if kind == "collector":
        return is_required_collector(name)
    if kind == "engine":
        return is_required_engine(name)
    return component_class == "REQUIRED"
