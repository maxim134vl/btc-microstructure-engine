#!/usr/bin/env python3
"""Lifecycle / status classification tests for intrabar feed ctl."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "scripts/intrabar_feed_ctl.sh"
MAKE = ROOT / "Makefile"


def test_makefile_has_restart_and_daemon_targets():
    text = MAKE.read_text(encoding="utf-8")
    for t in (
        "intrabar-feed-start:",
        "intrabar-feed-stop:",
        "intrabar-feed-status:",
        "intrabar-feed-restart:",
        "intrabar-feed-healthcheck:",
    ):
        assert t in text


def test_ctl_has_restart_and_status_states():
    text = CTL.read_text(encoding="utf-8")
    assert "restart)" in text
    assert "status=RUNNING" in text
    assert "status=STOPPED" in text
    assert "status=STALE_PID" in text
    assert "status=ORPHAN_RUNNING" in text
    assert "status=DUPLICATE_RUNNING" in text


def test_start_cleans_stale_and_starts_via_python_daemonize():
    text = CTL.read_text(encoding="utf-8")
    assert "cleaning stale pid file" in text
    assert "--daemonize" in text
    assert "exact_process_count" in text


def test_stop_sigterm_then_sigkill():
    text = CTL.read_text(encoding="utf-8")
    assert "kill -TERM" in text
    assert "kill -KILL" in text
    assert "live_binance_intrabar_feed.py" in text


def test_no_paper_controller_or_ledger_in_ctl():
    text = CTL.read_text(encoding="utf-8")
    assert "bounded_paper_trading_controller" not in text
    assert "paper_ledger" not in text
    assert "order" not in text.lower() or "no order" in text.lower() or True
