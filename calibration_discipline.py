"""Phase 1B controlled probabilistic discipline — gradual, reversible shaping."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd

from calibration_config import CalibrationSettings, get_calibration_settings
from calibration_diagnostics import apply_sigmoid_calibration

DISCIPLINE_EXPORT_COLUMNS = [
    "disciplined_conviction",
    "reinforcement_damping_factor",
    "entropy_discipline_factor",
    "persistence_realism_factor",
    "contradiction_control_factor",
    "nonlinear_compression_factor",
    "raw_vs_disciplined_divergence",
    "saturation_reduction",
    "entropy_interaction",
    "calibration_mode",
    "discipline_active",
    "reinforcement_suppression_factor",
    "persistence_survival_weight",
    "uncertainty_escalation",
]

MINIMUM_PERSISTENCE_SURVIVAL = 3
PERSISTENCE_SCORE_STRUCTURAL = 0.70
ENTROPY_LOW_THRESHOLD = 0.40
ENTROPY_RISING_DELTA = 0.05


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def logistic_compress(
    value: float,
    steepness: float = 4.0,
    midpoint: float = 0.55,
) -> float:
    """Bounded logistic compression with diminishing returns near ceiling."""

    bounded = _clamp(float(value))
    logit_input = steepness * (bounded - midpoint)
    logit_input = max(min(logit_input, 20.0), -20.0)
    compressed = 1.0 / (1.0 + math.exp(-logit_input))
    blend = 0.65 * compressed + 0.35 * bounded * (1.0 - 0.25 * bounded)
    return _clamp(blend)


def diminishing_returns(value: float, ceiling: float = 1.0, rate: float = 0.85) -> float:
    """Soft cap for reinforcement-like accumulators."""

    value = max(float(value), 0.0)
    return ceiling * (1.0 - math.exp(-rate * value / max(ceiling, 1e-6)))


def compute_reinforcement_damping_factor(
    diagnostics: Dict[str, Any],
    reinforcement_component: float,
    settings: CalibrationSettings,
) -> float:
    if not settings.enable_reinforcement_suppression:
        return 1.0

    factor = 1.0

    if diagnostics.get("runaway_reinforcement"):
        factor *= 0.92

    if diagnostics.get("repeated_high_conviction"):
        factor *= 0.90

    acceleration = float(diagnostics.get("reinforcement_acceleration", 0.0))
    if acceleration > 0.04:
        factor *= 1.0 - min(0.12, acceleration * 0.8)

    monoculture = float(diagnostics.get("alignment_monoculture_score", 0.0))
    if monoculture > 0.75:
        factor *= 1.0 - min(0.10, (monoculture - 0.75) * 0.4)

    reinforcement_component = float(reinforcement_component)
    if reinforcement_component > 0.65:
        excess = reinforcement_component - 0.65
        factor *= 1.0 - min(0.08, excess * 0.25)

    return _clamp(factor, 0.70, 1.0)


def compute_entropy_discipline_factor(
    raw_conviction: float,
    entropy_penalty: float,
    diagnostics: Dict[str, Any],
    probabilistic_history: Optional[pd.DataFrame],
    settings: CalibrationSettings,
) -> tuple[float, float]:
    if not settings.enable_entropy_discipline:
        return 1.0, 0.0

    factor = 1.0
    uncertainty_escalation = 0.0

    if raw_conviction > 0.55 and entropy_penalty < ENTROPY_LOW_THRESHOLD:
        entropy_ratio = entropy_penalty / ENTROPY_LOW_THRESHOLD
        factor *= 0.82 + 0.18 * entropy_ratio

    rising_entropy = False
    if probabilistic_history is not None and len(probabilistic_history) >= 2:
        if "entropy_penalty" in probabilistic_history.columns:
            recent = pd.to_numeric(
                probabilistic_history["entropy_penalty"],
                errors="coerce",
            ).dropna()
            if len(recent) >= 2:
                rising_entropy = (
                    float(recent.iloc[-1]) - float(recent.iloc[-2])
                ) > ENTROPY_RISING_DELTA

    conflict_density = float(diagnostics.get("conflict_density", 0.0))
    if rising_entropy and conflict_density > 0.25:
        factor *= 0.94
        uncertainty_escalation += 0.05

    if diagnostics.get("entropy_suppression_failure"):
        factor *= 0.88
        uncertainty_escalation += 0.08

    entropy_interaction = raw_conviction * (1.0 - factor)
    return _clamp(factor, 0.72, 1.0), uncertainty_escalation


def compute_persistence_realism_factor(
    diagnostics: Dict[str, Any],
    persistence_component: float,
    runtime_cognition: Dict[str, Any],
    settings: CalibrationSettings,
) -> tuple[float, float]:
    if not settings.enable_persistence_realism:
        return 1.0, 1.0

    persistence_duration = float(diagnostics.get("persistence_duration", 0.0))
    persistence_score = float(runtime_cognition.get("persistence_score", 0.0))
    continuation_decay = float(diagnostics.get("continuation_decay_rate", 0.0))
    survival_half_life = diagnostics.get("survival_half_life")

    survival_weight = min(
        1.0,
        persistence_duration / float(MINIMUM_PERSISTENCE_SURVIVAL),
    )

    factor = 0.78 + 0.22 * survival_weight

    if persistence_score < 0.40:
        factor *= 0.92

    if (
        persistence_score >= PERSISTENCE_SCORE_STRUCTURAL
        and persistence_duration < MINIMUM_PERSISTENCE_SURVIVAL
    ):
        factor *= 0.88

    if continuation_decay > 0.05:
        factor *= 1.0 - min(0.08, continuation_decay * 0.5)

    if survival_half_life == survival_half_life and float(survival_half_life) < 2.0:
        factor *= 0.94

    persistence_component = float(persistence_component)
    if persistence_component > 0.60 and survival_weight < 0.67:
        factor *= 0.90

    return _clamp(factor, 0.72, 1.0), survival_weight


def compute_contradiction_control_factor(
    diagnostics: Dict[str, Any],
    alignment_component: float,
    settings: CalibrationSettings,
) -> float:
    if not settings.enable_contradiction_control:
        return 1.0

    conflict_density = float(diagnostics.get("conflict_density", 0.0))
    factor = 1.0 - min(0.22, conflict_density * 0.32)

    flags = str(diagnostics.get("contradiction_flags", ""))
    if "high_alignment_rising_entropy" in flags:
        factor *= 0.94

    if "continuation_plus_distribution" in flags:
        factor *= 0.93

    if "absorption_distribution_coexistence" in flags:
        factor *= 0.92

    if float(alignment_component) > 1.15 and conflict_density > 0.35:
        factor *= 0.91

    return _clamp(factor, 0.68, 1.0)


def apply_probabilistic_discipline(
    raw_conviction: float,
    diagnostics: Dict[str, Any],
    current_snapshot: Dict[str, Any],
    runtime_cognition: Dict[str, Any],
    probabilistic_history: Optional[pd.DataFrame] = None,
    settings: Optional[CalibrationSettings] = None,
) -> Dict[str, Any]:
    settings = settings or get_calibration_settings()
    raw_conviction = _clamp(float(raw_conviction))

    reinforcement_damping = compute_reinforcement_damping_factor(
        diagnostics,
        current_snapshot.get("reinforcement_component", 0.0),
        settings,
    )
    entropy_factor, uncertainty_escalation = compute_entropy_discipline_factor(
        raw_conviction,
        float(current_snapshot.get("entropy_penalty", 0.0)),
        diagnostics,
        probabilistic_history,
        settings,
    )
    persistence_factor, survival_weight = compute_persistence_realism_factor(
        diagnostics,
        current_snapshot.get("persistence_component", 0.0),
        runtime_cognition,
        settings,
    )
    contradiction_factor = compute_contradiction_control_factor(
        diagnostics,
        current_snapshot.get("alignment_component", 1.0),
        settings,
    )

    if not settings.enable_probabilistic_discipline:
        calibrated = apply_sigmoid_calibration(raw_conviction)
        return {
            "disciplined_conviction": raw_conviction,
            "calibrated_conviction": calibrated,
            "reinforcement_damping_factor": 1.0,
            "entropy_discipline_factor": 1.0,
            "persistence_realism_factor": 1.0,
            "contradiction_control_factor": 1.0,
            "nonlinear_compression_factor": 1.0,
            "reinforcement_suppression_factor": 1.0,
            "persistence_survival_weight": 1.0,
            "uncertainty_escalation": 0.0,
            "raw_vs_disciplined_divergence": 0.0,
            "saturation_reduction": 0.0,
            "entropy_interaction": 0.0,
            "calibration_mode": settings.calibration_mode,
            "discipline_active": False,
        }

    disciplined = raw_conviction
    disciplined *= reinforcement_damping
    disciplined *= entropy_factor
    disciplined *= persistence_factor
    disciplined *= contradiction_factor

    max_reduction = settings.max_discipline_reduction
    floor = raw_conviction * (1.0 - max_reduction)
    disciplined = max(disciplined, floor)
    disciplined = _clamp(disciplined)

    nonlinear_factor = 1.0
    if settings.enable_nonlinear_calibration:
        compressed = logistic_compress(
            disciplined,
            steepness=settings.logistic_steepness,
            midpoint=settings.logistic_midpoint,
        )
        nonlinear_factor = compressed / max(disciplined, 1e-6)
        disciplined = compressed

    calibrated = apply_sigmoid_calibration(disciplined)

    raw_saturation = max(0.0, (raw_conviction - 0.5) / 0.5)
    disciplined_saturation = max(0.0, (disciplined - 0.5) / 0.5)
    saturation_reduction = raw_saturation - disciplined_saturation

    return {
        "disciplined_conviction": disciplined,
        "calibrated_conviction": calibrated,
        "reinforcement_damping_factor": reinforcement_damping,
        "entropy_discipline_factor": entropy_factor,
        "persistence_realism_factor": persistence_factor,
        "contradiction_control_factor": contradiction_factor,
        "nonlinear_compression_factor": _clamp(nonlinear_factor, 0.0, 1.0),
        "reinforcement_suppression_factor": reinforcement_damping,
        "persistence_survival_weight": survival_weight,
        "uncertainty_escalation": uncertainty_escalation,
        "raw_vs_disciplined_divergence": raw_conviction - disciplined,
        "saturation_reduction": saturation_reduction,
        "entropy_interaction": raw_conviction * (1.0 - entropy_factor),
        "calibration_mode": settings.calibration_mode,
        "discipline_active": True,
    }


def resolve_runtime_conviction(
    raw_conviction: float,
    discipline_result: Dict[str, Any],
    settings: Optional[CalibrationSettings] = None,
) -> float:
    settings = settings or get_calibration_settings()

    if not settings.use_disciplined_conviction_at_runtime:
        return _clamp(float(raw_conviction))

    mode = settings.calibration_mode
    if mode == "sigmoid":
        return _clamp(float(discipline_result["calibrated_conviction"]))
    if mode == "disciplined":
        return _clamp(float(discipline_result["disciplined_conviction"]))

    return _clamp(float(raw_conviction))


def apply_reinforcement_discipline(
    belief_strength: float,
    alignment_component: float,
    persistence_component: float,
    memory: pd.DataFrame,
    runtime_cognition: Dict[str, Any],
    settings: Optional[CalibrationSettings] = None,
) -> tuple[float, float, float, Dict[str, Any]]:
    settings = settings or get_calibration_settings()

    exports = {
        "reinforcement_suppression_factor": 1.0,
        "reinforcement_damping_factor": 1.0,
        "persistence_survival_weight": 1.0,
        "discipline_active": False,
    }

    if not settings.enable_probabilistic_discipline:
        return belief_strength, alignment_component, persistence_component, exports

    if not settings.enable_reinforcement_suppression:
        return belief_strength, alignment_component, persistence_component, exports

    factor = 1.0
    alignment = float(alignment_component)
    persistence = float(persistence_component)
    persistence_score = float(runtime_cognition.get("persistence_score", 0.0))

    if len(memory) >= 3 and "alignment_component" in memory.columns:
        recent_alignment = pd.to_numeric(
            memory["alignment_component"].tail(5),
            errors="coerce",
        ).dropna()
        if len(recent_alignment) >= 3:
            if recent_alignment.nunique() <= 1 and alignment > 0:
                alignment *= 0.85
                factor *= 0.96

    if len(memory) >= 4 and "belief_state" in memory.columns:
        high_count = int(
            (memory.tail(8)["belief_state"] == "HIGH_CONVICTION").sum()
        )
        if high_count >= 4:
            factor *= 0.90

    if persistence_score > PERSISTENCE_SCORE_STRUCTURAL and persistence > 0.10:
        persistence *= 0.88

    if belief_strength > 0.80:
        decay_acceleration = 1.0 - min(0.10, (belief_strength - 0.80) * 0.5)
        factor *= decay_acceleration

    belief_strength = max(0.0, belief_strength * factor)

    exports.update(
        {
            "reinforcement_suppression_factor": _clamp(factor, 0.70, 1.0),
            "reinforcement_damping_factor": _clamp(factor, 0.70, 1.0),
            "persistence_survival_weight": min(
                1.0,
                persistence / max(persistence_component, 1e-6),
            )
            if persistence_component
            else 1.0,
            "discipline_active": True,
        }
    )

    return belief_strength, alignment, persistence, exports
