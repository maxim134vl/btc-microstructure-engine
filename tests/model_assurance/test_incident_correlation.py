"""Minimal MODEL-5 incident correlation tests."""

from __future__ import annotations

import json
from pathlib import Path

from btc_ml.model_assurance.toxic_box import incident_correlation as ic
from btc_ml.model_assurance.toxic_box.common import read_jsonl


ACTIVE = {
    "registry_record_id": "REG",
    "model_id": "M",
    "model_version": "V1",
    "runtime_fingerprint": "fp",
    "paper_epoch_id": "EPOCH",
    "paper_only": True,
    "real_execution": False,
}

SOURCES = {
    "BINANCE_SPOT_BTCUSDT_AGGTRADE": {
        "source_id": "BINANCE_SPOT_BTCUSDT_AGGTRADE",
        "required_for": ["LIVE1A_CONTEXT", "CONTEXT_EVENT_PRICE", "TP_SL_MONITORING"],
    },
    "BINANCE_SPOT_BTCUSDT_BOOKTICKER": {
        "source_id": "BINANCE_SPOT_BTCUSDT_BOOKTICKER",
        "required_for": ["LIVE1B_EXECUTION"],
    },
    "BINANCE_SPOT_BTCUSDT_M15_KLINE": {
        "source_id": "BINANCE_SPOT_BTCUSDT_M15_KLINE",
        "required_for": ["COMPLETED_BAR_STRUCTURAL_BACKGROUND"],
    },
}


def _ctx(**kwargs):
    base = {
        "toxic_event_id": "CTX1",
        "branch": "CONTEXT",
        "subtype": "CTX_FALSE_DIRECTION",
        "severity": "WATCH",
        "status": "CANDIDATE",
        "registry_record_id": "REG",
        "model_version": "V1",
        "paper_epoch_id": "EPOCH",
        "timeframe": "M15",
        "context_event_id": "CE1",
        "lifecycle_episode_id": "LE1",
        "prediction_id": "P1",
        "subject_event_at": "2026-07-28T12:10:00Z",
        "detected_at": "2026-07-28T12:10:01Z",
    }
    base.update(kwargs)
    return base


def _trd(**kwargs):
    base = {
        "toxic_event_id": "TRD1",
        "branch": "TRADE",
        "subtype": "TRD_SEVERE_LOSS",
        "severity": "WATCH",
        "status": "CANDIDATE",
        "registry_record_id": "REG",
        "model_version": "V1",
        "paper_epoch_id": "EPOCH",
        "timeframe": "M15",
        "context_event_id": "CE1",
        "lifecycle_episode_id": "LE1",
        "trade_id": "T1",
        "subject_event_at": "2026-07-28T12:12:00Z",
        "detected_at": "2026-07-28T12:12:01Z",
        "economic_harm_usd": 12.5,
    }
    base.update(kwargs)
    return base


def _data(**kwargs):
    base = {
        "toxic_event_id": "DATA1",
        "branch": "EXTERNAL_DATA",
        "subtype": "DATA_STALE",
        "severity": "WARNING",
        "status": "OPEN",
        "source_id": "BINANCE_SPOT_BTCUSDT_AGGTRADE",
        "registry_record_id": "REG",
        "model_version": "V1",
        "paper_epoch_id": "EPOCH",
        "detected_at": "2026-07-28T12:00:00Z",
        "event_time": "2026-07-28T12:00:00Z",
        "resolved_at": None,
    }
    base.update(kwargs)
    return base


def test_context_trade_exact_one_incident():
    out = ic.correlate_events(
        events_by_branch={"EXTERNAL_DATA": [], "CONTEXT": [_ctx()], "TRADE": [_trd()]},
        sources=SOURCES,
        active=ACTIVE,
    )
    assert len(out["incidents"]) == 1
    inc = out["incidents"][0]
    assert set(inc["branches_present"]) == {"CONTEXT", "TRADE"}
    assert inc["root_cause_branch"] == "CONTEXT"
    assert "EXACT" in inc["linkage_methods"]
    assert inc["root_cause_confidence"] == "CONFIRMED"
    assert any(l["linkage_method"] == "EXACT" for l in out["links"])


def test_dependency_window_cross_branch():
    data = _data()
    ctx = _ctx(subject_event_at="2026-07-28T12:05:00Z")
    trd = _trd(subject_event_at="2026-07-28T12:06:00Z")
    out = ic.correlate_events(
        events_by_branch={"EXTERNAL_DATA": [data], "CONTEXT": [ctx], "TRADE": [trd]},
        sources=SOURCES,
        active=ACTIVE,
    )
    assert len(out["incidents"]) == 1
    inc = out["incidents"][0]
    assert set(inc["branches_present"]) == {"CONTEXT", "EXTERNAL_DATA", "TRADE"}
    assert inc["root_cause_branch"] == "EXTERNAL_DATA"
    assert "DEPENDENCY_WINDOW" in inc["linkage_methods"]
    assert inc["root_cause_confidence"] == "PROVISIONAL"
    assert inc["incident_status"] == "OPEN"


