"""Hybrid sizing: fail-open to canonical risk, scale only when the model can score."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.trading.hybrid_sizing.serve import (
    HybridSizer,
    cross_tf_features,
    ev_multiplier,
    last_closed_ohlc,
)
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


def _fresh(seconds_ago: int = 20) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def test_incomplete_xtf_does_not_score_as_training_book():
    artifacts = Path(__file__).resolve().parents[3] / "config" / "trading" / "hybrid_sizing"
    sizer = HybridSizer(artifacts, enabled=True)
    if sizer._model is None:
        pytest.skip("sizing_model.cbm not loadable in this environment")
    command = {
        "timeframe": "M15",
        "timeframe_direction": "LONG",
        "source_bar_close": "2026-07-01T16:00:00Z",
        "evaluation_timestamp": "2026-07-01T16:00:00Z",
        "context_started_at": "2026-07-01T12:00:00Z",
        "portfolio_open_risk_usd": 0,
        "cross_timeframe_metadata": json.dumps(
            {
                "M15": {
                    "direction": "LONG",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": "ACTIVE",
                },
                "M30": {
                    "direction": "NON_DIRECTIONAL",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": None,
                },
                "H1": {
                    "direction": "NON_DIRECTIONAL",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": None,
                },
                "H4": {
                    "direction": "NON_DIRECTIONAL",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": None,
                },
            }
        ),
    }
    decision = sizer.decide(command, side="LONG", timeframe="M15", stop_loss_bps=100.0, take_profit_bps=150.0)
    assert decision.multiplier == pytest.approx(1.0)
    assert decision.probability is None
    assert decision.reason.startswith("fallback:incomplete_xtf_lifecycle")
    assert decision.xtf_coverage_complete is False
    assert decision.xtf_missing_timeframes == ("M30", "H1", "H4")


def test_complete_xtf_scores_with_frozen_model(tmp_path: Path):
    artifacts = Path(__file__).resolve().parents[3] / "config" / "trading" / "hybrid_sizing"
    sizer = HybridSizer(artifacts, enabled=True)
    if sizer._model is None:
        pytest.skip("sizing_model.cbm not loadable in this environment")
    feed = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-01T15:30:00Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.4,
            },
            {
                "timestamp": "2026-07-01T15:45:00Z",
                "open": 100.4,
                "high": 101.2,
                "low": 100.0,
                "close": 100.8,
            },
        ]
    )
    feed_path = tmp_path / "live_market_feed.parquet"
    feed.to_parquet(feed_path, index=False)
    command = {
        "timeframe": "M15",
        "timeframe_direction": "LONG",
        "source_bar_close": "2026-07-01T16:00:00Z",
        "evaluation_timestamp": "2026-07-01T16:00:00Z",
        "context_started_at": "2026-07-01T12:00:00Z",
        "portfolio_open_risk_usd": 0,
        "cross_timeframe_metadata": json.dumps(
            {
                "M15": {
                    "direction": "LONG",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": "ACTIVE",
                },
                "M30": {
                    "direction": "LONG",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": "ACTIVE",
                },
                "H1": {
                    "direction": "SHORT",
                    "availability": "AVAILABLE_LAST_CONFIRMED",
                    "lifecycle_phase": "CHALLENGED",
                },
                "H4": {
                    "direction": "NON_DIRECTIONAL",
                    "availability": "FRESH_EVENT",
                    "lifecycle_phase": "NO_ACTIVE_CONTEXT",
                },
            }
        ),
    }
    decision = sizer.decide(
        command,
        side="LONG",
        timeframe="M15",
        stop_loss_bps=100.0,
        take_profit_bps=150.0,
        feed_path=feed_path,
    )
    assert decision.reason == "model"
    assert decision.xtf_coverage_complete is True
    assert decision.xtf_missing_timeframes == ()
    assert decision.probability is not None
    assert 0.5 <= float(decision.multiplier) <= 1.5


def test_untagged_lifecycle_parquet_is_incomplete_coverage(tmp_path: Path):
    from btc_ml.trading.hybrid_sizing.serve import lifecycle_parquet_xtf_status

    path = tmp_path / "life.parquet"
    pd.DataFrame({"timestamp": ["2026-07-01T15:45:00Z"], "active_market_context": ["LONG_CONTEXT"]}).to_parquet(
        path, index=False
    )
    status = lifecycle_parquet_xtf_status(path)
    assert status["tagged"] is False
    assert status["complete"] is False
    assert status["counts"]["M15"] == 1
    assert status["counts"]["H4"] == 0


def test_tagged_lifecycle_parquet_is_complete_coverage(tmp_path: Path):
    from btc_ml.trading.hybrid_sizing.serve import lifecycle_parquet_xtf_status

    path = tmp_path / "life.parquet"
    pd.DataFrame(
        {
            "timestamp": ["2026-07-01T15:45:00Z"] * 4,
            "timeframe": ["M15", "M30", "H1", "H4"],
        }
    ).to_parquet(path, index=False)
    status = lifecycle_parquet_xtf_status(path)
    assert status["complete"] is True
    assert status["counts"]["H4"] == 1


def test_cross_tf_agreement_counts():
    meta = {
        "M15": {"direction": "LONG", "availability": "FRESH_EVENT", "lifecycle_phase": "ACTIVE"},
        "M30": {"direction": "LONG", "availability": "FRESH_EVENT", "lifecycle_phase": "ACTIVE"},
        "H1": {"direction": "SHORT", "availability": "FRESH_EVENT", "lifecycle_phase": "CHALLENGED"},
        "H4": {"direction": "NON_DIRECTIONAL", "availability": "FRESH_EVENT", "lifecycle_phase": "NO_ACTIVE_CONTEXT"},
    }
    row = cross_tf_features(meta, own_tf="M15", own_dir="LONG")
    assert row["xtf_agree_n"] == 1
    assert row["xtf_disagree_n"] == 1
    assert row["xtf_neutral_n"] == 1
    assert row["xtf_active_n"] == 2
    assert row["xtf_net_agreement"] == 0


def test_ev_multiplier_clips():
    # EV at p=0.7153 with freeze payoffs is ~0.494; ratio 1.0 sits at the book rate.
    mid = ev_multiplier(0.7153, avg_win_r=0.9652, avg_loss_r=-0.6894, clip_lo=0.5, clip_hi=1.5, ev_scale_r=0.4941)
    assert mid == pytest.approx(1.0, abs=0.02)
    low = ev_multiplier(0.31, avg_win_r=0.9652, avg_loss_r=-0.6894, clip_lo=0.5, clip_hi=1.5, ev_scale_r=0.4941)
    high = ev_multiplier(0.94, avg_win_r=0.9652, avg_loss_r=-0.6894, clip_lo=0.5, clip_hi=1.5, ev_scale_r=0.4941)
    assert low == 0.5
    assert high == 1.5
    assert ev_multiplier(0.0, avg_win_r=0.9652, avg_loss_r=-0.6894, clip_lo=0.5, clip_hi=1.5, ev_scale_r=0.4941) is None


def test_last_closed_bar_does_not_use_forming_bar():
    # Cutoff 20:45. Forming M15 bar opens at 20:45; causal bar opens at 20:30.
    rows = [
        {"timestamp": "2026-01-01T20:15:00Z", "open": 1.0, "high": 3.0, "low": 0.5, "close": 2.0},
        {"timestamp": "2026-01-01T20:30:00Z", "open": 2.0, "high": 4.0, "low": 1.5, "close": 3.5},
        {"timestamp": "2026-01-01T20:45:00Z", "open": 3.5, "high": 9.0, "low": 3.0, "close": 8.0},
    ]
    feed = pd.DataFrame(rows)
    cutoff = pd.Timestamp("2026-01-01T20:45:00Z", tz="UTC")
    ohlc = last_closed_ohlc(feed, timeframe="M15", cutoff=cutoff)
    assert ohlc is not None
    assert ohlc["close"] == 3.5


@pytest.fixture
def engine_cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["entry_source"] = "s41_command_bus"
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n")
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo / "config" / "intrabar_paper_execution.json", repo_root=repo)
    return cfg, repo


def _engine(cfg) -> IntrabarPaperEngine:
    ep = create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="SZ20260907")
    ep = activate_epoch(ep, epochs_root=cfg.epochs_root)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    import time as time_mod

    now = time_mod.monotonic_ns()
    eng.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="live",
    )
    return eng


def _open_cmd(command_id: str = "TF_CMD_sz") -> dict:
    return {
        "command_id": command_id,
        "timeframe": "M15",
        "intent": "OPEN_LONG",
        "action_allowed": True,
        "lifecycle_episode_id": "M15:sz",
        "evaluation_timestamp": _fresh(20),
        "context_origin_price": 100.1,
    }


def test_missing_model_keeps_canonical_quantity(engine_cfg):
    cfg, _ = engine_cfg
    eng = _engine(cfg)
    result = eng.apply_s41_manager_command(_open_cmd())
    assert result["status"] == "ENTERED"
    pos = eng.books.open_positions()[0]
    assert pos["sizing_reason"].startswith("fallback:")
    assert pos["sizing_multiplier"] == pytest.approx(1.0)
    # Canonical 1% of 100k with 100 bps stop on a ~100.2 fill.
    assert pos["risk_amount_usd"] == pytest.approx(1000.0, rel=0.05)


def test_multiplier_scales_risk_budget(engine_cfg):
    cfg, _ = engine_cfg
    eng = _engine(cfg)

    class _Fixed:
        def decide(self, *args, **kwargs):
            from btc_ml.trading.hybrid_sizing.serve import SizingDecision

            return SizingDecision(1.5, 0.9, "model", {})

    eng.sizer = _Fixed()
    result = eng.apply_s41_manager_command(_open_cmd("TF_CMD_scaled"))
    assert result["status"] == "ENTERED"
    pos = eng.books.open_positions()[0]
    assert pos["sizing_multiplier"] == pytest.approx(1.5)
    assert pos["risk_amount_usd"] == pytest.approx(1500.0, rel=0.05)
    assert pos["canonical_risk_budget_usd"] == pytest.approx(1000.0, rel=0.05)
