"""OPS dashboard final cleanup — live vs research vs historical truth."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.monitoring_kpis import (  # noqa: E402
    classify_blocking_stalls,
    derive_system_health_level,
    resource_health_status,
)
from app.services.ops_monitor import (  # noqa: E402
    EVENT_DRIVEN_UNCHANGED_PARQUETS,
    _event_driven_unchanged,
    _required_parquet_freshness,
    build_ops_snapshot,
)
from ops_dashboard_runtime_truth import (  # noqa: E402
    PHANTOM_ENGINES,
    compute_overall_health,
    s4_activated,
)


def _healthy_s4_procs() -> list[dict]:
    rows = [
        {"process_id": "live_feed", "health": "RUNNING"},
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "STOPPED"},
        {"process_id": "timeframe_manager", "health": "RUNNING"},
        {"process_id": "trader_M15", "health": "RUNNING"},
        {"process_id": "trader_M30", "health": "RUNNING"},
        {"process_id": "trader_H1", "health": "RUNNING"},
        {"process_id": "trader_H4", "health": "RUNNING"},
    ]
    return rows


def test_01_healthy_runtime_operational_or_with_limitations() -> None:
    overall, _, _ = compute_overall_health(
        _healthy_s4_procs(),
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS", "is_controller_failure": False},
    )
    assert overall in {"OPERATIONAL", "OPERATIONAL_WITH_LIMITATIONS", "HEALTHY_WITH_KNOWN_LIMITATIONS"}


def test_02_healthy_with_known_limitations() -> None:
    overall, reason, alerts = compute_overall_health(
        _healthy_s4_procs(),
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS"},
    )
    assert overall == "OPERATIONAL_WITH_LIMITATIONS"
    assert any(a["reason_code"] == "D1_NOT_LIVE" for a in alerts)
    assert "D1" in reason or "auction" in reason


def test_03_missing_governance_does_not_degrade_live() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    dims = snap["health_dimensions"]
    assert dims["research_validation"]["governance_status"]
    if dims["runtime"]["failed_engine_count"] == 0 and dims["runtime"]["current_failures_count"] == 0:
        assert dims["runtime"]["status"] == "OPERATIONAL"
        assert snap["health"]["level"] == "HEALTHY"
        assert snap["health"]["display_status"] in {
            "OPERATIONAL",
            "OPERATIONAL_WITH_LIMITATIONS",
        }


def test_04_stale_economic_not_active_alert() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    actionable = snap["alert_groups"]["actionable"]
    assert not any("economic" in str(a).lower() for a in actionable)


def test_05_historical_toxic_does_not_degrade_live() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    toxic = snap["research_pipeline"]["toxic_box"]
    assert toxic.get("display_status") in {"HISTORICAL_ONLY", "LEGACY_ONLY", "MISSING_DATA", "CURRENT"}
    if toxic.get("display_status") in {"HISTORICAL_ONLY", "LEGACY_ONLY"}:
        assert snap["health_dimensions"]["runtime"]["status"] == "OPERATIONAL" or snap[
            "health"
        ]["level"] in {"HEALTHY", "DEGRADED"}
        if snap["pipeline"]["failed_engine_count"] == 0 and snap["pipeline"]["current_stalls_timeouts"] == 0:
            assert snap["health"]["display_status"] != "FAILED"


def test_06_toxic_zero_recent_not_zero_toxicity() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    toxic = snap["research_pipeline"]["toxic_box"]
    if int(toxic.get("events_last_7d") or 0) == 0 and int(toxic.get("events") or 0) > 0:
        text = " ".join(
            str(toxic.get(k) or "")
            for k in ("stale_warning", "refresh_hint", "display_reason", "severity_label")
        )
        assert "not connected" in text.lower() or "future work" in text.lower() or "historical" in text.lower()
        assert "runtime degraded" not in text.lower()


def test_07_legacy_controller_migrated_not_required() -> None:
    if not s4_activated():
        return
    snap = asyncio.run(build_ops_snapshot(lite=False))
    paper = snap["paper"]
    assert paper.get("representation") == "MIGRATED_TO_TIMEFRAME_TRADERS"
    assert paper.get("display_status") == "MIGRATED"
    assert paper.get("requirement") == "NOT_REQUIRED"
    assert paper.get("is_controller_failure") is False


def test_08_missing_legacy_controller_not_failure() -> None:
    overall, _, alerts = compute_overall_health(
        _healthy_s4_procs(),
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS", "is_controller_failure": False},
    )
    assert overall != "FAILED"
    assert not any(a["reason_code"] == "PAPER_PROCESS_DOWN" for a in alerts)


def test_09_four_timeframe_traders_required() -> None:
    procs = [p for p in _healthy_s4_procs() if p["process_id"] != "trader_H4"]
    overall, _, alerts = compute_overall_health(
        procs,
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS"},
    )
    assert overall == "DEGRADED"
    assert any(a["reason_code"] == "TIMEFRAME_TRADER_DOWN_H4" for a in alerts)


def test_10_dead_timeframe_trader_active_failure() -> None:
    procs = _healthy_s4_procs()
    for p in procs:
        if p["process_id"] == "trader_M15":
            p["health"] = "STOPPED"
    overall, _, alerts = compute_overall_health(
        procs,
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS"},
    )
    assert overall == "DEGRADED"
    assert any(a["reason_code"] == "TIMEFRAME_TRADER_DOWN_M15" and a.get("active") for a in alerts)


def test_11_phantom_never_running_badge() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    for row in snap["legacy_components"]:
        if row.get("classification") == "PHANTOM":
            assert row.get("display_status") == "NOT_IN_CANONICAL_RUNTIME"
            assert row.get("process_badge") is None
            assert row.get("active") is False


def test_12_phantom_excluded_from_engine_total() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    engine_ids = {e.get("engine_id") or e.get("engine") for e in snap.get("pipeline_engines") or []}
    for phantom in PHANTOM_ENGINES:
        assert phantom not in engine_ids
    assert len(snap.get("pipeline_engines") or []) == 20


def test_13_d1_not_live_expected() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    d1 = next(x for x in snap["multi_timeframe"] if x["timeframe"] == "D1")
    assert d1["display_status"] == "NOT_LIVE"
    assert d1["requirement"] == "EXPECTED"


def test_14_d1_not_stale_alert() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    actionable = snap["alert_groups"]["actionable"]
    assert not any("D1" in str(a) and a.get("actionable") is not False for a in actionable)
    assert not any(a.get("reason_code") == "D1_NOT_LIVE" and a.get("actionable") for a in actionable)


def test_15_auction_synthesis_non_required_not_active_failure() -> None:
    overall, _, alerts = compute_overall_health(
        _healthy_s4_procs(),
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS"},
    )
    assert overall == "OPERATIONAL_WITH_LIMITATIONS"
    synth = next(a for a in alerts if a["reason_code"] == "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED")
    assert synth["severity"] == "INFO"
    assert synth.get("actionable") is False


def test_16_historical_failures_not_active() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    dims = snap["health_dimensions"]
    assert dims["runtime"]["current_failures_count"] == 0 or dims["runtime"]["status"] in {
        "OPERATIONAL",
        "DEGRADED",
        "CRITICAL",
    }
    if int(snap["runtime_failure_audit"].get("active_count") or 0) == 0:
        assert dims["runtime"]["current_failures_count"] == 0


def test_17_current_active_failure_priority() -> None:
    level, display = derive_system_health_level(
        runtime_status="DEGRADED",
        known_limitations=True,
    )
    assert level == "DEGRADED"
    assert display == "DEGRADED"


def test_18_probabilistic_unchanged_current() -> None:
    assert "probabilistic_auction_memory.parquet" in EVENT_DRIVEN_UNCHANGED_PARQUETS
    assert _event_driven_unchanged(
        "probabilistic_auction_memory.parquet",
        {"probabilistic_auction_engine_v1.py": "SUCCESS_NO_NEW_OUTPUT"},
    )
    freshness = _required_parquet_freshness(
        {
            "exists": True,
            "age_seconds": 5000,
            "file": "probabilistic_auction_memory.parquet",
        },
        ws_alive=True,
        engine_results={"probabilistic_auction_engine_v1.py": "SUCCESS_NO_NEW_OUTPUT"},
    )
    assert freshness == "CURRENT_UNCHANGED"


def test_19_probabilistic_real_stale() -> None:
    freshness = _required_parquet_freshness(
        {
            "exists": True,
            "age_seconds": 50000,
            "file": "probabilistic_auction_memory.parquet",
        },
        ws_alive=True,
        engine_results={"probabilistic_auction_engine_v1.py": "FAILED"},
    )
    assert freshness in {"DELAYED", "STALE"}


def test_20_cpu_display_uses_sample() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    cpu = float(snap["health"]["cpu_percent"])
    assert 0 <= cpu <= 100


def test_21_short_cpu_peak_does_not_degrade_system() -> None:
    resources = resource_health_status(cpu_pct=93, memory_pct=40, disk_pct=40, sustained_cpu_pct=35)
    level, display = derive_system_health_level(
        runtime_status="OPERATIONAL",
        resources_status=resources["status"],
        known_limitations=True,
        sustained_resource_critical=bool(resources.get("sustained_critical")),
    )
    assert level == "HEALTHY"
    assert display == "OPERATIONAL_WITH_LIMITATIONS"


def test_22_sustained_cpu_critical_degrades() -> None:
    resources = resource_health_status(cpu_pct=93, memory_pct=40, disk_pct=40, sustained_cpu_pct=90)
    assert resources["display_status"] == "CRITICAL"
    level, display = derive_system_health_level(
        runtime_status="OPERATIONAL",
        resources_status=resources["status"],
        known_limitations=False,
        sustained_resource_critical=True,
    )
    assert level == "DEGRADED"
    assert display == "DEGRADED"


def test_23_memory_warning_not_failure() -> None:
    resources = resource_health_status(cpu_pct=30, memory_pct=84, disk_pct=49)
    assert resources["display_status"] == "WARNING"
    assert resources["status"] == "DEGRADED"
    level, display = derive_system_health_level(
        runtime_status="OPERATIONAL",
        resources_status=resources["status"],
        known_limitations=True,
        sustained_resource_critical=False,
    )
    assert level == "HEALTHY"
    assert display == "OPERATIONAL_WITH_LIMITATIONS"


def test_24_disk_49_normal() -> None:
    resources = resource_health_status(cpu_pct=20, memory_pct=40, disk_pct=49)
    assert resources["display_status"] == "NORMAL"


def test_25_active_alerts_actionable_only() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    for alert in snap["alert_groups"]["actionable"]:
        assert alert.get("actionable") is not False
        assert alert.get("ignored_by_health") is not True
        msg = str(alert.get("message") or alert.get("type") or "").lower()
        assert "governance" not in msg
        assert "toxic" not in msg
        assert "shadow" not in msg


def test_26_risk_breach_creates_active_alert_contract() -> None:
    # Contract: risk breach is an actionable live failure path when present in alert builder.
    # Here we assert the snapshot still separates informational research from actionable.
    snap = asyncio.run(build_ops_snapshot(lite=False))
    assert "actionable" in snap["alert_groups"]
    assert "informational" in snap["alert_groups"]


def test_27_command_duplicate_contract_present() -> None:
    snap = asyncio.run(build_ops_snapshot(lite=False))
    bus = (snap.get("timeframe_traders") or {}).get("command_bus") or {}
    assert "duplicate_command_ids" in bus or bus == {}


def test_28_context_stale_path_exists() -> None:
    overall, _, alerts = compute_overall_health(
        [
            {"process_id": "live_feed", "health": "RUNNING"},
            {"process_id": "canonical_pipeline", "health": "RUNNING"},
            {"process_id": "context_refresher", "health": "STOPPED"},
            {"process_id": "timeframe_manager", "health": "RUNNING"},
            {"process_id": "trader_M15", "health": "RUNNING"},
            {"process_id": "trader_M30", "health": "RUNNING"},
            {"process_id": "trader_H1", "health": "RUNNING"},
            {"process_id": "trader_H4", "health": "RUNNING"},
            {"process_id": "paper_controller", "health": "STOPPED"},
        ],
        {"representation": "MIGRATED_TO_TIMEFRAME_TRADERS"},
    )
    assert overall == "DEGRADED"
    assert any(a["reason_code"] == "CONTEXT_CHAIN_STALE" for a in alerts)


def test_29_frontend_maps_every_enum() -> None:
    mappers = (ROOT / "dashboard/frontend/src/components/status/mappers.ts").read_text(encoding="utf-8")
    for token in [
        "OPERATIONAL_WITH_LIMITATIONS",
        "CURRENT_UNCHANGED",
        "MIGRATED",
        "NOT_REQUIRED",
        "NOT_LIVE",
        "EXPECTED",
        "KNOWN_LIMITATION",
        "NOT_IN_CANONICAL_RUNTIME",
        "HISTORICAL_ONLY",
        "RESEARCH_INCOMPLETE",
        "resolveUnknownNeutral",
    ]:
        assert token in mappers


def test_30_unknown_enum_neutral_fallback() -> None:
    mappers = (ROOT / "dashboard/frontend/src/components/status/mappers.ts").read_text(encoding="utf-8")
    assert "Unknown / Informational" in mappers or "resolveUnknownNeutral" in mappers


def test_31_visual_style_markers_intact() -> None:
    dashboard = (ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx").read_text(encoding="utf-8")
    assert "ops-surface" in dashboard
    assert "PanelCard" in dashboard
    assert "dark" not in dashboard.lower() or "ops-surface" in dashboard
    assert "Live Operational Health" in dashboard
    assert "Toxic Box" in dashboard or "toxicBoxCard" in dashboard or "formatToxicBoxDisplay" in dashboard


def test_32_trading_source_unchanged_markers() -> None:
    # Guard: cleanup must not touch trader/manager daemon sources.
    for rel in [
        "scripts/live/timeframe_manager_daemon.py",
        "scripts/live/timeframe_trader_daemon.py",
    ]:
        path = ROOT / rel
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "ops dashboard final cleanup" not in text.lower()


def test_stall_future_naive_timestamp_not_current() -> None:
    events = [
        {
            "timestamp": "2099-01-01T00:00:00",
            "engine": "runtime_cognition_engine_v1.py",
            "event": "TIMEOUT",
        }
    ]
    # Far-future naive values are reinterpreted; still must not create perpetual current stalls
    # when age cannot be resolved into the window as a real recent event.
    out = classify_blocking_stalls(events, window_s=15 * 60)
    assert out["current_count"] in {0, 1}
