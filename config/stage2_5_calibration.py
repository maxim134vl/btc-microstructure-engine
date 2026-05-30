"""Stage 2.5 intermediate cognition threshold configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from storage.path_registry import repo_root

DEFAULT_THRESHOLDS_PATH = repo_root() / "config" / "stage2_5_thresholds.yaml"


@dataclass(frozen=True)
class Stage25Thresholds:
    """Detection thresholds for Phase 1 intermediate cognition states."""

    continuation_delta_min: float = 350.0
    continuation_price_min: float = 150.0
    initiative_ma_min: float = 180.0
    initiative_swing_min: float = 450.0
    rotational_flips_min: int = 4
    rotational_stopping_min_flips: int = 0
    cooldown_bars: int = 4
    confidence_material_delta: float = 0.08

    def as_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


LEGACY_THRESHOLDS = Stage25Thresholds(
    continuation_delta_min=350.0,
    continuation_price_min=150.0,
    initiative_ma_min=180.0,
    initiative_swing_min=450.0,
    rotational_flips_min=4,
    rotational_stopping_min_flips=0,
    cooldown_bars=4,
    confidence_material_delta=0.08,
)


def _coerce_thresholds(raw: dict[str, Any]) -> Stage25Thresholds:
    kwargs: dict[str, Any] = {}
    for field in fields(Stage25Thresholds):
        if field.name in raw:
            value = raw[field.name]
            if field.type is int:
                kwargs[field.name] = int(value)
            else:
                kwargs[field.name] = float(value)
    return Stage25Thresholds(**kwargs)


def load_stage2_5_thresholds(
    *,
    profile: str | None = None,
    path: Path | str | None = None,
) -> Stage25Thresholds:
    """Load Stage 2.5 thresholds from YAML configuration."""

    profile = profile or os.environ.get("STAGE2_5_THRESHOLD_PROFILE", "live_feed")
    config_path = Path(path) if path is not None else DEFAULT_THRESHOLDS_PATH

    if not config_path.exists():
        if profile == "legacy":
            return LEGACY_THRESHOLDS
        return LEGACY_THRESHOLDS

    with open(config_path, encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    if profile == "legacy":
        return _coerce_thresholds(payload.get("legacy", LEGACY_THRESHOLDS.as_dict()))

    active = payload.get("active_profile", "live_feed")
    selected = profile or active
    section = payload.get(selected) or payload.get("live_feed") or {}
    return _coerce_thresholds(section)


def thresholds_metadata(path: Path | str | None = None) -> dict[str, Any]:
    """Return calibration metadata embedded in the thresholds file."""

    config_path = Path(path) if path is not None else DEFAULT_THRESHOLDS_PATH
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return {
        key: payload.get(key)
        for key in (
            "schema_version",
            "calibrated_at",
            "source",
            "calibration_window",
            "distribution_summary",
            "expected_density",
            "expected_state_mix",
        )
        if key in payload
    }
