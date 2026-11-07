"""Load canonical benchmark behavior specifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from benchmark.conformance.paths import SPECS_DIR

SPEC_FILES = {
    "stage1": SPECS_DIR / "stage1_expected_behavior.yaml",
    "stage2": SPECS_DIR / "stage2_expected_behavior.yaml",
    "integrated": SPECS_DIR / "integrated_expected_behavior.yaml",
}


def load_spec(layer: str) -> dict[str, Any]:
    path = SPEC_FILES.get(layer)
    if not path or not path.exists():
        return {"metrics": {}, "lookback_days": 7}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_all_specs() -> dict[str, dict[str, Any]]:
    return {layer: load_spec(layer) for layer in SPEC_FILES}
