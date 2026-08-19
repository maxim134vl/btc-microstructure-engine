"""Same directional episode may OPEN again after the slot is free."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.proofs import build_synthetic_feed, isolated_environment  # noqa: E402
from btc_ml.trading.timeframe_manager import TimeframeManager  # noqa: E402

from test_s4_1_manager_independent_timeframe_traders import synthetic_sources  # noqa: E402


def test_manager_reopens_same_episode_on_later_cycle_when_flat(tmp_path, monkeypatch):
    monkeypatch.setattr(
        TimeframeManager,
        "_use_live1b_position_views",
        staticmethod(lambda: False),
    )
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    kwargs = dict(
        sources=synthetic_sources(),
        feed=build_synthetic_feed(),
        persist=True,
    )
    first = manager.run_cycle(evaluation_timestamp="2026-07-01T04:00:00Z", **kwargs)
    second = manager.run_cycle(evaluation_timestamp="2026-07-01T04:15:00Z", **kwargs)
    m15_first = next(cmd for cmd in first["commands"] if cmd["timeframe"] == "M15")
    m15_second = next(cmd for cmd in second["commands"] if cmd["timeframe"] == "M15")
    assert m15_first["intent"] == "OPEN_LONG"
    assert m15_second["intent"] == "OPEN_LONG"
    assert "EPISODE_ALREADY_TRADED" not in m15_second["reason_codes"]
    assert m15_first["command_id"] != m15_second["command_id"]
