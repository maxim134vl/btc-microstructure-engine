"""Replay resilience recovery after instability."""

from __future__ import annotations

from adversarial_diagnostics import build_adversarial_exports
from adversarial_config import AdversarialSettings
from scripts.replay_validation.adversarial.replay_utils import load_probabilistic


def run(limit: int = 50) -> None:
    import os

    os.environ["ENABLE_ADVERSARIAL_DIAGNOSTICS"] = "true"
    os.environ["ENABLE_STRESS_SENSITIVITY"] = "true"

    frame = load_probabilistic().tail(limit)
    settings = AdversarialSettings(
        enable_adversarial_diagnostics=True,
        enable_stress_sensitivity=True,
    )

    print("RESILIENCE RECOVERY REPLAY")
    print("=" * 60)
    for index in range(max(0, len(frame) - 5), len(frame)):
        row = frame.iloc[index]
        history = frame.iloc[:index]
        exports = build_adversarial_exports(
            row.to_dict(),
            history=history,
            settings=settings,
        )
        print(
            f"resilience={exports.get('resilience_score', 0):.3f} "
            f"recovery={exports.get('probabilistic_recovery_rate', 0):.3f} "
            f"fragility={exports.get('probabilistic_fragility_score', 0):.3f}"
        )


if __name__ == "__main__":
    run()
