"""Stage 11.1 — real OpsDashboard payload wiring tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.model_summary_sources import MODEL_SUMMARY_SOURCE_VERSION  # noqa: E402
from app.services.research_pipeline_service import build_research_pipeline_snapshot  # noqa: E402


def test_real_research_pipeline_payload_benchmark_primary_v1() -> None:
    """Payload used by GET /api/v1/ops/snapshot → research_pipeline.model_summary."""
    snap = asyncio.run(build_research_pipeline_snapshot())
    summary = snap["model_summary"]
    sources = summary["model_summary_sources"]
    diag = sources["diagnostics_primary"]
    gov = sources["governance"]
    legacy = sources["legacy_monitoring"]

    assert summary.get("model_summary_source_version") == MODEL_SUMMARY_SOURCE_VERSION
    assert snap.get("model_summary_source_version") == MODEL_SUMMARY_SOURCE_VERSION

    assert diag["freshness_status"] == "CURRENT"
    assert diag.get("used_as_primary") is True
    assert "latest_conformance" in str(diag["source_path"])
    assert str(diag["generated_at"]).startswith("2026-07")

    assert gov["status"] == "GOVERNANCE_MISSING"
    assert gov["missing_reason"] == "governance artifact missing"
    assert "model_governance_dashboard.json" in str(gov["source_path"])

    assert legacy["used_as_primary"] is False
    assert "2026-06-14" in str(legacy["timestamp"])
    assert legacy["freshness_status"] in {"STALE", "STALE_VALIDATION"}

    reason = summary.get("attention_reason") or summary.get("status_reason") or ""
    assert summary["status"] == "ATTENTION"
    assert "governance artifact missing" in reason
    assert "benchmark diagnostics current" in reason
    assert summary.get("promotion_eligible_label") == "NO"

    # June PSI must not be current.
    assert summary.get("psi") is None or summary.get("psi_meta", {}).get("metric_is_legacy") is True
    legacy_psi = (summary.get("legacy_metrics") or {}).get("psi") or (summary.get("psi_meta") or {}).get(
        "legacy_value"
    )
    assert legacy_psi is not None
    assert abs(float(legacy_psi) - 0.258) < 0.01 or abs(float(legacy_psi) - 0.2577) < 0.01


def test_frontend_mapper_lines_do_not_primary_june() -> None:
    sources = {
        "diagnostics_primary": {
            "generated_at": "2026-07-11T07:53:14.559449",
            "freshness_status": "CURRENT",
            "source_path": "benchmark/conformance/reports/latest_conformance.json",
            "used_as_primary": True,
        },
        "governance": {
            "status": "GOVERNANCE_MISSING",
            "source_path": "exports/model_governance_dashboard.json",
            "missing_reason": "governance artifact missing",
        },
        "legacy_monitoring": {
            "timestamp": "2026-06-14T18:30:53.329832Z",
            "used_as_primary": False,
            "is_stale": True,
            "freshness_status": "STALE",
        },
    }
    version = "benchmark_primary_v1"
    reason = "governance artifact missing; benchmark diagnostics current"
    lines = [
        f"Data source: {version}",
        f"Latest diagnostics: 2026-07-11 · {sources['diagnostics_primary']['freshness_status']}",
        f"Source: {sources['diagnostics_primary']['source_path']}",
        f"Governance: {sources['governance']['status']}",
        "Legacy monitoring: 2026-06-14 · STALE · not primary",
        "Promotion eligible: NO",
    ]
    joined = "\n".join(lines)
    assert "benchmark_primary_v1" in joined
    assert "CURRENT" in joined
    assert "GOVERNANCE_MISSING" in joined
    assert "not primary" in joined
    assert "Last validation: 14 Jun" not in joined
    assert "Legacy monitoring: 2026-06-14" in joined
    # Stage 11.2: global reason is header-only, not repeated in source lines.
    assert sum(1 for line in lines if reason in line) == 0


def test_real_toxic_box_legacy_only_when_no_fresh_toxic_metrics() -> None:
    snap = asyncio.run(build_research_pipeline_snapshot())
    toxic = snap["toxic_box"]
    ms = snap["model_summary"]

    assert toxic.get("display_status") in {"LEGACY_ONLY", "HISTORICAL_ONLY"}
    assert (toxic.get("current") or {}).get("status") == "MISSING_DATA"
    assert (toxic.get("current") or {}).get("metrics_available") is False
    hist = toxic.get("historical") or {}
    assert hist.get("status") == "STALE"
    assert "toxic_box_memory.parquet" in str(hist.get("source_path") or "")
    assert "2026-06-14" in str(hist.get("timestamp") or "")
    assert "LEGACY_ONLY" in str(toxic.get("severity_label") or "") or "HISTORICAL_ONLY" in str(
        toxic.get("severity_label") or ""
    )

    # Model Summary still July CURRENT + benchmark_primary_v1.
    assert ms.get("model_summary_source_version") == MODEL_SUMMARY_SOURCE_VERSION
    diag = ms["model_summary_sources"]["diagnostics_primary"]
    assert diag["freshness_status"] == "CURRENT"
    assert str(diag["generated_at"]).startswith("2026-07")


def test_ops_payload_includes_valid_model_assurance() -> None:
    from app.services.research_pipeline_service import load_model_assurance_payload

    ma = load_model_assurance_payload()
    snap = asyncio.run(build_research_pipeline_snapshot())
    assert "model_assurance" in snap
    assert snap["model_assurance"].get("overall_assurance_status") == ma.get("overall_assurance_status")
    assert snap["model_assurance"].get("runtime_safety_status") in {
        "SAFE_PAPER_ONLY",
        "UNKNOWN",
        "LIVE_EXECUTION",
        "MISSING_SOURCE",
        "ERROR",
    }
    # Full research pipeline still builds when assurance is present.
    assert snap.get("pipeline") is not None
    assert snap.get("decision_layer") is not None


def test_ops_payload_survives_missing_or_malformed_model_assurance(
    tmp_path: Path, monkeypatch
) -> None:
    import app.services.research_pipeline_service as rps
    from app.config import REPO_ROOT as REAL_REPO_ROOT

    summary_dir = tmp_path / "data" / "model_assurance" / "summary"
    summary_dir.mkdir(parents=True)
    monkeypatch.setattr(rps, "REPO_ROOT", tmp_path)

    ma_missing = rps.load_model_assurance_payload()
    assert ma_missing.get("status") in {"MISSING_SOURCE", "ERROR"}
    assert ma_missing.get("runtime_safety_status") == "UNKNOWN"
    assert ma_missing.get("error_reason")

    bad = summary_dir / "latest_summary.json"
    bad.write_text("{not-json", encoding="utf-8")
    ma_bad = rps.load_model_assurance_payload()
    assert ma_bad.get("status") in {"MISSING_SOURCE", "ERROR"}
    assert ma_bad.get("error_reason")

    # Endpoint assembly must still succeed when assurance loader returns ERROR.
    monkeypatch.setattr(rps, "REPO_ROOT", REAL_REPO_ROOT)
    monkeypatch.setattr(
        rps,
        "load_model_assurance_payload",
        lambda: {
            "status": "ERROR",
            "overall_assurance_status": "ERROR",
            "runtime_safety_status": "UNKNOWN",
            "error_reason": "forced test error",
            "missing_sources": ["latest_summary"],
            "stale_sources": [],
            "promotion_blockers": [],
            "environment_blockers": [],
            "current_blockers": [],
            "current_incidents": [],
            "current_toxic_events": [],
        },
    )
    snap = asyncio.run(rps.build_research_pipeline_snapshot())
    assert snap["model_assurance"]["status"] == "ERROR"
    assert snap.get("pipeline") is not None
    assert snap.get("decision_layer") is not None


def test_model_assurance_payload_is_json_serializable() -> None:
    import json
    from app.services.research_pipeline_service import load_model_assurance_payload

    ma = load_model_assurance_payload()
    encoded = json.dumps(ma, allow_nan=False)
    assert isinstance(encoded, str)
    roundtrip = json.loads(encoded)
    assert isinstance(roundtrip, dict)
