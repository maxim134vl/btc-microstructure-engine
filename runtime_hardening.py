"""Operational hardening — fail-fast integrity checks (Phase 4B)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class HardeningReport:
    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def check_python_version(report: HardeningReport) -> None:
    if sys.version_info < (3, 11):
        report.failures.append(f"Python >=3.11 required, got {sys.version_info.major}.{sys.version_info.minor}")
    else:
        report.passed.append("python version")


def check_working_directory(report: HardeningReport) -> None:
    root = _repo_root()
    if Path.cwd().resolve() != root.resolve():
        report.warnings.append(
            f"cwd is {Path.cwd()} — canonical runtime expects {root}"
        )
    if not (root / "run.py").exists():
        report.failures.append("run.py missing — not in repository root")
    else:
        report.passed.append("repository root layout")


def check_startup_dependencies(report: HardeningReport) -> None:
    required = ("pandas", "pyarrow", "numpy")
    missing = []
    for module in required:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        report.failures.append(f"missing runtime dependencies: {missing}")
    else:
        report.passed.append("startup dependencies")


def check_package_imports(report: HardeningReport) -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    try:
        import btc_ml  # noqa: F401
        from btc_ml.runtime.pipeline import (
            CANONICAL_PIPELINE,
            EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        )  # noqa: F401
        from storage.path_registry import PARQUET_REGISTRY  # noqa: F401
        from config import get_calibration_settings  # noqa: F401
        actual = len(CANONICAL_PIPELINE)
        if actual != EXPECTED_CANONICAL_PIPELINE_STEP_COUNT:
            report.failures.append(
                f"pipeline step count != {EXPECTED_CANONICAL_PIPELINE_STEP_COUNT} ({actual})"
            )
        elif "intermediate_cognition_engine_v1.py" not in CANONICAL_PIPELINE:
            report.failures.append(
                "pipeline missing intermediate_cognition_engine_v1.py"
            )
        elif "volume_localization_engine_v1.py" in CANONICAL_PIPELINE:
            # Phase 4C activated order: candle → localization → … → volume_response
            loc = CANONICAL_PIPELINE.index("volume_localization_engine_v1.py")
            candle = CANONICAL_PIPELINE.index("candle_structure_engine_v1.py")
            response = CANONICAL_PIPELINE.index("volume_response_engine_v1.py")
            if not (candle < loc < response):
                report.failures.append(
                    "volume localization order invalid "
                    f"(candle={candle}, localization={loc}, response={response})"
                )
            else:
                report.passed.append("canonical package imports")
        elif CANONICAL_PIPELINE[12] != "intermediate_cognition_engine_v1.py":
            report.failures.append(
                "pipeline step 13 must be intermediate_cognition_engine_v1.py "
                f"(got {CANONICAL_PIPELINE[12]!r})"
            )
        else:
            report.passed.append("canonical package imports")
    except ImportError as error:
        report.failures.append(f"package import failure: {error}")


def check_parquet_path_registry(report: HardeningReport) -> None:
    from storage.path_registry import (
        DATA_CATEGORIES,
        PARQUET_REGISTRY,
        ensure_data_layout,
        registry_summary,
        resolve_canonical,
    )

    ensure_data_layout()
    summary = registry_summary()
    empty_categories = [cat for cat in DATA_CATEGORIES if not summary.get(cat)]
    if empty_categories and empty_categories != ["replay"]:
        report.warnings.append(f"registry categories without files: {empty_categories}")

    for filename, category in PARQUET_REGISTRY.items():
        canonical = resolve_canonical(filename)
        if f"/{category}/" not in canonical.replace("\\", "/"):
            report.failures.append(f"registry category mismatch for {filename}")
            return

    report.passed.append("parquet path registry")


def check_parquet_migration_integrity(report: HardeningReport) -> None:
    from storage.path_registry import migrate_all_legacy, resolve_read

    migrated = migrate_all_legacy()
    if migrated:
        report.warnings.append(f"legacy parquets migrated to data/: {migrated}")

    critical = (
        "live_market_feed.parquet",
        "candle_structure_memory.parquet",
        "probabilistic_auction_memory.parquet",
        "runtime_cognition_memory.parquet",
    )
    missing = []
    for name in critical:
        path = resolve_read(name, migrate=False)
        if not os.path.exists(path):
            missing.append(name)
    if missing:
        report.warnings.append(f"critical parquets absent (cold start ok): {missing}")
    else:
        report.passed.append("critical parquet availability")

    report.passed.append("parquet migration integrity")


def check_feature_flag_consistency(report: HardeningReport) -> None:
    from config import (
        get_adversarial_settings,
        get_calibration_settings,
        get_ontology_settings,
        get_replay_settings,
        get_stabilization_settings,
    )

    calibration = get_calibration_settings()
    ontology = get_ontology_settings()
    stabilization = get_stabilization_settings()
    adversarial = get_adversarial_settings()
    replay = get_replay_settings()

    if ontology.use_legacy_climax_ontology and ontology.enable_ontology_refinement:
        report.warnings.append("USE_LEGACY_CLIMAX_ONTOLOGY=true with refinement enabled")

    if calibration.use_disciplined_conviction_at_runtime and not calibration.enable_probabilistic_discipline:
        report.failures.append(
            "USE_DISCIPLINED_CONVICTION_AT_RUNTIME requires ENABLE_PROBABILISTIC_DISCIPLINE"
        )

    if replay.enable_final_validation is False:
        report.warnings.append("ENABLE_FINAL_VALIDATION=false")

    report.passed.append(
        f"feature flags loaded (discipline={calibration.enable_probabilistic_discipline}, "
        f"ontology_refine={ontology.enable_ontology_refinement}, "
        f"stabilization={stabilization.enable_ontology_stabilization}, "
        f"adversarial={adversarial.enable_adversarial_diagnostics})"
    )


def check_config_integrity(report: HardeningReport) -> None:
    required = [
        "config/runtime.py",
        "config/calibration.py",
        "config/ontology.py",
        "config/adversarial.py",
        "config/stabilization.py",
        "config/replay.py",
    ]
    root = _repo_root()
    missing = [path for path in required if not (root / path).exists()]
    if missing:
        report.failures.append(f"config layer incomplete: {missing}")
    else:
        report.passed.append("config integrity")


def check_replay_environment(report: HardeningReport) -> None:
    root = _repo_root()
    replay_root = root / "scripts" / "replay_validation"
    if not replay_root.is_dir():
        report.failures.append("scripts/replay_validation missing")
        return
    for sub in ("final_validation", "ontology", "adversarial", "stabilization"):
        if not (replay_root / sub).is_dir():
            report.warnings.append(f"replay suite subdirectory missing: {sub}")
    for name in ("artifacts", "reports", "replays"):
        if not (root / name).is_dir():
            report.failures.append(f"missing artifact directory: {name}/")
            return
    report.passed.append("replay environment")


def check_mirror_dependency_leakage(report: HardeningReport) -> None:
    root = _repo_root()
    mirror = root / "btc-microstructure-engine"
    archived = root / "archive_removed" / "btc-microstructure-engine-mirror"
    if mirror.exists():
        report.failures.append("active mirror tree btc-microstructure-engine/ still present")
    elif archived.exists():
        report.passed.append("mirror archived")
    else:
        report.warnings.append("mirror archive path not found (may be pre-archive)")


def check_legacy_entrypoint_shims(report: HardeningReport) -> None:
    root = _repo_root()
    shim = root / "master_auction_runtime_v1.py"
    if not shim.exists():
        report.failures.append("master_auction_runtime_v1.py shim missing")
        return
    text = shim.read_text(encoding="utf-8")
    if "DeprecationWarning" not in text or "run_forever" not in text:
        report.failures.append("master_auction_runtime_v1.py is not a deprecation shim")
    else:
        report.passed.append("legacy entrypoint shims")


CHECKS: tuple[tuple[str, Callable[[HardeningReport], None]], ...] = (
    ("python version", check_python_version),
    ("repository root", check_working_directory),
    ("startup dependencies", check_startup_dependencies),
    ("package imports", check_package_imports),
    ("parquet path registry", check_parquet_path_registry),
    ("parquet migration", check_parquet_migration_integrity),
    ("feature flag consistency", check_feature_flag_consistency),
    ("config integrity", check_config_integrity),
    ("replay environment", check_replay_environment),
    ("mirror dependency leakage", check_mirror_dependency_leakage),
    ("legacy entrypoint shims", check_legacy_entrypoint_shims),
)


def run_hardening_checks(*, strict: bool = False) -> HardeningReport:
    report = HardeningReport()
    for _name, check in CHECKS:
        try:
            check(report)
        except Exception as error:
            report.failures.append(f"{_name}: {error}")
    if strict and report.warnings:
        report.failures.extend([f"strict: {warning}" for warning in report.warnings])
    return report


def main() -> int:
    print()
    print("RUNTIME HARDENING CHECKS")
    print("=" * 60)

    report = run_hardening_checks()
    for item in report.passed:
        print(f"  [PASS] {item}")
    for item in report.warnings:
        print(f"  [WARN] {item}")
    for item in report.failures:
        print(f"  [FAIL] {item}")

    print()
    if report.ok:
        print("HARDENING RESULT: PASS")
        return 0

    print("HARDENING RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
