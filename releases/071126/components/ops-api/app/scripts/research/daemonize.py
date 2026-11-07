#!/usr/bin/env python3
"""Detach a command into its own session so it survives the caller exiting.

Usage: daemonize.py <logfile> <command> [args...]

macOS has no `setsid` binary and `nohup ... &` from a short-lived shell still gets
torn down with that shell's process group, which silently killed multi-hour replay
runs mid-flight. The os.setsid() syscall is available, so double-fork here and exec
the command with stdio redirected to the log.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write(f"usage: {sys.argv[0]} <logfile> <command> [args...]\n")
        return 2

    log_path = sys.argv[1]
    command = sys.argv[2:]

    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)

    os.chdir("/Users/fontecrypto/btc-ml")
    os.execvp(command[0], command)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
