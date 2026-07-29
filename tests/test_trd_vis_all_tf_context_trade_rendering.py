"""TRD-VIS-ALL-TF — context/trade chart payload + renderer contract (fixtures only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))
sys.path.insert(0, str(ROOT / "src"))

import timeframe_chart_truth as tct  # noqa: E402


REQUIRED_CONTEXT_FIELDS = {
    "context_event_id",
    "event_type",
    "paper_epoch_id",
    "timeframe",
    "direction",
    "lifecycle_episode_id",
    "event_timestamp",
    "context_started_at",
    "context_ended_at",
    "context_price",
    "context_price_timestamp",
    "context_bar_open_timestamp",
    "context_bar_scheduled_close_timestamp",
    "context_bar_status",
    "context_bar_partial_close_at_context",
    "context_bar_partial_close_timestamp",
    "context_bar_final_close",
    "context_bar_final_close_timestamp",
    "bar_anchor_time",
    "causal_cutoff_timestamp",
    "source",
}


def _write_journal(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_h4_context_start_anchors_to_08_not_04(tmp_path, monkeypatch):
    journal = tmp_path / "events.jsonl"
    _write_journal(
        journal,
        [
            {
                "context_event_id": "CTX_d25c0ed08fd7b1d5c8af",
                "timeframe": "H4",
                "event_type": "CONTEXT_START",
                "previous_context": "OBSERVE",
                "new_context": "LONG_CONTEXT",
                "event_timestamp": "2026-07-29T09:40:34.724226Z",
                "context_event_price": "64690.19",
                "last_trade_timestamp": "2026-07-29T09:40:35.150000Z",
                "causal_cutoff_timestamp": "2026-07-29T09:40:34.724226Z",
                "lifecycle_episode_id": "H4:prov:1",
                "paper_epoch_id": "INTRABAR_RULES_V1_20260728_110636",
            }
        ],
    )
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", journal)
    candles = [
        {
            "timestamp": "2026-07-29T04:00:00Z",
            "bar_open": "2026-07-29T04:00:00Z",
            "close": 64000.0,
            "confirmed": True,
        },
        {
            "timestamp": "2026-07-29T08:00:00Z",
            "bar_open": "2026-07-29T08:00:00Z",
            "close": 64650.0,
            "confirmed": False,
            "is_partial": True,
        },
    ]
    events = tct.load_intrabar_context_events_for_tf(
        "H4",
        candles=candles,
        paper_epoch_id="INTRABAR_RULES_V1_20260728_110636",
    )
    assert len(events) == 1
    ev = events[0]
    assert set(REQUIRED_CONTEXT_FIELDS).issubset(ev.keys())
    assert ev["event_timestamp"] == "2026-07-29T09:40:34.724226Z"
    assert ev["bar_anchor_time"] == "2026-07-29T08:00:00Z"
    assert ev["context_price"] == pytest.approx(64690.19)
    assert ev["context_bar_status"] == "OPEN"
    assert ev["context_bar_final_close"] is None
    assert ev["bar_anchor_time"] != "2026-07-29T04:00:00Z"
    # context price must stay distinct from a trade entry price
    assert ev["context_price"] != 64687.82

    zones = tct.build_context_zones_from_events(events)
    assert len(zones) == 1
    assert zones[0]["direction"] == "LONG"
    assert zones[0]["active"] is True
    assert zones[0]["bar_anchor_time"] == "2026-07-29T08:00:00Z"


def test_all_tf_isolation_and_epoch_filter(tmp_path, monkeypatch):
    journal = tmp_path / "events.jsonl"
    rows = []
    for tf, direction, ts, cid in [
        ("M15", "LONG_CONTEXT", "2026-07-29T10:01:00Z", "CTX_m15"),
        ("M30", "SHORT_CONTEXT", "2026-07-29T10:02:00Z", "CTX_m30"),
        ("H1", "LONG_CONTEXT", "2026-07-29T10:03:00Z", "CTX_h1"),
        ("H4", "SHORT_CONTEXT", "2026-07-29T10:04:00Z", "CTX_h4"),
    ]:
        rows.append(
            {
                "context_event_id": cid,
                "timeframe": tf,
                "event_type": "CONTEXT_START",
                "previous_context": "OBSERVE",
                "new_context": direction,
                "event_timestamp": ts,
                "context_event_price": "100.0",
                "last_trade_timestamp": ts,
                "causal_cutoff_timestamp": ts,
                "lifecycle_episode_id": f"{tf}:prov:1",
                "paper_epoch_id": "EPOCH_A",
            }
        )
    # Foreign epoch must not appear when callers pass active epoch and journal stamps differ —
    # export keeps journal stamp; renderer/filter uses paper_epoch_id on payload.
    rows.append(
        {
            "context_event_id": "CTX_old_epoch",
            "timeframe": "H4",
            "event_type": "CONTEXT_START",
            "previous_context": "OBSERVE",
            "new_context": "LONG_CONTEXT",
            "event_timestamp": "2026-07-28T10:00:00Z",
            "context_event_price": "90.0",
            "last_trade_timestamp": "2026-07-28T10:00:00Z",
            "causal_cutoff_timestamp": "2026-07-28T10:00:00Z",
            "lifecycle_episode_id": "H4:old",
            "paper_epoch_id": "EPOCH_OLD",
        }
    )
    _write_journal(journal, rows)
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", journal)

    for tf in tct.TIMEFRAMES:
        events = tct.load_intrabar_context_events_for_tf(tf, paper_epoch_id="EPOCH_A")
        assert all(e["timeframe"] == tf for e in events)
        assert all(e.get("context_event_id") != f"CTX_{tf.lower()}_other" for e in events)
        foreign_tf = [e for e in events if e["timeframe"] != tf]
        assert foreign_tf == []
        # TF isolation: only this TF's START appears among START events for this TF
        starts = [e for e in events if e["event_type"] == "CONTEXT_START"]
        assert {e["context_event_id"] for e in starts} <= {f"CTX_{tf.lower()}"}
        if tf == "H4":
            ids = {e["context_event_id"] for e in starts}
            assert "CTX_h4" in ids
            assert "CTX_old_epoch" not in ids
            assert "CTX_m15" not in ids
            assert "CTX_m30" not in ids
            assert "CTX_h1" not in ids


def test_context_end_flip_observe_zones(tmp_path, monkeypatch):
    journal = tmp_path / "events.jsonl"
    _write_journal(
        journal,
        [
            {
                "context_event_id": "CTX_start",
                "timeframe": "M15",
                "event_type": "CONTEXT_START",
                "previous_context": "OBSERVE",
                "new_context": "LONG_CONTEXT",
                "event_timestamp": "2026-07-29T10:00:00Z",
                "context_event_price": "1",
                "causal_cutoff_timestamp": "2026-07-29T10:00:00Z",
            },
            {
                "context_event_id": "CTX_flip",
                "timeframe": "M15",
                "event_type": "CONTEXT_FLIP",
                "previous_context": "LONG_CONTEXT",
                "new_context": "SHORT_CONTEXT",
                "event_timestamp": "2026-07-29T10:15:00Z",
                "context_event_price": "2",
                "causal_cutoff_timestamp": "2026-07-29T10:15:00Z",
            },
            {
                "context_event_id": "CTX_end",
                "timeframe": "M15",
                "event_type": "CONTEXT_END",
                "previous_context": "SHORT_CONTEXT",
                "new_context": "OBSERVE",
                "event_timestamp": "2026-07-29T10:30:00Z",
                "context_event_price": "3",
                "causal_cutoff_timestamp": "2026-07-29T10:30:00Z",
            },
        ],
    )
    monkeypatch.setattr(tct, "INTRABAR_CONTEXT_JOURNAL", journal)
    events = tct.load_intrabar_context_events_for_tf("M15")
    assert [e["event_type"] for e in events] == ["CONTEXT_START", "CONTEXT_FLIP", "CONTEXT_END"]
    assert events[0]["event_timestamp"] == "2026-07-29T10:00:00Z"
    zones = tct.build_context_zones_from_events(events)
    assert len(zones) == 2
    assert zones[0]["direction"] == "LONG"
    assert zones[0]["end_reason"] == "CONTEXT_FLIP"
    assert zones[0]["active"] is False
    assert zones[1]["direction"] == "SHORT"
    assert zones[1]["end_reason"] == "CONTEXT_END"
    assert zones[1]["active"] is False
    # OBSERVE end does not open a directional zone
    assert all(z["direction"] in {"LONG", "SHORT"} for z in zones)


def test_renderer_contains_context_and_anchor_helpers():
    js = (ROOT / "apps" / "context_visualizer" / "public" / "lifecycle_app.js").read_text(encoding="utf-8")
    assert "drawContextOverlays" in js
    assert "containingBarIndex" in js
    assert "Контекст" in js
    assert "Цена контекста" in js
    assert "formatContextDetail" in js
    assert "context_events" in js
    assert "bar_anchor_time" in js
    # Must not snap solely via nearest-previous without exact open preference
    assert "Prefer exact containing-bar open match" in js


def test_h4_entry_anchor_contract_matches_context():
    from btc_ml.live.intrabar.partial_bar_state import bar_open_for

    ctx_ts = "2026-07-29T09:40:34.724226Z"
    fill_ts = "2026-07-29T09:40:34.909113Z"
    ctx_anchor = bar_open_for(ctx_ts, "H4").isoformat().replace("+00:00", "Z")
    fill_anchor = bar_open_for(fill_ts, "H4").isoformat().replace("+00:00", "Z")
    assert ctx_anchor.startswith("2026-07-29T08:00:00")
    assert fill_anchor.startswith("2026-07-29T08:00:00")
    assert not ctx_anchor.startswith("2026-07-29T04:00:00")
    assert not fill_anchor.startswith("2026-07-29T04:00:00")
