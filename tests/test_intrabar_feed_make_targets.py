#!/usr/bin/env python3
"""Makefile / ctl targets for intrabar feed."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_makefile_has_intrabar_targets():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    for t in (
        "intrabar-feed-start:",
        "intrabar-feed-stop:",
        "intrabar-feed-status:",
        "intrabar-feed-tail:",
        "intrabar-feed-restart:",
        "intrabar-feed-healthcheck:",
    ):
        assert t in text


def test_ctl_script_exists_and_commands():
    ctl = ROOT / "scripts/intrabar_feed_ctl.sh"
    assert ctl.exists()
    text = ctl.read_text(encoding="utf-8")
    assert "start)" in text
    assert "stop)" in text
    assert "status)" in text
    assert "tail)" in text
    assert "restart)" in text
    assert "live_binance_intrabar_feed.py" in text
    assert "estimated_cadence_seconds" in text
    assert "seconds_since_latest_row" in text
    assert "--daemonize" in text
    assert "$(setsid" not in text


def test_runtime_stack_not_auto_attached():
    # Ensure intrabar feed is not wired into runtime_stack.sh start by default.
    rs = (ROOT / "scripts/runtime_stack.sh").read_text(encoding="utf-8")
    assert "live_binance_intrabar_feed" not in rs
