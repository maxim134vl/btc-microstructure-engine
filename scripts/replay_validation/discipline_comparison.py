"""Before/after replay comparison for Phase 1B probabilistic discipline."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd

from calibration_config import CalibrationSettings
from calibration_discipline import apply_probabilistic_discipline
from calibration_diagnostics import build_diagnostic_exports
from scripts.replay_validation.replay_utils import (
    load_probabilistic,
    load_reinforcement,
    rows_with_decomposition,
)


def run(limit: int = 100) -> pd.DataFrame:
    probabilistic = rows_with_decomposition(load_probabilistic())
    if len(probabilistic) == 0:
        probabilistic = load_probabilistic().tail(limit)
    else:
        probabilistic = probabilistic.tail(limit)

    reinforcement = load_reinforcement()

    enabled_settings = CalibrationSettings(
        enable_probabilistic_discipline=True,
        calibration_mode="disciplined",
    )

    rows = []
    for index, (_, row) in enumerate(probabilistic.iterrows()):
        history = probabilistic.iloc[:index]
        raw = float(
            row.get(
                "raw_conviction",
                row.get("conviction_probability", 0.0),
            )
        )
        snapshot = row.to_dict()
        snapshot["raw_conviction"] = raw

        diagnostics = build_diagnostic_exports(
            probabilistic_history=history,
            reinforcement_history=reinforcement,
            reinforcement_window=reinforcement.tail(25),
            runtime_cognition={},
            current_row=snapshot,
        )
        discipline = apply_probabilistic_discipline(
            raw_conviction=raw,
            diagnostics=diagnostics,
            current_snapshot=snapshot,
            runtime_cognition={},
            probabilistic_history=history,
            settings=enabled_settings,
        )

        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "raw_conviction": raw,
                "disciplined_conviction": discipline["disciplined_conviction"],
                "divergence": discipline["raw_vs_disciplined_divergence"],
                "saturation_reduction": discipline["saturation_reduction"],
                "entropy_interaction": discipline["entropy_interaction"],
                "conflict_density": diagnostics.get("conflict_density"),
                "persistence_duration": diagnostics.get("persistence_duration"),
                "reinforcement_damping_factor": discipline[
                    "reinforcement_damping_factor"
                ],
            }
        )

    output = pd.DataFrame(rows)

    print("DISCIPLINE BEFORE/AFTER REPLAY")
    print("=" * 60)
    print(output.tail(min(10, len(output))).to_string(index=False))
    print()
    if len(output) > 0:
        print("Mean divergence:", round(float(output["divergence"].mean()), 4))
        print(
            "Mean saturation reduction:",
            round(float(output["saturation_reduction"].mean()), 4),
        )
        print(
            "Mean entropy interaction:",
            round(float(output["entropy_interaction"].mean()), 4),
        )

    return output


if __name__ == "__main__":
    run()
