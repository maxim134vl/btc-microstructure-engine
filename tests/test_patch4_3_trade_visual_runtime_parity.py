#!/usr/bin/env python3
"""Patch 4.3 §19 — trade visual runtime parity contract.

These tests assert semantic invariants of the trade visual, never a historical
snapshot: no live context ID, trade count or episode number is hardcoded, so a
new live trade or a new context episode can not break them.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.visual.canonical_trade_view import (  # noqa: E402
    ECONOMICS_VERSION,
    LEGACY_TIMEFRAME,
    activation_boundary,
    build_canonical_visual_trades,
    legacy_archive_dir,
    reconcile,
    utc_series,
    utc_stamp,
)

PUBLIC_DATA = ROOT / "apps/context_visualizer/public/data"
OVERLAYS = PUBLIC_DATA / "paper_trade_overlays.json"
RENDER_LAYER = PUBLIC_DATA / "normalized_trade_render_layer.json"
PNL_SUMMARY = PUBLIC_DATA / "pnl_summary.json"
CANONICAL_VIEW = ROOT / "data/research/paper_simulator/canonical_visual_trade_view.parquet"
REFRESHER = ROOT / "scripts/live/run_market_context_visual_refresher.py"
VIEW_BUILDER = ROOT / "src/btc_ml/visual/canonical_trade_view.py"
LIFECYCLE_MEMORY = ROOT / "data/cognition/market_context_lifecycle_memory.parquet"
TRADER_BOOKS = ROOT / "data/trading/timeframe_traders"
MANAGER_COMMANDS = ROOT / "data/trading/manager/timeframe_command_memory.parquet"
VIEWER_CSS = ROOT / "apps/context_visualizer/public/lifecycle.css"
VIEWER_HTML = ROOT / "apps/context_visualizer/public/index.html"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def overlays() -> dict:
    return _json(OVERLAYS)


@pytest.fixture(scope="module")
def shapes(overlays: dict) -> list[dict]:
    return [row for row in (overlays.get("trade_shapes") or []) if isinstance(row, dict)]


@pytest.fixture(scope="module")
def view() -> pd.DataFrame:
    return build_canonical_visual_trades()


# 1. production visual source contract -------------------------------------


def test_01_production_visual_source_is_canonical_view(overlays: dict) -> None:
    assert overlays["source_closed"].endswith("canonical_visual_trade_view.parquet")
    assert overlays["controller_ledger_used_for_render"] is True


def test_02_legacy_archive_remains_read_only() -> None:
    archive = legacy_archive_dir()
    assert archive is not None and archive.exists()
    parquets = sorted(archive.glob("*.parquet"))
    assert parquets
    for path in parquets:
        assert not path.stat().st_mode & 0o200, f"legacy archive writable: {path.name}"


def test_03_research_files_remain_writable() -> None:
    assert CANONICAL_VIEW.exists()
    assert CANONICAL_VIEW.stat().st_mode & 0o200


# 4-6. dynamic context identifiers -----------------------------------------


def test_04_context_ids_are_dynamic_and_resolvable(view: pd.DataFrame) -> None:
    episodes = pd.read_parquet(LIFECYCLE_MEMORY, columns=["context_episode_id"])
    known = {
        str(int(value))
        for value in episodes["context_episode_id"].dropna().tolist()
    }
    for _, row in view.iterrows():
        episode = row["context_episode_id"]
        if episode is None:
            continue
        assert str(episode) in known, f"context episode {episode} not in lifecycle memory"


def test_05_no_hardcoded_live_context_id_in_parity_sources() -> None:
    """Live context numbers must not be pinned in the render path."""
    for path in (REFRESHER, VIEW_BUILDER, Path(__file__)):
        text = path.read_text(encoding="utf-8")
        for literal in ("712", "715", "721", "740"):
            assert not re.search(rf"CONTEXT_ID\s*=\s*{literal}\b", text)
            assert f"POLICY_CONTEXT_TRADE_{literal}" not in text


def test_06_synthetic_fixture_ids_still_supported() -> None:
    """A fully synthetic row keeps its own identifiers through the contract."""
    from btc_ml.visual import canonical_trade_view as ctv

    row = ctv._row(
        visual_trade_id="VIS_SYNTHETIC_1",
        source_trade_id="SYNTHETIC_1",
        source_book="SYNTHETIC",
        source_schema_version="synthetic_v1",
        timeframe="M15",
        side="LONG",
        entry_ts="2026-01-01T00:00:00Z",
        exit_ts="2026-01-01T01:00:00Z",
        entry_price=100.0,
        exit_price=110.0,
        quantity=1.0,
        gross_pnl=10.0,
        fees_paid=1.0,
        slippage_paid=1.0,
        net_pnl=8.0,
        context_episode_id="999999",
        lifecycle_episode_id=None,
        manager_command_id="CMD_1",
        position_id="POS_1",
        lineage_status="S4_TIMEFRAME_LINEAGE",
        activation_epoch="POST_S4_ACTIVATION",
        stop_loss_price=95.0,
        take_profit_price=120.0,
        notional_usd=100.0,
        r_multiple=None,
        entry_price_source="TEST",
        exit_price_source="TEST",
        exit_reason="TEST",
    )
    assert row["context_episode_id"] == "999999"
    assert row["economics_version"] == ECONOMICS_VERSION


# 7-10. dynamic trade count -------------------------------------------------


def test_07_trade_count_matches_canonical_source(shapes: list[dict], view: pd.DataFrame) -> None:
    assert len(shapes) == len(view)


def test_08_no_hardcoded_production_trade_count(overlays: dict, view: pd.DataFrame) -> None:
    counts = overlays.get("counts") or {}
    assert counts["visual_trade_overlay_count_expected"] == len(view)
    assert counts["visual_trade_overlay_count_rendered"] == len(view)


def test_09_unique_eligible_source_count_equals_payload(shapes: list[dict], view: pd.DataFrame) -> None:
    assert len({row["trade_id"] for row in shapes}) == view["visual_trade_id"].nunique()


def test_10_duplicate_visual_trade_ids_absent(view: pd.DataFrame) -> None:
    assert reconcile(view)["duplicate_visual_trade_ids"] == 0


# 11-14. cutover and lineage -----------------------------------------------


def test_11_legacy_and_s4_cutover_do_not_overlap(view: pd.DataFrame) -> None:
    report = reconcile(view)
    assert report["cutover_overlap"] == 0
    assert report["activation_boundary"] == activation_boundary()


def test_12_legacy_trade_remains_legacy_global(view: pd.DataFrame) -> None:
    legacy = view[view["activation_epoch"] == "PRE_S4_ACTIVATION"]
    if not len(legacy):
        pytest.skip("no legacy history in the view")
    assert set(legacy["timeframe"]) == {LEGACY_TIMEFRAME}
    assert legacy["manager_command_id"].isna().all()


def test_13_s4_trade_preserves_timeframe(view: pd.DataFrame) -> None:
    s4 = view[view["activation_epoch"] == "POST_S4_ACTIVATION"]
    if not len(s4):
        pytest.skip("timeframe trader tail is still empty")
    assert set(s4["timeframe"]).issubset({"M15", "M30", "H1", "H4"})
    assert s4["lineage_status"].eq("S4_TIMEFRAME_LINEAGE").all()


def test_14_open_position_not_rendered_as_closed(view: pd.DataFrame, shapes: list[dict]) -> None:
    assert view["exit_timestamp"].notna().all()
    for shape in shapes:
        if str(shape.get("status") or "").upper() == "CLOSED":
            assert shape.get("exit_ts")


# 15-18. point-in-time parity ----------------------------------------------


def test_15_source_trade_lineage_exists(view: pd.DataFrame) -> None:
    assert view["source_trade_id"].notna().all()
    assert view["source_book"].notna().all()


def test_16_context_lineage_exists(view: pd.DataFrame) -> None:
    assert view["lineage_status"].notna().all()


def test_17_no_future_context_join(view: pd.DataFrame) -> None:
    lifecycle = pd.read_parquet(LIFECYCLE_MEMORY, columns=["timestamp", "context_episode_id"])
    lifecycle["timestamp"] = utc_series(lifecycle["timestamp"])
    for _, row in view.iterrows():
        episode = row["context_episode_id"]
        if episode is None:
            continue
        first_seen = lifecycle.loc[
            lifecycle["context_episode_id"].astype("Float64")
            == pd.to_numeric(episode, errors="coerce"),
            "timestamp",
        ].min()
        entry = utc_stamp(row["entry_timestamp"])
        assert first_seen <= entry, f"{row['visual_trade_id']} joined a future context"


def test_18_no_future_trade_join(view: pd.DataFrame) -> None:
    entry = utc_series(view["entry_timestamp"])
    exit_ = utc_series(view["exit_timestamp"])
    assert (entry < exit_).all()


# 19-25. economics parity ---------------------------------------------------


def test_19_canonical_economics_version(overlays: dict) -> None:
    assert overlays["economics_version"] == ECONOMICS_VERSION
    summary = _json(PNL_SUMMARY)
    assert summary["pnl_mode"] == ECONOMICS_VERSION
    assert summary["accounting_mode"] == ECONOMICS_VERSION


def test_20_visual_does_not_recompute_pnl(shapes: list[dict], view: pd.DataFrame) -> None:
    ledger = {row["visual_trade_id"]: row for _, row in view.iterrows()}
    for shape in shapes:
        source = ledger.get(shape["trade_id"])
        assert source is not None
        assert shape.get("copied_canonical_economics") is not False
        assert abs(float(shape["net_realized_pnl_usd"]) - float(source["net_pnl"])) < 1e-6


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_21_22_directional_pnl_parity(view: pd.DataFrame, side: str) -> None:
    rows = view[view["side"] == side]
    if not len(rows):
        pytest.skip(f"no {side} trade in the canonical view")
    for _, row in rows.iterrows():
        expected = (
            (row["exit_price"] - row["entry_price"]) * row["quantity"]
            if side == "LONG"
            else (row["entry_price"] - row["exit_price"]) * row["quantity"]
        )
        assert abs(float(row["gross_pnl"]) - expected) < 1e-6


def test_23_fees_parity(shapes: list[dict], view: pd.DataFrame) -> None:
    ledger = {row["visual_trade_id"]: row for _, row in view.iterrows()}
    for shape in shapes:
        assert abs(float(shape["fees_usd"]) - float(ledger[shape["trade_id"]]["fees_paid"])) < 1e-6


def test_24_slippage_parity(shapes: list[dict], view: pd.DataFrame) -> None:
    ledger = {row["visual_trade_id"]: row for _, row in view.iterrows()}
    for shape in shapes:
        assert (
            abs(float(shape["slippage_usd"]) - float(ledger[shape["trade_id"]]["slippage_paid"]))
            < 1e-6
        )


def test_25_net_pnl_identity(view: pd.DataFrame) -> None:
    assert reconcile(view)["pnl_reconciliation_errors"] == 0


# 26-31. determinism and no mutation ---------------------------------------


def test_26_payload_deterministic() -> None:
    first = build_canonical_visual_trades()
    second = build_canonical_visual_trades()
    pd.testing.assert_frame_equal(first, second)


def test_27_repeated_refresh_idempotent() -> None:
    from btc_ml.visual.canonical_trade_view import write_canonical_visual_trades

    before = build_canonical_visual_trades()
    write_canonical_visual_trades()
    after = build_canonical_visual_trades()
    pd.testing.assert_frame_equal(before, after)


def test_28_no_ledger_mutation() -> None:
    archive = legacy_archive_dir()
    assert archive is not None
    before = {p.name: p.stat().st_mtime for p in sorted(archive.glob("*.parquet"))}
    build_canonical_visual_trades()
    after = {p.name: p.stat().st_mtime for p in sorted(archive.glob("*.parquet"))}
    assert before == after


def test_29_no_manager_command_mutation() -> None:
    if not MANAGER_COMMANDS.exists():
        pytest.skip("manager command memory not present")
    before = MANAGER_COMMANDS.stat().st_mtime
    build_canonical_visual_trades()
    assert MANAGER_COMMANDS.stat().st_mtime == before


def test_30_no_trader_book_mutation() -> None:
    books = sorted(TRADER_BOOKS.glob("*/*.parquet"))
    before = {str(p): p.stat().st_mtime for p in books}
    build_canonical_visual_trades()
    after = {str(p): p.stat().st_mtime for p in books}
    assert before == after


def test_31_visual_refresher_reports_live_ok() -> None:
    status = PUBLIC_DATA / "visual_runtime_status.json"
    if not status.exists():
        pytest.skip("visual runtime status not exported")
    assert _json(status).get("visual_status") in {"LIVE_OK", "SOURCE_WAITING_NO_NEW_BAR"}


# 32-35. frontend and visual preservation ----------------------------------


def test_32_frontend_receives_legacy_timeframe(shapes: list[dict]) -> None:
    for shape in shapes:
        assert shape.get("timeframe")
        assert shape["timeframe"] in {LEGACY_TIMEFRAME, "M15", "M30", "H1", "H4"}


def test_33_nullable_fields_are_null_not_undefined(shapes: list[dict]) -> None:
    raw = OVERLAYS.read_text(encoding="utf-8")
    assert "undefined" not in raw
    for shape in shapes:
        assert "manager_command_id" in shape


def test_34_visual_css_unchanged() -> None:
    baseline = ROOT / "data/research/patch4_3_visual_baseline_20260724_184231.json"
    if not baseline.exists():
        pytest.skip("visual baseline artifact missing")
    import hashlib

    recorded = _json(baseline)
    for rel, digest in (recorded.get("css_sha256") or {}).items():
        path = ROOT / rel
        if not path.exists():
            continue
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"CSS changed: {rel}"


def test_35_chart_design_unchanged() -> None:
    html = VIEWER_HTML.read_text(encoding="utf-8")
    assert "lifecycle_app.js" in html
    assert VIEWER_CSS.exists()


# 36-39. safety flags -------------------------------------------------------


def test_36_no_exchange_calls() -> None:
    text = VIEW_BUILDER.read_text(encoding="utf-8")
    for forbidden in ("binance", "requests.post", "create_order", "api_key"):
        assert forbidden not in text.lower()


def test_37_real_execution_disabled(view: pd.DataFrame) -> None:
    if not len(view):
        pytest.skip("empty view")
    assert view["paper_only"].all()
    assert not view["execution_enabled"].any()


def test_38_continuation_off() -> None:
    import os

    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"


def test_39_price_gate_off() -> None:
    import os

    assert os.environ.get("PRICE_GATE", "OFF").upper() == "OFF"
