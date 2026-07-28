"""MODEL-6.1 data-quality suppression contract tests (exactly four)."""

from __future__ import annotations

from pathlib import Path

from btc_ml.model_assurance.drift.monitor import (
    SOURCE_AGG,
    SOURCE_BOOK,
    SOURCE_M15,
    MetricTracker,
    compute_data_quality_suppression,
    drift_event_id_for,
    load_active_open_data_quality_events,
)
from btc_ml.model_assurance.toxic_box.common import append_jsonl, read_jsonl


ACTIVE = {
    "registry_record_id": "REG",
    "model_id": "M",
    "model_version": "V1",
    "runtime_fingerprint": "fp",
    "paper_epoch_id": "EPOCH",
}

NUM_THR = {"watch": 0.25, "warning": 0.50, "critical": 1.00}
CAT_THR = {"watch": 0.10, "warning": 0.20, "critical": 0.30}


def _open(source_id: str, subtype: str = "DATA_STALE") -> dict:
    return {
        "branch": "EXTERNAL_DATA",
        "status": "OPEN",
        "source_id": source_id,
        "subtype": subtype,
        "severity": "WARNING",
        "toxic_event_id": f"TOX_{source_id}_{subtype}_OPEN",
        "detected_at": "2026-07-28T12:00:00Z",
        "event_time": "2026-07-28T12:00:00Z",
        "observed_value": 20.0,
        "threshold": 10.0,
    }


def _resolved(source_id: str, subtype: str = "DATA_STALE") -> dict:
    return {
        "branch": "EXTERNAL_DATA",
        "status": "RESOLVED",
        "source_id": source_id,
        "subtype": subtype,
        "severity": "WARNING",
        "toxic_event_id": f"TOX_{source_id}_{subtype}_RES",
        "detected_at": "2026-07-28T12:00:00Z",
        "resolved_at": "2026-07-28T12:05:00Z",
        "event_time": "2026-07-28T12:05:00Z",
        "evidence": {"resolved_from": f"TOX_{source_id}_{subtype}_OPEN"},
    }


def test_resolved_external_event_does_not_suppress():
    events = [_open(SOURCE_BOOK), _resolved(SOURCE_BOOK)]
    open_now = load_active_open_data_quality_events(events)
    assert open_now == []
    plan = compute_data_quality_suppression(open_now)
    assert plan["data_quality_status"] == "CLEAR"
    assert plan["suppressed_input_metrics"] == set()
    assert plan["suppressed_feature_metrics"] == set()
    assert plan["suppressed_sources"] == []


def test_m15_kline_degradation_does_not_suppress_agg_book_input():
    plan = compute_data_quality_suppression([_open(SOURCE_M15, "DATA_STALE")])
    assert SOURCE_M15 in plan["suppressed_sources"]
    # M15 must not suppress agg/book input metrics
    assert "quantity" not in plan["suppressed_input_metrics"]
    assert "trade_return_bps" not in plan["suppressed_input_metrics"]
    assert "spread_bps" not in plan["suppressed_input_metrics"]
    assert "mid_return_bps" not in plan["suppressed_input_metrics"]
    # structural feature fields only
    assert plan["suppressed_feature_metrics"] == {"structural_rank", "location_bias"}
    assert "market_context" not in plan["suppressed_feature_metrics"]


def test_aggtrade_degradation_suppresses_only_dependent_metrics():
    plan = compute_data_quality_suppression([_open(SOURCE_AGG)])
    assert "quantity" in plan["suppressed_input_metrics"]
    assert "trade_return_bps" in plan["suppressed_input_metrics"]
    # bookTicker input remains independent
    assert "spread_bps" not in plan["suppressed_input_metrics"]
    assert "book_update_interarrival_ms" not in plan["suppressed_input_metrics"]
    # feature cognition depends on aggTrade
    assert "market_context" in plan["suppressed_feature_metrics"]
    assert "lifecycle" in plan["suppressed_feature_metrics"]


def test_recovery_admits_baseline_again_and_no_duplicate_events(tmp_path: Path):
    tr = MetricTracker(
        branch="input",
        metric="quantity",
        timeframe=None,
        kind="numeric",
        active=ACTIVE,
        baseline_min=5,
        window_size=5,
        min_consecutive=3,
        recovery_consecutive=3,
        numeric_thr=NUM_THR,
        categorical_thr=CAT_THR,
    )
    # Healthy baseline collection
    tr.add_values([1.0, 1.1, 1.0])
    assert tr.baseline_status == "COLLECTING"
    assert len(tr.baseline_values) == 3

    # Active aggTrade issue — do not admit
    tr.set_suppressed(True)
    assert tr.add_values([9.0, 9.0, 9.0]) == []
    assert len(tr.baseline_values) == 3

    # Recovery — new healthy values admitted; prior baseline kept
    tr.set_suppressed(False)
    assert tr.status == "COLLECTING_BASELINE"
    tr.add_values([1.2, 1.0])
    assert len(tr.baseline_values) == 5
    assert tr.baseline_status == "FROZEN"

    # Produce a transition then persist twice without duplicates
    wins = []
    for _ in range(3):
        wins.extend(tr.add_values([50.0] * 5))
    events_path = tmp_path / "events.jsonl"
    existing: set[str] = set()
    for w in wins:
        trn = w.get("transition")
        if not trn:
            continue
        eid = drift_event_id_for(
            baseline_id=tr.baseline_id,
            branch=tr.branch,
            metric=tr.metric,
            timeframe=tr.timeframe,
            previous_status=trn["previous_status"],
            new_status=trn["new_status"],
        )
        if eid in existing:
            continue
        append_jsonl(events_path, {"drift_event_id": eid, **trn})
        existing.add(eid)
    # Replay
    for w in wins:
        trn = w.get("transition")
        if not trn:
            continue
        eid = drift_event_id_for(
            baseline_id=tr.baseline_id,
            branch=tr.branch,
            metric=tr.metric,
            timeframe=tr.timeframe,
            previous_status=trn["previous_status"],
            new_status=trn["new_status"],
        )
        if eid in existing:
            continue
        append_jsonl(events_path, {"drift_event_id": eid, **trn})
        existing.add(eid)
    rows = read_jsonl(events_path)
    assert len(rows) == 1
    assert len({r["drift_event_id"] for r in rows}) == 1
