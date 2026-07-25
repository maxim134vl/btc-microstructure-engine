"""Domain view builders — expose existing runtime parquet surfaces only."""

from __future__ import annotations

import contextlib
import io
import json
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd
import psutil

from app.config import CANONICAL_PIPELINE, ONTOLOGY_EVENT_TYPES, REGIME_LABELS, TIMEFRAMES
from app.services.parquet_service import (
    df_records,
    file_snapshot,
    latest_row,
    parse_regime_vector,
    read_parquet,
)
from app.services.mtf_observability import classify_mtf_health
from runtime_dependency_map import DEPENDENCIES
from src.btc_ml.runtime import pipeline as runtime_pipeline


def _health_color(status: str) -> str:
    if status in ("GREEN", "SUCCESS", "running", "alive"):
        return "GREEN"
    if status in ("YELLOW", "WARN", "DEFERRED", "SKIPPED"):
        return "YELLOW"
    return "RED"


async def build_runtime_operations() -> dict[str, Any]:
    engine_state = await read_parquet("runtime_engine_state.parquet", tail=500)
    dependency_state = await read_parquet("runtime_dependency_state.parquet", tail=200)
    loop_audit_path = os.path.join("reports", "runtime_loop", "pipeline_cycle_audit.jsonl")

    latest_by_engine: dict[str, dict[str, Any]] = {}
    for row in df_records(engine_state):
        latest_by_engine[row["engine"]] = row

    pipeline_order = []
    failed = []
    skipped = []
    active = []
    for engine in CANONICAL_PIPELINE:
        entry = latest_by_engine.get(engine, {})
        status = entry.get("status", "UNKNOWN")
        dep_skipped = False
        if engine in DEPENDENCIES:
            dep_rows = [
                r for r in df_records(dependency_state) if r.get("engine") == engine
            ]
            if dep_rows:
                dep_skipped = False
        pipeline_order.append(
            {
                "engine": engine,
                "status": status,
                "duration_s": entry.get("duration"),
                "timestamp": entry.get("timestamp"),
                "mode": "in-process"
                if engine
                in (
                    "auction_convergence_engine_v1.py",
                    "auction_reinforcement_engine_v1.py",
                    "probabilistic_auction_engine_v1.py",
                    "adaptive_meta_cognition_engine_v1.py",
                    "stage2_cognition_runtime_v1.py",
                    "state_transition_engine_v1.py",
                )
                else "subprocess",
            }
        )
        if status == "FAILED":
            failed.append(engine)
        elif status == "SUCCESS":
            active.append(engine)

    synthesis = await read_parquet("auction_synthesis_memory.parquet", tail=5)
    state_transition_waiting = len(synthesis) < 2

    cycle_count = getattr(runtime_pipeline, "_CYCLE_COUNT", 0)
    loop_cycles = 0
    if os.path.exists(loop_audit_path):
        with open(loop_audit_path, encoding="utf-8") as handle:
            loop_cycles = sum(1 for _ in handle if _.strip())

    key_writes = [
        file_snapshot(name)
        for name in (
            "probabilistic_auction_memory.parquet",
            "auction_reinforcement_memory.parquet",
            "runtime_cognition_memory.parquet",
            "auction_synthesis_memory.parquet",
            "live_market_feed.parquet",
        )
    ]

    stale_writes = [item for item in key_writes if item.get("stale")]
    operational = "GREEN"
    if failed:
        operational = "RED"
    elif state_transition_waiting or stale_writes:
        operational = "YELLOW"

    return {
        "operational_health": operational,
        "runtime_alive": True,
        "pipeline_cycle_counter": max(cycle_count, loop_cycles),
        "current_cycle": max(cycle_count, loop_cycles),
        "engine_execution_order": pipeline_order,
        "active_engines": active,
        "failed_engines": failed,
        "skipped_engines": skipped,
        "state_transition_waiting": state_transition_waiting,
        "synthesis_row_count": int(len(synthesis)),
        "last_parquet_writes": key_writes,
        "runtime_continuity": {
            "status": "GREEN" if loop_cycles >= 1 or cycle_count >= 1 else "YELLOW",
            "loop_audit_cycles": loop_cycles,
            "in_memory_cycle_count": cycle_count,
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "uptime_seconds": round(time.time() - psutil.boot_time(), 1),
        },
        "recent_events": df_records(engine_state, limit=40),
        "generated_at": datetime.now().isoformat(),
    }


