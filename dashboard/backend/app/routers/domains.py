"""Unified dashboard API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.domain_builders import (
    build_live_snapshot,
    build_mtf_cognition,
    build_ontology_panel,
    build_probabilistic_cognition,
    build_regime_monitoring,
    build_reinforcement_contradictions,
    build_replay_audit,
    build_runtime_health,
    build_runtime_operations,
    build_state_transitions,
    build_topology,
)

router = APIRouter()


@router.get("/snapshot")
async def snapshot():
    return await build_live_snapshot()


@router.get("/runtime/operations")
async def runtime_operations():
    return await build_runtime_operations()


@router.get("/ontology")
async def ontology():
    return await build_ontology_panel()


@router.get("/cognition/probabilistic")
async def probabilistic_cognition():
    return await build_probabilistic_cognition()


@router.get("/state-transitions")
async def state_transitions():
    return await build_state_transitions()


@router.get("/mtf/cognition")
async def mtf_cognition():
    return await build_mtf_cognition()


@router.get("/reinforcement")
async def reinforcement():
    return await build_reinforcement_contradictions()


@router.get("/regime")
async def regime():
    return await build_regime_monitoring()


@router.get("/health/runtime")
async def runtime_health():
    return await build_runtime_health()


@router.get("/replay")
async def replay():
    return await build_replay_audit()


@router.get("/topology")
async def topology():
    return await build_topology()
