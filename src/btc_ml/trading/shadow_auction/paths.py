"""Shadow Auction write-boundary paths.

Canonical storage for Docker/VPS/host parity is repo-local:

    data/trading/shadow_auction

Legacy ``external_volume`` mode (e.g. /Volumes/MaksTiger) remains supported
when ``storage_mode`` is set explicitly, but is no longer the default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import WRITE_BOUNDARY_VIOLATION


DEFAULT_STORAGE_MODE = "repo_local"
DEFAULT_DATA_ROOT = "data/trading/shadow_auction"
# Legacy defaults kept for external_volume mode / old tests.
DEFAULT_EXTERNAL_DATA_ROOT = "/Volumes/MaksTiger/btc-ml/shadow_auction"
DEFAULT_VOLUME_ROOT = "/Volumes/MaksTiger"

REQUIRED_SUBDIRS = (
    "memory",
    "manifests",
    "logs",
    "health",
    "replay",
    "archive",
)

# Sibling Shadow / canonical persistent roots that Auction must never write into.
# Paths are relative to the repository root unless absolute.
# Note: data/trading/shadow_auction itself is the allowed Auction root.
FORBIDDEN_PERSISTENT_RELATIVE = (
    "data/cognition",
    "data/trading/shadow_economic_correlation",
    "data/trading/shadow_structural_protection",
    "data/trading/intrabar_paper",
    "data/trading/paper_epochs",
)

REPO_LOCAL_RELATIVE = "data/trading/shadow_auction"


def forbidden_persistent_roots(repo: Path | None = None) -> tuple[Path, ...]:
    root = (repo or repo_root()).resolve()
    out: list[Path] = []
    for rel in FORBIDDEN_PERSISTENT_RELATIVE:
        out.append((root / rel).resolve())
    # Explicit absolute traps for accidental /tmp fallbacks.
    out.append(Path("/tmp").resolve())
    out.append(Path("/var/tmp").resolve())
    return tuple(out)


def assert_not_forbidden_persistent(
    path: Path | str,
    *,
    repo: Path | None = None,
) -> Path:
    """Refuse writes into canonical/EQCORR/STP/tmp persistent locations."""
    target = Path(path).expanduser().resolve()
    for forbidden in forbidden_persistent_roots(repo):
        try:
            target.relative_to(forbidden)
        except ValueError:
            continue
        raise RuntimeError(
            f"{WRITE_BOUNDARY_VIOLATION}: refused write into forbidden root {forbidden} "
            f"(target={target})"
        )
    return target


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def storage_mode(config: Mapping[str, Any] | None = None) -> str:
    cfg = dict(config or {})
    mode = str(cfg.get("storage_mode") or DEFAULT_STORAGE_MODE).strip().lower()
    if mode in {"repo_local", "local", "repository"}:
        return "repo_local"
    if mode in {"external_volume", "external", "ssd"}:
        return "external_volume"
    raise ValueError(f"unsupported shadow_auction storage_mode: {mode}")


def resolve_data_root(
    config: Mapping[str, Any] | None = None,
    *,
    repo: Path | None = None,
) -> Path:
    """Resolve configured data_root; relative paths are anchored at repo root."""
    root = (repo or repo_root()).resolve()
    cfg = dict(config or {})
    raw = cfg.get("data_root")
    if raw is None or str(raw).strip() == "":
        if storage_mode(cfg) == "repo_local":
            return (root / DEFAULT_DATA_ROOT).resolve()
        return Path(DEFAULT_EXTERNAL_DATA_ROOT).expanduser().resolve()
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def configured_data_root(config: dict | None = None, *, repo: Path | None = None) -> Path:
    return resolve_data_root(config, repo=repo)


def configured_volume_root(config: dict | None = None) -> Path | None:
    if config and config.get("required_volume_root"):
        return Path(str(config["required_volume_root"])).expanduser()
    if storage_mode(config) == "external_volume":
        return Path(DEFAULT_VOLUME_ROOT)
    return None


def assert_shadow_write_path(
    path: Path | str,
    *,
    data_root: Path | str,
    repo: Path | None = None,
) -> Path:
    """Refuse any write outside the configured Shadow Auction root.

    Repo-local mode allows writes under ``data/trading/shadow_auction``.
    Sibling trading/cognition roots remain forbidden.
    """
    root = Path(data_root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{WRITE_BOUNDARY_VIOLATION}: refused write to {target}") from exc

    assert_not_forbidden_persistent(target, repo=repo or repo_root())
    return target


def subdir(data_root: Path | str, name: str) -> Path:
    if name not in REQUIRED_SUBDIRS:
        raise ValueError(f"unknown shadow_auction subdir: {name}")
    return Path(data_root) / name
