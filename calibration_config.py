"""Phase 1B calibration feature flags — conservative, reversible rollout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

CalibrationMode = Literal["raw", "disciplined", "sigmoid"]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class CalibrationSettings:
    """Runtime calibration configuration."""

    enable_probabilistic_discipline: bool = False
    use_disciplined_conviction_at_runtime: bool = False
    calibration_mode: CalibrationMode = "raw"

    enable_nonlinear_calibration: bool = True
    enable_reinforcement_suppression: bool = True
    enable_entropy_discipline: bool = True
    enable_persistence_realism: bool = True
    enable_contradiction_control: bool = True

    logistic_steepness: float = 4.0
    logistic_midpoint: float = 0.55
    max_discipline_reduction: float = 0.30


def get_calibration_settings() -> CalibrationSettings:
    """Load settings from environment with safe defaults (discipline OFF)."""

    mode = os.environ.get("CALIBRATION_MODE", "raw").strip().lower()
    if mode not in {"raw", "disciplined", "sigmoid"}:
        mode = "raw"

    discipline_enabled = _env_bool("ENABLE_PROBABILISTIC_DISCIPLINE", False)
    use_at_runtime = _env_bool("USE_DISCIPLINED_CONVICTION_AT_RUNTIME", False)

    return CalibrationSettings(
        enable_probabilistic_discipline=discipline_enabled,
        use_disciplined_conviction_at_runtime=use_at_runtime,
        calibration_mode=mode,  # type: ignore[arg-type]
        enable_nonlinear_calibration=_env_bool(
            "ENABLE_NONLINEAR_CALIBRATION",
            True,
        ),
        enable_reinforcement_suppression=_env_bool(
            "ENABLE_REINFORCEMENT_SUPPRESSION",
            True,
        ),
        enable_entropy_discipline=_env_bool(
            "ENABLE_ENTROPY_DISCIPLINE",
            True,
        ),
        enable_persistence_realism=_env_bool(
            "ENABLE_PERSISTENCE_REALISM",
            True,
        ),
        enable_contradiction_control=_env_bool(
            "ENABLE_CONTRADICTION_CONTROL",
            True,
        ),
        logistic_steepness=_env_float("CALIBRATION_LOGISTIC_STEEPNESS", 4.0),
        logistic_midpoint=_env_float("CALIBRATION_LOGISTIC_MIDPOINT", 0.55),
        max_discipline_reduction=_env_float(
            "CALIBRATION_MAX_DISCIPLINE_REDUCTION",
            0.30,
        ),
    )


def discipline_active(settings: CalibrationSettings | None = None) -> bool:
    settings = settings or get_calibration_settings()
    return settings.enable_probabilistic_discipline
