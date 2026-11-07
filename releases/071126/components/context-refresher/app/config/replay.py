"""Replay validation configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from calibration_config import _env_bool


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ReplaySettings:
    default_replay_limit: int = 50
    enable_final_validation: bool = True
    enable_stress_replay: bool = True
    artifacts_dir: str = "artifacts"
    reports_dir: str = "reports"
    replays_dir: str = "replays"


def get_replay_settings() -> ReplaySettings:
    return ReplaySettings(
        default_replay_limit=_env_int("REPLAY_DEFAULT_LIMIT", 50),
        enable_final_validation=_env_bool("ENABLE_FINAL_VALIDATION", True),
        enable_stress_replay=_env_bool("ENABLE_STRESS_REPLAY", True),
        artifacts_dir=os.environ.get("ARTIFACTS_DIR", "artifacts"),
        reports_dir=os.environ.get("REPORTS_DIR", "reports"),
        replays_dir=os.environ.get("REPLAYS_DIR", "replays"),
    )
