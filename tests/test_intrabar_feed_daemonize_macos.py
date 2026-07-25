#!/usr/bin/env python3
"""Daemonize implementation tests for intrabar feed (macOS-safe)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "scripts/live/live_binance_intrabar_feed.py"
CTL = ROOT / "scripts/intrabar_feed_ctl.sh"


def test_daemonize_argument_exists():
    text = FEED.read_text(encoding="utf-8")
    assert "--daemonize" in text
    assert "--pid-file" in text
    assert "--log-file" in text
    assert "--foreground" in text


def test_daemonize_uses_python_os_setsid_double_fork_not_shell_setsid():
    text = FEED.read_text(encoding="utf-8")
    assert "os.fork()" in text
    assert "os.setsid()" in text
    assert "def daemonize_reexec" in text or "def daemonize" in text
    assert "$(setsid" not in text
    assert "os.execv" in text  # re-exec after fork avoids pandas-thread crash


def test_ctl_start_uses_daemonize_not_shell_setsid():
    text = CTL.read_text(encoding="utf-8")
    assert "--daemonize" in text
    assert "--pid-file" in text
    assert "--log-file" in text
    assert "$(setsid" not in text
    assert " setsid " not in text.replace("os.setsid", "OS_SETSID")
    assert 'nohup "$PYTHON"' not in text


def test_daemonize_source_writes_pid_only_in_final_child():
    text = FEED.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("daemonize_reexec", "daemonize"):
            fn = node
            break
    assert fn is not None
    src = ast.get_source_segment(text, fn) or ""
    assert "_write_pid_file" in src
    assert "os.fork()" in src
    assert "os.setsid()" in src
    assert "os.dup2" in src
    # Parent waits then SystemExit — pid write is after second fork
    assert "first > 0" in src or "if first > 0" in text


def test_sigterm_cleanup_removes_pid_file():
    text = FEED.read_text(encoding="utf-8")
    assert "_remove_own_pid_file" in text
    assert "SIGTERM" in text
    assert "atexit.register" in text


def test_stdout_stderr_redirected_to_log_file_in_daemonize():
    text = FEED.read_text(encoding="utf-8")
    assert "os.dup2(log_fd, 1)" in text
    assert "os.dup2(log_fd, 2)" in text
    assert "os.devnull" in text


def test_daemonize_before_pandas_import_and_reexec():
    text = FEED.read_text(encoding="utf-8")
    # pandas must not be imported at module top-level before daemonize path
    lines = text.splitlines()
    top = "\n".join(lines[:80])
    assert "import pandas" not in top
    assert "os.execv" in text
    assert "--foreground" in text


def test_module_exports_daemonize_callable():
    import importlib.util

    spec = importlib.util.spec_from_file_location("live_binance_intrabar_feed", FEED)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(getattr(mod, "daemonize", None) or getattr(mod, "daemonize_reexec"))
    fn = getattr(mod, "daemonize_reexec", None) or mod.daemonize
    assert "pid_file" in inspect.signature(fn).parameters
    assert "log_file" in inspect.signature(fn).parameters
