#!/usr/bin/env python3
"""Start S4.1 manager + traders detached from the launcher process group.

Plain `nohup ... &` keeps daemons in the IDE/shell process group; they die when
that group is torn down. This launcher uses start_new_session=True (setsid).
PAPER ONLY / NO REAL EXECUTION.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "venv" / "bin" / "python"
INTERVAL = sys.argv[1] if len(sys.argv) > 1 else "60"

ROLES: list[tuple[str, list[str]]] = [
    (
        "timeframe_manager",
        [
            str(PYTHON),
            str(ROOT / "scripts/live/timeframe_manager_daemon.py"),
            "--approved-timeframe-manager",
            "--paper-only",
            "--no-real-execution",
            "--interval-seconds",
            INTERVAL,
        ],
    ),
]


def _trader(tf: str) -> tuple[str, list[str]]:
    return (
        f"trader_{tf}",
        [
            str(PYTHON),
            str(ROOT / "scripts/live/timeframe_trader_daemon.py"),
            "--timeframe",
            tf,
            "--approved-timeframe-trader",
            "--paper-only",
            "--no-real-execution",
            "--interval-seconds",
            INTERVAL,
        ],
    )


for _tf in ("M15", "M30", "H1", "H4"):
    ROLES.append(_trader(_tf))


def main() -> int:
    (ROOT / "run").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    launched: list[tuple[str, int]] = []
    for role, cmd in ROLES:
        log_path = ROOT / "logs" / f"{role}.log"
        with log_path.open("a", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        (ROOT / "run" / f"{role}.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
        launched.append((role, proc.pid))
        print(f"launched role={role} pid={proc.pid}")
        time.sleep(0.4)

    time.sleep(5)
    failed = 0
    for role, pid in launched:
        try:
            import os

            os.kill(pid, 0)
            print(f"alive role={role} pid={pid}")
        except OSError:
            print(f"FAILED role={role} pid={pid}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