def test_no_false_correlation_across_epoch_or_timestamp_only():
    ctx_a = _ctx(paper_epoch_id="EPOCH", lifecycle_episode_id="LE_A", toxic_event_id="C_A")
    trd_b = _trd(
        paper_epoch_id="OTHER_EPOCH",
        lifecycle_episode_id="LE_A",
        toxic_event_id="T_B",
        trade_id="T_B",
        subject_event_at="2026-07-28T12:10:05Z",
    )
    ctx_near = _ctx(
        toxic_event_id="C_NEAR",
        lifecycle_episode_id="LE_NEAR",
        context_event_id="CE_NEAR",
        prediction_id="P_NEAR",
        subject_event_at="2026-07-28T12:10:00Z",
    )
    trd_near = _trd(
        toxic_event_id="T_NEAR",
        trade_id="T_NEAR",
        lifecycle_episode_id="LE_OTHER",
        context_event_id="CE_OTHER",
        prediction_id="P_OTHER",
        subject_event_at="2026-07-28T12:10:02Z",
    )
    # data without dependency layer match should not root-cause link
    data_book = _data(
        toxic_event_id="DATA_BOOK",
        source_id="BINANCE_SPOT_BTCUSDT_BOOKTICKER",
        detected_at="2026-07-28T12:09:00Z",
        event_time="2026-07-28T12:09:00Z",
    )
    # context inside bookTicker window but bookTicker is TRADE-only dependency
    out = ic.correlate_events(
        events_by_branch={
            "EXTERNAL_DATA": [data_book],
            "CONTEXT": [ctx_a, ctx_near],
            "TRADE": [trd_b, trd_near],
        },
        sources=SOURCES,
        active=ACTIVE,
    )
    # trd_b filtered by epoch mismatch inside correlate via active? trades still loaded —
    # _same_active not applied inside correlate for members; load_new filters.
    # Here we pass mixed epochs directly: exact link requires same paper_epoch_id.
    epochs_in_incidents = {i.get("paper_epoch_id") for i in out["incidents"]}
    assert epochs_in_incidents == {"EPOCH"}
    # Near timestamps alone must not merge ctx_near + trd_near
    for inc in out["incidents"]:
        ids = set(inc.get("toxic_event_ids") or [])
        assert not ({"C_NEAR", "T_NEAR"} <= ids)
    # bookTicker data must not attach to context-only via timestamp
    for inc in out["incidents"]:
        if "C_NEAR" in (inc.get("toxic_event_ids") or []):
            assert "EXTERNAL_DATA" not in (inc.get("branches_present") or [])


def test_idempotent_rerun_and_unique_trade_harm(tmp_path: Path):
    ctx = _ctx()
    trd1 = _trd(toxic_event_id="TRD1", subtype="TRD_SEVERE_LOSS", economic_harm_usd=10.0)
    trd2 = _trd(
        toxic_event_id="TRD1B",
        subtype="TRD_COST_DOMINATED",
        economic_harm_usd=10.0,
        trade_id="T1",
        subject_event_at="2026-07-28T12:13:00Z",
    )
    events = {"EXTERNAL_DATA": [], "CONTEXT": [ctx], "TRADE": [trd1, trd2]}
    out1 = ic.correlate_events(events_by_branch=events, sources=SOURCES, active=ACTIVE)
    out2 = ic.correlate_events(events_by_branch=events, sources=SOURCES, active=ACTIVE)
    assert len(out1["incidents"]) == 1
    assert out1["incidents"][0]["incident_id"] == out2["incidents"][0]["incident_id"]
    assert out1["incidents"][0]["economic_harm_usd"] == 10.0

    # Persist twice via update_incident_snapshot — no duplicate incident_ids
    incidents_path = tmp_path / "incidents.jsonl"
    links_path = tmp_path / "links.jsonl"
    current = tmp_path / "current.json"
    ic.update_incident_snapshot(
        incidents_path=incidents_path,
        links_path=links_path,
        current_path=current,
        incidents=out1["incidents"],
        links=out1["links"],
    )
    ic.update_incident_snapshot(
        incidents_path=incidents_path,
        links_path=links_path,
        current_path=current,
        incidents=out2["incidents"],
        links=out2["links"],
    )
    rows = read_jsonl(incidents_path)
    assert len({r["incident_id"] for r in rows}) == 1
    assert len(rows) == 1


def test_resolved_data_resolves_incident():
    data_open = _data(status="OPEN", toxic_event_id="DATA_OPEN")
    ctx = _ctx(subject_event_at="2026-07-28T12:05:00Z")
    trd = _trd(subject_event_at="2026-07-28T12:06:00Z")
    open_out = ic.correlate_events(
        events_by_branch={"EXTERNAL_DATA": [data_open], "CONTEXT": [ctx], "TRADE": [trd]},
        sources=SOURCES,
        active=ACTIVE,
    )
    assert open_out["incidents"][0]["incident_status"] == "OPEN"

    data_resolved = _data(
        status="RESOLVED",
        toxic_event_id="DATA_RESOLVED",
        detected_at="2026-07-28T12:00:00Z",
        resolved_at="2026-07-28T12:30:00Z",
        event_time="2026-07-28T12:30:00Z",
        evidence={"resolved_from": "DATA_OPEN"},
    )
    # Replay stream: OPEN then RESOLVED
    resolved_out = ic.correlate_events(
        events_by_branch={
            "EXTERNAL_DATA": [data_open, data_resolved],
            "CONTEXT": [ctx],
            "TRADE": [trd],
        },
        sources=SOURCES,
        active=ACTIVE,
    )
    assert len(resolved_out["incidents"]) == 1
    assert resolved_out["incidents"][0]["incident_status"] == "RESOLVED"
    assert resolved_out["incidents"][0]["resolved_at"] == "2026-07-28T12:30:00Z"
