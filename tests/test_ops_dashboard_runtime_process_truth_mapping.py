from __future__ import annotations

import json
from datetime import datetime, timezone

import ops_dashboard_runtime_truth as truth


def _install_collector_contract(tmp_path, monkeypatch, *, pid=4242, connected=True):
    registry = tmp_path / "collector_pids.json"
    heartbeats = tmp_path / "collector_heartbeats"
    manifest = tmp_path / "required_runtime_components.yaml"
    heartbeats.mkdir()
    registry.write_text(json.dumps({"binance_live_feed": pid}), encoding="utf-8")
    (heartbeats / "binance_live_feed.json").write_text(
        json.dumps(
            {
                "collector": "binance_live_feed",
                "status": "CONNECTED" if connected else "DISCONNECTED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        "REQUIRED_COLLECTORS:\n"
        "  - binance_live_feed\n"
        "REQUIRED_ENGINES:\n"
        "  - runtime_cognition_engine_v1.py\n"
        "THRESHOLDS:\n"
        "  collector_ws: 120\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(truth, "COLLECTOR_PID_REGISTRY_PATH", registry)
    monkeypatch.setattr(truth, "COLLECTOR_HEARTBEAT_DIR", heartbeats)
    monkeypatch.setattr(truth, "REQUIRED_RUNTIME_COMPONENTS_PATH", manifest)


def test_running_required_binance_collector_is_not_failed(tmp_path, monkeypatch):
    _install_collector_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(
        truth,
        "_ps_lines",
        lambda: [
            "4242 1 00:10 /repo/venv/bin/python /repo/live_binance_feed_v2.py",
            "5000 1 00:10 /repo/venv/bin/python run.py",
        ],
    )
    rows = truth.inspect_processes()
    feed = next(row for row in rows if row["process_id"] == "live_feed")
    assert feed["health"] == "RUNNING"
    assert feed["required"] is True
    assert feed["health_reason"] == "collector_registry_pid_and_heartbeat_healthy"


def test_missing_optional_legacy_context_refresher_is_not_critical():
    processes = [
        {"process_id": "live_feed", "health": "RUNNING", "required": True},
        {"process_id": "canonical_pipeline", "health": "RUNNING", "required": True},
        {"process_id": "context_refresher", "health": "STOPPED", "required": False},
        {"process_id": "paper_controller", "health": "RUNNING", "required": False},
    ]
    overall, _, alerts = truth.compute_overall_health(
        processes, {"representation": "RUNNING_NO_ELIGIBLE_TRADE"}
    )
    assert overall != "FAILED"
    assert not any(alert["reason_code"] == "CONTEXT_CHAIN_STALE" for alert in alerts)


def test_missing_required_collector_still_fails(tmp_path, monkeypatch):
    _install_collector_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(truth, "_ps_lines", lambda: [])
    rows = truth.inspect_processes()
    feed = next(row for row in rows if row["process_id"] == "live_feed")
    assert feed["health"] == "STOPPED"
    assert feed["required"] is True
    overall, _, alerts = truth.compute_overall_health(
        rows, {"representation": "RUNNING_NO_ELIGIBLE_TRADE"}
    )
    assert overall == "FAILED"
    assert any(alert["reason_code"] == "FEED_DOWN" for alert in alerts)


def test_canonical_pipeline_ps_mapping_is_unchanged(tmp_path, monkeypatch):
    _install_collector_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(
        truth,
        "_ps_lines",
        lambda: [
            "4242 1 00:10 /repo/venv/bin/python /repo/live_binance_feed_v2.py",
            "5000 1 00:10 /repo/venv/bin/python run.py",
        ],
    )
    rows = truth.inspect_processes()
    pipeline = next(row for row in rows if row["process_id"] == "canonical_pipeline")
    assert pipeline["health"] == "RUNNING"
    assert pipeline["required"] is True
    assert pipeline["command"].endswith("run.py")
