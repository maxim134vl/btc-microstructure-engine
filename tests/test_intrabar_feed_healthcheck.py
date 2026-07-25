#!/usr/bin/env python3
"""Healthcheck behavior tests for intrabar feed ctl."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "scripts/intrabar_feed_ctl.sh"


def test_healthcheck_command_exists():
    text = CTL.read_text(encoding="utf-8")
    assert "healthcheck)" in text
    assert "healthcheck=PASS" in text
    assert "healthcheck=FAIL" in text
    assert "STALE_DATA" in text


def test_healthcheck_requires_running_and_fresh():
    text = CTL.read_text(encoding="utf-8")
    assert "age >= 150" in text
    assert 'status != "RUNNING"' in text or "NOT_RUNNING" in text


def test_healthcheck_flags_duplicate_orphan():
    text = CTL.read_text(encoding="utf-8")
    assert "DUPLICATE_PROCESS" in text
    assert "ORPHAN_PROCESS" in text
