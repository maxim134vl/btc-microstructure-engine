"""External SSD write-boundary paths for Shadow Auction.

Heavy data MUST live under the configured external volume. Silent fallback to
the repository tree is forbidden.
"""

from __future__ import annotations

from pathlib import Path

from . import WRITE_BOUNDARY_VIOLATION


DEFAULT_DATA_ROOT = "/Volumes/MaksTiger/btc-ml/shadow_auction"
DEFAULT_VOLUME_ROOT = "/Volumes/MaksTiger"

REQUIRED_SUBDIRS = (
    "memory",
    "manifests",
    "logs",
    "health",
    "replay",
    "archive",
)

# Sibling Shadow / canonical persistent roots that AES6 must never write into.
# Paths are relative to the repository root unless absolute.
FORBIDDEN_PERSISTENT_RELATIVE = (
    "data/cognition",
    "data/trading",
    "data/trading/shadow_economic_correlation",
    "data/trading/shadow_structural_protection",
    "data/trading/intrabar_paper",
)


def forbidden_persistent_roots(repo: Path | None = None) -> tuple[Path, ...]:
    root = (repo or repo_root()).resolve()
    out: list[Path] = []
    for rel in FORBIDDEN_PERSISTENT_RELATIVE:
        out.append((root / rel).resolve())
    # Explicit absolute traps for accidental /tmp or repo-local "Volumes" fakes.
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


def configured_data_root(config: dict | None = None) -> Path:
    if config and config.get("data_root"):
        return Path(str(config["data_root"])).expanduser()
    return Path(DEFAULT_DATA_ROOT)


def configured_volume_root(config: dict | None = None) -> Path:
    if config and config.get("required_volume_root"):
        return Path(str(config["required_volume_root"])).expanduser()
    return Path(DEFAULT_VOLUME_ROOT)


def assert_shadow_write_path(
    path: Path | str,
    *,
    data_root: Path | str,
    repo: Path | None = None,
) -> Path:
    """Refuse any write outside the external Shadow Auction root.

    Also refuse paths that resolve under the repository tree (no silent
    internal-SSD fallback), and refuse known sibling Shadow / canonical roots.
    """
    root = Path(data_root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{WRITE_BOUNDARY_VIOLATION}: refused write to {target}") from exc

    repo_path = (repo or repo_root()).resolve()
    try:
        target.relative_to(repo_path)
    except ValueError:
        assert_not_forbidden_persistent(target, repo=repo_path)
        return target
    raise RuntimeError(
        f"{WRITE_BOUNDARY_VIOLATION}: refused write inside repository {target}"
    )


def subdir(data_root: Path | str, name: str) -> Path:
    if name not in REQUIRED_SUBDIRS:
        raise ValueError(f"unknown shadow_auction subdir: {name}")
    return Path(data_root) / name
