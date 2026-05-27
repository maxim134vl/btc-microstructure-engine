"""Final repository sanity audit — Phase 4A/4B."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MIRROR_ACTIVE = ROOT / "btc-microstructure-engine"
MIRROR_ARCHIVED = ROOT / "archive_removed" / "btc-microstructure-engine-mirror"

LEGACY_ENTRYPOINTS = (
    "master_auction_runtime_v1.py",
    "autonomous_runtime_v1.py",
    "autonomous_runtime_v2.py",
    "behavioral_runtime_orchestrator_v1.py",
)

DUPLICATE_ENGINE_NAMES = (
    "probabilistic_auction_engine_v1.py",
    "master_auction_runtime_v1.py",
    "auction_synthesis_engine_v1.py",
)


def check_canonical_runtime_uniqueness() -> bool:
    package = ROOT / "src" / "btc_ml" / "runtime" / "pipeline.py"
    run_py = ROOT / "run.py"
    run_sh = ROOT / "run.sh"

    if not package.exists():
        print("FAIL: src/btc_ml/runtime/pipeline.py missing")
        return False
    if not run_py.exists() or not run_sh.exists():
        print("FAIL: canonical run.py / run.sh missing")
        return False

    if MIRROR_ACTIVE.exists():
        print("FAIL: active mirror tree still present: btc-microstructure-engine/")
        return False

    if not MIRROR_ARCHIVED.exists():
        print("WARN: archived mirror not found at archive_removed/btc-microstructure-engine-mirror/")
    else:
        print("PASS: mirror archived; canonical runtime is unique")

    print("PASS: canonical runtime paths identified")
    return True


def check_legacy_shims() -> bool:
    for name in LEGACY_ENTRYPOINTS:
        path = ROOT / name
        if not path.exists():
            print(f"FAIL: missing legacy shim: {name}")
            return False
        text = path.read_text(encoding="utf-8")
        if "DeprecationWarning" not in text:
            print(f"FAIL: {name} missing DeprecationWarning shim")
            return False
    print("PASS: legacy entrypoints are deprecation shims")
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


def check_path_registry() -> bool:
    registry = ROOT / "storage" / "path_registry.py"
    if not registry.exists():
        print("FAIL: storage/path_registry.py missing")
        return False

    sys.path.insert(0, str(ROOT))
    from storage.path_registry import PARQUET_REGISTRY, ensure_data_layout, resolve_canonical

    ensure_data_layout()
    for filename in PARQUET_REGISTRY:
        canonical = resolve_canonical(filename)
        if not canonical.startswith(str(ROOT / "data")) and os.environ.get("BTC_ML_DATA_ROOT") is None:
            if "/data/" not in canonical.replace("\\", "/"):
                print(f"FAIL: non-canonical path for {filename}: {canonical}")
                return False

    print(f"PASS: path registry ({len(PARQUET_REGISTRY)} parquets)")
    return True


def check_package_imports() -> bool:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import btc_ml  # noqa: F401
        from btc_ml.runtime.pipeline import CANONICAL_PIPELINE, run_once  # noqa: F401
        from btc_ml.storage import resolve_read, resolve_write  # noqa: F401
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
    for category in ("live", "cognition", "reinforcement", "probabilistic", "diagnostics", "replay", "artifacts"):
        if not (ROOT / "data" / category).is_dir():
            print(f"FAIL: missing data/{category}/")
            return False
    print("PASS: artifact and data separation directories present")
    return True


def check_runtime_parquet_references() -> bool:
    from storage.path_registry import resolve_read

    critical = [
        "live_market_feed.parquet",
        "candle_structure_memory.parquet",
        "probabilistic_auction_memory.parquet",
        "runtime_cognition_memory.parquet",
    ]
    missing = []
    dead_root = []
    for name in critical:
        canonical = resolve_read(name, migrate=False)
        legacy = ROOT / name
        if not Path(canonical).exists() and not legacy.exists():
            missing.append(name)
        if legacy.exists() and Path(canonical).exists() and legacy.resolve() != Path(canonical).resolve():
            dead_root.append(name)

    if dead_root:
        print(f"WARN: duplicate root+canonical parquets (migrate recommended): {dead_root}")
    if missing:
        print(f"WARN: runtime parquets absent (cold start): {missing}")
    else:
        print("PASS: critical runtime parquets resolvable")
    return True


def check_mirror_dependency_leakage() -> bool:
    pattern = re.compile(r"btc-microstructure-engine")
    offenders: list[str] = []
    skip_files = {
        "scripts/final_repo_audit.py",
        "scripts/verify_phase4b_hardening.py",
    }
    for path in ROOT.rglob("*.py"):
        if "archive_removed" in path.parts or "btc-microstructure-engine-mirror" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if rel in skip_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not pattern.search(stripped):
                continue
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("print("):
                continue
            if "import" in stripped or "from " in stripped or "os.path" in stripped or "Path(" in stripped:
                offenders.append(f"{rel}: {stripped[:80]}")
                break

    if offenders:
        print(f"FAIL: mirror dependency leakage: {offenders[:8]}")
        return False

    print("PASS: no mirror dependency leakage in active tree")
    return True


def check_duplicate_engines() -> bool:
    duplicates: list[str] = []
    for name in DUPLICATE_ENGINE_NAMES:
        matches = list(ROOT.rglob(name))
        active = [
            str(p.relative_to(ROOT))
            for p in matches
            if "archive_removed" not in p.parts
            and "archive/" not in str(p.relative_to(ROOT))
            and "btc-microstructure-engine-mirror" not in p.parts
        ]
        if len(active) > 1:
            duplicates.append(f"{name}: {active}")

    if duplicates:
        print(f"WARN: duplicate engine paths: {duplicates}")
    else:
        print("PASS: no duplicate active engine copies")
    return True


def check_unresolved_shims() -> bool:
    shim_dir = ROOT / "src" / "btc_ml"
    broken: list[str] = []
    for init in shim_dir.rglob("__init__.py"):
        if init.parent == shim_dir:
            continue
        try:
            text = init.read_text(encoding="utf-8")
        except OSError:
            continue
        if "from parquet_utils" in text or "from config import" in text:
            # expected shim pattern
            continue
        if init.parent.name == "replay" and "__all__ = []" in text:
            broken.append(str(init.relative_to(ROOT)))

    if broken:
        print(f"WARN: empty or incomplete shims: {broken}")
    print("PASS: shim packages present")
    return True


def check_config_divergence() -> bool:
    sys.path.insert(0, str(ROOT))
    from config import get_calibration_settings
    from calibration_config import get_calibration_settings as direct

    if get_calibration_settings() != direct():
        print("FAIL: config/__init__ diverges from calibration_config")
        return False
    print("PASS: config layer consistent with source modules")
    return True


def check_broken_replay_references() -> bool:
    replay_root = ROOT / "scripts" / "replay_validation"
    if not replay_root.is_dir():
        print("FAIL: replay_validation missing")
        return False

    broken: list[str] = []
    for path in replay_root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            broken.append(str(path.relative_to(ROOT)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(".parquet"):
                if "mirror" in node.value or "btc-microstructure-engine" in node.value:
                    broken.append(f"{path.name}:{node.value}")

    if broken:
        print(f"FAIL: broken replay parquet references: {broken}")
        return False

    print("PASS: replay references clean")
    return True


def main() -> int:
    print()
    print("FINAL REPOSITORY AUDIT (Phase 4B)")
    print("=" * 60)

    checks = [
        ("canonical runtime uniqueness", check_canonical_runtime_uniqueness()),
        ("legacy entrypoint shims", check_legacy_shims()),
        ("no root backup duplicates", check_duplicate_backups_at_root()),
        ("parquet path registry", check_path_registry()),
        ("unified config layer", check_config_layer()),
        ("package imports", check_package_imports()),
        ("artifact/data directories", check_artifact_directories()),
        ("runtime parquet references", check_runtime_parquet_references()),
        ("mirror dependency leakage", check_mirror_dependency_leakage()),
        ("duplicate engines", check_duplicate_engines()),
        ("unresolved shims", check_unresolved_shims()),
        ("config divergence", check_config_divergence()),
        ("replay references", check_broken_replay_references()),
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
