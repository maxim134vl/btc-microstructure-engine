"""Load config/required_runtime_components.yaml — health manifest single source of truth."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from storage.path_registry import repo_root

MANIFEST_PATH = repo_root() / "config" / "required_runtime_components.yaml"


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML parser for manifest (no external deps required)."""
    result: dict[str, Any] = {}
    current_key: str | None = None
    thresholds: dict[str, Any] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_key = line[:-1].strip()
            if current_key == "THRESHOLDS":
                result[current_key] = thresholds
            else:
                result[current_key] = []
            continue
        if current_key == "THRESHOLDS" and ":" in line:
            key, value = line.strip().split(":", 1)
            thresholds[key.strip()] = int(value.strip().split("#")[0].strip())
            continue
        if line.strip().startswith("- ") and current_key:
            result[current_key].append(line.strip()[2:].strip())
    return result


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return _default_manifest()
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    try:
        import yaml

        data = yaml.safe_load(text) or {}
    except Exception:
        data = _parse_simple_yaml(text)
    return {
        "required_collectors": frozenset(data.get("REQUIRED_COLLECTORS", [])),
        "required_parquet": frozenset(data.get("REQUIRED_PARQUET", [])),
        "required_engines": frozenset(data.get("REQUIRED_ENGINES", [])),
        "thresholds": data.get("THRESHOLDS", {}),
    }


def _default_manifest() -> dict[str, Any]:
    return {
        "required_collectors": frozenset({"binance_live_feed"}),
        "required_parquet": frozenset(
            {
                "live_market_feed.parquet",
                "candle_structure_memory.parquet",
                "runtime_cognition_memory.parquet",
                "probabilistic_auction_memory.parquet",
            }
        ),
        "required_engines": frozenset(
            {
                "candle_structure_engine_v1.py",
                "runtime_cognition_engine_v1.py",
                "probabilistic_auction_engine_v1.py",
            }
        ),
        "thresholds": {},
    }


def required_collectors() -> frozenset[str]:
    return load_manifest()["required_collectors"]


def required_parquet() -> frozenset[str]:
    return load_manifest()["required_parquet"]


def required_engines() -> frozenset[str]:
    return load_manifest()["required_engines"]


def thresholds() -> dict[str, Any]:
    return load_manifest()["thresholds"]


def threshold(name: str, default: float) -> float:
    return float(thresholds().get(name, default))


def is_required_collector(name: str) -> bool:
    return name in required_collectors()


def is_required_parquet(name: str) -> bool:
    return name in required_parquet()


def is_required_engine(name: str) -> bool:
    return name in required_engines()


def manifest_summary() -> dict[str, Any]:
    manifest = load_manifest()
    return {
        "path": str(MANIFEST_PATH),
        "required_collectors": sorted(manifest["required_collectors"]),
        "required_parquet": sorted(manifest["required_parquet"]),
        "required_engines": sorted(manifest["required_engines"]),
        "thresholds": manifest["thresholds"],
    }
