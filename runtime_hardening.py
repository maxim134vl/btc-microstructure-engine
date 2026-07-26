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


# Frozen relative order of the base cognition chain (localization may be inserted).
# Absolute indices are intentionally NOT used — insertion shifts later steps.
BASE_CANONICAL_PIPELINE_ORDER: tuple[str, ...] = (
    "candle_structure_engine_v1.py",
    "volume_classification_engine_v1.py",
    "schema_validation_engine_v1.py",
    "behavioral_sequence_memory_v1.py",
    "behavioral_volume_observer_v1.py",
    "microstructure_candle_engine_v1.py",
    "volume_response_engine_v1.py",
    "climactic_behavior_engine_v1.py",
    "auction_convergence_engine_v1.py",
    "auction_synthesis_engine_v1.py",
    "stage2_cognition_runtime_v1.py",
    "runtime_cognition_engine_v1.py",
    "intermediate_cognition_engine_v1.py",
    "auction_reinforcement_engine_v1.py",
    "probabilistic_auction_engine_v1.py",
    "auction_context_arbitration_engine_v1.py",
    "auction_decay_engine_v1.py",
    "state_transition_engine_v1.py",
    "adaptive_meta_cognition_engine_v1.py",
    "mtf_availability_runtime_engine_v1.py",
)

VOLUME_LOCALIZATION_ENGINE = "volume_localization_engine_v1.py"
CANDLE_STRUCTURE_ENGINE = "candle_structure_engine_v1.py"
VOLUME_RESPONSE_ENGINE = "volume_response_engine_v1.py"
BASE_PIPELINE_STEP_COUNT = len(BASE_CANONICAL_PIPELINE_ORDER)
ACTIVATED_PIPELINE_STEP_COUNT = BASE_PIPELINE_STEP_COUNT + 1


def validate_canonical_pipeline_order(
    pipeline: list[str] | tuple[str, ...],
    expected_step_count: int,
) -> list[str]:
    """Validate relative architectural order (no absolute index coupling).

    Returns a list of failure strings; empty means pass.
    """
    failures: list[str] = []
    steps = list(pipeline)
    actual = len(steps)

    if expected_step_count not in (
        BASE_PIPELINE_STEP_COUNT,
        ACTIVATED_PIPELINE_STEP_COUNT,
    ):
        failures.append(
            f"unexpected pipeline mode step count {expected_step_count} "
            f"(allowed {BASE_PIPELINE_STEP_COUNT} or {ACTIVATED_PIPELINE_STEP_COUNT})"
        )
        # Still report length mismatch when caller passes an unsupported mode.
        if actual != expected_step_count:
            failures.append(
                f"pipeline step count != {expected_step_count} ({actual})"
            )
        return failures

    if actual != expected_step_count:
        failures.append(
            f"pipeline step count != {expected_step_count} ({actual})"
        )

    activated = expected_step_count == ACTIVATED_PIPELINE_STEP_COUNT
    loc_count = steps.count(VOLUME_LOCALIZATION_ENGINE)

    if activated:
        if loc_count == 0:
            failures.append(
                "volume_localization_engine_v1.py missing in activated pipeline"
            )
        elif loc_count > 1:
            failures.append(
                "volume_localization_engine_v1.py registered more than once"
            )
    else:
        if loc_count != 0:
            failures.append(
                "volume_localization_engine_v1.py must be absent in 20-step pipeline"
            )

    # Required base engines present exactly once.
    for engine in BASE_CANONICAL_PIPELINE_ORDER:
        count = steps.count(engine)
        if count == 0:
            failures.append(f"required engine missing: {engine}")
        elif count > 1:
            failures.append(f"required engine duplicated: {engine}")

    # Base relative order preserved (localization ignored when extracting).
    base_observed = [e for e in steps if e != VOLUME_LOCALIZATION_ENGINE]
    if base_observed != list(BASE_CANONICAL_PIPELINE_ORDER):
        failures.append(
            "base cognition relative order violated "
            "(localization insertion must not reorder other engines)"
        )

    # Localization sandwich when present.
    if loc_count == 1 and CANDLE_STRUCTURE_ENGINE in steps and VOLUME_RESPONSE_ENGINE in steps:
        candle = steps.index(CANDLE_STRUCTURE_ENGINE)
        loc = steps.index(VOLUME_LOCALIZATION_ENGINE)
        response = steps.index(VOLUME_RESPONSE_ENGINE)
        if not (candle < loc < response):
            failures.append(
                "volume localization order invalid "
                f"(candle={candle}, localization={loc}, response={response})"
            )

    # Core cognition relative chain (names, not absolute indices).
    cognition_chain = (
        "stage2_cognition_runtime_v1.py",
        "runtime_cognition_engine_v1.py",
        "intermediate_cognition_engine_v1.py",
    )
    if all(engine in steps for engine in cognition_chain):
        idxs = [steps.index(engine) for engine in cognition_chain]
        if idxs != sorted(idxs):
            failures.append(
                "cognition relative order violated "
                "(stage2 → runtime_cognition → intermediate_cognition)"
            )

    return failures


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

        failures = validate_canonical_pipeline_order(
            CANONICAL_PIPELINE,
            EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        )
        if failures:
            report.failures.extend(failures)
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
