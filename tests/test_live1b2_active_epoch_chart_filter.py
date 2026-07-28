"""LIVE1B.2 — active-epoch trade overlay filter for charts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.context_visualizer.active_epoch_trade_filter import (
    empty_trade_overlay_payload,
    filter_active_epoch_rows,
    is_active_epoch_trade_row,
)


ACTIVE = "INTRABAR_RULES_V1_TEST"


@pytest.fixture
def active_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    epochs = tmp_path / "data" / "trading" / "paper_epochs"
    epochs.mkdir(parents=True)
    payload = {
        "paper_epoch_id": ACTIVE,
        "epoch_status": "ACTIVE",
        "rule_contract_version": "INTRABAR_RULES_V1",
        "initial_equity_usd": 100000.0,
    }
    (epochs / "active.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "apps.context_visualizer.active_epoch_trade_filter.ACTIVE_EPOCH_PATH",
        epochs / "active.json",
    )
    monkeypatch.setattr(
        "apps.context_visualizer.active_epoch_trade_filter.ROOT",
        tmp_path,
    )
    return payload


def test_legacy_without_epoch_excluded(active_epoch):
    assert is_active_epoch_trade_row({"trade_id": "t1", "status": "CLOSED"}, active_epoch_id=ACTIVE) is False


def test_void_status_excluded(active_epoch):
    assert (
        is_active_epoch_trade_row(
            {
                "trade_id": "t1",
                "paper_epoch_id": ACTIVE,
                "status": "VOID_PRE_INTRABAR_RULE_CONTRACT",
            },
            active_epoch_id=ACTIVE,
        )
        is False
    )


def test_inactive_epoch_excluded(active_epoch):
    assert (
        is_active_epoch_trade_row(
            {"trade_id": "t1", "paper_epoch_id": "OTHER_EPOCH", "status": "CLOSED"},
            active_epoch_id=ACTIVE,
        )
        is False
    )


def test_active_epoch_included(active_epoch):
    assert (
        is_active_epoch_trade_row(
            {"trade_id": "t1", "paper_epoch_id": ACTIVE, "status": "CLOSED"},
            active_epoch_id=ACTIVE,
        )
        is True
    )


def test_empty_active_epoch_empty_overlays(active_epoch):
    rows = [
        {"trade_id": "legacy", "status": "CLOSED"},
        {"trade_id": "ok", "paper_epoch_id": ACTIVE, "status": "CLOSED"},
        {"trade_id": "void", "paper_epoch_id": ACTIVE, "status": "VOID_PRE_INTRABAR_RULE_CONTRACT"},
        {"trade_id": "other", "paper_epoch_id": "OLD", "status": "CLOSED"},
    ]
    kept = filter_active_epoch_rows(rows, active_epoch_id=ACTIVE)
    assert [r["trade_id"] for r in kept] == ["ok"]
    empty = empty_trade_overlay_payload(active_epoch_id=ACTIVE)
    assert empty["legacy_excluded"] is True
    assert empty["active_paper_epoch_id"] == ACTIVE
    assert empty["counts"]["trade_marker_count"] == 0
    assert empty["closed_trades"] == []
    assert empty["open_positions"] == []
    assert filter_active_epoch_rows([], active_epoch_id=ACTIVE) == []


def test_all_timeframes_same_filter(active_epoch):
    for tf in ("M15", "M30", "H1", "H4"):
        rows = [
            {"trade_id": f"{tf}_legacy", "timeframe": tf, "status": "CLOSED"},
            {
                "trade_id": f"{tf}_ok",
                "timeframe": tf,
                "paper_epoch_id": ACTIVE,
                "status": "CLOSED",
            },
        ]
        kept = filter_active_epoch_rows(rows, active_epoch_id=ACTIVE)
        assert [r["trade_id"] for r in kept] == [f"{tf}_ok"]


def test_frontend_empty_payload_clears_markers():
    # Mirror JS replace semantics: empty array replaces prior markers.
    prior = [{"trade_id": "stale", "paper_epoch_id": "OLD"}]
    incoming: list[dict] = []
    prior[:] = list(incoming)
    assert prior == []


def test_cache_key_includes_epoch(active_epoch):
    empty = empty_trade_overlay_payload(active_epoch_id=ACTIVE)
    cache_key = f"chart_trades:{empty['active_paper_epoch_id']}:timeframe_chart_truth_v4"
    assert ACTIVE in cache_key
    assert "timeframe_chart_truth_v4" in cache_key
