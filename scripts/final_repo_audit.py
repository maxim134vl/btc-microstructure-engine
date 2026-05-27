"""Final repository sanity audit — Phase 4A consolidation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_canonical_runtime_uniqueness() -> bool:
    canonical = ROOT / "master_auction_runtime_v1.py"
    mirror = ROOT / "btc-microstructure-engine" / "master_auction_runtime_v1.py"
    package = ROOT / "src" / "btc_ml" / "runtime" / "pipeline.py"

    if not canonical.exists():
        print("FAIL: canonical master_auction_runtime_v1.py missing")
        return False
    if not package.exists():
        print("FAIL: src/btc_ml/runtime/pipeline.py missing")
        return False
    if mirror.exists():
        print("WARN: mirror runtime still present (archive pending): btc-microstructure-engine/")

    print("PASS: canonical runtime paths identified")
    return True


def check_duplicate_backups_at_root() -> bool:
    backups = list(ROOT.glob("*_backup*.py"))
    if backups:
        print(f"FAIL: backup files remain at root: {[p.name for p in backups]}")
        return False
    print("PASS: no backup engines at repository root")
    return True


def check_config_layer() -> bool:
    required = [
        "config/runtime.py",
        "config/calibration.py",
        "config/ontology.py",
        "config/adversarial.py",
        "config/stabilization.py",
        "config/replay.py",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        print(f"FAIL: config layer incomplete: {missing}")
        return False
    print("PASS: unified config layer present")
    return True


def check_package_imports() -> bool:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import btc_ml  # noqa: F401
        from btc_ml.runtime.pipeline import CANONICAL_PIPELINE, run_once  # noqa: F401
        from config import get_calibration_settings  # noqa: F401
    except ImportError as error:
        print(f"FAIL: package import error: {error}")
        return False

    print(f"PASS: package imports OK (pipeline steps={len(CANONICAL_PIPELINE)})")
    return True


def check_artifact_directories() -> bool:
    for name in ("artifacts", "reports", "replays"):
        if not (ROOT / name).is_dir():
            print(f"FAIL: missing directory: {name}/")
            return False
    print("PASS: artifact separation directories present")
    return True


def check_orphan_runtime_parquet_references() -> bool:
    critical = [
        "live_market_feed.parquet",
        "candle_structure_memory.parquet",
        "probabilistic_auction_memory.parquet",
        "runtime_cognition_memory.parquet",
    ]
    missing = [name for name in critical if not (ROOT / name).exists()]
    if missing:
        print(f"WARN: runtime parquets absent (may be cold start): {missing}")
    else:
        print("PASS: critical runtime parquets present")
    return True


def main() -> int:
    print()
    print("FINAL REPOSITORY AUDIT")
    print("=" * 60)

    checks = [
        ("canonical runtime uniqueness", check_canonical_runtime_uniqueness()),
        ("no root backup duplicates", check_duplicate_backups_at_root()),
        ("unified config layer", check_config_layer()),
        ("package imports", check_package_imports()),
        ("artifact directories", check_artifact_directories()),
        ("runtime parquet references", check_orphan_runtime_parquet_references()),
    ]

    print()
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    print()
    if all(result for _, result in checks):
        print("AUDIT RESULT: PASS")
        return 0

    print("AUDIT RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
