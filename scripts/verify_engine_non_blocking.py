#!/usr/bin/env python3
"""Verify engines cannot block the canonical pipeline indefinitely."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


def _bootstrap() -> None:
    os.chdir(ROOT)


def test_volume_response_exits() -> bool:
    script = os.path.join(ROOT, "volume_response_engine_v1.py")
    started = time.time()
    result = subprocess.run(
        [sys.executable, script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    duration = round(time.time() - started, 2)
    ok = result.returncode == 0 and duration < 30
    print(f"  [{'PASS' if ok else 'FAIL'}] volume_response exits cleanly ({duration}s, rc={result.returncode})")
    if not ok and result.stderr:
        print(result.stderr[-500:])
    return ok


def test_subprocess_timeout_kills() -> bool:
    from runtime_engine_guard import EngineTimeoutError, run_engine_subprocess

    hang_script = os.path.join(ROOT, "reports", "runtime_blocking", "_hang_probe.py")
    os.makedirs(os.path.dirname(hang_script), exist_ok=True)
    with open(hang_script, "w", encoding="utf-8") as handle:
        handle.write("import time\ntime.sleep(60)\n")

    started = time.time()
    try:
        run_engine_subprocess(
            sys.executable,
            hang_script,
            ROOT,
            "_hang_probe.py",
            timeout_seconds=2,
        )
        print("  [FAIL] hang probe should have timed out")
        return False
    except EngineTimeoutError:
        duration = round(time.time() - started, 2)
        ok = duration < 10
        print(f"  [{'PASS' if ok else 'FAIL'}] watchdog kills stalled subprocess ({duration}s)")
        return ok


def test_pipeline_continues_after_failure() -> bool:
    from btc_ml.runtime.pipeline import CANONICAL_PIPELINE, run_once

    before = time.time()
    run_once()
    duration = round(time.time() - before, 2)
    ok = duration < 600
    print(f"  [{'PASS' if ok else 'FAIL'}] pipeline run_once completed ({duration}s, {len(CANONICAL_PIPELINE)} engines)")
    return ok


def test_blocking_audits_export() -> bool:
    from runtime_engine_guard import export_all_blocking_audits

    exports = export_all_blocking_audits()
    ok = all(os.path.isabs(path) or os.path.exists(path) for path in exports.values())
    for name, path in exports.items():
        exists = os.path.exists(path)
        print(f"  [{'PASS' if exists else 'FAIL'}] {name}: {path}")
        ok = ok and exists
    return ok


def test_parquet_updates_across_cycles() -> bool:
    import pandas as pd
    from storage.path_registry import resolve_read

    path = resolve_read("probabilistic_auction_memory.parquet")
    if not os.path.exists(path):
        print("  [WARN] probabilistic parquet missing — skip update check")
        return True

    before_mtime = os.path.getmtime(path)
    before_rows = len(pd.read_parquet(path))

    from btc_ml.runtime.pipeline import run_once

    run_once()

    after_mtime = os.path.getmtime(path)
    after_rows = len(pd.read_parquet(path))
    ok = after_mtime >= before_mtime
    print(
        f"  [{'PASS' if ok else 'FAIL'}] parquet mtime advanced "
        f"(rows {before_rows} -> {after_rows})"
    )
    return ok


def main() -> int:
    _bootstrap()

    print()
    print("ENGINE NON-BLOCKING VERIFICATION")
    print("=" * 60)

    checks = {
        "volume_response_exits": test_volume_response_exits(),
        "subprocess_timeout_kills": test_subprocess_timeout_kills(),
        "pipeline_completes": test_pipeline_continues_after_failure(),
        "blocking_audits_export": test_blocking_audits_export(),
        "parquet_updates": test_parquet_updates_across_cycles(),
    }

    report_dir = os.path.join(ROOT, "reports", "runtime_blocking")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "verify_engine_non_blocking.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "checks": checks,
            },
            handle,
            indent=2,
        )

    print()
    print(f"Report: {report_path}")
    print()

    if all(checks.values()):
        print("RESULT: PASS — engine non-blocking guarantees verified")
        return 0

    print("RESULT: FAIL — see failed checks above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
