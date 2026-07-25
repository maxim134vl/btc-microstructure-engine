#!/usr/bin/env python3
"""Re-scope the S4.1 legacy migration to the legacy ledger files only.

The first activation pass locked and archived every parquet in
``data/research/paper_simulator/``. The freeze belongs on the archived copy
only: audit tests and visual tooling copy the live files into throwaway roots,
and a read-only source mode propagates into those copies. This restores write
permissions on the live directory and rebuilds a ledger-scoped immutable
archive.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading import activation as act  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    stamp = (argv or sys.argv[1:] or ["20260724_202010"])[0]
    restored: list[str] = []
    for path in sorted(act.LEGACY_PAPER_DIR.glob("*.parquet")):
        os.chmod(path, 0o644)
        restored.append(path.name)

    archive_dir = ROOT / "data" / "archive" / f"legacy_global_paper_ledger_{stamp}"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    payload = act.archive_legacy_ledger(stamp, mode=act.MODE_CLOSED_HISTORY_ONLY)

    print(f"restored_writable={len(restored)}")
    print(
        json.dumps(
            {
                "legacy_ledger_state": payload["legacy_ledger_state"],
                "archive_dir": payload["archive_dir"],
                "archived_files": payload["archived_files"],
                "immutable_archive_paths": payload["immutable_archive_paths"],
                "source_write_freeze_enforced_by": payload["source_write_freeze_enforced_by"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
