"""Hotfix — resources must not roll into System/model health; research ≠ Degraded."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.monitoring_kpis import (  # noqa: E402
    build_health_dimensions,
    derive_system_health_level,
    resource_health_status,
)

MAPPERS = ROOT / "dashboard/frontend/src/components/status/mappers.ts"
OPS_DASHBOARD = ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx"
OPS_MONITOR = ROOT / "dashboard/backend/app/services/ops_monitor.py"


def _dims(*, runtime: str = "OPERATIONAL", memory: float = 84.0, research: str = "ATTENTION"):
    resources = resource_health_status(cpu_pct=20.0, memory_pct=memory, disk_pct=30.0)
    return build_health_dimensions(
        runtime_status=runtime,
        runtime_reason="Required runtime infrastructure nominal",
        current_failures_count=0,
        failed_engine_count=0,
        required_datasets_stale_count=0,
        collectors_status="Receiving Data",
        websocket_status="Receiving Data",
        pipeline_status="Running",
        resources=resources,
        research_status=research,
        research_reason="governance artifact missing; economic validation stale",
        governance_status="GOVERNANCE_MISSING",
        economic_status="STALE_VALIDATION / HISTORICAL",
        shadow_status="MISSING_DATA",
        toxic_status="LEGACY_ONLY / STALE",
        historical_failures_count=10,
        historical_stalls_count=1,
        latest_historical_failure_at=None,
        latest_historical_stall_at=None,
        historical_reason="Historical events present",
    )


def test_memory_84_runtime_healthy_system_operational():
    dims = _dims(memory=84.0)
    assert dims["resources"]["memory_pct"] == 84.0
    assert dims["resources"]["status"] in {"DEGRADED", "CRITICAL"}
    assert "Resource warning: memory" in str(dims["resources"]["reason"])
    level, suffix = derive_system_health_level(
        runtime_status=dims["runtime"]["status"],
        resources_status=dims["resources"]["status"],
    )
    assert dims["runtime"]["status"] == "OPERATIONAL"
    assert level == "HEALTHY"
    assert suffix is None


def test_memory_95_runtime_healthy_system_still_operational():
    dims = _dims(memory=95.0)
    assert dims["resources"]["memory_pct"] == 95.0
    level, suffix = derive_system_health_level(
        runtime_status=dims["runtime"]["status"],
        resources_status=dims["resources"]["status"],
    )
    assert level == "HEALTHY"
    assert suffix is None
    assert dims["runtime"]["status"] == "OPERATIONAL"


def test_research_incompleteness_is_attention_not_degraded():
    dims = _dims(research="ATTENTION")
    assert dims["research_validation"]["status"] in {"ATTENTION", "INCOMPLETE", "STALE", "MISSING_DATA"}
    assert dims["research_validation"]["status"] != "DEGRADED"
    level, _ = derive_system_health_level(
        runtime_status=dims["runtime"]["status"],
        resources_status=dims["resources"]["status"],
    )
    assert level == "HEALTHY"
    assert dims["runtime"]["status"] == "OPERATIONAL"


def test_current_runtime_failure_still_degrades():
    dims = _dims(runtime="DEGRADED", memory=40.0, research="ATTENTION")
    level, suffix = derive_system_health_level(
        runtime_status=dims["runtime"]["status"],
        resources_status=dims["resources"]["status"],
    )
    assert level == "DEGRADED"
    assert suffix is None


def test_frontend_forbidden_resource_rollup_and_research_degraded_labels():
    mappers = MAPPERS.read_text(encoding="utf-8")
    ops_dash = OPS_DASHBOARD.read_text(encoding="utf-8")
    backend = OPS_MONITOR.read_text(encoding="utf-8")

    # System health mapper must not paint resource warnings as Degraded.
    assert 'display === "OPERATIONAL_WITH_WARNINGS"' in mappers or "OPERATIONAL_WITH_WARNINGS" in mappers
    assert 'label: "Operational · Resource Warning"' not in mappers
    assert re.search(
        r'OPERATIONAL_WITH_WARNINGS[\s\S]{0,120}system\("operational"',
        mappers,
    ) or 'return system("operational", "operational")' in mappers

    # Research dimension ATTENTION must label ATTENTION/INCOMPLETE, not Degraded.
    assert 'label: "ATTENTION"' in mappers or 'label = token === "INCOMPLETE" ? "INCOMPLETE" : "ATTENTION"' in mappers
    assert "attention_required" in mappers

    # OpsDashboard wires research through translateHealthDimensionStatus.
    assert "translateHealthDimensionStatus(dimensions.research_validation.status)" in ops_dash

    # Backend must not promote resource reason into top health.
    assert 'health["primary_reason"] = resource_reason' not in backend
    assert "Host memory critical" not in backend


def test_derive_ignores_resource_critical():
    level, suffix = derive_system_health_level(
        runtime_status="OPERATIONAL",
        resources_status="CRITICAL",
    )
    assert level == "HEALTHY"
    assert suffix is None
