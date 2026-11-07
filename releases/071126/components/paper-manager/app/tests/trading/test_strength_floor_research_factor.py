"""Default strength floor stays 0.5 x timeframe weight.

An explicit research factor changes only the call that passes it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from btc_ml.cognition.living_market_process import TRADE_STRENGTH_FLOOR, trade_strength_floor
from btc_ml.trading.anti_saw_path_density import _parse_cfg
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
from btc_ml.trading.proofs import isolated_environment
from btc_ml.trading.timeframe_manager import (
    PROCESS_STRENGTH_TOO_WEAK,
    TimeframeManager,
    _strength_too_weak,
)
from btc_ml.trading.timeframe_state_adapter import TimeframeSources
from tests.trading.test_s41_same_bar_redecision import (
    _availability,
    _feed_from,
    _intents,
    _life,
    _reasons,
)


def _apply_research_policy():
    path = ROOT / "scripts" / "research" / "run_etll_hybrid_tick_lived_replay.py"
    spec = importlib.util.spec_from_file_location("etll_hybrid_tick_lived_replay", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.apply_research_policy


def test_default_floors_match_the_book_policy():
    assert TRADE_STRENGTH_FLOOR == 0.5
    assert trade_strength_floor("M15") == 0.5
    assert trade_strength_floor("M30") == 0.75
    assert trade_strength_floor("H1") == 1.0
    assert trade_strength_floor("H4") == 2.0
    assert trade_strength_floor("H4", factor=0.5) == trade_strength_floor("H4")


def test_explicit_factor_is_opt_in():
    assert _strength_too_weak({"process_strength": 0.3}, "M15") is True
    assert _strength_too_weak({"process_strength": 0.3}, "M15", factor=0.2) is False
    assert _strength_too_weak({"process_strength": 0.3}, "H4") is True
    assert trade_strength_floor("H4", factor=0.25) == 1.0


def test_omitted_saw_overrides_keep_config_thresholds():
    raw = json.loads((ROOT / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    block = dict(raw["anti_saw_path_density"])
    factor, updated = _apply_research_policy()(
        block,
        strength_multiplier=None,
        saw_overrides={
            "balance_support_enter": None,
            "balance_max_net_disp_ratio": None,
            "min_path_atr": None,
            "min_failed_breakouts": None,
            "volume_two_sided_enter": None,
            "auction_balance_share": None,
        },
    )
    assert factor is None
    assert updated["balance_support_enter"] == 0.55
    assert updated["balance_max_net_disp_ratio"] == 0.40
    assert updated["min_path_atr"] == 2.0
    assert updated["min_failed_breakouts"] == 1
    parsed = _parse_cfg({"anti_saw_path_density": updated})
    assert parsed["balance_support_enter"] == 0.55
    assert parsed["min_path_atr"] == 2.0


def test_named_saw_override_changes_only_that_key():
    raw = json.loads((ROOT / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))
    _, updated = _apply_research_policy()(
        dict(raw["anti_saw_path_density"]),
        strength_multiplier=0.35,
        saw_overrides={"min_path_atr": 3.0, "balance_support_enter": None},
    )
    assert updated["min_path_atr"] == 3.0
    assert updated["balance_support_enter"] == 0.55


def test_manager_default_blocks_m15_strength_0_3(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    assert manager.strength_floor_factor is None
    cycle = _m15_cycle(manager, strength=0.3)
    assert "OPEN_LONG" not in _intents(cycle, "M15")
    assert PROCESS_STRENGTH_TOO_WEAK in _reasons(cycle, "M15")


def test_manager_research_factor_can_allow_the_same_row(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
        strength_floor_factor=0.2,
    )
    cycle = _m15_cycle(manager, strength=0.3)
    assert "OPEN_LONG" in _intents(cycle, "M15")
    assert PROCESS_STRENGTH_TOO_WEAK not in _reasons(cycle, "M15")


def _m15_cycle(manager: TimeframeManager, *, strength: float) -> dict:
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-09-16T07:00:00Z",
                    bar_open="2026-09-16T06:45:00Z",
                    bar_close="2026-09-16T07:00:00Z",
                )
            ]
        ),
        lifecycle=pd.DataFrame(
            [
                _life(
                    ts="2026-09-16T06:45:00Z",
                    tf="M15",
                    context="LONG_CONTEXT",
                    episode=360,
                    started="2026-09-16T03:15:00Z",
                    raw_status="ACTIVE",
                    process_strength=strength,
                )
            ]
        ),
        lifecycle_source="parquet",
    )
    return manager.run_cycle(
        evaluation_timestamp="2026-09-16T07:00:00Z",
        sources=sources,
        feed=_feed_from("2026-09-16T05:00:00Z"),
        persist=True,
        now="2026-09-16T07:01:00Z",
        decision_index={},
    )
