"""Minimal MODEL-1 behavioral validation tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from btc_ml.model_assurance import behavioral_validation as bv


def _ts(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_long_outcome_metrics():
    start = 100.0
    prices = [101.0, 102.0, 99.0, 100.5]
    end = prices[-1]
    m = bv.compute_signed_metrics(direction="LONG", start_price=start, end_price=end, prices=prices)
    assert m["signed_return_bps"] == pytest.approx(50.0)
    assert m["mfe_bps"] == pytest.approx(200.0)
    assert m["mae_bps"] == pytest.approx(-100.0)


def test_short_outcome_symmetric_to_long():
    start = 100.0
    prices = [101.0, 102.0, 99.0, 100.5]
    end = prices[-1]
    long_m = bv.compute_signed_metrics(direction="LONG", start_price=start, end_price=end, prices=prices)
    short_m = bv.compute_signed_metrics(direction="SHORT", start_price=start, end_price=end, prices=prices)
    assert long_m["signed_return_bps"] == pytest.approx((end / start - 1.0) * 10_000.0)
    assert short_m["signed_return_bps"] == pytest.approx((start / end - 1.0) * 10_000.0)
    long_rets = [(p / start - 1.0) * 10_000.0 for p in prices]
    short_rets = [(start / p - 1.0) * 10_000.0 for p in prices]
    assert long_m["mfe_bps"] == pytest.approx(max(long_rets))
    assert long_m["mae_bps"] == pytest.approx(min(long_rets))
    assert short_m["mfe_bps"] == pytest.approx(max(short_rets))
    assert short_m["mae_bps"] == pytest.approx(min(short_rets))
    # Exact inversion of per-path returns: (start/p - 1) == - (p/start - 1) * (start/p) * (p/start) ...
    # Contract: SHORT metrics are the LONG formulas with inverted price ratio.
    assert short_m["mfe_bps"] == pytest.approx(max((start / p - 1.0) * 10_000.0 for p in prices))
    assert short_m["mae_bps"] == pytest.approx(min((start / p - 1.0) * 10_000.0 for p in prices))


def test_context_flip_closes_and_opens(tmp_path: Path):
    active = {
        "registry_record_id": "REG_TEST",
        "model_id": "BTC_INTRABAR_RULE_BASED",
        "model_version": "INTRABAR_RULES_V1",
        "runtime_fingerprint": "fp",
        "paper_epoch_id": "EPOCH",
    }
    state = bv.ValidationState({}, {}, {}, set())
    start_event = {
        "context_event_id": "E1",
        "event_type": "CONTEXT_START",
        "new_context": "LONG_CONTEXT",
        "timeframe": "M15",
        "event_timestamp": "2026-07-28T12:00:00Z",
        "event_monotonic_ns": 1,
        "context_event_price": "100",
        "lifecycle_episode_id": "L1",
        "last_trade_id": 1,
    }
    created = bv.process_context_event(state, active=active, event=start_event)
    assert len(created) == 1
    assert state.open_by_tf["M15"] == created[0]["prediction_id"]
    flip = {
        "context_event_id": "E2",
        "event_type": "CONTEXT_FLIP",
        "new_context": "SHORT_CONTEXT",
        "previous_context": "LONG_CONTEXT",
        "timeframe": "M15",
        "event_timestamp": "2026-07-28T12:10:00Z",
        "event_monotonic_ns": 2,
        "context_event_price": "101",
        "lifecycle_episode_id": "L1",
        "last_trade_id": 2,
    }
    created2 = bv.process_context_event(state, active=active, event=flip)
    assert len(created2) == 1
    old = state.predictions[created[0]["prediction_id"]]
    assert old["prediction_status"] == "CLOSED"
    assert old["close_reason"] == "CONTEXT_FLIP"
    assert created2[0]["direction"] == "SHORT"
    assert state.open_by_tf["M15"] == created2[0]["prediction_id"]


def test_trade_after_cutoff_ignored(tmp_path: Path):
    raw = tmp_path / "raw"
    start = _ts("2026-07-28T12:00:00Z")
    cutoff = start + timedelta(seconds=900)
    part = raw / "agg_trade" / "date=2026-07-28" / "hour=12"
    part.mkdir(parents=True)
    rows = {
        "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
        "exchange_trade_timestamp": [
            "2026-07-28T12:05:00Z",
            "2026-07-28T12:15:00Z",
            "2026-07-28T12:20:00Z",  # after cutoff
        ],
        "aggregate_trade_id": [1, 2, 3],
        "price": [100.0, 110.0, 50.0],
    }
    pq.write_table(pa.table(rows), part / "batch.parquet")
    out = bv.evaluate_horizon_window(
        direction="LONG",
        start_price=100.0,
        start_ts=start,
        cutoff_ts=cutoff,
        raw_root=raw,
        now=cutoff + timedelta(seconds=1),
    )
    assert out["outcome_status"] == "EVALUATED"
    assert out["end_price"] == 110.0
    assert out["observation_count"] == 2
    assert out["signed_return_bps"] == pytest.approx(1000.0)
    assert out["mfe_bps"] == pytest.approx(1000.0)


def test_rerun_no_duplicate_predictions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    (root / "data" / "model_assurance" / "registry" / "active").mkdir(parents=True)
    (root / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (root / "data" / "raw_market_events_v2" / "agg_trade").mkdir(parents=True)
    active = {
        "registry_record_id": "REG_TEST",
        "model_id": "BTC_INTRABAR_RULE_BASED",
        "model_version": "INTRABAR_RULES_V1",
        "runtime_fingerprint": "fp",
        "paper_epoch_id": "EPOCH",
        "paper_epoch_activated_at": "2026-07-28T11:00:00Z",
        "paper_only": True,
        "real_execution": False,
    }
    active_path = root / "data" / "model_assurance" / "registry" / "active" / "active_model.json"
    active_path.write_text(json.dumps(active) + "\n", encoding="utf-8")
    events = [
        {
            "context_event_id": "E1",
            "event_type": "CONTEXT_START",
            "new_context": "LONG_CONTEXT",
            "timeframe": "M15",
            "event_timestamp": "2026-07-28T12:00:00Z",
            "event_monotonic_ns": 1,
            "context_event_price": "100",
            "lifecycle_episode_id": "L1",
            "last_trade_id": 1,
        }
    ]
    (root / "data" / "cognition" / "intrabar_context_events" / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bv, "read_active_runtime", lambda repo_root=None: active)
    monkeypatch.setattr(bv, "latest_agg_trade_ts", lambda raw_root: _ts("2026-07-28T12:01:00Z"))
    s1 = bv.run_once(repo_root=root)
    assert s1["eligible_contexts"] == 1
    s2 = bv.run_once(repo_root=root)
    assert s2["eligible_contexts"] == 1
    pred_path = bv.paths(root)["predictions"]
    lines = [ln for ln in pred_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