async def _ontology_events_for_timeframe(timeframe: str) -> list[dict[str, Any]]:
    candles = await read_parquet("candle_structure_memory.parquet")
    if len(candles) == 0:
        return []

    from app.services.mtf_observability import aggregate_behavioral_timeframe
    from auction_climax_engine_v1 import process_auction_climax

    if timeframe == "M15":
        dataset = candles.copy()
    else:
        dataset = aggregate_behavioral_timeframe(candles.copy(), timeframe)

    with contextlib.redirect_stdout(io.StringIO()):
        result = process_auction_climax(dataset=dataset, timeframe=timeframe)
    states = result.get("auction_states", pd.DataFrame())
    if len(states) == 0:
        return []

    events = states[states["auction_event_type"] != "NORMAL"].tail(50)
    return df_records(events)


async def build_ontology_panel() -> dict[str, Any]:
    probabilistic = await read_parquet("probabilistic_auction_memory.parquet", tail=1)
    latest_prob = latest_row(probabilistic) or {}

    events_by_tf: dict[str, list[dict[str, Any]]] = {}
    counts_by_tf: dict[str, dict[str, int]] = {}
    for tf in TIMEFRAMES:
        try:
            events = await _ontology_events_for_timeframe(tf)
        except Exception as error:
            events = [{"error": str(error), "timeframe": tf}]
        events_by_tf[tf] = events
        counts: dict[str, int] = {label: 0 for label in ONTOLOGY_EVENT_TYPES}
        for event in events:
            event_type = str(event.get("auction_event_type", ""))
            if event_type in counts:
                counts[event_type] += 1
        counts_by_tf[tf] = counts

    overlap_raw = latest_prob.get("ontology_overlap_matrix")
    ambiguity_raw = latest_prob.get("ontology_ambiguity_heatmap")

    return {
        "ontology_event_feed": events_by_tf.get("M15", [])[-20:],
        "events_by_timeframe": events_by_tf,
        "event_counts_by_timeframe": counts_by_tf,
        "ontology_density": {
            "semantic_fragility_score": latest_prob.get("semantic_fragility_score"),
            "ontology_drift_score": latest_prob.get("ontology_drift_score"),
            "ontology_stability_score": latest_prob.get("ontology_stability_score"),
            "grey_zone_expansion_rate": latest_prob.get("grey_zone_expansion_rate"),
        },
        "ontology_overlap_matrix": overlap_raw,
        "ontology_ambiguity_heatmap": ambiguity_raw,
        "climactic_behavior": latest_row(await read_parquet("climactic_behavior_memory.parquet", tail=1)),
        "generated_at": datetime.now().isoformat(),
    }


COGNITION_METRICS = (
    "raw_conviction",
    "disciplined_conviction",
    "calibrated_conviction",
    "conflict_density",
    "survival_half_life",
    "saturation_score",
    "calibration_drift_score",
    "resilience_score",
    "calibration_stability_score",
    "semantic_fragility_score",
    "contradiction_escalation_score",
    "unresolved_contradiction_score",
    "entropy_interaction",
    "reinforcement_component",
)


async def build_probabilistic_cognition() -> dict[str, Any]:
    df = await read_parquet("probabilistic_auction_memory.parquet", tail=200)
    latest = latest_row(df) or {}
    timeline = df_records(df, limit=120)

    decomposition = {
        key: latest.get(key)
        for key in (
            "alignment_component",
            "persistence_component",
            "location_component",
            "unfinished_auction_component",
            "entropy_penalty",
            "conflict_penalty",
            "reinforcement_component",
        )
    }

    return {
        "latest": {key: latest.get(key) for key in COGNITION_METRICS if key in latest or True},
        "decomposition": decomposition,
        "timeline": timeline,
        "entropy_state": {
            "entropy_transition_type": latest.get("entropy_transition_type"),
            "entropy_interaction": latest.get("entropy_interaction"),
            "entropy_decay_rate": latest.get("entropy_decay_rate"),
            "entropy_divergence_score": latest.get("entropy_divergence_score"),
        },
        "contradiction": {
            "conflict_density": latest.get("conflict_density"),
            "contradiction_flags": latest.get("contradiction_flags"),
            "contradiction_clusters": latest.get("contradiction_clusters"),
            "contradiction_duration": latest.get("contradiction_duration"),
            "contradiction_escalation_score": latest.get("contradiction_escalation_score"),
        },
        "generated_at": datetime.now().isoformat(),
    }


