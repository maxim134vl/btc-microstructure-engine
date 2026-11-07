"""Phase 2B adversarial diagnostics orchestrator — warning-first, feature-flagged."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from adversarial_config import (
    AdversarialSettings,
    adversarial_active,
    get_adversarial_settings,
)
from calibration_resilience import (
    RESILIENCE_EXPORT_COLUMNS,
    compute_resilience_metrics,
    neutral_resilience_exports,
)
from failure_mode_analysis import (
    FAILURE_EXPORT_COLUMNS,
    analyze_failure_modes,
    neutral_failure_exports,
)
from instability_propagation import (
    INSTABILITY_EXPORT_COLUMNS,
    compute_instability_propagation,
    neutral_instability_exports,
)
from regime_transition_survival import (
    SURVIVAL_EXPORT_COLUMNS,
    compute_transition_survival,
    neutral_survival_exports,
)
from synthetic_stress_engine import (
    generate_all_stress_scenarios,
    stress_degradation_score,
)

ADVERSARIAL_EXPORT_COLUMNS = (
    FAILURE_EXPORT_COLUMNS
    + INSTABILITY_EXPORT_COLUMNS
    + SURVIVAL_EXPORT_COLUMNS
    + RESILIENCE_EXPORT_COLUMNS
)


def log_adversarial_warning(message: str) -> None:
    print(f"[ADVERSARIAL WARNING] {message}")


def build_adversarial_exports(
    snapshot: Dict[str, Any],
    history: Optional[pd.DataFrame] = None,
    settings: Optional[AdversarialSettings] = None,
) -> Dict[str, Any]:
    settings = settings or get_adversarial_settings()
    history = history if history is not None else pd.DataFrame()

    if not adversarial_active(settings):
        return {
            **neutral_failure_exports(),
            **neutral_instability_exports(),
            **neutral_survival_exports(),
            **neutral_resilience_exports(),
        }

    failure_exports = analyze_failure_modes(snapshot, history)
    instability_exports = compute_instability_propagation(snapshot, history)
    survival_exports = compute_transition_survival(snapshot, history)

    stress_sensitivity = 0.0
    if settings.enable_stress_sensitivity:
        scenarios = generate_all_stress_scenarios(
            snapshot,
            seed=settings.stress_engine_seed,
        )
        if scenarios:
            stress_sensitivity = sum(
                stress_degradation_score(snapshot, item["stressed_snapshot"])
                for item in scenarios
            ) / len(scenarios)

    resilience_exports = compute_resilience_metrics(
        snapshot={
            **snapshot,
            **failure_exports,
            **instability_exports,
            **survival_exports,
        },
        history=history,
        failure_exports=failure_exports,
        stress_sensitivity=stress_sensitivity,
        active=True,
    )

    exports = {
        **failure_exports,
        **instability_exports,
        **survival_exports,
        **resilience_exports,
    }

    if settings.warn_on_failure_mode:
        fragility = float(exports.get("probabilistic_fragility_score", 0.0))
        if fragility >= settings.fragility_warning_threshold:
            log_adversarial_warning(
                f"fragility={fragility:.3f} mode={exports.get('failure_mode')} "
                f"origin={exports.get('instability_origin')}"
            )

    return exports
