"""Write-boundary paths for structural protection shadow."""

from __future__ import annotations

from pathlib import Path

from . import WRITE_BOUNDARY_VIOLATION


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def shadow_root(repo: Path | None = None) -> Path:
    return (repo or repo_root()) / "data" / "trading" / "shadow_structural_protection"


def shadow_epoch_root(repo: Path | None = None, *, epoch_id: str) -> Path:
    """Return isolated shadow state root for one PAPER epoch."""
    epoch = str(epoch_id or "").strip()
    if not epoch or epoch in {".", ".."} or "/" in epoch or "\\" in epoch:
        raise ValueError(f"invalid paper epoch id: {epoch_id!r}")
    return shadow_root(repo) / "epochs" / epoch


def paper_books_root(repo: Path | None = None, *, epoch_id: str) -> Path:
    return (repo or repo_root()) / "data" / "trading" / "intrabar_paper" / epoch_id / "books"


def assert_shadow_write_path(path: Path, *, repo: Path | None = None) -> Path:
    root = shadow_root(repo).resolve()
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{WRITE_BOUNDARY_VIOLATION}: refused write to {target}") from exc
    # Explicit forbidden siblings
    forbidden_parts = (
        "intrabar_paper",
        "paper_epochs",
        "shadow_economic_correlation",
        "/cognition/",
    )
    s = str(target)
    for part in forbidden_parts:
        if part in s and "shadow_structural_protection" not in s:
            raise RuntimeError(f"{WRITE_BOUNDARY_VIOLATION}: refused write to {target}")
    return target