async def build_state_transitions() -> dict[str, Any]:
    transitions = await read_parquet("state_transition_memory.parquet", tail=100)
    synthesis = await read_parquet("auction_synthesis_memory.parquet", tail=5)
    probabilistic = await read_parquet("probabilistic_auction_memory.parquet", tail=2)

    latest_transition = latest_row(transitions)
    synth_latest = latest_row(synthesis)
    synth_previous = df_records(synthesis, limit=2)
    previous_auction = synth_previous[-2]["auction_state"] if len(synth_previous) >= 2 else None

    waiting = len(synthesis) < 2
    return {
        "waiting_for_second_state": waiting,
        "current_auction_state": synth_latest.get("auction_state") if synth_latest else None,
        "previous_auction_state": previous_auction,
        "latest_transition": latest_transition,
        "chronology": df_records(transitions, limit=50),
        "probabilistic_regime_tail": df_records(probabilistic, limit=2),
        "transition_instability": latest_transition.get("transition_state") if latest_transition else None,
        "generated_at": datetime.now().isoformat(),
    }


async def _timeframe_cognition_snapshot(timeframe: str) -> dict[str, Any]:
    candles = await read_parquet("candle_structure_memory.parquet")
    if len(candles) == 0:
        return {"timeframe": timeframe, "status": "NO_DATA"}

    from app.services.mtf_observability import aggregate_behavioral_timeframe
    from auction_climax_engine_v1 import process_auction_climax

    dataset = (
        candles.copy()
        if timeframe == "M15"
        else aggregate_behavioral_timeframe(candles.copy(), timeframe)
    )
    with contextlib.redirect_stdout(io.StringIO()):
        result = process_auction_climax(dataset=dataset, timeframe=timeframe)
    states = result.get("auction_states", pd.DataFrame())
    if len(states) == 0:
        return {"timeframe": timeframe, "status": "EMPTY"}

    latest = states.iloc[-1]
    recent_events = states[states["auction_event_type"] != "NORMAL"].tail(5)
    return {
        "timeframe": timeframe,
        "status": "LIVE",
        "latest_event_type": _serialize_cell(latest.get("auction_event_type")),
        "latest_timestamp": _serialize_cell(latest.get("timestamp")),
        "auction_state": _serialize_cell(latest.get("auction_state")),
        "cluster_behavior_resolution": _serialize_cell(latest.get("cluster_behavior_resolution")),
        "recent_events": df_records(recent_events),
        "in_live_pipeline": timeframe in ("M15", "M30", "H1", "H4"),
    }


def _latest_engine_status(engine_state: pd.DataFrame, engine: str) -> dict[str, Any]:
    for row in reversed(df_records(engine_state)):
        if row.get("engine") == engine:
            return row
    return {}


async def build_mtf_health() -> dict[str, Any]:
    synthesis = latest_row(
        await read_parquet(
            "multi_timeframe_synthesis.parquet",
            tail=1,
            columns=["timestamp", "synthesis_state", "lineage_propagation_timestamp"],
        )
    ) or {}
    runtime_cog = latest_row(
        await read_parquet(
            "runtime_cognition_memory.parquet",
            tail=1,
            columns=["timestamp", "synthesis_state", "lineage_propagation_timestamp"],
        )
    ) or {}
    input_candle = latest_row(
        await read_parquet("candle_structure_memory.parquet", tail=1, columns=["timestamp"])
    ) or {}
    live_candle = latest_row(
        await read_parquet("live_market_feed.parquet", tail=1, columns=["timestamp"])
    ) or {}
    engine_state = await read_parquet(
        "runtime_engine_state.parquet",
        tail=2000,
        columns=["timestamp", "engine", "status", "duration"],
    )
    producer = _latest_engine_status(engine_state, "stage2_cognition_runtime_v1.py")
    synthesis_snapshot = file_snapshot("multi_timeframe_synthesis.parquet")
    runtime_snapshot = file_snapshot("runtime_cognition_memory.parquet")

    health = classify_mtf_health(
        latest_event_timestamp=synthesis.get("timestamp") or runtime_cog.get("timestamp"),
        latest_input_candle_timestamp=input_candle.get("timestamp"),
        producer_heartbeat_timestamp=producer.get("timestamp"),
        producer_last_status=producer.get("status"),
        output_mtime=synthesis_snapshot.get("mtime"),
        source_reference_timestamp=live_candle.get("timestamp") or input_candle.get("timestamp"),
        lineage_propagation_timestamp=(
            synthesis.get("lineage_propagation_timestamp")
            or runtime_cog.get("lineage_propagation_timestamp")
        ),
    )
    health.update(
        {
            "producer_engine": "stage2_cognition_runtime_v1.py",
            "output_file": "multi_timeframe_synthesis.parquet",
            "output_row_count": synthesis_snapshot.get("row_count"),
            "runtime_cognition_output_mtime": runtime_snapshot.get("mtime"),
            "runtime_cognition_latest_event_timestamp": runtime_cog.get("timestamp"),
        }
    )
    return health


