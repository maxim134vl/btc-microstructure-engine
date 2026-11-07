"""Owner-written UI messages. Standard library only; no history reader or scheduler."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "ops_owner_publication_v1"
# Exclusive authority for each projection. Unimplemented projections stay unavailable.
OWNERS = {
    "context_chain": "context_refresh_daemon",
    "multi_timeframe": "mtf_availability_runtime_engine_v1.py",
    "collectors": "collector_watchdog",
    "engines": "canonical_engine_registry",
    "pipeline_engines": "canonical_engine_registry",
    "pipeline": "canonical_cycle_coordinator",
    "parquet": "runtime_dataset_metadata",
    "datasets": "runtime_dataset_metadata",
    "feed_confidence": "collector_watchdog",
    "stability": "runtime_supervision",
    "health": "runtime_supervision",
    "health_dimensions": "runtime_supervision",
    "status_planes": "runtime_supervision",
    "runtime_stability": "runtime_supervision",
    "overall_health": "runtime_supervision",
    "overall_reason": "runtime_supervision",
    "processes": "runtime_supervision",
    "alerts": "runtime_supervision",
    "alert_groups": "runtime_supervision",
    "warnings": "runtime_supervision",
    "ribbon": "runtime_supervision",
    "manifest": "runtime_dataset_metadata",
    "classification": "runtime_dataset_metadata",
    "runtime_failure_audit": "canonical_engine_registry",
    "runtime_skipped_engine_audit": "canonical_engine_registry",
    "mtf_cognition_health": "stage2_cognition_runtime_v1.py",
    "paper": "intrabar_paper_manager",
    "timeframe_traders": "timeframe_manager",
    "live1b_paper": "intrabar_paper_manager",
    "financial_performance": "financial_engine_v3",
    "research_pipeline.pipeline": "canonical_cycle_coordinator",
    "research_pipeline.decision_layer": "timeframe_manager",
    "research_pipeline.model_governance": "model_governance",
    "research_pipeline.economic_validation": "economic_validation_engine_v1.py",
    "research_pipeline.shadow_inference": "shadow_inference_engine_v1.py",
    "research_pipeline.toxic_box": "toxic_box_engine_v1.py",
    "research_pipeline.drift_monitoring": "model_drift_monitoring",
    "research_pipeline.model_summary": "model_assurance",
    "research_pipeline.model_assurance": "model_assurance",
    "research_pipeline.ribbon_extensions": "runtime_supervision",
    "manager": "timeframe_manager",
    "risk": "portfolio_risk",
    "known_limitations": "runtime_supervision",
    "legacy_components": "runtime_supervision",
    "shadow_structural_protection": "shadow_structural",
    "shadow_economic_correlation": "shadow_eqcorr",
    "shadow_stp_be33": "shadow_stp_be33",
    "shadow_auction": "shadow_auction",
    "cross_layer_outcome_reconciliation": "trd_outcome2",
    "debug_snapshot": "context_visualizer",
    "validation_snapshot": "benchmark_reports",
    "validation_report": "benchmark_reports",
    "validation_stage2_5_compare": "benchmark_reports",
    "validation_stage2_5_calibration": "benchmark_reports",
    "validation_conformance_health": "benchmark_reports",
    "validation_export": "benchmark_reports",
    "validation_compare": "benchmark_reports",
    "validation_evolution_snapshot": "benchmark_reports",
    "validation_evolution_report": "benchmark_reports",
    "visual_cognition_snapshot": "context_visualizer",
    "visual_cognition_events": "context_visualizer",
}

def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def utc(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("PUBLICATION_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)

def make_message(section, payload, *, source_ids, observation_at, published_at,
                 delivery_until, producer_state="PUBLISHED", request_key=""):
    if section not in OWNERS:
        raise ValueError("UNKNOWN_SECTION")
    if utc(delivery_until) < utc(published_at):
        raise ValueError("INVALID_DELIVERY_LEASE")
    body = dict(schema_version=SCHEMA, section=section, owner=OWNERS[section],
                observation_at=observation_at, published_at=published_at,
                delivery_until=delivery_until, producer_state=producer_state,
                source_ids=source_ids, request_key=request_key,
                payload_sha256=digest(payload), payload=payload)
    return {**body, "generation_id": digest(body)}

def verify_message(message, section):
    if not isinstance(message, dict):
        raise ValueError("MESSAGE_NOT_OBJECT")
    if message.get("schema_version") != SCHEMA or message.get("section") != section:
        raise ValueError("PUBLICATION_SCHEMA_OR_SECTION")
    if message.get("owner") != OWNERS[section]:
        raise ValueError("PUBLICATION_OWNER")
    if digest(message["payload"]) != message.get("payload_sha256"):
        raise ValueError("PAYLOAD_SHA_MISMATCH")
    body = {k:v for k,v in message.items() if k != "generation_id"}
    if digest(body) != message.get("generation_id"):
        raise ValueError("GENERATION_SHA_MISMATCH")
    if not isinstance(message.get("source_ids"), dict) or not message["source_ids"]:
        raise ValueError("SOURCE_IDENTITY_REQUIRED")
    if utc(message["delivery_until"]) < utc(message["published_at"]):
        raise ValueError("INVALID_DELIVERY_LEASE")
    if message.get("observation_at") is not None and utc(message["observation_at"]) > utc(message["published_at"]):
        raise ValueError("OBSERVATION_AFTER_PUBLICATION")
    return message

def write_message(root, message):
    """Called ONLY by an owner after its normal publication; never by API."""
    verify_message(message, message["section"])
    target = Path(root)/"data/runtime/ops"/(message["section"]+".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = encoded(message)
    if target.exists() and target.read_bytes() == raw:
        return target
    fd, name = tempfile.mkstemp(prefix=target.name+".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(name, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        if os.path.exists(name): os.unlink(name)
    return target


# Fixed routing, never a calculation or a dynamic target supplied by a message.
COLLECTOR_OPERATIONS = {
    'operations.collector.binance_live_feed': ('binance_live_feed', True, 'live_binance_feed_v2.py'),
    'operations.collector.multi_exchange': ('multi_exchange', False, 'multi_exchange_collector.py'),
    'operations.collector.orderbook': ('orderbook', False, 'orderbook_collector.py'),
    'operations.collector.oi': ('oi', False, 'oi_collector.py'),
    'operations.collector.liquidation': ('liquidation', False, 'liquidation_collector.py'),
    'operations.collector.watchdog': ('watchdog', True, 'collector_watchdog.py'),
}
OPERATIONAL_ROUTES = {
    'operations.canonical': {'replace': ('engines','pipeline_engines','pipeline','runtime_failure_audit','runtime_skipped_engine_audit'),
                             'extend': ('processes','warnings')},
    'operations.system': {'replace': ('status_planes',), 'extend': ()},
    'operations.ingress_control': {'replace': ('collectors.level','collectors.native_overall','collectors.last_native_audit_at'), 'extend': ()},
    **{name:{'replace':(), 'extend':('collectors.collectors','collectors.required','collectors.optional','collectors.legacy','processes','warnings')}
       for name in COLLECTOR_OPERATIONS},
}
OWNERS.update({'operations.canonical':'canonical_cycle_coordinator',
               'operations.system':'runtime_dataset_metadata','operations.ingress_control':'collector_watchdog',
               **{key:('collector_watchdog' if row[0]=='watchdog' else 'collector:'+row[0])
                  for key,row in COLLECTOR_OPERATIONS.items()}})

# OPS-04: each financial/execution/risk field has exactly one owner route.
TRADING_ROUTES = {
 'trading.execution': {'replace':('paper','live1b_paper','timeframe_traders.traders'), 'extend':()},
 'trading.financial': {'replace':('financial_performance','timeframe_traders.portfolio'), 'extend':()},
 'trading.manager': {'replace':('manager','timeframe_traders.manager','timeframe_traders.command_bus'), 'extend':()},
 'trading.risk': {'replace':('risk',), 'extend':()},
}
OPERATIONAL_ROUTES.update(TRADING_ROUTES)
OWNERS.update({'trading.execution':'intrabar_paper_manager','trading.financial':'financial_engine_v3',
               'trading.manager':'timeframe_manager','trading.risk':'portfolio_risk'})
