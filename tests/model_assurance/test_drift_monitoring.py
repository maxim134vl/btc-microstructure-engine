"""Minimal MODEL-6 drift monitoring tests."""

from __future__ import annotations

from pathlib import Path

from btc_ml.model_assurance.drift import statistics as stats
from btc_ml.model_assurance.drift.monitor import MetricTracker, drift_event_id_for, window_id_for
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


def _tracker(**kwargs) -> MetricTracker:
    base = dict(
        branch="performance",
        metric="net_pnl_usd",
        timeframe=None,
        kind="numeric",
        active=ACTIVE,
        baseline_min=20,
        window_size=5,
        min_consecutive=3,
        recovery_consecutive=3,
        numeric_thr=NUM_THR,
        categorical_thr=CAT_THR,
    )
    base.update(kwargs)
    return MetricTracker(**base)


def test_baseline_collects_and_freezes():
    tr = _tracker(baseline_min=10, window_size=5)
    assert tr.baseline_status == "COLLECTING"
    tr.add_values([1.0] * 9)
    assert tr.baseline_status == "COLLECTING"
    tr.add_values([1.0])
    assert tr.baseline_status == "FROZEN"
    assert tr.status == "STABLE"
    assert len(tr.baseline_values) == 10


def test_numeric_shift_three_windows_creates_transition():
    tr = _tracker(baseline_min=30, window_size=10, min_consecutive=3)
    tr.add_values([0.0] * 30)
    assert tr.baseline_status == "FROZEN"
    # Strong shift: baseline ~0, current ~10
    windows = []
    for _ in range(3):
        windows.extend(tr.add_values([10.0] * 10))
    assert len(windows) == 3
    assert windows[0].get("transition") is None
    assert windows[1].get("transition") is None
    assert windows[2].get("transition") is not None
    assert windows[2]["transition"]["new_status"] in {"WATCH", "WARNING", "CRITICAL"}
    assert tr.status == windows[2]["transition"]["new_status"]
    assert windows[2]["statistic_value"] >= NUM_THR["watch"]


def test_categorical_shift_single_window_does_not_change_status():
    tr = _tracker(
        branch="context",
        metric="direction_share",
        timeframe="M15",
        kind="categorical",
        baseline_min=20,
        window_size=10,
        min_consecutive=3,
    )
    tr.add_values(["LONG"] * 20)
    assert tr.baseline_status == "FROZEN"
    assert tr.status == "STABLE"
    # Single shifted window
    wins = tr.add_values(["SHORT"] * 10)
    assert len(wins) == 1
    assert wins[0]["window_severity"] in {"WATCH", "WARNING", "CRITICAL"}
    assert wins[0].get("transition") is None
    assert tr.status == "STABLE"
    # Distance itself is positive / deterministic
    d = stats.categorical_js_distance({"LONG": 20}, {"SHORT": 10})
    assert d > CAT_THR["watch"]


def test_external_degradation_suppresses_input_feature_not_drift_alert():
    tr = _tracker(branch="input", metric="quantity", baseline_min=5, window_size=5)
    tr.add_values([1.0, 1.1, 1.2, 1.0, 0.9])
    tr.set_suppressed(True)
    assert tr.status == "SUPPRESSED_DATA_QUALITY"
    # Further values must not create windows/events while suppressed
    wins = tr.add_values([100.0] * 20)
    assert wins == []
    assert tr.status == "SUPPRESSED_DATA_QUALITY"


def test_active_filtering_and_no_duplicate_windows_events(tmp_path: Path):
    tr = _tracker(baseline_min=5, window_size=5, min_consecutive=3)
    tr.add_values([1.0] * 5)
    # Produce three shifted windows → one transition
    all_windows = []
    for _ in range(3):
        all_windows.extend(tr.add_values([50.0] * 5))
    assert any(w.get("transition") for w in all_windows)

    windows_path = tmp_path / "windows.jsonl"
    events_path = tmp_path / "events.jsonl"
    existing_w: set[str] = set()
    existing_e: set[str] = set()

    def persist(windows):
        for w in windows:
            wid = w["window_id"]
            if wid in existing_w:
                continue
            append_jsonl(windows_path, w)
            existing_w.add(wid)
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
            if eid in existing_e:
                continue
            append_jsonl(
                events_path,
                {
                    "drift_event_id": eid,
                    "previous_status": trn["previous_status"],
                    "new_status": trn["new_status"],
                },
            )
            existing_e.add(eid)

    persist(all_windows)
    # Replay same window ids — no duplicates
    persist(all_windows)
    assert len(read_jsonl(windows_path)) == len({r["window_id"] for r in read_jsonl(windows_path)})
    assert len(read_jsonl(events_path)) == 1

    # Different epoch identity → different window ids
    other = dict(ACTIVE)
    other["paper_epoch_id"] = "OTHER"
    wid_a = window_id_for(ACTIVE, branch="performance", metric="net_pnl_usd", timeframe=None, window_index=1)
    wid_b = window_id_for(other, branch="performance", metric="net_pnl_usd", timeframe=None, window_index=1)
    assert wid_a != wid_b