def _serialize_cell(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


async def build_mtf_cognition() -> dict[str, Any]:
    synthesis = latest_row(
        await read_parquet(
            "multi_timeframe_synthesis.parquet",
            tail=1,
            columns=["timestamp", "synthesis_state", "lineage_propagation_timestamp"],
        )
    )
    runtime_cog = latest_row(
        await read_parquet(
            "runtime_cognition_memory.parquet",
            tail=1,
            columns=["timestamp", "synthesis_state", "lineage_propagation_timestamp"],
        )
    )
    htf = latest_row(await read_parquet("htf_structure_memory.parquet", tail=1))
    context = latest_row(await read_parquet("htf_ltf_context_memory.parquet", tail=1))
    health = await build_mtf_health()

    tf_states = []
    for tf in TIMEFRAMES:
        tf_states.append(await _timeframe_cognition_snapshot(tf))

    return {
        "timeframe_states": tf_states,
        "stage2_synthesis": synthesis,
        "runtime_cognition": runtime_cog,
        "health": health,
        "htf_structure": htf,
        "htf_ltf_context": context,
        "hierarchy": [item.get("timeframe") for item in tf_states],
        "d1_macro_anchor": next((t for t in tf_states if t.get("timeframe") == "D1"), None),
        "generated_at": datetime.now().isoformat(),
    }


async def build_reinforcement_contradictions() -> dict[str, Any]:
    reinforcement = await read_parquet("auction_reinforcement_memory.parquet", tail=100)
    probabilistic = await read_parquet("probabilistic_auction_memory.parquet", tail=1)
    latest_prob = latest_row(probabilistic) or {}
    latest_reinf = latest_row(reinforcement) or {}

    return {
        "reinforcement_latest": latest_reinf,
        "reinforcement_timeline": df_records(reinforcement, limit=80),
        "contradiction_redistribution_score": latest_prob.get("contradiction_redistribution_score"),
        "contradiction_escalation_score": latest_prob.get("contradiction_escalation_score"),
        "unresolved_contradiction_score": latest_prob.get("unresolved_contradiction_score"),
        "contradiction_duration": latest_prob.get("contradiction_duration"),
        "reinforcement_stability_score": latest_prob.get("reinforcement_stability_score"),
        "reinforcement_asymmetry_creep": latest_prob.get("reinforcement_asymmetry_creep"),
        "ontology_reinforcement_divergence": latest_prob.get("ontology_reinforcement_divergence"),
        "stabilization_active": latest_prob.get("ontology_stabilization_active"),
        "generated_at": datetime.now().isoformat(),
    }


async def build_regime_monitoring() -> dict[str, Any]:
    df = await read_parquet("probabilistic_auction_memory.parquet", tail=120)
    latest = latest_row(df) or {}
    vector = parse_regime_vector(latest.get("regime_probability_vector"))

    return {
        "current_regime": latest.get("auction_regime"),
        "regime_state": latest.get("regime_state"),
        "regime_confidence": latest.get("regime_confidence"),
        "regime_transition_probability": latest.get("regime_transition_probability"),
        "regime_probabilities": vector or {label: 0.0 for label in REGIME_LABELS},
        "regime_drift_score": latest.get("regime_drift_score"),
        "adversarial_fragility": latest.get("probabilistic_fragility_score"),
        "regime_timeline": df_records(df, limit=80),
        "d1_bias": None,
        "generated_at": datetime.now().isoformat(),
    }


async def build_runtime_health() -> dict[str, Any]:
    from storage.path_registry import PARQUET_REGISTRY

    snapshots = [file_snapshot(name) for name in sorted(PARQUET_REGISTRY.keys())]
    stale = [item for item in snapshots if item.get("stale")]
    missing = [item for item in snapshots if not item.get("exists")]

    continuity_path = os.path.join("reports", "runtime_loop", "verify_runtime_loop_continuity.json")
    continuity = {}
    if os.path.exists(continuity_path):
        with open(continuity_path, encoding="utf-8") as handle:
            continuity = json.load(handle)

    alerts = []
    for item in stale:
        alerts.append(
            {
                "severity": "YELLOW",
                "type": "stale_parquet",
                "file": item["file"],
                "age_seconds": item.get("age_seconds"),
            }
        )
    for item in missing:
        alerts.append(
            {
                "severity": "RED",
                "type": "missing_parquet",
                "file": item["file"],
            }
        )

    return {
        "operational_health": "RED" if missing else ("YELLOW" if stale else "GREEN"),
        "parquet_snapshots": snapshots,
        "stale_parquet": stale,
        "missing_parquet": missing,
        "runtime_continuity_report": continuity,
        "alerts": alerts,
        "cache_health": {"ttl_seconds": 1.5, "status": "GREEN"},
        "generated_at": datetime.now().isoformat(),
    }


async def build_replay_audit() -> dict[str, Any]:
    report_dirs = [
        os.path.join("reports", "runtime_loop"),
        os.path.join("reports", "ontology_density"),
    ]
    exports: list[dict[str, Any]] = []
    for directory in report_dirs:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            exports.append(
                {
                    "name": name,
                    "path": path,
                    "size_bytes": os.path.getsize(path),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                }
            )

    return {
        "replay_exports": exports,
        "replay_controls": {
            "verify_runtime_loop": "scripts/verify_runtime_loop_continuity.py",
            "ontology_density": "scripts/run_ontology_density_diagnostics.py",
        },
        "generated_at": datetime.now().isoformat(),
    }


async def build_topology() -> dict[str, Any]:
    dependency_state = await read_parquet("runtime_dependency_state.parquet", tail=200)
    engine_state = await read_parquet("runtime_engine_state.parquet", tail=200)

    nodes = []
    for index, engine in enumerate(CANONICAL_PIPELINE):
        latest = None
        for row in reversed(df_records(engine_state)):
            if row.get("engine") == engine:
                latest = row
                break
        nodes.append(
            {
                "id": engine,
                "order": index + 1,
                "status": latest.get("status", "UNKNOWN") if latest else "UNKNOWN",
                "duration_s": latest.get("duration") if latest else None,
                "dependencies": DEPENDENCIES.get(engine, []),
            }
        )

    edges = []
    for engine, deps in DEPENDENCIES.items():
        for dep in deps:
            edges.append({"from": dep, "to": engine, "type": "dependency_guard"})

    for index in range(len(CANONICAL_PIPELINE) - 1):
        edges.append(
            {
                "from": CANONICAL_PIPELINE[index],
                "to": CANONICAL_PIPELINE[index + 1],
                "type": "pipeline_order",
            }
        )

    dead_nodes = [node["id"] for node in nodes if node["status"] == "FAILED"]

    return {
        "pipeline_nodes": nodes,
        "edges": edges,
        "dependency_records": df_records(dependency_state, limit=50),
        "dead_nodes": dead_nodes,
        "orchestration_integrity": "RED" if dead_nodes else "GREEN",
        "generated_at": datetime.now().isoformat(),
    }


async def build_intermediate_cognition(*, tail: int = 40) -> dict[str, Any]:
    """Stage 2.5 intermediate cognition timeline for dashboard."""

    df = await read_parquet("intermediate_cognition_memory.parquet", tail=tail)
    latest = latest_row(df) or {}
    records = df_records(df, limit=tail)

    distribution: dict[str, int] = {}
    for row in records:
        state = str(row.get("intermediate_state") or "UNKNOWN")
        distribution[state] = distribution.get(state, 0) + 1

    return {
        "purpose": "Tier-2 intermediate cognition — context narration between Stage 2 synthesis events",
        "latest": latest,
        "timeline": records,
        "distribution": distribution,
        "event_count": len(records),
        "linked_stage2_anchor": latest.get("anchor_stage2_state"),
        "anchor_timestamp": latest.get("anchor_timestamp"),
        "generated_at": datetime.now().isoformat(),
    }


async def build_live_snapshot() -> dict[str, Any]:
    return {
        "runtime_operations": await build_runtime_operations(),
        "ontology": await build_ontology_panel(),
        "probabilistic_cognition": await build_probabilistic_cognition(),
        "state_transitions": await build_state_transitions(),
        "mtf_cognition": await build_mtf_cognition(),
        "intermediate_cognition": await build_intermediate_cognition(),
        "reinforcement": await build_reinforcement_contradictions(),
        "regime": await build_regime_monitoring(),
        "runtime_health": await build_runtime_health(),
        "replay_audit": await build_replay_audit(),
        "topology": await build_topology(),
        "generated_at": datetime.now().isoformat(),
    }
