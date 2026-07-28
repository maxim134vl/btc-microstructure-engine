"""Minimal MODEL-2 external data toxicity tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from btc_ml.model_assurance.toxic_box import external_data as ed


def _cfg() -> dict:
    return {
        "schema_version": "test",
        "monitoring_mode": "LIVE_CURRENT",
        "runtime_impact": "NON_BLOCKING",
        "check_interval_seconds": 5,
        "startup_grace_period_seconds": 0,
        "future_clock_skew_tolerance_ms": 2000,
        "pipeline": {"max_queue_current_events": 40000, "max_writer_lag_ms": 5000},
        "sources": [
            {
                "source_id": "BINANCE_SPOT_BTCUSDT_AGGTRADE",
                "provider": "BINANCE",
                "dataset_name": "spot_aggTrade",
                "symbol": "BTCUSDT",
                "transport": "WEBSOCKET",
                "schema_version": "1.0.0",
                "required_for": ["LIVE1A_CONTEXT"],
                "expected_frequency": "STREAM",
                "max_age_seconds": 60,
                "exchange_timestamp_available": True,
                "sequence_field": "aggregate_trade_id",
                "provenance": "agg_trade",
                "health_stream_key": "aggTrade",
                "stream_dir": "agg_trade",
            },
            {
                "source_id": "BINANCE_SPOT_BTCUSDT_BOOKTICKER",
                "provider": "BINANCE",
                "dataset_name": "spot_bookTicker",
                "symbol": "BTCUSDT",
                "transport": "WEBSOCKET",
                "schema_version": "1.0.0",
                "required_for": ["LIVE1B_EXECUTION"],
                "expected_frequency": "STREAM",
                "max_age_seconds": 10,
                "exchange_timestamp_available": False,
                "sequence_field": "update_id",
                "provenance": "book_ticker",
                "health_stream_key": "bookTicker",
                "stream_dir": "book_ticker",
            },
            {
                "source_id": "BINANCE_SPOT_BTCUSDT_M15_KLINE",
                "provider": "BINANCE",
                "dataset_name": "spot_m15_completed_kline",
                "symbol": "BTCUSDT",
                "transport": "PARQUET_FEED",
                "schema_version": "live_market_feed_v1",
                "required_for": ["COMPLETED_BAR_STRUCTURAL_BACKGROUND"],
                "expected_frequency": "M15",
                "max_age_seconds": 1200,
                "exchange_timestamp_available": True,
                "sequence_field": None,
                "provenance": "live_market_feed.parquet",
                "health_stream_key": None,
                "stream_dir": None,
            },
        ],
    }


def _write_stream(root: Path, stream: str, rows: list[dict], *, hour: int = 12) -> None:
    part = root / stream / "date=2026-07-28" / f"hour={hour}"
    part.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, part / "batch.parquet")


def _seed(tmp_path: Path, *, now: datetime, cognition: dict, agg_rows=None, book_rows=None, m15_ts=None):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "live").mkdir(parents=True)
    (tmp_path / "data" / "raw_market_events_v2").mkdir(parents=True)
    (tmp_path / "config" / "model_assurance_external_sources.json").write_text(
        json.dumps(_cfg(), indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "data" / "runtime" / "intrabar_cognition_health.json").write_text(
        json.dumps(cognition) + "\n", encoding="utf-8"
    )
    raw = tmp_path / "data" / "raw_market_events_v2"
    if agg_rows is None:
        agg_rows = [
            {
                "aggregate_trade_id": 100,
                "price": 1.0,
                "quantity": 0.1,
                "exchange_trade_timestamp": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
                "exchange_event_timestamp": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
                "local_receive_timestamp": (now - timedelta(seconds=4)).isoformat().replace("+00:00", "Z"),
                "local_receive_monotonic_ns": 1,
                "connection_session_id": "s1",
                "reconnect_generation": 1,
            },
            {
                "aggregate_trade_id": 101,
                "price": 1.1,
                "quantity": 0.1,
                "exchange_trade_timestamp": (now - timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
                "exchange_event_timestamp": (now - timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
                "local_receive_timestamp": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
                "local_receive_monotonic_ns": 2,
                "connection_session_id": "s1",
                "reconnect_generation": 1,
            },
        ]
    if book_rows is None:
        book_rows = [
            {
                "update_id": 10,
                "best_bid_price": 100.0,
                "best_ask_price": 100.1,
                "exchange_event_timestamp": None,
                "local_receive_timestamp": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "local_receive_monotonic_ns": 3,
                "connection_session_id": "s1",
                "reconnect_generation": 1,
            },
            {
                "update_id": 12,
                "best_bid_price": 100.0,
                "best_ask_price": 100.2,
                "exchange_event_timestamp": None,
                "local_receive_timestamp": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "local_receive_monotonic_ns": 4,
                "connection_session_id": "s1",
                "reconnect_generation": 1,
            },
        ]
    _write_stream(raw, "agg_trade", agg_rows)
    _write_stream(raw, "book_ticker", book_rows)
    bar_open = m15_ts or (now - timedelta(seconds=100))
    pq.write_table(
        pa.table(
            {
                "timestamp": [bar_open.replace(tzinfo=None)],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.05],
                "volume": [10.0],
            }
        ),
        tmp_path / "data" / "live" / "live_market_feed.parquet",
    )
    return tmp_path


def test_fresh_sources_current_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc)
    cognition = {
        "started_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "streams": {
            "aggTrade": {"received": 10, "last": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z")},
            "bookTicker": {"received": 10, "last": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
        },
        "queue": {"enqueue_rejected": 0, "queue_current_events": 1, "writer_lag_ms": 1},
        "writer": {"write_errors": 0, "writer_lag_ms": 1},
    }
    root = _seed(tmp_path, now=now, cognition=cognition)
    monkeypatch.setattr(ed, "read_active_runtime", lambda repo_root=None: {
        "registry_record_id": "REG",
        "model_id": "M",
        "model_version": "V",
        "runtime_fingerprint": "fp",
        "paper_epoch_id": "E",
        "paper_only": True,
        "real_execution": False,
    })
    result = ed.evaluate_external_sources(repo_root=root, now=now)
    assert result["summary"]["status"] == "CURRENT_HEALTHY"
    assert result["summary"]["healthy_sources"] == 3
    assert result["summary"]["open_events"] == 0


def test_stale_source_one_open_no_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc)
    cognition = {
        "started_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "streams": {
            "aggTrade": {"received": 10, "last": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z")},
            "bookTicker": {"received": 10, "last": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
        },
        "queue": {"enqueue_rejected": 0, "queue_current_events": 1, "writer_lag_ms": 1},
        "writer": {"write_errors": 0},
    }
    root = _seed(tmp_path, now=now, cognition=cognition)
    monkeypatch.setattr(ed, "read_active_runtime", lambda repo_root=None: {"registry_record_id": "REG", "model_id": "M", "model_version": "V", "runtime_fingerprint": "fp", "paper_epoch_id": "E"})
    ed.evaluate_external_sources(repo_root=root, now=now)
    ed.evaluate_external_sources(repo_root=root, now=now)
    events = ed._read_jsonl(ed.paths(root)["events"])
    stale_open = [e for e in events if e.get("subtype") == "DATA_STALE" and e.get("status") == "OPEN"]
    assert len(stale_open) == 1
    assert stale_open[0]["source_id"] == "BINANCE_SPOT_BTCUSDT_AGGTRADE"


def test_recovery_emits_one_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(ed, "read_active_runtime", lambda repo_root=None: {"registry_record_id": "REG", "model_id": "M", "model_version": "V", "runtime_fingerprint": "fp", "paper_epoch_id": "E"})
    stale_cog = {
        "started_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "streams": {
            "aggTrade": {"received": 10, "last": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z")},
            "bookTicker": {"received": 10, "last": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
        },
        "queue": {"enqueue_rejected": 0, "queue_current_events": 1},
        "writer": {"write_errors": 0},
    }
    root = _seed(tmp_path, now=now, cognition=stale_cog)
    ed.evaluate_external_sources(repo_root=root, now=now)
    fresh_cog = dict(stale_cog)
    fresh_cog["streams"] = {
        "aggTrade": {"received": 11, "last": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z")},
        "bookTicker": {"received": 11, "last": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")},
    }
    (root / "data" / "runtime" / "intrabar_cognition_health.json").write_text(json.dumps(fresh_cog) + "\n", encoding="utf-8")
    ed.evaluate_external_sources(repo_root=root, now=now)
    events = ed._read_jsonl(ed.paths(root)["events"])
    resolved = [e for e in events if e.get("subtype") == "DATA_STALE" and e.get("status") == "RESOLVED"]
    assert len(resolved) == 1


def test_agg_gap_rewind_and_book_rewind():
    rows = [
        {"aggregate_trade_id": 10},
        {"aggregate_trade_id": 12},  # gap
        {"aggregate_trade_id": 11},  # rewind
        {"aggregate_trade_id": 11},  # duplicate
    ]
    issues = ed._scan_agg_sequence(rows, prev_id=9)
    subtypes = {i["subtype"] for i in issues}
    assert "DATA_GAP" in subtypes
    assert "DATA_SEQUENCE_REWIND" in subtypes
    assert "DATA_DUPLICATE" in subtypes

    book = [
        {"update_id": 5, "best_bid_price": 1.0, "best_ask_price": 1.1},
        {"update_id": 8, "best_bid_price": 1.0, "best_ask_price": 1.1},  # jump ok
        {"update_id": 7, "best_bid_price": 1.0, "best_ask_price": 1.1},  # rewind
    ]
    b_issues = ed._scan_book_sequence(book, prev_id=5)
    assert any(i["subtype"] == "DATA_SEQUENCE_REWIND" for i in b_issues)
    assert not any(i["subtype"] == "DATA_GAP" for i in b_issues)


def test_future_timestamp_and_missing_book_exchange_ts_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc)
    # exchange far in future vs local receive
    future = (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    local = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    agg_rows = [
        {
            "aggregate_trade_id": 1,
            "price": 1.0,
            "quantity": 0.1,
            "exchange_trade_timestamp": future,
            "exchange_event_timestamp": future,
            "local_receive_timestamp": local,
            "local_receive_monotonic_ns": 1,
            "connection_session_id": "s1",
            "reconnect_generation": 1,
        }
    ]
    book_rows = [
        {
            "update_id": 1,
            "best_bid_price": 1.0,
            "best_ask_price": 0.5,  # schema breach
            "exchange_event_timestamp": None,
            "local_receive_timestamp": local,
            "local_receive_monotonic_ns": 2,
            "connection_session_id": "s1",
            "reconnect_generation": 1,
        }
    ]
    cognition = {
        "started_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "streams": {
            "aggTrade": {"received": 1, "last": local},
            "bookTicker": {"received": 1, "last": local},
        },
        "queue": {"enqueue_rejected": 0, "queue_current_events": 0},
        "writer": {"write_errors": 0},
    }
    root = _seed(tmp_path, now=now, cognition=cognition, agg_rows=agg_rows, book_rows=book_rows)
    monkeypatch.setattr(ed, "read_active_runtime", lambda repo_root=None: {"registry_record_id": "REG", "model_id": "M", "model_version": "V", "runtime_fingerprint": "fp", "paper_epoch_id": "E"})
    ed.evaluate_external_sources(repo_root=root, now=now)
    events = ed._read_jsonl(ed.paths(root)["events"])
    subtypes = {(e.get("source_id"), e.get("subtype"), e.get("status")) for e in events if e.get("status") == "OPEN"}
    assert ("BINANCE_SPOT_BTCUSDT_AGGTRADE", "DATA_FUTURE_LEAKAGE", "OPEN") in subtypes
    assert ("BINANCE_SPOT_BTCUSDT_BOOKTICKER", "DATA_SCHEMA_BREAK", "OPEN") in subtypes
    # missing book exchange ts must not create FUTURE_LEAKAGE on book
    assert ("BINANCE_SPOT_BTCUSDT_BOOKTICKER", "DATA_FUTURE_LEAKAGE", "OPEN") not in subtypes


def _evt(source_id: str, subtype: str, status: str, *, detected_at: str, resolved_at=None, severity="WARNING"):
    row = {
        "branch": "EXTERNAL_DATA",
        "source_id": source_id,
        "subtype": subtype,
        "status": status,
        "severity": severity,
        "detected_at": detected_at,
        "event_time": detected_at,
        "toxic_event_id": f"TOX_{source_id}_{subtype}_{status}_{detected_at}",
    }
    if resolved_at:
        row["resolved_at"] = resolved_at
    return row


def test_open_then_resolved_summary_is_healthy():
    events = [
        _evt("S1", "DATA_STALE", "OPEN", detected_at="2026-07-28T12:00:00Z"),
        _evt(
            "S1",
            "DATA_STALE",
            "RESOLVED",
            detected_at="2026-07-28T12:00:00Z",
            resolved_at="2026-07-28T12:05:00Z",
        ),
    ]
    assert ed.reconstruct_active_open_events(events) == []
    sources = [{"source_id": "S1", "source_health": "HEALTHY"}]
    summary = ed.build_external_data_summary(active={}, sources=sources, events=events, starting=False)
    assert summary["open_events"] == 0
    assert summary["warning_events"] == 0
    assert summary["status"] == "CURRENT_HEALTHY"
    assert summary["last_resolved_at"] == "2026-07-28T12:05:00Z"


def test_open_resolved_open_keeps_one_active_issue():
    events = [
        _evt("S1", "DATA_STALE", "OPEN", detected_at="2026-07-28T12:00:00Z"),
        _evt(
            "S1",
            "DATA_STALE",
            "RESOLVED",
            detected_at="2026-07-28T12:00:00Z",
            resolved_at="2026-07-28T12:05:00Z",
        ),
        _evt("S1", "DATA_STALE", "OPEN", detected_at="2026-07-28T12:10:00Z", severity="WARNING"),
    ]
    active = ed.reconstruct_active_open_events(events)
    assert len(active) == 1
    assert active[0]["detected_at"] == "2026-07-28T12:10:00Z"
    sources = [{"source_id": "S1", "source_health": "DEGRADED"}]
    summary = ed.build_external_data_summary(active={}, sources=sources, events=events, starting=False)
    assert summary["open_events"] == 1
    assert summary["warning_events"] == 1
    assert summary["status"] == "CURRENT_DEGRADED"


def test_multiple_historical_pairs_count_only_latest_states():
    events = [
        _evt("AGG", "DATA_STALE", "OPEN", detected_at="2026-07-28T11:00:00Z"),
        _evt(
            "AGG",
            "DATA_STALE",
            "RESOLVED",
            detected_at="2026-07-28T11:00:00Z",
            resolved_at="2026-07-28T11:01:00Z",
        ),
        _evt("BOOK", "DATA_STALE", "OPEN", detected_at="2026-07-28T11:02:00Z"),
        _evt(
            "BOOK",
            "DATA_STALE",
            "RESOLVED",
            detected_at="2026-07-28T11:02:00Z",
            resolved_at="2026-07-28T11:03:00Z",
        ),
        _evt("AGG", "DATA_GAP", "OPEN", detected_at="2026-07-28T11:04:00Z"),
        _evt(
            "AGG",
            "DATA_GAP",
            "RESOLVED",
            detected_at="2026-07-28T11:04:00Z",
            resolved_at="2026-07-28T11:05:00Z",
        ),
        # one still open
        _evt("BOOK", "DATA_SEQUENCE_REWIND", "OPEN", detected_at="2026-07-28T11:06:00Z", severity="CRITICAL"),
        # duplicate historical open for already-resolved stale must not count
        _evt("AGG", "DATA_STALE", "OPEN", detected_at="2026-07-28T10:59:00Z"),
        _evt(
            "AGG",
            "DATA_STALE",
            "RESOLVED",
            detected_at="2026-07-28T10:59:00Z",
            resolved_at="2026-07-28T10:59:30Z",
        ),
    ]
    active = ed.reconstruct_active_open_events(events)
    assert len(active) == 1
    assert active[0]["source_id"] == "BOOK"
    assert active[0]["subtype"] == "DATA_SEQUENCE_REWIND"
    sources = [
        {"source_id": "AGG", "source_health": "HEALTHY"},
        {"source_id": "BOOK", "source_health": "CRITICAL"},
    ]
    summary = ed.build_external_data_summary(active={}, sources=sources, events=events, starting=False)
    assert summary["open_events"] == 1
    assert summary["critical_events"] == 1
    assert summary["counts_by_source"] == {"BOOK": 1}
    assert summary["counts_by_subtype"] == {"DATA_SEQUENCE_REWIND": 1}
    assert summary["status"] == "CURRENT_CRITICAL"
    enriched = ed._enrich_source_current_state(sources, events=events, active_open=active)
    by_id = {s["source_id"]: s for s in enriched}
    assert by_id["AGG"]["active_issue_count"] == 0
    assert by_id["AGG"]["active_issues"] == []
    assert by_id["BOOK"]["active_issue_count"] == 1
    assert by_id["BOOK"]["active_issues"][0]["subtype"] == "DATA_SEQUENCE_REWIND"
