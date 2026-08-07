"""Stage 13 — Ops health dimensions semantics."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.monitoring_kpis import (  # noqa: E402
    build_health_dimensions,
    classify_blocking_stalls,
    derive_system_health_level,
    resource_health_status,
    toxic_severity_level,
)
from app.services.ops_monitor import build_ops_snapshot, build_pipeline_status  # noqa: E402
from app.services.research_pipeline_service import (  # noqa: E402
    build_model_governance_snapshot,
    build_shadow_inference_snapshot,
    build_toxic_box_snapshot,
)


def test_runtime_healthy_research_attention() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    dims = snap["health_dimensions"]
    gov = snap["research_pipeline"]["model_governance"]["governance_status"]
    assert dims["runtime"]["status"] in {"OPERATIONAL", "DEGRADED", "CRITICAL"}
    if gov == "GOVERNANCE_MISSING" and dims["runtime"]["failed_engine_count"] == 0:
        assert dims["runtime"]["status"] == "OPERATIONAL"
        assert snap["health"]["level"] == "HEALTHY"
        assert str(snap["health"].get("display_status") or "OPERATIONAL").upper() in {
            "OPERATIONAL",
            "OPERATIONAL_WITH_LIMITATIONS",
            "HEALTHY_WITH_KNOWN_LIMITATIONS",
        }
        assert not str(snap["health"].get("primary_reason") or "").startswith("Resource warning:")
        assert dims["research_validation"]["status"] in {
            "ATTENTION",
            "RESEARCH_INCOMPLETE",
            "INCOMPLETE",
        }


def test_historical_failures_not_active() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    audit = snap["runtime_failure_audit"]
    dims = snap["health_dimensions"]
    if int(audit.get("total_count") or 0) > 0 and int(audit.get("active_count") or 0) == 0:
        assert dims["runtime"]["current_failures_count"] == 0
        assert dims["historical_audit"]["historical_failures_count"] > 0
        assert dims["historical_audit"]["status"] in {"INFORMATIONAL", "ATTENTION"}
        assert audit.get("affects_health") is False


def test_historical_stall_not_current_lagging() -> None:
    pipeline = asyncio.run(build_pipeline_status())
    current = int(pipeline.get("current_stalls_timeouts") or 0)
    historical = int(pipeline.get("historical_stalls_timeouts") or 0)
    assert pipeline.get("stalled_engine_count") == pipeline.get("current_stalled_engine_count")
    if historical > 0 and int(pipeline.get("timeout_count") or 0) == 0:
        assert current == 0


def test_classify_blocking_stalls_window() -> None:
    events = [
        {"timestamp": "2026-07-13T05:40:00Z", "event": "TIMEOUT"},
        {"timestamp": "2026-07-13T10:35:00Z", "event": "STALL_DETECTED"},
    ]
    now = 1_783_939_200.0  # 2026-07-13T10:40:00Z
    out = classify_blocking_stalls(events, now=now, window_s=15 * 60)
    assert out["current_count"] == 1
    assert out["historical_count"] == 1


def test_active_stall_marks_system_degraded() -> None:
    dims = build_health_dimensions(
        runtime_status="DEGRADED",
        runtime_reason="active stall detected",
        current_failures_count=0,
        failed_engine_count=0,
        required_datasets_stale_count=0,
        collectors_status="Receiving Data",
        websocket_status="Receiving Data",
        pipeline_status="Running",
        resources=resource_health_status(cpu_pct=10, memory_pct=40, disk_pct=20),
        research_status="ATTENTION",
        research_reason="governance missing",
        governance_status="GOVERNANCE_MISSING",
        economic_status="STALE_VALIDATION / HISTORICAL",
        shadow_status="MISSING_DATA",
        toxic_status="LEGACY_ONLY / STALE",
        historical_failures_count=10,
        historical_stalls_count=0,
        latest_historical_failure_at=None,
        latest_historical_stall_at=None,
        historical_reason="none",
    )
    level, suffix = derive_system_health_level(
        runtime_status=dims["runtime"]["status"],
        resources_status=dims["resources"]["status"],
    )
    assert level == "DEGRADED"
    assert suffix in {None, "DEGRADED"}


def test_toxic_legacy_not_elevated() -> None:
    toxic = asyncio.run(build_toxic_box_snapshot())
    assert toxic.get("display_status") in {
        "LEGACY_ONLY",
        "HISTORICAL_ONLY",
        "MISSING_DATA",
        "CURRENT",
    }
    if toxic.get("display_status") in {"LEGACY_ONLY", "HISTORICAL_ONLY"}:
        label = str(toxic.get("severity_label") or "").upper()
        assert "LEGACY" in label or "HISTORICAL" in label
        assert "Elevated" not in str(toxic.get("severity_label") or "")
        assert toxic.get("level") == "GREY"
    ribbon_toxic = next(
        item
        for item in asyncio.run(build_ops_snapshot(lite=False))["ribbon"]
        if item["key"] == "toxic_box"
    )
    assert "Elevated" not in str(ribbon_toxic.get("value") or "")
    ribbon_val = str(ribbon_toxic.get("value") or "").upper()
    assert (
        "LEGACY" in ribbon_val
        or "HISTORICAL" in ribbon_val
        or ribbon_toxic["value"] == "MISSING_DATA"
    )


def test_toxic_current_elevated_threshold() -> None:
    level, label = toxic_severity_level(
        events_last_7d=20,
        events_last_30d=30,
        trend="UP",
        hours_since_last_routed=1.0,
        is_bulk_backfill=False,
    )
    assert level == "YELLOW"
    assert label == "Elevated"


def test_economic_stale_not_runtime() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    eco = snap["research_pipeline"]["economic_validation"]
    dims = snap["health_dimensions"]
    if eco.get("freshness", {}).get("is_stale"):
        assert "STALE" in dims["research_validation"]["economic_status"].upper()
        if dims["runtime"]["failed_engine_count"] == 0 and dims["runtime"]["current_failures_count"] == 0:
            assert dims["runtime"]["status"] == "OPERATIONAL"
        ribbon_eco = next(item for item in snap["ribbon"] if item["key"] == "economic_validation")
        assert "STALE_VALIDATION" in str(ribbon_eco.get("value") or "")


def test_shadow_missing_not_runtime() -> None:
    shadow = asyncio.run(build_shadow_inference_snapshot())
    snap = asyncio.run(build_ops_snapshot(lite=False))
    dims = snap["health_dimensions"]
    if shadow.get("validation_status") in {"MISSING_DATA", "MISSING"}:
        assert dims["research_validation"]["shadow_status"] == "MISSING_DATA"
        if dims["runtime"]["failed_engine_count"] == 0:
            assert dims["runtime"]["status"] == "OPERATIONAL"


def test_governance_missing_not_runtime() -> None:
    gov = asyncio.run(build_model_governance_snapshot())
    snap = asyncio.run(build_ops_snapshot(lite=False))
    dims = snap["health_dimensions"]
    assert gov["governance_status"] == "GOVERNANCE_MISSING"
    assert gov["promotion_eligible_label"] == "NO"
    assert dims["research_validation"]["governance_status"] == "GOVERNANCE_MISSING"
    if dims["runtime"]["failed_engine_count"] == 0:
        assert dims["runtime"]["status"] == "OPERATIONAL"


def test_frontend_mapper_source_guards() -> None:
    mappers = (ROOT / "dashboard/frontend/src/components/status/mappers.ts").read_text(encoding="utf-8")
    research = (ROOT / "dashboard/frontend/src/components/status/researchMappers.ts").read_text(encoding="utf-8")
    dashboard_entry = (ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx").read_text(
        encoding="utf-8"
    )
    dashboard = (ROOT / "dashboard/frontend/src/components/ops/OpsUnifiedDashboard.tsx").read_text(
        encoding="utf-8"
    )

    assert "resolveRuntimeStability" in mappers
    assert "resolveHealthDimensionStatus" in mappers
    assert "HISTORICAL ONLY" in research or "LEGACY_ONLY" in research
    assert "STALE_VALIDATION" in research or "HISTORICAL / STALE" in research
    assert "OpsUnifiedDashboard" in dashboard_entry
    assert "Historical Audit" in dashboard
    assert "Research / Validation" in dashboard or "Model Assurance" in dashboard
    assert "Legacy Paper Controller" in dashboard or "Paper Controller" in dashboard
    assert "NOT_IN_CANONICAL_RUNTIME" in dashboard or "Legacy / Excluded" in dashboard
    assert 'translateStallCount(stallCount)' not in dashboard
    assert "Stalls & timeouts" not in dashboard or "Current stalls" in dashboard
