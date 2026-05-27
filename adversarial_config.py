"""Phase 2B adversarial diagnostics feature flags — default OFF, warning-first."""

from __future__ import annotations

import os
from dataclasses import dataclass

from calibration_config import _env_bool, _env_float


@dataclass(frozen=True)
class AdversarialSettings:
    enable_adversarial_diagnostics: bool = False
    enable_stress_sensitivity: bool = False
    stress_engine_seed: int = 42
    warn_on_failure_mode: bool = True
    fragility_warning_threshold: float = 0.45


def get_adversarial_settings() -> AdversarialSettings:
    seed_raw = os.environ.get("STRESS_ENGINE_SEED", "42")
    try:
        seed = int(seed_raw)
    except ValueError:
        seed = 42

    return AdversarialSettings(
        enable_adversarial_diagnostics=_env_bool(
            "ENABLE_ADVERSARIAL_DIAGNOSTICS",
            False,
        ),
        enable_stress_sensitivity=_env_bool(
            "ENABLE_STRESS_SENSITIVITY",
            False,
        ),
        stress_engine_seed=seed,
        warn_on_failure_mode=_env_bool("ADVERSARIAL_WARN_ON_FAILURE", True),
        fragility_warning_threshold=_env_float(
            "FRAGILITY_WARNING_THRESHOLD",
            0.45,
        ),
    )


def adversarial_active(settings: AdversarialSettings | None = None) -> bool:
    settings = settings or get_adversarial_settings()
    return settings.enable_adversarial_diagnostics
