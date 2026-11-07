"""Start the visual refresher in its own session so it outlives its launcher.

A plain `nohup ... &` leaves the daemon in the launching shell's process group,
so it is killed when that shell's group is torn down -- which is how the
refresher died at 08:25:32 and again at 11:07:32. `start_new_session=True`
issues setsid(2), detaching it from the controlling terminal and process group.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/Users/fontecrypto/btc-ml")
SCRIPT = ROOT / "scripts/live/run_market_context_visual_refresher.py"
LOG = ROOT / "logs/context_visual_refresher.log"
PID_FILE = ROOT / "runtime_context_visual_refresher.pid"


def main() -> int:
    interval = sys.argv[1] if len(sys.argv) > 1 else "20"
    with LOG.open("a") as handle:
        process = subprocess.Popen(
            [str(ROOT / "venv/bin/python"), str(SCRIPT), "--interval-seconds", interval],
            cwd=str(ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    print(f"launched pid={process.pid} interval={interval}s")

    for _ in range(15):
        time.sleep(1)
        if process.poll() is not None:
            print(f"FAILED: exited early rc={process.returncode}")
            return 1
    recorded = PID_FILE.read_text().strip() if PID_FILE.exists() else "<none>"
    print(f"alive after 15s; pid_file={recorded}")
    return 0 if recorded == str(process.pid) else 2


if __name__ == "__main__":
    raise SystemExit(main())
