"""Policy unit tests — pure functions, no I/O."""

from __future__ import annotations

from btc_watchdog.policies import (
    Action,
    decide_dead_collector,
    decide_reconnect_storm,
    decide_stall,
)
from btc_watchdog.state import CircuitBreaker, RestartBudget


def test_stall_below_threshold_no_action() -> None:
    assert decide_stall(60.0, 120) == []


def test_stall_above_threshold_emits_restart() -> None:
    actions = decide_stall(300.0, 120)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "restart"
    assert a.target == "btc_pipeline"
    assert a.policy == "stall-detect"


def test_stall_with_none_iter_age() -> None:
    assert decide_stall(None, 120) == []


def test_reconnect_storm_fires_per_feed_above_threshold() -> None:
    actions = decide_reconnect_storm({"binance": 20.0, "okx": 0.5}, threshold=10.0)
    assert {a.target for a in actions} == {"binance"}
    assert actions[0].kind == "trip_circuit"


def test_dead_collector_requires_threshold_passed() -> None:
    # threshold_passed=False suppresses everything
    assert decide_dead_collector({"btc_orderbook": 0.0}, threshold_passed=False) == []
    # threshold_passed=True + up==0 -> action
    a = decide_dead_collector({"btc_orderbook": 0.0, "btc_oi": 1.0}, threshold_passed=True)
    assert len(a) == 1
    assert a[0].target == "btc_orderbook"


def test_budget_exhausts_at_max() -> None:
    b = RestartBudget(3, window_seconds=3600)
    assert b.try_consume()
    assert b.try_consume()
    assert b.try_consume()
    assert not b.try_consume()
    assert b.used() == 3


def test_circuit_open_then_auto_close() -> None:
    cb = CircuitBreaker(cooloff_seconds=0)  # immediate cooloff
    cb.trip("feed-x")
    assert not cb.is_open("feed-x")        # cooloff is 0 -> already closed


def test_circuit_reset_returns_true_if_was_open() -> None:
    cb = CircuitBreaker(cooloff_seconds=3600)
    cb.trip("feed-x")
    assert cb.is_open("feed-x")
    assert cb.reset("feed-x") is True
    assert not cb.is_open("feed-x")
    assert cb.reset("feed-x") is False     # no-op on already-closed
