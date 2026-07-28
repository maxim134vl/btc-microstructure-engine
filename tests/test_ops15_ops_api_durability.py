"""OPS1.5 — durable OPS API control + endpoint survival tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
SCRIPTS = BACKEND / "scripts"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ops_api_ctl as ctl  # noqa: E402
from app.main import app  # noqa: E402
from app.services import research_pipeline_service as rps  # noqa: E402
from app.services.ops_monitor import build_ops_snapshot  # noqa: E402


def test_ops_snapshot_http_200_via_test_client() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    snap = client.get("/api/v1/ops/snapshot")
    assert snap.status_code == 200
    body = snap.json()
    assert body.get("generated_at")
    assert body.get("health") is not None or body.get("overall_health") is not None
    assert body.get("processes") is not None or body.get("runtime_truth") is not None
    assert body.get("research_pipeline") is not None
    rp = body["research_pipeline"]
    assert rp.get("model_assurance") is not None or body.get("model_assurance") is not None
    assert rp.get("decision_layer") is not None
    # trading / context presentation planes
    assert body.get("runtime_truth") is not None or body.get("context_chain") is not None
    assert body.get("context_chain") is not None or rp.get("decision_layer") is not None


def test_optional_section_error_does_not_kill_endpoint(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import app.services.ops_monitor as ops_monitor

    monkeypatch.setattr(
        rps,
        "load_model_assurance_payload",
        lambda: {
            "status": "ERROR",
            "overall_assurance_status": "ERROR",
            "runtime_safety_status": "UNKNOWN",
            "error_reason": "forced_ops15_section_error",
            "missing_sources": ["latest_summary"],
            "stale_sources": [],
            "promotion_blockers": [],
            "environment_blockers": [],
            "current_blockers": [],
            "current_incidents": [],
            "current_toxic_events": [],
        },
    )
    ops_monitor._OPS_SNAPSHOT_CACHE.clear()
    ops_monitor._RESEARCH_CACHE["ts"] = 0.0
    ops_monitor._RESEARCH_CACHE["data"] = None
    client = TestClient(app)
    resp = client.get("/api/v1/ops/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    ma = (body.get("research_pipeline") or {}).get("model_assurance") or body.get("model_assurance")
    assert ma is not None
    assert ma.get("status") == "ERROR" or ma.get("overall_assurance_status") == "ERROR"
    assert ma.get("error_reason") == "forced_ops15_section_error"
    assert body.get("generated_at")
    assert body.get("research_pipeline", {}).get("decision_layer") is not None


def test_ops_snapshot_payload_json_serializable() -> None:
    snap = asyncio.run(build_ops_snapshot(ws_connected=False, lite=True))
    encoded = json.dumps(snap, allow_nan=False, default=str)
    assert isinstance(encoded, str)
    roundtrip = json.loads(encoded)
    assert isinstance(roundtrip, dict)
    assert roundtrip.get("generated_at")


def test_stale_pid_file_detected_and_cleared(tmp_path: Path) -> None:
    pid_file = tmp_path / "ops_api.pid"
    pid_file.write_text("99999999\n", encoding="utf-8")
    resolved = ctl.resolve_managed_pid(pid_file)
    assert resolved["pid"] == 99999999
    assert resolved["alive"] is False
    assert resolved["stale_pid_file"] is True
    assert resolved["note"] == "stale_pid_process_missing"

    cleared = ctl.clear_stale_pid_file(pid_file)
    assert cleared["cleared"] is True
    assert not pid_file.exists()
