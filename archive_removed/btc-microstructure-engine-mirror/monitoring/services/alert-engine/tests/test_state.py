"""Unit tests for the Redis-backed AlertState. Uses fakeredis."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from btc_alert_engine.state import AlertState, fingerprint


@pytest.fixture
async def state() -> AlertState:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AlertState(client)


def test_fingerprint_is_stable_under_label_reorder() -> None:
    a = {"labels": {"alertname": "X", "a": "1", "b": "2"}}
    b = {"labels": {"alertname": "X", "b": "2", "a": "1"}}
    assert fingerprint(a) == fingerprint(b)


def test_fingerprint_differs_with_labels() -> None:
    a = {"labels": {"alertname": "X", "instance": "i1"}}
    b = {"labels": {"alertname": "X", "instance": "i2"}}
    assert fingerprint(a) != fingerprint(b)


@pytest.mark.asyncio
async def test_cooldown_round_trip(state: AlertState) -> None:
    fp = "abc123"
    assert not await state.is_in_cooldown(fp)
    await state.mark_active(fp, {"hi": "there"}, cooldown_s=60)
    assert await state.is_in_cooldown(fp)


@pytest.mark.asyncio
async def test_list_active_returns_payloads(state: AlertState) -> None:
    await state.mark_active("a", {"alertname": "A"}, cooldown_s=60)
    await state.mark_active("b", {"alertname": "B"}, cooldown_s=60)
    active = await state.list_active()
    names = sorted(a.get("alertname") for a in active)
    assert names == ["A", "B"]


@pytest.mark.asyncio
async def test_resolve_clears_active_but_keeps_cooldown(state: AlertState) -> None:
    fp = "z"
    await state.mark_active(fp, {"alertname": "Z"}, cooldown_s=60)
    await state.mark_resolved(fp)
    assert await state.is_in_cooldown(fp)         # cooldown still in effect
    assert not await state.list_active()           # but no longer "active"
